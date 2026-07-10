"""Ticket management routes — all scoped to the caller's tenant.

GET    /tickets                         — paginated audit_log list
GET    /tickets/queue                   — low-confidence review queue
GET    /tickets/mine                    — tickets the current end user submitted
GET    /tickets/{ticket_id}             — detail view (includes current assignment)
POST   /tickets/{ticket_id}/acknowledge — technician confirms they've seen the ticket
POST   /tickets/{ticket_id}/rollback-comment — undo a previously posted comment
POST   /tickets/{ticket_id}/comment     — post a (corrected) comment directly
POST   /tickets/queue/{queue_id}/approve  — post suggestion to JSM
POST   /tickets/queue/{queue_id}/reject   — reject suggestion
POST   /tickets/queue/{queue_id}/edit     — edit comment then post
POST   /tickets/submit                  — end-user creates new JSM ticket

Note: manual ticket "claiming" was removed in favor of always-on assignment
(see assignment_node.py / assignment_service.py) — every ticket already has a
technician assigned automatically, with automatic reassignment on timeout.
Acknowledge is the only technician-driven action needed now.
"""

import json
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import require_any_auth, require_technician
from app.db.sqlite import get_db
from app.models.api_schemas import (
    LowConfQueueEntry,
    OkResponse,
    SuggestionApproveResponse,
    SuggestionEditRequest,
    SuggestionRejectRequest,
    TicketSummary,
    TicketSubmit,
)
from app.services import assignment_service, comment_poster, rollback_store, ticket_status, transition_service
from app.services import itsm_client
from app.services.notification_bus import notification_bus

_settings = get_settings()
log = get_logger(__name__)

router = APIRouter(prefix="/tickets", tags=["tickets"])

_NOW = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731


