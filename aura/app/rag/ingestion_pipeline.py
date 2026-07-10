"""Phase 0 Knowledge Ingestion Pipeline.

Orchestration order per run:
  1. Create run record in ingestion_runs (SQLite)
  2. Load last_sync_timestamp cursor from platform_config
  3. Fetch resolved tickets from JSM (paginated)
  4. Per-ticket: skip-guard → dedup check → chunk
  5. Fit BM25 on full batch of new chunks
  6. Embed all chunks (dense + sparse) in batches
  7. Upsert to Qdrant resolved_tickets collection
  8. Write IngestionAuditEntry rows to SQLite
  9. Advance sync cursor in platform_config
 10. Finalise run record; emit INGESTION_COMPLETE
"""

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable, TypedDict

from qdrant_client.models import PointStruct, SparseVector
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.qdrant_client import SPARSE_VECTOR_NAME, ensure_tenant_collection, get_qdrant_client
from app.models.jsm import IngestionAuditEntry, IngestionRunSummary, JSMTicket, TicketChunk
from app.rag.chunker import DynamicChunker
from app.rag.embedder import EmbeddedChunk, GeminiEmbedder
from app.services.itsm_client import get_itsm_client

log = get_logger(__name__)

# Deterministic Qdrant point IDs — UUID5 keyed on chunk_id string
_POINT_NS = uuid.NAMESPACE_URL

# Progress event emitted to WebSocket subscribers (and returned by the generator)
class IngestionProgressEvent(TypedDict):
    run_id: str
    status: str          # "started" | "fetched" | "processing" | "completed" | "failed"
    progress_pct: int
    tickets_fetched: int
    tickets_indexed: int
    tickets_skipped: int
    chunks_created: int
    message: str


ProgressCallback = Callable[[IngestionProgressEvent], None]


