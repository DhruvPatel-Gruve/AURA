"""Scheduled job: assignment timeout checker.

Fired every minute by APScheduler. Calls assignment_service.check_overdue()
once per active tenant, which reassigns unacknowledged tickets past
assignment_timeout_minutes to another technician on the team, or re-notifies
+ escalates when no alternative technician is available.

A lightweight table scan per tenant — intentionally cheap so it can run
every 60 seconds without measurable overhead, same rationale as
sla_checker.py. One tenant's failure is logged and skipped rather than
aborting the rest of the sweep.
"""

from app.core.logging import get_logger
from app.db.sqlite import get_session
from app.services import assignment_service, tenant_registry

log = get_logger(__name__)


async def run_assignment_timeout_checker() -> None:
    """Entry point called by APScheduler — plain async function."""
    async with get_session() as db:
        tenant_ids = await tenant_registry.list_active_tenant_ids(db)

    for tenant_id in tenant_ids:
        async with get_session() as db:
            try:
                await assignment_service.check_overdue(db, tenant_id)
            except Exception as exc:
                log.error("assignment_timeout_checker.failed", tenant_id=tenant_id, error=str(exc))