# ── List tickets ──────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_tickets(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    category: str | None = None,
    action_taken: str | None = None,
    status: str | None = None,
    ticket_id: str | None = None,
    team_id: str | None = None,
) -> dict:
    tenant_id = current_user["tenant_id"]
    clauses = ["a.tenant_id = :tenant_id"]
    params: dict = {"now": datetime.now(timezone.utc).isoformat(), "tenant_id": tenant_id}

    # A category's owning team, looked up by name — audit_log only stores
    # the category name, not team_id, so every team-scoped filter/column
    # goes through this same category_config correlation.
    team_expr = "(SELECT cc.team_id FROM category_config cc WHERE cc.tenant_id = a.tenant_id AND cc.name = a.category)"

    if category:
        clauses.append("a.category = :category")
        params["category"] = category
    if team_id:
        clauses.append(f"{team_expr} = :team_id")
        params["team_id"] = team_id
    if action_taken:
        clauses.append("a.action_taken = :action_taken")
        params["action_taken"] = action_taken
    if status:
        clauses.append("ts.status = :status")
        params["status"] = status
    if ticket_id:
        clauses.append("a.ticket_id LIKE :ticket_id")
        params["ticket_id"] = f"%{ticket_id}%"

    where = " WHERE " + " AND ".join(clauses)
    offset = (page - 1) * page_size

    total_row = await db.execute(
        sa_text(
            f"SELECT COUNT(*) FROM audit_log a "
            f"LEFT JOIN ticket_status ts ON ts.tenant_id = a.tenant_id AND ts.ticket_id = a.ticket_id{where}"
        ),
        params,
    )
    total = total_row.scalar() or 0

    # sla_status/claimed_by/assigned_to/acknowledged_at are derived here (not
    # stored on audit_log) so the dashboard and ticket list can show live SLA
    # urgency, who's already working a ticket, and whether it still needs
    # acknowledging — without a per-row detail fetch.
    rows = await db.execute(
        sa_text(
            f"SELECT a.ticket_id, a.action_taken, a.priority, a.category, a.auto_comment_enabled, "
            f"       a.confidence_score, a.abstained, a.created_at, "
            f"       ts.status as status, "
            f"       se.deadline as sla_deadline, "
            f"       CASE WHEN se.breached_at IS NOT NULL THEN 'breached' "
            f"            WHEN se.warning_sent_at IS NOT NULL THEN 'warning' "
            f"            WHEN se.deadline IS NOT NULL THEN 'ok' "
            f"            ELSE NULL END as sla_status, "
            f"       (SELECT cc.claimed_by FROM collision_claims cc "
            f"        WHERE cc.tenant_id = a.tenant_id AND cc.ticket_id = a.ticket_id AND cc.released_at IS NULL "
            f"          AND cc.expires_at > :now "
            f"        ORDER BY cc.claimed_at DESC LIMIT 1) as claimed_by, "
            f"       (SELECT ta.assigned_to FROM ticket_assignments ta "
            f"        WHERE ta.tenant_id = a.tenant_id AND ta.ticket_id = a.ticket_id AND ta.is_current = 1 "
            f"        ORDER BY ta.assigned_at DESC LIMIT 1) as assigned_to, "
            f"       (SELECT ta.acknowledged_at FROM ticket_assignments ta "
            f"        WHERE ta.tenant_id = a.tenant_id AND ta.ticket_id = a.ticket_id AND ta.is_current = 1 "
            f"        ORDER BY ta.assigned_at DESC LIMIT 1) as acknowledged_at, "
            f"       {team_expr} as team_id "
            f"FROM audit_log a "
            f"LEFT JOIN sla_events se ON se.tenant_id = a.tenant_id AND se.ticket_id = a.ticket_id "
            f"LEFT JOIN ticket_status ts ON ts.tenant_id = a.tenant_id AND ts.ticket_id = a.ticket_id"
            f"{where} "
            f"ORDER BY a.created_at DESC LIMIT {page_size} OFFSET {offset}"
        ),
        params,
    )
    items = [
        TicketSummary(
            ticket_id=r["ticket_id"],
            summary=r["ticket_id"],    # raw_ticket not in audit_log; use ID as summary
            category=r["category"],
            priority=r["priority"],
            status=r["status"],
            sla_deadline=r["sla_deadline"],
            sla_status=r["sla_status"],
            action_taken=r["action_taken"],
            claimed_by=r["claimed_by"],
            abstained=bool(r["abstained"]),
            confidence_score=r["confidence_score"],
            auto_comment_enabled=(
                None if r["auto_comment_enabled"] is None else bool(r["auto_comment_enabled"])
            ),
            assigned_to=r["assigned_to"],
            acknowledged_at=r["acknowledged_at"],
            team_id=r["team_id"],
        )
        for r in rows.mappings()
    ]
    return {"items": [i.model_dump() for i in items], "total": total, "page": page, "page_size": page_size}


# ── Low-confidence queue ──────────────────────────────────────────────────────

@router.get("/queue", response_model=list[LowConfQueueEntry])
async def list_queue(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_technician)],
    team_id: str | None = None,
    category: str | None = None,
) -> list[LowConfQueueEntry]:
    tenant_id = current_user["tenant_id"]
    clauses = ["lc.tenant_id = :tenant_id", "lc.resolved_at IS NULL"]
    params: dict = {"tenant_id": tenant_id}
    if team_id:
        clauses.append("lc.team_id = :team_id")
        params["team_id"] = team_id
    # low_confidence_queue has no category column — correlate to the
    # ticket's latest audit_log row for it, same as the category filter
    # already used for GET /tickets.
    category_expr = (
        "(SELECT a.category FROM audit_log a WHERE a.tenant_id = lc.tenant_id AND a.ticket_id = lc.ticket_id "
        "ORDER BY a.created_at DESC LIMIT 1)"
    )
    if category:
        clauses.append(f"{category_expr} = :category")
        params["category"] = category

    where = "WHERE " + " AND ".join(clauses)
    result = await db.execute(
        sa_text(
            f"SELECT lc.queue_id, lc.ticket_id, lc.formatted_comment, lc.confidence_score, "
            f"       lc.citations, lc.abstained, lc.resolution_action, lc.queued_at, lc.team_id, "
            f"       {category_expr} as category "
            f"FROM low_confidence_queue lc {where} ORDER BY lc.queued_at ASC"
        ),
        params,
    )
    entries = []
    for r in result.mappings():
        try:
            cits = json.loads(r["citations"]) if r["citations"] else []
        except (json.JSONDecodeError, TypeError):
            cits = []
        entries.append(
            LowConfQueueEntry(
                queue_id=r["queue_id"],
                ticket_id=r["ticket_id"],
                summary=r["ticket_id"],
                category=r["category"],
                confidence_score=r["confidence_score"],
                formatted_comment=r["formatted_comment"] or "",
                citations=cits,
                abstained=bool(r["abstained"]),
                queued_at=datetime.fromisoformat(r["queued_at"]),
                team_id=r["team_id"],
            )
        )
    return entries


