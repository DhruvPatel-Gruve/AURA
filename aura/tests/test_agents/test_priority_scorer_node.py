"""Tests for priority_scorer_node (Node 2)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_state(summary: str, description: str = "", embedding=None) -> dict:
    return {
        "ticket_id": "TEST-200",
        "tenant_id": "test-tenant-1",
        "raw_ticket": {"summary": summary, "description": description},
        "query_embedding": embedding or [0.1] * 768,
        "audit_steps": [],
        "pipeline_halted": False,
        "halt_reason": None,
        "priority": None,
        "priority_method": None,
        "category": None,
        "assigned_team": None,
        "collision_detected": False,
        "claimed_by": None,
        "auto_comment_enabled": False,
        "sla_deadline": None,
        "sla_status": None,
        "abstained": False,
        "abstention_reason": None,
        "top_retrieval_score": None,
        "retrieved_chunks": None,
        "llm_raw_response": None,
        "confidence_score": None,
        "formatted_comment": None,
        "citations": None,
        "action_taken": None,
        "jsm_comment_id": None,
    }


@pytest.fixture
def mock_embedder_node():
    embedder = MagicMock()
    embedder.embed_query_text = AsyncMock(return_value=[0.2] * 768)
    with patch("app.agents.nodes.priority_scorer_node.get_embedder", return_value=embedder):
        yield embedder


@pytest.fixture
def mock_qdrant_node():
    response = MagicMock()
    response.points = []
    client = MagicMock()
    client.query_points = AsyncMock(return_value=response)
    with patch("app.agents.nodes.priority_scorer_node.get_qdrant_client", return_value=client):
        yield client


@pytest.mark.asyncio
async def test_critical_keyword_detected(mock_embedder_node, mock_qdrant_node):
    from app.agents.nodes.priority_scorer_node import priority_scorer_node
    state = _make_state("production outage affecting all users", "system down completely")
    result = await priority_scorer_node(state)

    assert result["priority"] == "CRITICAL"
    assert result["priority_method"] == "keyword_rule"
    assert len(result["query_embedding"]) == 768


@pytest.mark.asyncio
async def test_low_keyword_detected(mock_embedder_node, mock_qdrant_node):
    from app.agents.nodes.priority_scorer_node import priority_scorer_node
    state = _make_state("how to configure outlook settings", "just a question about email")
    result = await priority_scorer_node(state)

    assert result["priority"] == "LOW"
    assert result["priority_method"] == "keyword_rule"


@pytest.mark.asyncio
async def test_semantic_fallback_when_no_keyword(mock_embedder_node, mock_qdrant_node):
    from app.agents.nodes.priority_scorer_node import priority_scorer_node
    # No keyword matches → falls back to Qdrant (which returns empty → MEDIUM default)
    state = _make_state("printer paper jam in room 301", "HP printer jammed")
    result = await priority_scorer_node(state)

    assert result["priority"] == "MEDIUM"
    assert result["priority_method"] in ("historical_match", "default_fallback")