class IngestionPipeline:
    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id
        self._chunker = DynamicChunker()
        self._embedder = GeminiEmbedder()
        self._settings = get_settings()
        self._collection: str | None = None  # resolved lazily in run(), needs an await
        self._project_key: str | None = None  # this tenant's jsm_project_key, loaded in run()

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(
        self,
        run_id: str,
        on_progress: ProgressCallback | None = None,
    ) -> AsyncGenerator[IngestionProgressEvent, None]:
        """Async generator — yields IngestionProgressEvent at each milestone.

        Usage::
            async for event in pipeline.run(run_id):
                await notification_bus.broadcast(event)
        """
        summary = IngestionRunSummary(run_id=run_id, started_at=_utcnow())
        await self._upsert_run(summary)

        def _emit(status: str, pct: int, msg: str = "") -> IngestionProgressEvent:
            return IngestionProgressEvent(
                run_id=run_id,
                status=status,
                progress_pct=pct,
                tickets_fetched=summary.tickets_fetched,
                tickets_indexed=summary.tickets_indexed,
                tickets_skipped=summary.tickets_skipped,
                chunks_created=summary.chunks_created,
                message=msg,
            )

        try:
            yield _emit("started", 0)

            self._collection = await ensure_tenant_collection(self._tenant_id)
            self._project_key = await self._load_project_key()

            # ── Step 2: load cursor ────────────────────────────────────────────
            cursor = await self._load_cursor()
            log.info("ingestion.cursor_loaded", tenant_id=self._tenant_id, since=cursor)

            # ── Step 3: fetch tickets ──────────────────────────────────────────
            async with get_itsm_client(self._tenant_id) as itsm:
                tickets = await itsm.search_tickets(since=cursor)

            summary.tickets_fetched = len(tickets)
            yield _emit("fetched", 5, f"Fetched {len(tickets)} resolved tickets")
            log.info("ingestion.tickets_fetched", count=len(tickets))

            if not tickets:
                await self._finalise(summary, status="completed")
                yield _emit("completed", 100, "No new tickets to index")
                return

            # ── Steps 4–8: per-ticket processing ──────────────────────────────
            new_chunks: list[TicketChunk] = []
            audit_entries: list[IngestionAuditEntry] = []

            for i, ticket in enumerate(tickets):
                # 4a: skip — no useful content
                if _is_empty(ticket):
                    summary.tickets_skipped += 1
                    audit_entries.append(_make_audit(run_id, ticket, "skipped_no_resolution", self._project_key))
                    continue

                # 4b: dedup — ticket already indexed in Qdrant
                if await self._already_indexed(ticket.ticket_id):
                    summary.tickets_skipped += 1
                    audit_entries.append(_make_audit(run_id, ticket, "skipped_duplicate", self._project_key))
                    continue

                # 4c: chunk
                chunks = self._chunker.chunk(ticket)
                new_chunks.extend(chunks)
                audit_entries.append(
                    _make_audit(run_id, ticket, "indexed", self._project_key, chunk_count=len(chunks))
                )

                # Emit progress every 10 tickets
                if (i + 1) % 10 == 0:
                    pct = min(5 + int(((i + 1) / len(tickets)) * 85), 90)
                    yield _emit("processing", pct, f"Processed {i + 1}/{len(tickets)} tickets")

            # ── Step 5: fit BM25 on full new-chunk corpus ──────────────────────
            if new_chunks:
                self._embedder.fit_bm25([c.content for c in new_chunks])

                # ── Step 6: embed ──────────────────────────────────────────────
                embedded = await self._embedder.embed_chunks(new_chunks)
                yield _emit("processing", 92, f"Embedded {len(embedded)} chunks")

                # ── Step 7: upsert to Qdrant ───────────────────────────────────
                await self._upsert_to_qdrant(embedded)
                summary.chunks_created = len(embedded)

                # Count indexed tickets (unique ticket_ids in new_chunks)
                summary.tickets_indexed = len({c.ticket_id for c in new_chunks})

            # ── Step 8: write audit entries ────────────────────────────────────
            await self._write_audit_entries(audit_entries)

            # ── Step 9: advance cursor ─────────────────────────────────────────
            await self._advance_cursor(_utcnow())

            # ── Step 10: finalise ──────────────────────────────────────────────
            await self._finalise(summary, status="completed")
            yield _emit("completed", 100)
            log.info(
                "ingestion.run_complete",
                run_id=run_id,
                indexed=summary.tickets_indexed,
                skipped=summary.tickets_skipped,
                chunks=summary.chunks_created,
            )

        except Exception as exc:
            log.error("ingestion.run_failed", run_id=run_id, error=str(exc))
            summary.error_message = str(exc)
            await self._finalise(summary, status="failed")
            yield _emit("failed", 0, str(exc))
            raise

    # ── Qdrant helpers ────────────────────────────────────────────────────────

    async def _already_indexed(self, ticket_id: str) -> bool:
        """Return True if any point with payload.ticket_id == ticket_id exists."""
        client = get_qdrant_client()
        result, _ = await client.scroll(
            collection_name=self._collection,
            scroll_filter={
                "must": [{"key": "ticket_id", "match": {"value": ticket_id}}]
            },
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return len(result) > 0

    async def _upsert_to_qdrant(self, embedded: list[EmbeddedChunk]) -> None:
        await upsert_embedded_chunks(embedded, self._collection)

    # ── SQLite helpers ────────────────────────────────────────────────────────

    async def _load_project_key(self) -> str | None:
        """This tenant's own jsm_project_key (None for Zendesk tenants) —
        used only as the audit trail's `source_project` label."""
        row = await self._db.execute(
            text("SELECT jsm_project_key FROM platform_config WHERE tenant_id = :tid"),
            {"tid": self._tenant_id},
        )
        return row.scalar_one_or_none()

    async def _load_cursor(self) -> datetime | None:
        row = await self._db.execute(
            text("SELECT last_sync_timestamp FROM platform_config WHERE tenant_id = :tid"),
            {"tid": self._tenant_id},
        )
        val = row.scalar_one_or_none()
        if val:
            return datetime.fromisoformat(val)
        # First run: seed cursor to configured lookback window
        lookback_days = self._settings.ingestion_lookback_days
        from datetime import timedelta
        return _utcnow() - timedelta(days=lookback_days)

    async def _advance_cursor(self, ts: datetime) -> None:
        await self._db.execute(
            text(
                "UPDATE platform_config SET last_sync_timestamp = :ts, updated_at = :ts "
                "WHERE tenant_id = :tid"
            ),
            {"ts": ts.isoformat(), "tid": self._tenant_id},
        )
        await self._db.commit()

    async def _upsert_run(self, summary: IngestionRunSummary) -> None:
        await self._db.execute(
            text(
                """
                INSERT INTO ingestion_runs
                    (run_id, tenant_id, started_at, tickets_fetched, tickets_indexed,
                     tickets_skipped, chunks_created, status)
                VALUES
                    (:run_id, :tenant_id, :started_at, 0, 0, 0, 0, 'running')
                """
            ),
            {"run_id": summary.run_id, "tenant_id": self._tenant_id, "started_at": summary.started_at.isoformat()},
        )
        await self._db.commit()

    async def _finalise(self, summary: IngestionRunSummary, status: str) -> None:
        summary.status = status  # type: ignore[assignment]
        summary.completed_at = _utcnow()
        await self._db.execute(
            text(
                """
                UPDATE ingestion_runs
                SET completed_at      = :completed_at,
                    tickets_fetched   = :tickets_fetched,
                    tickets_indexed   = :tickets_indexed,
                    tickets_skipped   = :tickets_skipped,
                    chunks_created    = :chunks_created,
                    status            = :status,
                    error_message     = :error_message
                WHERE run_id = :run_id
                """
            ),
            {
                "run_id": summary.run_id,
                "completed_at": summary.completed_at.isoformat(),
                "tickets_fetched": summary.tickets_fetched,
                "tickets_indexed": summary.tickets_indexed,
                "tickets_skipped": summary.tickets_skipped,
                "chunks_created": summary.chunks_created,
                "status": status,
                "error_message": summary.error_message,
            },
        )
        await self._db.commit()

    async def _write_audit_entries(self, entries: list[IngestionAuditEntry]) -> None:
        for entry in entries:
            await self._db.execute(
                text(
                    """
                    INSERT INTO audit_log
                        (entry_id, tenant_id, ticket_id, action_taken, abstained,
                         audit_steps, created_at)
                    VALUES
                        (:entry_id, :tenant_id, :ticket_id, :action_taken, 0,
                         '[]', :created_at)
                    """
                ),
                {
                    "entry_id": str(uuid.uuid4()),
                    "tenant_id": self._tenant_id,
                    "ticket_id": entry.ticket_id,
                    "action_taken": entry.action,
                    "created_at": entry.timestamp.isoformat(),
                },
            )
        await self._db.commit()


# ── Shared upsert (used by both ticket and document ingestion) ────────────────

async def upsert_embedded_chunks(embedded: list[EmbeddedChunk], collection_name: str) -> None:
    """Upsert a list of embedded chunks into the given Qdrant collection.

    Builds deterministic point IDs (UUID5 of chunk_id) so re-ingesting the
    same content performs an idempotent overwrite rather than a duplicate insert.
    Handles both TicketChunk and DocumentChunk payloads.
    """
    client = get_qdrant_client()
    points: list[PointStruct] = []

    for ec in embedded:
        point_id = str(uuid.uuid5(_POINT_NS, ec.chunk.chunk_id))

        if isinstance(ec.chunk, TicketChunk):
            meta = ec.chunk.metadata
            payload: dict = {
                "source_type": "ticket",
                "ticket_id": ec.chunk.ticket_id,
                "chunk_id": ec.chunk.chunk_id,
                "chunk_type": ec.chunk.chunk_type,
                "category": meta.category,
                "priority": meta.priority,
                "resolved_date": meta.resolved_date.isoformat() if meta.resolved_date else None,
                "content": ec.chunk.content,
            }
        else:  # DocumentChunk
            meta = ec.chunk.metadata
            payload = {
                "source_type": "document",
                "doc_id": ec.chunk.doc_id,
                "chunk_id": ec.chunk.chunk_id,
                "chunk_type": ec.chunk.chunk_type,
                "filename": meta.filename,
                "content": ec.chunk.content,
                "uploaded_at": meta.uploaded_at.isoformat(),
            }

        points.append(
            PointStruct(
                id=point_id,
                vector={
                    "": ec.dense_vector,
                    SPARSE_VECTOR_NAME: SparseVector(
                        indices=ec.sparse_indices,
                        values=ec.sparse_values,
                    ),
                },
                payload=payload,
            )
        )

    await client.upsert(collection_name=collection_name, points=points)
    log.info("qdrant.upserted", collection=collection_name, count=len(points))


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _is_empty(ticket: JSMTicket) -> bool:
    return not ticket.resolution_note and not ticket.comments


def _make_audit(
    run_id: str,
    ticket: JSMTicket,
    action: str,
    project_key: str | None,
    chunk_count: int = 0,
) -> IngestionAuditEntry:
    return IngestionAuditEntry(
        run_id=run_id,
        ticket_id=ticket.ticket_id,
        action=action,  # type: ignore[arg-type]
        chunk_count=chunk_count,
        timestamp=_utcnow(),
        source_project=project_key,
    )
