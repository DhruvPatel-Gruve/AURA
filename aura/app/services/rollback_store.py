"""Rollback store — register and execute reversible JSM actions.

Every time AURA posts a comment to JSM (confidence_gate_node, Path A), it
immediately registers a RollbackRecord so the action can be undone with one
click from the Admin Rollback History page. At L2+ autonomy, status
transitions are also registered the same way.

Two JSM actions are reversible today:
    comment_posted      → DELETE /rest/api/3/issue/{ticket_id}/comment/{comment_id}
    ticket_transitioned → POST /rest/api/3/issue/{ticket_id}/transitions (reverse transition id)

The rollback_call column stores the reverse operation as JSON, e.g.:
    { "method": "DELETE", "url": "/rest/api/3/issue/{tid}/comment/{cid}", "body": null }
    { "method": "POST", "url": "/rest/api/3/issue/{tid}/transitions", "body": {"transition": {"id": "5"}} }

Executing a rollback:
  1. Reads the rollback_call JSON from SQLite.
  2. Calls the matching jsm_client method for action_type (no generic HTTP
     dispatch — each action_type has a small, explicit handler below).
  3. Stamps rolled_back_at and rolled_back_by to prevent double-execution.
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Public API ────────────────────────────────────────────────────────────────

async def register(
    db: AsyncSession,
    *,
    tenant_id: str,
    action_type: str,
    ticket_id: str,
    rollback_call: dict,
    actor: str,
) -> str:
    """Register a reversible action and return its action_id (UUID).

    Args:
        action_type:   "comment_posted" (only type in L1 POC)
        ticket_id:     JSM ticket key, e.g. "IT-1234"
        rollback_call: { method, url, body } describing the reverse HTTP call
        actor:         user_id or "AURA_AGENT"

    Returns:
        action_id (UUID string) — stored in the audit_log.rollback_ref field
    """
    action_id = str(uuid.uuid4())
    await db.execute(
        sa_text(
            "INSERT INTO rollback_store "
            "(action_id, tenant_id, ticket_id, action_type, rollback_call, actor, created_at) "
            "VALUES (:aid, :tenant, :tid, :atype, :rcall, :actor, :now)"
        ),
        {
            "aid": action_id,
            "tenant": tenant_id,
            "tid": ticket_id,
            "atype": action_type,
            "rcall": json.dumps(rollback_call),
            "actor": actor,
            "now": _now_iso(),
        },
    )
    await db.commit()
    log.info("rollback.registered", action_id=action_id, ticket_id=ticket_id, action_type=action_type)
    return action_id


async def execute(
    db: AsyncSession,
    tenant_id: str,
    action_id: str,
    triggered_by: str,
) -> dict:
    """Execute the reverse action for a previously registered rollback.

    Guards:
      - Raises ValueError if the action_id does not exist (or belongs to a
        different tenant — same error, so a technician probing a foreign
        action_id learns nothing beyond "not found").
      - Raises ValueError if the rollback has already been executed
        (rolled_back_at is not NULL) to prevent double-deletion.

    Returns:
        { success: bool, details: str }
    """
    result = await db.execute(
        sa_text(
            "SELECT action_id, ticket_id, action_type, rollback_call, rolled_back_at "
            "FROM rollback_store WHERE action_id = :aid AND tenant_id = :tenant"
        ),
        {"aid": action_id, "tenant": tenant_id},
    )
    row = result.mappings().first()

    if row is None:
        raise ValueError(f"Rollback action {action_id!r} not found.")

    if row["rolled_back_at"] is not None:
        raise ValueError(
            f"Action {action_id!r} has already been rolled back at {row['rolled_back_at']}."
        )

    rollback_call = json.loads(row["rollback_call"])
    ticket_id: str = row["ticket_id"]
    action_type: str = row["action_type"]

    # Claim the row BEFORE dispatching, conditioned on it still being
    # unclaimed. Two concurrent `execute()` calls for the same action_id can
    # both pass the SELECT check above before either commits an UPDATE — the
    # original code then let both proceed to `_dispatch()`, which could fire
    # the same reverse Jira call twice (e.g. two transition-back requests).
    # This UPDATE is the actual atomic race-closer: only one caller's WHERE
    # clause matches, so only one gets rowcount=1.
    claim = await db.execute(
        sa_text(
            "UPDATE rollback_store "
            "SET rolled_back_at = :now, rolled_back_by = :by "
            "WHERE action_id = :aid AND rolled_back_at IS NULL"
        ),
        {"now": _now_iso(), "by": triggered_by, "aid": action_id},
    )
    if claim.rowcount == 0:
        await db.rollback()
        raise ValueError(f"Action {action_id!r} has already been rolled back.")
    await db.commit()

    # Execute the reverse operation. If this raises, the row is left claimed
    # (rolled_back_at set) rather than reverted — a failed-but-claimed
    # rollback is surfaced via the exception and should be retried manually
    # via a fresh action, not silently re-attempted automatically.
    details = await _dispatch(tenant_id, ticket_id, action_type, rollback_call)

    log.info(
        "rollback.executed",
        action_id=action_id,
        ticket_id=ticket_id,
        triggered_by=triggered_by,
    )
    return {"success": True, "details": details}


async def get_history(
    db: AsyncSession,
    *,
    tenant_id: str,
    ticket_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Return paginated rollback history for the Admin Rollback History page."""
    clauses: list[str] = ["tenant_id = :tenant_id"]
    params: dict = {"tenant_id": tenant_id}

    if ticket_id:
        clauses.append("ticket_id = :ticket_id")
        params["ticket_id"] = ticket_id
    if date_from:
        clauses.append("created_at >= :date_from")
        params["date_from"] = date_from.isoformat()
    if date_to:
        clauses.append("created_at <= :date_to")
        params["date_to"] = date_to.isoformat()

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    count_result = await db.execute(
        sa_text(f"SELECT COUNT(*) FROM rollback_store{where}"), params
    )
    total: int = count_result.scalar() or 0

    offset = (page - 1) * page_size
    rows_result = await db.execute(
        sa_text(
            f"SELECT action_id, ticket_id, action_type, actor, created_at,"
            f"       rolled_back_at, rolled_back_by"
            f" FROM rollback_store{where}"
            f" ORDER BY created_at DESC"
            f" LIMIT {page_size} OFFSET {offset}"
        ),
        params,
    )
    items = [dict(r) for r in rows_result.mappings().all()]

    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // page_size)),
    }


