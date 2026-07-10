"""Conversation service — ongoing dialogue with the ticket reporter after
AURA's initial resolution comment, until the reporter confirms it's fixed
or goes quiet long enough that AURA assumes so.

Responsibilities:
  1. start_tracking()      — begin tracking right after AURA's first comment.
  2. check_for_replies()   — periodic scan: detect new reporter replies and
                             run one conversation turn for each.
  3. check_idle_timeouts() — periodic scan: auto-resolve conversations that
                             have gone quiet past conversation_idle_timeout_hours.

Deliberately NOT the 11-node graph — a reply doesn't need re-triage or
re-assignment. It's a small linear flow:
classify (confirmation?) -> transition+close, or retrieve+generate+gate.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from openai import AsyncOpenAI
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.nodes.autonomy_node import get_auto_comment_enabled
from app.agents.nodes.confidence_gate_node import apply_confidence_gate
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.qdrant_client import ensure_tenant_collection
from app.models.jsm import JSMComment, JSMTicket
from app.rag.retriever import HybridRetriever
from app.services import kill_switch, transition_service

log = get_logger(__name__)

_FALLBACK_IDLE_TIMEOUT_HOURS = 24
_TOP_K = 5
_MAX_CONTEXT_CHARS = 4000

_CONFIRMATION_SYSTEM_PROMPT = (
    "You are analyzing a reply on an IT support ticket that AURA previously "
    "responded to. Determine whether this reply confirms the issue is now "
    "resolved/fixed (e.g. \"thanks, that worked\", \"all good now\").\n"
    "Respond with valid JSON only, no markdown: {\"confirmed\": true or false}"
)

_REPLY_SYSTEM_PROMPT = (
    "You are an IT support assistant continuing a conversation on a support "
    "ticket. The reporter has replied with a further question or issue. "
    "Resolve it using ONLY the provided context from previously resolved "
    "tickets and the conversation so far. Do not use general knowledge or "
    "make up steps. If the context is insufficient, set confidence below 0.5.\n\n"
    "Respond with valid JSON only (no markdown, no explanation):\n"
    '{"solution": "<step-by-step reply in Markdown>", '
    '"confidence": <float 0.0-1.0>, '
    '"citations": ["<ticket_id>", ...]}'
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_dt(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Tracking lifecycle ──────────────────────────────────────────────────────

async def start_tracking(
    db: AsyncSession, tenant_id: str, ticket_id: str, reporter_account_id: str | None,
) -> bool:
    """Begin tracking a ticket's conversation right after its first comment.

    INSERT OR IGNORE — safe to call more than once for the same ticket (e.g.
    if both an automated post and a technician approval somehow both fire).

    Returns True if a new row was inserted, False if one already existed.
    """
    now = _now_iso()
    result = await db.execute(
        sa_text(
            "INSERT OR IGNORE INTO ticket_conversations "
            "(tenant_id, ticket_id, status, reporter_account_id, last_aura_comment_at, turn_count, created_at, updated_at) "
            "VALUES (:tenant, :tid, 'active', :rid, :now, 1, :now, :now)"
        ),
        {"tenant": tenant_id, "tid": ticket_id, "rid": reporter_account_id, "now": now},
    )
    await db.commit()
    return result.rowcount > 0


async def touch(db: AsyncSession, tenant_id: str, ticket_id: str) -> None:
    """Bump the watermark on an existing conversation — called after any
    comment is posted (AURA auto-post or a technician's approve/edit), so
    the idle-timeout clock resets and the conversation is reactivated if it
    had previously been auto-resolved (e.g. the reporter reopened it).

    No-op if `ticket_id` isn't tracked yet (start_tracking() handles that).
    """
    now = _now_iso()
    await db.execute(
        sa_text(
            "UPDATE ticket_conversations SET status = 'active', "
            "last_aura_comment_at = :now, turn_count = turn_count + 1, updated_at = :now "
            "WHERE tenant_id = :tenant AND ticket_id = :tid"
        ),
        {"now": now, "tenant": tenant_id, "tid": ticket_id},
    )
    await db.commit()


# ── Periodic scans ────────────────────────────────────────────────────────────

async def check_for_replies(db: AsyncSession, tenant_id: str) -> None:
    """Scan one tenant's active conversations for a new reply from the reporter."""
    if not kill_switch.is_enabled(tenant_id):
        log.info("conversation_service.skipped", tenant_id=tenant_id, reason="kill_switch_off")
        return

    rows = (await db.execute(
        sa_text(
            "SELECT ticket_id, reporter_account_id, last_aura_comment_at, turn_count "
            "FROM ticket_conversations WHERE tenant_id = :tid AND status = 'active'"
        ),
        {"tid": tenant_id},
    )).mappings().all()

    for row in rows:
        ticket_id = row["ticket_id"]
        reporter_id = row["reporter_account_id"]
        watermark = _parse_dt(row["last_aura_comment_at"])

        try:
            from app.services.itsm_client import get_itsm_client
            async with get_itsm_client(tenant_id) as itsm:
                ticket = await itsm.get_ticket(ticket_id)
        except Exception as exc:
            log.error("conversation_service.fetch_failed", ticket_id=ticket_id, error=str(exc))
            continue

        if ticket is None:
            continue

        reply = _find_new_reporter_comment(ticket.comments, reporter_id, watermark)
        if reply is None:
            continue

        try:
            await _run_conversation_turn(db, tenant_id, ticket, reply, reporter_id)
        except Exception as exc:
            log.error("conversation_service.turn_failed", ticket_id=ticket_id, error=str(exc))


async def check_idle_timeouts(db: AsyncSession, tenant_id: str) -> None:
    """Auto-resolve one tenant's conversations that have gone quiet past the
    idle timeout."""
    row = (await db.execute(
        sa_text("SELECT conversation_idle_timeout_hours FROM platform_config WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )).first()
    timeout_hours = row[0] if row and row[0] is not None else _FALLBACK_IDLE_TIMEOUT_HOURS

    rows = (await db.execute(
        sa_text(
            "SELECT ticket_id, last_aura_comment_at FROM ticket_conversations "
            "WHERE tenant_id = :tid AND status = 'active'"
        ),
        {"tid": tenant_id},
    )).mappings().all()

    now = _now()
    for row in rows:
        last_comment_at = _parse_dt(row["last_aura_comment_at"])
        if now - last_comment_at < timedelta(hours=timeout_hours):
            continue

        ticket_id = row["ticket_id"]
        try:
            await _close_conversation(db, tenant_id, ticket_id, closing_comment=(
                "Resolving this ticket due to inactivity — please reopen or "
                "comment if the issue persists."
            ))
        except Exception as exc:
            log.error("conversation_service.idle_close_failed", ticket_id=ticket_id, error=str(exc))


# ── Internal: one conversation turn ──────────────────────────────────────────

async def _run_conversation_turn(
    db: AsyncSession,
    tenant_id: str,
    ticket: JSMTicket,
    reply: JSMComment,
    reporter_account_id: str | None,
) -> None:
    settings = get_settings()
    confirmed = await _classify_confirmation(reply.body, settings)

    if confirmed:
        await _close_conversation(db, tenant_id, ticket.ticket_id, closing_comment=None)
        return

    # Not a confirmation — generate a follow-up reply using the same
    # confidence-gate decision as the initial resolution.
    collection = await ensure_tenant_collection(tenant_id)
    retriever = HybridRetriever()
    query_text = f"{ticket.summary}\n{reply.body}"
    chunks = await retriever.retrieve(query_text=query_text, top_k=_TOP_K, collection=collection)

    if not chunks:
        solution, confidence, citations = (
            "Unable to generate a reliable resolution from the available knowledge base.",
            0.0,
            [],
        )
        formatted_comment = f"**AURA** _(Confidence: 0%)_\n\n{solution}"
    else:
        formatted_comment, confidence, citations = await _generate_reply(
            settings, ticket, reply, chunks
        )

    category_row = (await db.execute(
        sa_text(
            "SELECT category FROM audit_log WHERE tenant_id = :tenant AND ticket_id = :tid "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"tenant": tenant_id, "tid": ticket.ticket_id},
    )).first()
    category = category_row[0] if category_row else None
    auto_comment_enabled = await get_auto_comment_enabled(db, tenant_id, category)

    # apply_confidence_gate posts (via comment_poster.post_and_track, which
    # bumps the watermark itself) or queues for review. If held for review,
    # last_aura_comment_at stays put until a technician approves/edits —
    # that path also goes through post_and_track, so the watermark still
    # moves forward the same way once someone actually replies.
    await apply_confidence_gate(
        tenant_id=tenant_id,
        ticket_id=ticket.ticket_id,
        formatted_comment=formatted_comment,
        confidence=confidence,
        citations=citations,
        assigned_team=None,
        auto_comment_enabled=auto_comment_enabled,
        reporter_account_id=reporter_account_id,
    )


async def _close_conversation(
    db: AsyncSession, tenant_id: str, ticket_id: str, closing_comment: str | None,
) -> None:
    if closing_comment:
        try:
            from app.services.itsm_client import get_itsm_client
            async with get_itsm_client(tenant_id) as itsm:
                await itsm.post_comment_markdown(ticket_id, closing_comment)
        except Exception as exc:
            log.error("conversation_service.closing_comment_failed", ticket_id=ticket_id, error=str(exc))

    # Resolved unconditionally — inactivity-close doesn't depend on the
    # per-category autonomy toggle, only In Progress -> Resolved reachability.
    await transition_service.try_transition(
        tenant_id, ticket_id, transition_service.resolved_status_name(tenant_id), original_status=None
    )

    await db.execute(
        sa_text(
            "UPDATE ticket_conversations SET status = 'resolved', updated_at = :now "
            "WHERE tenant_id = :tenant AND ticket_id = :tid"
        ),
        {"now": _now_iso(), "tenant": tenant_id, "tid": ticket_id},
    )
    await db.commit()
    log.info("conversation_service.resolved", ticket_id=ticket_id)


# ── Internal: LLM calls ───────────────────────────────────────────────────────

async def _classify_confirmation(reply_text: str, settings) -> bool:
    try:
        client = AsyncOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            timeout=settings.ollama_timeout_seconds,
        )
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.ollama_model,
                messages=[
                    {"role": "system", "content": _CONFIRMATION_SYSTEM_PROMPT},
                    {"role": "user", "content": reply_text[:1000]},
                ],
                max_tokens=32,
                temperature=0,
            ),
            timeout=settings.ollama_timeout_seconds,
        )
        raw = (response.choices[0].message.content or "{}").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return bool(json.loads(raw).get("confirmed", False))
    except Exception as exc:
        log.error("conversation_service.classify_failed", error=str(exc))
        return False  # safe default — keep the conversation going rather than closing incorrectly


async def _generate_reply(settings, ticket: JSMTicket, reply: JSMComment, chunks: list) -> tuple[str, float, list[str]]:
    context_parts: list[str] = []
    total_chars = 0
    for i, chunk in enumerate(chunks, 1):
        block = f"[{i}] {chunk['ticket_id']} ({chunk['chunk_type']}):\n{chunk['content']}"
        if total_chars + len(block) > _MAX_CONTEXT_CHARS:
            break
        context_parts.append(block)
        total_chars += len(block)

    formatted_context = "\n\n".join(context_parts)
    valid_ticket_ids = {c["ticket_id"] for c in chunks}

    user_prompt = (
        f"Original Ticket:\nTitle: {ticket.summary}\n\n"
        f"Reporter's Follow-up:\n{reply.body}\n\n"
        f"Context from Resolved Tickets:\n{formatted_context}"
    )

    solution = "Unable to generate a reliable resolution from the available knowledge base."
    confidence = 0.5
    citations: list[str] = []

    try:
        client = AsyncOpenAI(
            base_url=settings.ollama_base_url,
            api_key="ollama",
            timeout=settings.ollama_timeout_seconds,
        )
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.ollama_model,
                messages=[
                    {"role": "system", "content": _REPLY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=1024,
                temperature=0.2,
            ),
            timeout=settings.ollama_timeout_seconds,
        )
        raw = (response.choices[0].message.content or "{}").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        parsed = json.loads(raw)
        solution = parsed.get("solution") or solution
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        raw_cits = parsed.get("citations") or []
        citations = [c for c in raw_cits if c in valid_ticket_ids]
    except Exception as exc:
        log.error("conversation_service.reply_generation_failed", ticket_id=ticket.ticket_id, error=str(exc))

    formatted_comment = (
        f"**AURA** _(Confidence: {confidence * 100:.0f}%)_\n\n"
        + solution
        + "\n\n---\n**Sources:** "
        + (", ".join(f"[{tid}]" for tid in citations) if citations else "_none_")
    )
    return formatted_comment, confidence, citations


# ── Internal: reply detection ─────────────────────────────────────────────────

def _find_new_reporter_comment(
    comments: list[JSMComment],
    reporter_account_id: str | None,
    watermark: datetime,
) -> JSMComment | None:
    """Return the most recent comment authored by the reporter after
    watermark, or None. Comments from AURA (the service account) or a
    technician never match, since neither is the reporter's accountId."""
    if not reporter_account_id:
        return None
    candidates = [
        c for c in comments
        if c.author_account_id == reporter_account_id and c.created > watermark
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.created)
