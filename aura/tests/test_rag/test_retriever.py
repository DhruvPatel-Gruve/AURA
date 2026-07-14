"""Tests for HybridRetriever._dense_search — the actual Qdrant call site.

Regression coverage for a real production bug: qdrant-client 1.18 removed
AsyncQdrantClient.search() in favor of query_points() (which wraps results
in a QueryResponse.points list instead of a bare list). The old .search()
call was never covered by a test that actually exercised the real method
name, so it went undetected until a live ticket crashed the whole pipeline.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.retriever import HybridRetriever


def _query_response(points):
    resp = MagicMock()
    resp.points = points
    return resp


def _hit(chunk_id="c1", ticket_id="T-1", chunk_type="resolution", content="fix it", score=0.9):
    hit = MagicMock()
    hit.score = score
    hit.payload = {
        "chunk_id": chunk_id,
        "ticket_id": ticket_id,
        "chunk_type": chunk_type,
        "content": content,
    }
    return hit


@pytest.mark.asyncio
async def test_dense_search_calls_query_points_not_search():
    client = MagicMock()
    client.query_points = AsyncMock(return_value=_query_response([_hit()]))

    with patch("app.rag.retriever.get_qdrant_client", return_value=client):
        retriever = HybridRetriever.__new__(HybridRetriever)
        candidates = await retriever._dense_search([0.1] * 768, limit=5, collection="resolved_tickets")

    client.query_points.assert_called_once()
    kwargs = client.query_points.call_args.kwargs
    assert kwargs["using"] == ""
    assert kwargs["query"] == [0.1] * 768
    assert len(candidates) == 1
    assert candidates[0].chunk_id == "c1"
    assert candidates[0].score == 0.9


@pytest.mark.asyncio
async def test_dense_search_returns_empty_list_on_qdrant_error():
    client = MagicMock()
    client.query_points = AsyncMock(side_effect=Exception("connection refused"))

    with patch("app.rag.retriever.get_qdrant_client", return_value=client):
        retriever = HybridRetriever.__new__(HybridRetriever)
        candidates = await retriever._dense_search([0.1] * 768, limit=5, collection="resolved_tickets")

    assert candidates == []


@pytest.mark.asyncio
async def test_probe_top_score_survives_qdrant_error():
    client = MagicMock()
    client.query_points = AsyncMock(side_effect=Exception("connection refused"))
    embedder = MagicMock()
    embedder.embed_query_text = AsyncMock(return_value=[0.2] * 768)

    with patch("app.rag.retriever.get_qdrant_client", return_value=client), \
         patch("app.rag.retriever.get_embedder", return_value=embedder):
        retriever = HybridRetriever("test-tenant-1")
        top_score, query_vector = await retriever.probe_top_score(query_text="vpn broken", collection="resolved_tickets")

    assert top_score == 0.0
    assert len(query_vector) == 768