# ── End-user "my tickets" ─────────────────────────────────────────────────────
# Must be declared before /{ticket_id} — otherwise "mine" is captured as a
# ticket_id path param and this route is unreachable.

@router.get("/mine")
async def list_my_tickets(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
) -> list[dict]:
    """Tickets the current user submitted, with AURA's processing status if
    the agent pipeline has picked it up yet (a freshly submitted ticket has
    no audit_log row until the next JSM poll runs it through the graph).
    """
    rows = await db.execute(
        sa_text(
            "SELECT ust.ticket_id, ust.submitted_at, "
            "       a.action_taken, a.abstained, a.confidence_score, a.jsm_comment_id, a.created_at as processed_at, "
            "       ts.status as jira_status "
            "FROM user_submitted_tickets ust "
            "LEFT JOIN audit_log a ON a.tenant_id = ust.tenant_id AND a.ticket_id = ust.ticket_id "
            "LEFT JOIN ticket_status ts ON ts.tenant_id = ust.tenant_id AND ts.ticket_id = ust.ticket_id "
            "WHERE ust.tenant_id = :tenant_id AND ust.user_id = :uid "
            "ORDER BY ust.submitted_at DESC LIMIT 50"
        ),
        {"tenant_id": current_user["tenant_id"], "uid": current_user["user_id"]},
    )
    return [
        {
            "ticket_id": r["ticket_id"],
            "submitted_at": r["submitted_at"],
            "status": (
                r["jira_status"]
                or ("resolved" if r["jsm_comment_id"] else ("reviewing" if r["action_taken"] else "open"))
            ),
            "abstained": bool(r["abstained"]) if r["abstained"] is not None else False,
            "confidence_score": r["confidence_score"],
            "processed_at": r["processed_at"],
        }
        for r in rows.mappings()
    ]


# ── Ticket detail ─────────────────────────────────────────────────────────────

