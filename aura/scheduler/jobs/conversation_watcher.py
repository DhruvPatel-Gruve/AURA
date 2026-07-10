"""Scheduled job: conversation watcher.

Fired on the same interval as jsm_poller (default 5 min — sparser than the
1-minute sla_checker/assignment_timeout_checker jobs, since each active
conversation costs a Jira fetch plus at least one LLM call).

Calls conversation_service.check_for_replies() then check_idle_timeouts()
once per active tenant, each independently wrapped so one tenant's failure
doesn't block the rest of the sweep or the idle-timeout pass.
"""

from app.core.logging import get_logger
from app.db.sqlite import get_session
from app.services import conversation_service, tenant_registry

log = get_logger(__name__)


async def run_conversation_watcher() -> None:
    """Entry point called by APScheduler — plain async function."""
    async with get_session() as db:
        tenant_ids = await tenant_registry.list_active_tenant_ids(db)

    for tenant_id in tenant_ids:
        async with get_session() as db:
            try:
                await conversation_service.check_for_replies(db, tenant_id)
            except Exception as exc:
                log.error("conversation_watcher.replies_failed", tenant_id=tenant_id, error=str(exc))

            try:
                await conversation_service.check_idle_timeouts(db, tenant_id)
            except Exception as exc:
                log.error("conversation_watcher.idle_failed", tenant_id=tenant_id, error=str(exc))
