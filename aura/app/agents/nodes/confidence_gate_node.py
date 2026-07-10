"""Node 10 — Confidence gate.

Path A (toggle ON and confidence >= threshold):
  - POST Markdown comment to JSM and start/refresh conversation tracking
    via comment_poster.post_and_track()
  - Broadcast AURA_COMMENT_POSTED WS event

Path B (toggle OFF, or confidence < threshold):
  - Write to low_confidence_queue for technician review
  - Broadcast LOW_CONFIDENCE_QUEUED WS event

Toggle OFF: comment-only-after-manual-approval — everything queues for a
technician regardless of confidence. Toggle ON: today's confidence-threshold
auto-post/queue split.

Jira status transitions (Open -> In Progress, and later In Progress ->
Resolved) are NOT decided here — In Progress happens unconditionally in
jsm_poller as soon as a ticket is first picked up, and Resolved happens via
conversation_service's idle timeout. Neither depends on this toggle.

apply_confidence_gate() is the reusable core (plain params, no AgentState)
so conversation_service.py's turn-2+ replies go through the exact same
auto-post-or-queue decision as the initial resolution, instead of a
duplicated copy of this logic. comment_poster is lazy-imported inside
apply_confidence_gate to avoid a circular import: comment_poster imports
conversation_service, which imports apply_confidence_gate from this module.
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text as sa_text

from app.core.logging import get_logger
from app.db.sqlite import get_session
from app.models.agent_state import AgentState
from app.services.notification_bus import notification_bus

log = get_logger(__name__)

_FALLBACK_THRESHOLD = 0.90


async def confidence_gate_node(state: AgentState) -> dict:
    ticket_id = state["ticket_id"]
    raw_ticket = state.get("raw_ticket") or {}

    result = await apply_confidence_gate(
        tenant_id=state["tenant_id"],
        ticket_id=ticket_id,
        formatted_comment=state.get("formatted_comment") or "",
        confidence=state.get("confidence_score") or 0.0,
        citations=state.get("citations") or [],
        assigned_team=state.get("assigned_team"),
        auto_comment_enabled=state.get("auto_comment_enabled") or False,
        reporter_account_id=raw_ticket.get("reporter_account_id"),
    )

    now = datetime.now(timezone.utc).isoformat()
    if result["action_taken"] == "comment_posted":
        decision = f"Auto-posted to JSM (score={result['confidence']:.2f} >= {result['threshold']})"
    else:
        decision = f"Held for technician review (score={result['confidence']:.2f} < {result['threshold']})"
        if result.get("error"):
            decision = f"JSM post failed; held for review (score={result['confidence']:.2f}): {result['error']}"

    step = {
        "node_name": "confidence_gate_node",
        "timestamp": now,
        "decision": decision,
        "metadata": {
            "jsm_comment_id": result.get("jsm_comment_id"),
            "rollback_action_id": result.get("rollback_action_id"),
            "threshold": result["threshold"],
        },
    }
    return {
        "action_taken": result["action_taken"],
        "jsm_comment_id": result.get("jsm_comment_id"),
        "audit_steps": [step],
    }


async def apply_confidence_gate(
    tenant_id: str,
    ticket_id: str,
    formatted_comment: str,
    confidence: float,
    citations: list[str],
    assigned_team: str | None,
    auto_comment_enabled: bool,
    reporter_account_id: str | None = None,
) -> dict:
    """Core auto-post-or-queue decision, reused by the initial resolution
    (confidence_gate_node) and conversation replies (conversation_service).

    reporter_account_id is passed through to comment_poster.post_and_track()
    on a successful post, so conversation tracking starts/refreshes the same
    way every turn (safe to pass on every call, not just the first).

    Returns {action_taken, jsm_comment_id?, rollback_action_id?, threshold,
    confidence, error?}.
    """
    now = datetime.now(timezone.utc).isoformat()

    async with get_session() as db:
        row = (await db.execute(
            sa_text("SELECT confidence_threshold FROM platform_config WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )).first()
    threshold = float(row[0]) if row and row[0] is not None else _FALLBACK_THRESHOLD

    if auto_comment_enabled and confidence >= threshold:
        # ── Path A: auto-post ─────────────────────────────────────────────────
        from app.services import comment_poster

        try:
            async with get_session() as db:
                result = await comment_poster.post_and_track(
                    db, tenant_id, ticket_id, formatted_comment,
                    actor="AURA_AGENT", reporter_account_id=reporter_account_id,
                )
        except Exception as exc:
            # Post failed — downgrade to hold-for-review
            await _write_to_queue(
                tenant_id, ticket_id, formatted_comment, confidence, citations,
                assigned_team, reporter_account_id, now,
            )
            return {
                "action_taken": "held_low_confidence",
                "confidence": confidence,
                "threshold": threshold,
                "error": str(exc),
            }

        await _notify_team_or_admins(
            tenant_id,
            assigned_team,
            "AURA_COMMENT_POSTED",
            {
                "ticket_id": ticket_id,
                "confidence_score": confidence,
                "jsm_comment_id": result["jsm_comment_id"],
                "rollback_action_id": result["rollback_action_id"],
                "preview": formatted_comment[:200],
            },
        )

        return {
            "action_taken": "comment_posted",
            "jsm_comment_id": result["jsm_comment_id"],
            "rollback_action_id": result["rollback_action_id"],
            "confidence": confidence,
            "threshold": threshold,
        }

    # ── Path B: hold for review ───────────────────────────────────────────────
    await _write_to_queue(
        tenant_id, ticket_id, formatted_comment, confidence, citations,
        assigned_team, reporter_account_id, now,
    )
    await _notify_team_or_admins(
        tenant_id,
        assigned_team,
        "LOW_CONFIDENCE_QUEUED",
        {"ticket_id": ticket_id, "confidence_score": confidence, "threshold": threshold},
    )
    return {"action_taken": "held_low_confidence", "confidence": confidence, "threshold": threshold}


async def _notify_team_or_admins(tenant_id: str, team_id: str | None, event_type: str, payload: dict) -> None:
    """Notify the ticket's assigned team, or admins if no team is set.

    Broadcasting to everyone regardless of team was the original behaviour;
    this scopes the notification to the people who actually own the ticket.
    """
    if team_id:
        await notification_bus.broadcast_to_team(tenant_id, team_id, event_type, payload)
    else:
        await notification_bus.broadcast_to_admins(tenant_id, event_type, payload)


async def _write_to_queue(
    tenant_id: str,
    ticket_id: str,
    formatted_comment: str,
    confidence: float,
    citations: list[str],
    assigned_team: str | None,
    reporter_account_id: str | None,
    now: str,
) -> None:
    async with get_session() as db:
        await db.execute(
            sa_text(
                "INSERT OR REPLACE INTO low_confidence_queue "
                "(queue_id, tenant_id, ticket_id, formatted_comment, confidence_score, "
                " citations, abstained, team_id, reporter_account_id, queued_at) "
                "VALUES (:qid, :tenant, :tid, :comment, :score, :cit, 0, :team, :rid, :now)"
            ),
            {
                "qid": str(uuid.uuid4()),
                "tenant": tenant_id,
                "tid": ticket_id,
                "comment": formatted_comment or "",
                "score": confidence,
                "cit": json.dumps(citations or []),
                "team": assigned_team or "",
                "rid": reporter_account_id,
                "now": now,
            },
        )