@router.get("/{ticket_id}")
async def get_ticket_detail(
    ticket_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
) -> dict:
    tenant_id = current_user["tenant_id"]
    result = await db.execute(
        sa_text(
            "SELECT entry_id, ticket_id, action_taken, priority, category, "
            "       auto_comment_enabled, confidence_score, abstained, "
            "       jsm_comment_id, audit_steps, created_at "
            "FROM audit_log WHERE tenant_id = :tenant_id AND ticket_id = :tid ORDER BY created_at DESC LIMIT 1"
        ),
        {"tenant_id": tenant_id, "tid": ticket_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found in audit log")

    try:
        audit_steps = json.loads(row["audit_steps"]) if row["audit_steps"] else []
    except (json.JSONDecodeError, TypeError):
        audit_steps = []

    assignment_row = (await db.execute(
        sa_text(
            "SELECT assigned_to, assigned_at, acknowledged_at FROM ticket_assignments "
            "WHERE tenant_id = :tenant_id AND ticket_id = :tid AND is_current = 1"
        ),
        {"tenant_id": tenant_id, "tid": ticket_id},
    )).mappings().first()

    timeout_row = (await db.execute(
        sa_text("SELECT assignment_timeout_minutes FROM platform_config WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )).first()

    # Best-effort live fetch — a single-ticket ITSM call is cheap here (unlike
    # the list endpoint, which would N+1) and keeps the detail view accurate
    # even if a technician changed the status directly in Jira/Zendesk. It
    # also carries the original ticket text (summary/description) and the
    # comment thread — neither of which audit_log stores; AURA's own posted
    # comments live only on the real ticket, not in this DB.
    status = await ticket_status.get_status(db, tenant_id, ticket_id)
    summary: str | None = None
    description: str | None = None
    comments: list[dict] = []
    try:
        async with itsm_client.get_itsm_client(tenant_id) as itsm:
            live_ticket = await itsm.get_ticket(ticket_id)
        if live_ticket:
            summary = live_ticket.summary
            description = live_ticket.description
            comments = [
                {"author": c.author, "body": c.body, "created": c.created.isoformat()}
                for c in live_ticket.comments
            ]
            if live_ticket.status:
                status = live_ticket.status
                await ticket_status.set_status(db, tenant_id, ticket_id, status)
    except Exception:
        pass  # fall back to the cached status fetched above; question/comments stay blank

    rollback_action_id = await _get_active_comment_rollback(db, tenant_id, ticket_id)

    return {
        "ticket_id": row["ticket_id"],
        "summary": summary,
        "description": description,
        "action_taken": row["action_taken"],
        "priority": row["priority"],
        "category": row["category"],
        "status": status,
        "auto_comment_enabled": (
            None if row["auto_comment_enabled"] is None else bool(row["auto_comment_enabled"])
        ),
        "confidence_score": row["confidence_score"],
        "abstained": bool(row["abstained"]),
        "jsm_comment_id": row["jsm_comment_id"],
        "comments": comments,
        "rollback_action_id": rollback_action_id,
        "audit_steps": audit_steps,
        "created_at": row["created_at"],
        "assigned_to": assignment_row["assigned_to"] if assignment_row else None,
        "assigned_at": assignment_row["assigned_at"] if assignment_row else None,
        "acknowledged_at": assignment_row["acknowledged_at"] if assignment_row else None,
        "assignment_timeout_minutes": timeout_row[0] if timeout_row and timeout_row[0] is not None else 60,
    }


# ── Assignment acknowledgment ─────────────────────────────────────────────────

@router.post("/{ticket_id}/acknowledge", response_model=OkResponse)
async def acknowledge_ticket(
    ticket_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_technician)],
) -> OkResponse:
    tenant_id = current_user["tenant_id"]
    ok = await assignment_service.acknowledge(db, tenant_id, ticket_id, current_user["user_id"])
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="No unacknowledged current assignment to you for this ticket",
        )

    # Acknowledging is the human "I'm on it" signal — reflect that on the
    # real ticket immediately so its status is a live, accurate picture of
    # who's actually working it, not just internal AURA bookkeeping.
    await transition_service.try_transition(
        tenant_id,
        ticket_id,
        transition_service.in_progress_status_name(tenant_id),
        original_status=None,
        actor=current_user["user_id"],
    )
    return OkResponse()


# ── Rollback / re-post a comment directly on a ticket ────────────────────────
# For any ticket carrying a still-active posted comment (auto-posted above
# the confidence threshold, or previously approved/edited by a technician) —
# a technician who disagrees with it can roll it back and post a corrected
# reply. Unlike the low_confidence_queue actions above, these act on a
# ticket_id directly since an already-posted comment has no queue row.

@router.post("/{ticket_id}/rollback-comment", response_model=OkResponse)
async def rollback_ticket_comment(
    ticket_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_technician)],
) -> OkResponse:
    tenant_id = current_user["tenant_id"]
    await _assert_can_action_ticket(db, current_user, ticket_id)
    await _assert_ticket_acknowledged(db, tenant_id, ticket_id, current_user)

    action_id = await _get_active_comment_rollback(db, tenant_id, ticket_id)
    if action_id is None:
        raise HTTPException(status_code=404, detail="No posted comment to roll back for this ticket.")

    try:
        await rollback_store.execute(db, tenant_id, action_id, triggered_by=current_user["user_id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.execute(
        sa_text(
            "UPDATE audit_log SET action_taken = 'rolled_back_by_technician', jsm_comment_id = NULL "
            "WHERE entry_id = (SELECT entry_id FROM audit_log WHERE tenant_id = :tenant_id AND ticket_id = :tid "
            "ORDER BY created_at DESC LIMIT 1)"
        ),
        {"tenant_id": tenant_id, "tid": ticket_id},
    )
    await db.commit()

    await notification_bus.broadcast_to_tenant(
        tenant_id,
        "TECHNICIAN_COMMENT_ROLLED_BACK",
        {"ticket_id": ticket_id, "rolled_back_by": current_user["user_id"]},
    )
    return OkResponse()


@router.post("/{ticket_id}/comment", response_model=SuggestionApproveResponse)
async def post_ticket_comment(
    ticket_id: str,
    body: SuggestionEditRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_technician)],
) -> SuggestionApproveResponse:
    tenant_id = current_user["tenant_id"]
    await _assert_can_action_ticket(db, current_user, ticket_id)
    await _assert_ticket_acknowledged(db, tenant_id, ticket_id, current_user)

    # Best-effort — carries the reporter id through so conversation tracking
    # can still match a future reply, same as the auto-post path.
    reporter_account_id: str | None = None
    try:
        async with itsm_client.get_itsm_client(tenant_id) as itsm:
            live_ticket = await itsm.get_ticket(ticket_id)
        if live_ticket:
            reporter_account_id = live_ticket.reporter_account_id
    except Exception:
        pass

    result = await comment_poster.post_and_track(
        db, tenant_id, ticket_id, body.edited_comment,
        actor=current_user["user_id"],
        reporter_account_id=reporter_account_id,
    )
    jsm_comment_id = result["jsm_comment_id"]
    await _sync_audit_log_action(db, tenant_id, ticket_id, "comment_posted", jsm_comment_id)

    await notification_bus.broadcast_to_tenant(
        tenant_id,
        "TECHNICIAN_COMMENT_POSTED",
        {"ticket_id": ticket_id, "jsm_comment_id": jsm_comment_id, "posted_by": current_user["user_id"]},
    )
    return SuggestionApproveResponse(jsm_comment_id=jsm_comment_id, posted_at=datetime.now(timezone.utc))


