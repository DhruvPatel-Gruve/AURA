"""Scheduled job: incremental knowledge ingestion.

Fired every N hours by APScheduler. Loops over every active tenant, creates
a fresh DB session, instantiates the pipeline, consumes the async generator
to drive execution, and logs the final summary. One tenant's exception is
caught and logged so the sweep continues to the next tenant and APScheduler
keeps scheduling future runs.
"""

import uuid

from app.core.logging import get_logger
from app.db.sqlite import _get_session_factory, get_session
from app.rag.ingestion_pipeline import IngestionPipeline
from app.services import ingestion_lock, kill_switch, tenant_registry

log = get_logger(__name__)


async def run_ingestion_sync() -> None:
    """Entry point called by APScheduler — must be a plain async function."""
    async with get_session() as db:
        tenant_ids = await tenant_registry.list_active_tenant_ids(db)

    for tenant_id in tenant_ids:
        await _sync_one_tenant(tenant_id)


async def _sync_one_tenant(tenant_id: str) -> None:
    if not kill_switch.is_enabled(tenant_id):
        log.info("ingestion_sync.skipped", tenant_id=tenant_id, reason="kill_switch_off")
        return

    # Shares app/services/ingestion_lock with the manual POST /ingestion/trigger
    # route — prevents a manual trigger and this scheduled run from both
    # passing Qdrant's dedup check for the SAME tenant before either upserts
    # (double-embedding). Unrelated tenants are never blocked by each other.
    if not await ingestion_lock.try_acquire(tenant_id):
        log.info("ingestion_sync.skipped", tenant_id=tenant_id, reason="run_already_in_progress")
        return

    run_id = str(uuid.uuid4())
    log.info("ingestion_sync.starting", tenant_id=tenant_id, run_id=run_id)

    session_factory = _get_session_factory()
    try:
        async with session_factory() as db:
            pipeline = IngestionPipeline(db=db, tenant_id=tenant_id)
            try:
                async for event in pipeline.run(run_id=run_id):
                    log.info(
                        "ingestion_sync.progress",
                        tenant_id=tenant_id,
                        run_id=run_id,
                        status=event["status"],
                        pct=event["progress_pct"],
                        indexed=event["tickets_indexed"],
                        skipped=event["tickets_skipped"],
                        chunks=event["chunks_created"],
                    )
            except Exception as exc:
                # APScheduler swallows exceptions by default; we re-log here for
                # visibility then let the scheduler continue its schedule.
                log.error("ingestion_sync.failed", tenant_id=tenant_id, run_id=run_id, error=str(exc))
    finally:
        ingestion_lock.release(tenant_id)
