"""Live Jira workflow status cache — Open / In Progress / Resolved (whatever
the connected JSM project's workflow actually defines).

Kept in its own table rather than on audit_log, which is append-only and must
never be UPDATEd. Written from three places, each best-effort:
  - audit_finalizer_node: initial status when the pipeline first processes a ticket
  - transition_service: whenever AURA moves a ticket to a new status
  - jsm_poller: refreshed for every open ticket fetched each poll cycle
"""

from datetime import datetime, timezone

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_status(db: AsyncSession, tenant_id: str, ticket_id: str, status: str | None) -> None:
    if not status:
        return
    await db.execute(
        sa_text(
            "INSERT INTO ticket_status (tenant_id, ticket_id, status, updated_at) "
            "VALUES (:tenant, :tid, :status, :now) "
            "ON CONFLICT(tenant_id, ticket_id) DO UPDATE SET status = :status, updated_at = :now"
        ),
        {"tenant": tenant_id, "tid": ticket_id, "status": status, "now": datetime.now(timezone.utc).isoformat()},
    )


async def get_status(db: AsyncSession, tenant_id: str, ticket_id: str) -> str | None:
    row = (await db.execute(
        sa_text("SELECT status FROM ticket_status WHERE tenant_id = :tenant AND ticket_id = :tid"),
        {"tenant": tenant_id, "tid": ticket_id},
    )).first()
    return row[0] if row else None