# ── Queue actions ─────────────────────────────────────────────────────────────

@router.post("/queue/{queue_id}/approve", response_model=SuggestionApproveResponse)
async def approve_suggestion(
    queue_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_technician)],
) -> SuggestionApproveResponse:
    tenant_id = current_user["tenant_id"]
    row = await _get_queue_entry(db, tenant_id, queue_id)
    _assert_can_action_queue_entry(current_user, row)
    ticket_id = row["ticket_id"]
    comment = row["formatted_comment"] or ""
    await _assert_ticket_acknowledged(db, tenant_id, ticket_id, current_user)

    result = await comment_poster.post_and_track(
        db, tenant_id, ticket_id, comment,
        actor=current_user["user_id"],
        reporter_account_id=row["reporter_account_id"],
    )
    jsm_comment_id = result["jsm_comment_id"]

    now = _NOW()
    await db.execute(
        sa_text(
            "UPDATE low_confidence_queue SET resolved_at = :now, resolved_by = :by, "
            "resolution_action = 'approved' WHERE queue_id = :qid"
        ),
        {"now": now, "by": current_user["user_id"], "qid": queue_id},
    )
    await _sync_audit_log_action(db, tenant_id, ticket_id, "comment_posted", jsm_comment_id)

    await notification_bus.broadcast_to_tenant(
        tenant_id,
        "TECHNICIAN_COMMENT_POSTED",
        {"ticket_id": ticket_id, "jsm_comment_id": jsm_comment_id, "posted_by": current_user["user_id"]},
    )

    return SuggestionApproveResponse(jsm_comment_id=jsm_comment_id, posted_at=datetime.now(timezone.utc))


