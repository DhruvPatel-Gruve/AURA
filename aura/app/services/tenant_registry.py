"""Small shared helper — list active tenants for the scheduler jobs to loop
over. Every job (jsm_poller, sla_checker, assignment_timeout_checker,
conversation_watcher, ingestion_sync) now runs its per-tenant work in a loop
over this list instead of assuming a single tenant.
"""

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_active_tenant_ids(db: AsyncSession) -> list[str]:
    result = await db.execute(sa_text("SELECT tenant_id FROM tenants WHERE status = 'active'"))
    return [row[0] for row in result.all()]
