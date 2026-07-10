"""Scheduled job: JSM open-ticket poller.

Fired every N minutes by APScheduler. Loops over every active tenant; for
each newly created open ticket on that tenant's ITSM instance:
  1. Check whether the ticket has already been processed by AURA
     (present in audit_log or low_confidence_queue).
  2. If new: build initial AgentState and invoke the compiled LangGraph
     pipeline.

One tenant's fetch/pipeline failure is logged and the sweep moves on to the
next tenant — a broken Jira token for Tenant A must never stall Tenant B's
polling.

Open -> In Progress is no longer transitioned here — it now happens when a
technician acknowledges the ticket (see tickets.py's acknowledge_ticket),
which is the real "someone is actively working this" signal. Tickets AURA
auto-resolves without any technician ever acknowledging go straight from
Open to Resolved, which is an accurate reflection of what actually happened.

Cursor: last_poll_timestamp in platform_config advances AFTER all tickets in
a tenant's batch are processed, so a crash mid-batch re-processes that
tenant from the old cursor (safe — queue/log inserts are idempotent via
INSERT OR REPLACE / OR IGNORE).
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text as sa_text

from app.core.logging import get_logger
from app.db.sqlite import get_session
from app.models.agent_state import make_initial_state
from app.services import kill_switch, tenant_registry, ticket_status
from app.services.itsm_client import get_itsm_client

log = get_logger(__name__)

# Belt-and-suspenders per-ticket ceiling — every LLM/HTTP call inside the
# graph already has its own timeout, but this guarantees one anomalous
# ticket can never stall the whole batch (and thus every subsequent
# scheduled poll, since the job runs with max_instances=1) indefinitely.
_PIPELINE_TIMEOUT_SECONDS = 180


async def run_jsm_poller() -> None:
    """Entry point called by APScheduler — plain async function."""
    async with get_session() as db:
        tenant_ids = await tenant_registry.list_active_tenant_ids(db)

    for tenant_id in tenant_ids:
        try:
            await _poll_one_tenant(tenant_id)
        except Exception as exc:
            log.error("jsm_poller.tenant_failed", tenant_id=tenant_id, error=str(exc))


async def _poll_one_tenant(tenant_id: str) -> None:
    if not kill_switch.is_enabled(tenant_id):
        log.info("jsm_poller.skipped", tenant_id=tenant_id, reason="kill_switch_off")
        return

    # ── Step 1: read last-poll cursor ─────────────────────────────────────────
    async with get_session() as db:
        result = await db.execute(
            sa_text("SELECT last_poll_timestamp FROM platform_config WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        row = result.first()

    last_poll_ts: datetime | None = None
    if row and row[0]:
        try:
            last_poll_ts = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
        except ValueError:
            last_poll_ts = None

    now = datetime.now(timezone.utc)

    # ── Step 2: fetch open tickets from JSM ───────────────────────────────────
    tickets = []
    try:
        async with get_itsm_client(tenant_id) as itsm:
            tickets = await itsm.search_open_tickets(since=last_poll_ts)
    except Exception as exc:
        log.error("jsm_poller.fetch_failed", tenant_id=tenant_id, error=str(exc))
        return

    if not tickets:
        log.info("jsm_poller.no_new_tickets", tenant_id=tenant_id, since=str(last_poll_ts))
        await _advance_cursor(tenant_id, now)
        return

    log.info("jsm_poller.tickets_fetched", tenant_id=tenant_id, count=len(tickets), since=str(last_poll_ts))

    # Refresh the live status cache for every fetched ticket — cheap, and
    # keeps status current for tickets still moving through Open → In
    # Progress → Resolved while AURA is actively processing them.
    async with get_session() as db:
        for ticket in tickets:
            await ticket_status.set_status(db, tenant_id, ticket.ticket_id, ticket.status)

    # ── Step 3: check which tickets haven't been processed yet ───────────────
    ticket_ids = [t.ticket_id for t in tickets]
    already_processed = await _get_processed_ids(tenant_id, ticket_ids)

    new_tickets = [t for t in tickets if t.ticket_id not in already_processed]
    log.info(
        "jsm_poller.pipeline_candidates",
        tenant_id=tenant_id,
        total=len(tickets),
        already_processed=len(already_processed),
        new=len(new_tickets),
    )

    # ── Step 4: invoke agent pipeline for each new ticket ────────────────────
    # Import here to avoid circular imports at module load and to defer
    # LangGraph graph compilation until first actual use.
    from app.agents.graph import compiled_graph

    for ticket in new_tickets:
        raw_ticket = ticket.model_dump(mode="json")
        # Convert datetime objects to ISO strings for JSON-serializability
        for key in ("created", "resolved"):
            if raw_ticket.get(key) and not isinstance(raw_ticket[key], str):
                raw_ticket[key] = raw_ticket[key].isoformat()

        state = make_initial_state(tenant_id, ticket.ticket_id, raw_ticket)
        try:
            await asyncio.wait_for(
                compiled_graph.ainvoke(state), timeout=_PIPELINE_TIMEOUT_SECONDS
            )
            log.info("jsm_poller.pipeline_complete", tenant_id=tenant_id, ticket_id=ticket.ticket_id)
        except Exception as exc:
            log.error(
                "jsm_poller.pipeline_failed",
                tenant_id=tenant_id,
                ticket_id=ticket.ticket_id,
                error=str(exc),
            )
            # A mid-graph exception means audit_finalizer_node never ran, so
            # nothing would otherwise be written anywhere — the ticket would
            # just silently vanish. Write a minimal fallback row so it's at
            # least visible in the Admin Audit Log instead of untraceable.
            await _write_error_audit_entry(tenant_id, ticket.ticket_id, str(exc))

    # ── Step 5: advance cursor ────────────────────────────────────────────────
    await _advance_cursor(tenant_id, now)
    log.info("jsm_poller.cursor_advanced", tenant_id=tenant_id, to=now.isoformat())


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_processed_ids(tenant_id: str, ticket_ids: list[str]) -> set[str]:
    """Return ticket IDs that already have an audit_log or queue entry."""
    if not ticket_ids:
        return set()

    # Build parameterised IN clause
    placeholders = ", ".join(f":id{i}" for i in range(len(ticket_ids)))
    params = {f"id{i}": tid for i, tid in enumerate(ticket_ids)}
    params["tenant"] = tenant_id

    async with get_session() as db:
        result = await db.execute(
            sa_text(
                f"SELECT DISTINCT ticket_id FROM audit_log "
                f"WHERE tenant_id = :tenant AND ticket_id IN ({placeholders})"
            ),
            params,
        )
        in_audit = {row[0] for row in result.all()}

        result2 = await db.execute(
            sa_text(
                f"SELECT ticket_id FROM low_confidence_queue "
                f"WHERE tenant_id = :tenant AND ticket_id IN ({placeholders})"
            ),
            params,
        )
        in_queue = {row[0] for row in result2.all()}

    return in_audit | in_queue


async def _write_error_audit_entry(tenant_id: str, ticket_id: str, error: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    audit_steps = json.dumps([{
        "node_name": "jsm_poller",
        "timestamp": now,
        "decision": f"Pipeline crashed before completion: {error}",
        "metadata": {"error": error},
    }])
    async with get_session() as db:
        await db.execute(
            sa_text(
                "INSERT OR IGNORE INTO audit_log "
                "(entry_id, tenant_id, ticket_id, action_taken, audit_steps, created_at) "
                "VALUES (:eid, :tenant, :tid, 'pipeline_error', :steps, :now)"
            ),
            {"eid": str(uuid.uuid4()), "tenant": tenant_id, "tid": ticket_id, "steps": audit_steps, "now": now},
        )


async def _advance_cursor(tenant_id: str, ts: datetime) -> None:
    async with get_session() as db:
        await db.execute(
            sa_text(
                "UPDATE platform_config SET last_poll_timestamp = :ts, updated_at = :ts "
                "WHERE tenant_id = :tid"
            ),
            {"ts": ts.isoformat(), "tid": tenant_id},
        )