@router.post("/queue/{queue_id}/reject", response_model=OkResponse)
async def reject_suggestion(
    queue_id: str,
    body: SuggestionRejectRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_technician)],
) -> OkResponse:
    tenant_id = current_user["tenant_id"]
    row = await _get_queue_entry(db, tenant_id, queue_id)  # 404 guard
    _assert_can_action_queue_entry(current_user, row)
    await db.execute(
        sa_text(
            "UPDATE low_confidence_queue SET resolved_at = :now, resolved_by = :by, "
            "resolution_action = 'rejected' WHERE queue_id = :qid"
        ),
        {"now": _NOW(), "by": "technician", "qid": queue_id},
    )
    await _sync_audit_log_action(db, tenant_id, row["ticket_id"], "rejected_by_technician")
    return OkResponse()


@router.post("/queue/{queue_id}/edit", response_model=SuggestionApproveResponse)
async def edit_and_post_suggestion(
    queue_id: str,
    body: SuggestionEditRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_technician)],
) -> SuggestionApproveResponse:
    tenant_id = current_user["tenant_id"]
    row = await _get_queue_entry(db, tenant_id, queue_id)
    _assert_can_action_queue_entry(current_user, row)
    ticket_id = row["ticket_id"]
    await _assert_ticket_acknowledged(db, tenant_id, ticket_id, current_user)

    result = await comment_poster.post_and_track(
        db, tenant_id, ticket_id, body.edited_comment,
        actor=current_user["user_id"],
        reporter_account_id=row["reporter_account_id"],
    )
    jsm_comment_id = result["jsm_comment_id"]

    await db.execute(
        sa_text(
            "UPDATE low_confidence_queue SET resolved_at = :now, resolved_by = :by, "
            "resolution_action = 'edited_and_posted' WHERE queue_id = :qid"
        ),
        {"now": _NOW(), "by": current_user["user_id"], "qid": queue_id},
    )
    await _sync_audit_log_action(db, tenant_id, ticket_id, "comment_posted", jsm_comment_id)

    return SuggestionApproveResponse(jsm_comment_id=jsm_comment_id, posted_at=datetime.now(timezone.utc))


# ── End-user ticket submit ────────────────────────────────────────────────────

@router.post("/submit")
@limiter.limit(_settings.rate_limit_ticket_submit)
async def submit_ticket(
    request: Request,
    body: TicketSubmit,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
) -> dict:
    tenant_id = current_user["tenant_id"]
    # category_hint is the reporter's free-text guess (e.g. "Hardware") — not
    # a valid Jira issuetype, so it can't be sent as one (that was the bug:
    # every submission failed with an opaque Jira 400). Fold it into the
    # description instead; AURA's real category comes from triage_node once
    # the ticket enters the pipeline.
    description = body.description
    if body.category_hint:
        description = f"**Reported category:** {body.category_hint}\n\n{description}"

    try:
        async with itsm_client.get_itsm_client(tenant_id) as itsm:
            ticket_id = await itsm.create_ticket(summary=body.summary, description=description)
    except httpx.HTTPStatusError as exc:
        log.error("tickets.submit_failed", status=exc.response.status_code, body=exc.response.text)
        raise HTTPException(
            status_code=502,
            detail="The ITSM provider rejected the ticket. Please try again or contact IT support directly.",
        ) from exc

    await db.execute(
        sa_text(
            "INSERT INTO user_submitted_tickets (tenant_id, ticket_id, user_id, submitted_at) "
            "VALUES (:tenant_id, :tid, :uid, :now)"
        ),
        {"tenant_id": tenant_id, "tid": ticket_id, "uid": current_user["user_id"], "now": _NOW()},
    )
    return {"ticket_id": ticket_id, "message": "Ticket created successfully"}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _sync_audit_log_action(
    db: AsyncSession, tenant_id: str, ticket_id: str, action_taken: str, jsm_comment_id: str | None = None,
) -> None:
    """Reflect a technician's queue decision (approve/edit/reject) onto the
    ticket's latest audit_log row so GET /tickets shows the true outcome
    instead of the stale 'held_low_confidence' it was queued under.
    """
    await db.execute(
        sa_text(
            "UPDATE audit_log SET action_taken = :action, "
            "jsm_comment_id = COALESCE(:cid, jsm_comment_id) "
            "WHERE entry_id = (SELECT entry_id FROM audit_log WHERE tenant_id = :tenant_id AND ticket_id = :tid "
            "ORDER BY created_at DESC LIMIT 1)"
        ),
        {"action": action_taken, "cid": jsm_comment_id, "tenant_id": tenant_id, "tid": ticket_id},
    )


