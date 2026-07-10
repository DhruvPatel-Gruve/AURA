"""Scheduled job: SLA checker + stale claim expiry.

Fired every minute by APScheduler.
  - sla_engine.check_all_active() scans every non-resolved SLA event and
    emits SLA_WARNING / SLA_BREACHED WebSocket events for thresholds crossed.
    It scans across all tenants in one query (rows already carry tenant_id),
    so it's called once, not per-tenant.
  - collision_service.expire_stale_claims() bulk-expires collision claims
    whose expiry timestamp has passed — also a cross-tenant scan, since
    "expired" is a plain timestamp comparison with no per-tenant behaviour.

Both operations are lightweight table scans — intentionally cheap so they
can run every 60 seconds without measurable overhead.
"""

from app.core.logging import get_logger
from app.db.sqlite import get_session
from app.services import collision_service, sla_engine

log = get_logger(__name__)


async def run_sla_checker() -> None:
    """Entry point called by APScheduler — plain async function."""
    async with get_session() as db:
        try:
            await sla_engine.check_all_active(db)
        except Exception as exc:
            log.error("sla_checker.sla_failed", error=str(exc))

        try:
            expired_count = await collision_service.expire_stale_claims(db)
            if expired_count:
                log.info("sla_checker.claims_expired", count=expired_count)
        except Exception as exc:
            log.error("sla_checker.claims_failed", error=str(exc))
