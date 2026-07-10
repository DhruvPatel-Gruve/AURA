"""Ingestion API — 3 endpoints, all scoped to the caller's tenant.

POST /api/v1/ingestion/trigger   — manually kick off an ingestion run
GET  /api/v1/ingestion/status    — status of the most recent run
GET  /api/v1/ingestion/runs      — paginated run history
"""

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import require_admin, require_manager
from app.db.sqlite import get_db
from app.models.jsm import IngestionRunSummary
from app.rag.ingestion_pipeline import IngestionPipeline
from app.services import ingestion_lock, kill_switch

log = get_logger(__name__)
router = APIRouter(prefix="/ingestion", tags=["ingestion"])


# ── Response schemas ──────────────────────────────────────────────────────────

class TriggerResponse(BaseModel):
    run_id: str
    message: str


class RunsResponse(BaseModel):
    runs: list[IngestionRunSummary]
    total: int
    page: int
    page_size: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/trigger", response_model=TriggerResponse, status_code=202)
async def trigger_ingestion(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> TriggerResponse:
    """Manually trigger an incremental ingestion run for the caller's tenant.

    Returns immediately with a run_id; the pipeline executes in the background.
    Returns 409 if a run is already in progress for this tenant (manual OR
    scheduled — both share the same per-tenant lock, see
    app/services/ingestion_lock.py). Returns 503 if this tenant's kill switch
    is active.
    """
    tenant_id = current_user["tenant_id"]

    if not kill_switch.is_enabled(tenant_id):
        raise HTTPException(status_code=503, detail="AURA is currently disabled (kill switch active).")

    if not await ingestion_lock.try_acquire(tenant_id):
        raise HTTPException(status_code=409, detail="An ingestion run is already in progress.")

    run_id = str(uuid.uuid4())

    async def _background(run_id: str) -> None:
        # Open a dedicated session — the request session closes after trigger returns
        from app.db.sqlite import _get_session_factory
        session_factory = _get_session_factory()
        try:
            async with session_factory() as bg_db:
                pipeline = IngestionPipeline(db=bg_db, tenant_id=tenant_id)
                async for event in pipeline.run(run_id=run_id):
                    log.info(
                        "ingestion.api_trigger_progress",
                        tenant_id=tenant_id,
                        run_id=run_id,
                        status=event["status"],
                        pct=event["progress_pct"],
                    )
        except Exception as exc:
            log.error("ingestion.api_trigger_failed", tenant_id=tenant_id, run_id=run_id, error=str(exc))
        finally:
            ingestion_lock.release(tenant_id)

    asyncio.create_task(_background(run_id))
    log.info("ingestion.triggered", tenant_id=tenant_id, run_id=run_id)
    return TriggerResponse(run_id=run_id, message="Ingestion run started.")


@router.get("/status", response_model=IngestionRunSummary | None)
async def get_ingestion_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
) -> IngestionRunSummary | None:
    """Return the most recent ingestion run record for the caller's tenant."""
    row = await db.execute(
        text(
            """
            SELECT run_id, started_at, completed_at, tickets_fetched,
                   tickets_indexed, tickets_skipped, chunks_created,
                   status, error_message
            FROM ingestion_runs
            WHERE tenant_id = :tenant_id
            ORDER BY started_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": current_user["tenant_id"]},
    )
    record = row.mappings().first()
    if not record:
        return None
    return _row_to_summary(dict(record))


@router.get("/runs", response_model=RunsResponse)
async def list_ingestion_runs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RunsResponse:
    """Return paginated ingestion run history for the caller's tenant, most recent first."""
    tenant_id = current_user["tenant_id"]
    offset = (page - 1) * page_size

    total_row = await db.execute(
        text("SELECT COUNT(*) FROM ingestion_runs WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    total: int = total_row.scalar_one()

    rows = await db.execute(
        text(
            """
            SELECT run_id, started_at, completed_at, tickets_fetched,
                   tickets_indexed, tickets_skipped, chunks_created,
                   status, error_message
            FROM ingestion_runs
            WHERE tenant_id = :tenant_id
            ORDER BY started_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"tenant_id": tenant_id, "limit": page_size, "offset": offset},
    )
    runs = [_row_to_summary(dict(r)) for r in rows.mappings()]
    return RunsResponse(runs=runs, total=total, page=page, page_size=page_size)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_summary(row: dict) -> IngestionRunSummary:
    from datetime import datetime
    def _dt(val: str | None) -> datetime | None:
        return datetime.fromisoformat(val) if val else None

    return IngestionRunSummary(
        run_id=row["run_id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        completed_at=_dt(row["completed_at"]),
        tickets_fetched=row["tickets_fetched"],
        tickets_indexed=row["tickets_indexed"],
        tickets_skipped=row["tickets_skipped"],
        chunks_created=row["chunks_created"],
        status=row["status"],
        error_message=row["error_message"],
    )