async def _get_queue_entry(db: AsyncSession, tenant_id: str, queue_id: str) -> dict:
    result = await db.execute(
        sa_text(
            "SELECT queue_id, ticket_id, formatted_comment, reporter_account_id, resolved_at, team_id "
            "FROM low_confidence_queue WHERE tenant_id = :tenant_id AND queue_id = :qid"
        ),
        {"tenant_id": tenant_id, "qid": queue_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Queue entry not found")
    if row["resolved_at"] is not None:
        raise HTTPException(status_code=409, detail="Queue entry already resolved")
    return dict(row)


async def _get_active_comment_rollback(db: AsyncSession, tenant_id: str, ticket_id: str) -> str | None:
    """The most recent not-yet-rolled-back "comment_posted" rollback action
    for this ticket, if any — used both to decide whether to show a Rollback
    control and to find what to roll back when it's clicked."""
    row = (await db.execute(
        sa_text(
            "SELECT action_id FROM rollback_store WHERE tenant_id = :tenant_id AND ticket_id = :tid "
            "AND action_type = 'comment_posted' AND rolled_back_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"tenant_id": tenant_id, "tid": ticket_id},
    )).first()
    return row[0] if row else None


async def _assert_can_action_ticket(db: AsyncSession, current_user: dict, ticket_id: str) -> None:
    """Same team-ownership rule as _assert_can_action_queue_entry, but for
    routes keyed on a bare ticket_id (no queue row to read team_id from)."""
    if current_user["role"] == "admin":
        return
    row = (await db.execute(
        sa_text(
            "SELECT cc.team_id FROM audit_log a "
            "LEFT JOIN category_config cc ON cc.tenant_id = a.tenant_id AND cc.name = a.category "
            "WHERE a.tenant_id = :tenant_id AND a.ticket_id = :tid ORDER BY a.created_at DESC LIMIT 1"
        ),
        {"tenant_id": current_user["tenant_id"], "tid": ticket_id},
    )).first()
    team_id = row[0] if row else None
    if team_id and team_id != current_user["team_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This ticket belongs to another team — you can view it but not act on it.",
        )


async def _assert_ticket_acknowledged(
    db: AsyncSession, tenant_id: str, ticket_id: str, current_user: dict,
) -> None:
    """A technician must acknowledge a ticket (AssignmentControl's
    "Acknowledge" action) before posting a comment on it — acknowledging is
    the "I'm actually looking at this" signal and is what flips the real
    ticket to In Progress. Without this gate a technician could approve/edit
    a queued suggestion sight-unseen. Admins bypass this, same as the
    team-ownership check above; they have no assignment of their own to
    acknowledge against.
    """
    if current_user["role"] == "admin":
        return
    row = (await db.execute(
        sa_text(
            "SELECT acknowledged_at FROM ticket_assignments "
            "WHERE tenant_id = :tenant_id AND ticket_id = :tid AND is_current = 1"
        ),
        {"tenant_id": tenant_id, "tid": ticket_id},
    )).mappings().first()
    if row is None or row["acknowledged_at"] is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Acknowledge this ticket before posting a comment on it.",
        )


def _assert_can_action_queue_entry(current_user: dict, row: dict) -> None:
    """A technician may only approve/edit/reject queue items for their own
    team — everything else is visible (GET /queue has no team filter) but
    read-only. Admins bypass this; they have no team_id of their own."""
    if current_user["role"] == "admin":
        return
    if row["team_id"] != current_user["team_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This ticket belongs to another team — you can view it but not act on it.",
        )