# ── Dispatch ──────────────────────────────────────────────────────────────────

async def _dispatch(tenant_id: str, ticket_id: str, action_type: str, rollback_call: dict) -> str:
    """Route the rollback_call to the appropriate ITSM client method."""
    from app.services.itsm_client import get_itsm_client

    if action_type == "comment_posted":
        url: str = rollback_call.get("url", "")
        # Extract comment_id from URL path: .../comment/{comment_id}
        parts = url.rstrip("/").split("/")
        comment_id = parts[-1] if parts else ""
        if not comment_id:
            raise ValueError(f"Cannot extract comment_id from rollback_call URL: {url!r}")

        async with get_itsm_client(tenant_id) as itsm:
            deleted = await itsm.delete_comment(ticket_id, comment_id)

        if not deleted:
            return (
                f"This ITSM provider doesn't support deleting comments — "
                f"the original comment (id {comment_id}) on ticket {ticket_id} "
                f"was not removed."
            )
        return f"Comment {comment_id} deleted from ticket {ticket_id}."

    if action_type == "ticket_transitioned":
        transition_id = ((rollback_call.get("body") or {}).get("transition") or {}).get("id")
        if not transition_id:
            raise ValueError(f"Cannot extract transition id from rollback_call: {rollback_call!r}")

        async with get_itsm_client(tenant_id) as itsm:
            await itsm.transition_issue(ticket_id, transition_id)

        return f"Ticket {ticket_id} transitioned back via transition {transition_id}."

    raise ValueError(f"Unsupported rollback action_type: {action_type!r}")
