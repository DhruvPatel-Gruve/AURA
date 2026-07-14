"""Integration tests for app.rag.ingestion_pipeline.IngestionPipeline."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.ingestion_pipeline import IngestionPipeline, _is_empty
from app.services.ai_config_service import ResolvedAIConfig
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_CONFIGURED_AI = ResolvedAIConfig(
    tenant_id=TENANT,
    embedding_provider="gemini", embedding_api_key="k", embedding_base_url=None,
    embedding_model="models/gemini-embedding-2", embedding_vector_size=768,
    llm_base_url="http://localhost:11434/v1", llm_model="qwen3:8b", llm_api_key=None,
)


# ── Helper: collect all events from the async generator ───────────────────────

async def _run(pipeline: IngestionPipeline, run_id: str) -> list[dict]:
    events = []
    async for event in pipeline.run(run_id=run_id):
        events.append(event)
    return events


# ── _is_empty ─────────────────────────────────────────────────────────────────

def test_is_empty_true_when_no_resolution_no_comments(sample_tickets):
    empty_ticket = sample_tickets[2]   # TEST-003
    assert _is_empty(empty_ticket) is True


def test_is_empty_false_when_resolution_present(sample_ticket):
    assert _is_empty(sample_ticket) is False


def test_is_empty_false_when_only_comments(sample_ticket):
    ticket = sample_ticket.model_copy(update={"resolution_note": None})
    assert _is_empty(ticket) is False


# ── Full pipeline run ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_emits_started_event(
    db_session, mock_qdrant, mock_jsm_search, mock_embedder
):
    with patch("app.rag.ingestion_pipeline.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.rag.ingestion_pipeline.get_embedder", return_value=mock_embedder):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        run_id = str(uuid.uuid4())
        events = await _run(pipeline, run_id)

    assert events[0]["status"] == "started"
    assert events[0]["run_id"] == run_id


@pytest.mark.asyncio
async def test_pipeline_emits_completed_event(
    db_session, mock_qdrant, mock_jsm_search, mock_embedder
):
    with patch("app.rag.ingestion_pipeline.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.rag.ingestion_pipeline.get_embedder", return_value=mock_embedder):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        events = await _run(pipeline, str(uuid.uuid4()))

    statuses = [e["status"] for e in events]
    assert "completed" in statuses


@pytest.mark.asyncio
async def test_pipeline_skips_empty_ticket(
    db_session, mock_qdrant, mock_jsm_search, mock_embedder
):
    """TEST-003 has no resolution or comments — must be counted as skipped."""
    with patch("app.rag.ingestion_pipeline.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.rag.ingestion_pipeline.get_embedder", return_value=mock_embedder):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        events = await _run(pipeline, str(uuid.uuid4()))

    final = events[-1]
    assert final["tickets_skipped"] >= 1


@pytest.mark.asyncio
async def test_pipeline_indexes_valid_tickets(
    db_session, mock_qdrant, mock_jsm_search, mock_embedder
):
    """TEST-001 and TEST-002 have content — both must be indexed."""
    with patch("app.rag.ingestion_pipeline.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.rag.ingestion_pipeline.get_embedder", return_value=mock_embedder):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        events = await _run(pipeline, str(uuid.uuid4()))

    final = events[-1]
    assert final["tickets_indexed"] == 2


@pytest.mark.asyncio
async def test_pipeline_upserts_to_qdrant(
    db_session, mock_qdrant, mock_jsm_search, mock_embedder
):
    with patch("app.rag.ingestion_pipeline.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.rag.ingestion_pipeline.get_embedder", return_value=mock_embedder):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        await _run(pipeline, str(uuid.uuid4()))

    mock_qdrant.upsert.assert_called_once()
    call_kwargs = mock_qdrant.upsert.call_args.kwargs
    assert len(call_kwargs["points"]) > 0


@pytest.mark.asyncio
async def test_pipeline_qdrant_point_ids_are_uuid5(
    db_session, mock_qdrant, mock_jsm_search, mock_embedder
):
    with patch("app.rag.ingestion_pipeline.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.rag.ingestion_pipeline.get_embedder", return_value=mock_embedder):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        await _run(pipeline, str(uuid.uuid4()))

    points = mock_qdrant.upsert.call_args.kwargs["points"]
    for point in points:
        # UUID5 values are valid UUIDs
        parsed = uuid.UUID(point.id)
        assert parsed.version == 5


@pytest.mark.asyncio
async def test_pipeline_dedup_skips_already_indexed(
    db_session, mock_embedder, sample_tickets
):
    """When Qdrant scroll returns a hit, the ticket must be skipped."""
    from app.db import qdrant_client as _qdrant_client_module
    _qdrant_client_module._ensured_collections.clear()

    mock_qdrant = MagicMock()
    # scroll returns a non-empty result → ticket already indexed
    mock_qdrant.scroll = AsyncMock(return_value=([MagicMock()], None))
    mock_qdrant.upsert = AsyncMock(return_value=None)
    mock_qdrant.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    mock_qdrant.create_collection = AsyncMock(return_value=None)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    # Only return TEST-001 (valid ticket)
    mock_jsm.search_tickets = AsyncMock(return_value=[sample_tickets[0]])

    with patch("app.db.qdrant_client._client", mock_qdrant), \
         patch("app.rag.ingestion_pipeline.get_qdrant_client", return_value=mock_qdrant), \
         patch("app.rag.ingestion_pipeline.get_itsm_client", return_value=mock_jsm), \
         patch("app.rag.ingestion_pipeline.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.rag.ingestion_pipeline.get_embedder", return_value=mock_embedder):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        events = await _run(pipeline, str(uuid.uuid4()))

    final = events[-1]
    assert final["tickets_skipped"] == 1
    assert final["tickets_indexed"] == 0
    mock_qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_writes_run_record_to_sqlite(
    db_session, mock_qdrant, mock_jsm_search, mock_embedder
):
    from sqlalchemy import text

    run_id = str(uuid.uuid4())
    with patch("app.rag.ingestion_pipeline.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.rag.ingestion_pipeline.get_embedder", return_value=mock_embedder):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        await _run(pipeline, run_id)

    row = await db_session.execute(
        text("SELECT status, tickets_indexed FROM ingestion_runs WHERE run_id = :rid"),
        {"rid": run_id},
    )
    record = row.mappings().first()
    assert record is not None
    assert record["status"] == "completed"
    assert record["tickets_indexed"] == 2


@pytest.mark.asyncio
async def test_pipeline_advances_sync_cursor(
    db_session, mock_qdrant, mock_jsm_search, mock_embedder
):
    from sqlalchemy import text

    with patch("app.rag.ingestion_pipeline.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.rag.ingestion_pipeline.get_embedder", return_value=mock_embedder):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        await _run(pipeline, str(uuid.uuid4()))

    row = await db_session.execute(
        text("SELECT last_sync_timestamp FROM platform_config WHERE tenant_id = :tid"),
        {"tid": TENANT},
    )
    ts = row.scalar_one_or_none()
    assert ts is not None


@pytest.mark.asyncio
async def test_pipeline_chunks_have_sparse_and_dense_vectors(
    db_session, mock_qdrant, mock_jsm_search, mock_embedder
):
    with patch("app.rag.ingestion_pipeline.get_ai_config", return_value=_CONFIGURED_AI), \
         patch("app.rag.ingestion_pipeline.get_embedder", return_value=mock_embedder):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        await _run(pipeline, str(uuid.uuid4()))

    points = mock_qdrant.upsert.call_args.kwargs["points"]
    for point in points:
        vectors = point.vector
        assert "" in vectors                    # unnamed dense vector
        assert "bm25" in vectors                # named sparse vector
        assert len(vectors[""]) == 768          # correct dimensionality


# ── AI-config gate ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_yields_failed_event_when_embeddings_not_configured(
    db_session, mock_qdrant, mock_jsm_search,
):
    """A tenant with no embedding provider configured must get a clean
    'failed' event — not an unhandled exception deep inside the embedder."""
    from app.services.ai_config_service import ResolvedAIConfig

    unconfigured = ResolvedAIConfig(
        tenant_id=TENANT,
        embedding_provider=None, embedding_api_key=None, embedding_base_url=None,
        embedding_model=None, embedding_vector_size=None,
        llm_base_url=None, llm_model=None, llm_api_key=None,
    )
    with patch("app.rag.ingestion_pipeline.get_ai_config", return_value=unconfigured):
        pipeline = IngestionPipeline(db=db_session, tenant_id=TENANT)
        events = await _run(pipeline, str(uuid.uuid4()))

    statuses = [e["status"] for e in events]
    assert statuses == ["started", "failed"]
    assert "Model & AI Configuration" in events[-1]["message"]

    from sqlalchemy import text
    row = (await db_session.execute(
        text("SELECT status FROM ingestion_runs WHERE tenant_id = :tid ORDER BY started_at DESC LIMIT 1"),
        {"tid": TENANT},
    )).first()
    assert row[0] == "failed"
