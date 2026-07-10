"""Tests for abstention_node (Node 8)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import SAMPLE_TENANT_ID as TENANT


async def _seed_platform_config(db, abstention_threshold: float = 0.60):
    from sqlalchemy import text as sa_text
    await db.execute(
        sa_text(
            "UPDATE platform_config SET confidence_threshold = 0.90, "
            "abstention_threshold = :abst WHERE tenant_id = :tenant"
        ),
        {"abst": abstention_threshold, "tenant": TENANT},
    )
    await db.commit()


@pytest.fixture(autouse=True)
def silence_bus():
    with patch(
        "app.agents.nodes.abstention_node.notification_bus.broadcast_to_tenant",
        new=AsyncMock(return_value=None),
    ):
        yield


@pytest.mark.asyncio
async def test_above_threshold_proceeds(base_state, mock_get_session):
    await _seed_platform_config(mock_get_session, abstention_threshold=0.60)

    mock_retriever = MagicMock()
    mock_retriever.probe_top_score = AsyncMock(return_value=(0.85, [0.1] * 768))

    with patch("app.agents.nodes.abstention_node.HybridRetriever", return_value=mock_retriever), \
         patch("app.agents.nodes.abstention_node.ensure_tenant_collection", new=AsyncMock(return_value="resolved_tickets_test")):
        from app.agents.nodes.abstention_node import abstention_node
        result = await abstention_node(base_state)

    assert result["abstained"] is False
    assert result.get("pipeline_halted") is None or not result.get("pipeline_halted")
    assert result["top_retrieval_score"] == 0.85


@pytest.mark.asyncio
async def test_below_threshold_abstains(base_state, mock_get_session):
    await _seed_platform_config(mock_get_session, abstention_threshold=0.60)

    mock_retriever = MagicMock()
    mock_retriever.probe_top_score = AsyncMock(return_value=(0.30, [0.1] * 768))

    with patch("app.agents.nodes.abstention_node.HybridRetriever", return_value=mock_retriever), \
         patch("app.agents.nodes.abstention_node.ensure_tenant_collection", new=AsyncMock(return_value="resolved_tickets_test")):
        from app.agents.nodes.abstention_node import abstention_node
        result = await abstention_node(base_state)

    assert result["abstained"] is True
    assert result["pipeline_halted"] is True
    assert result["halt_reason"] == "abstention"
    assert result["action_taken"] == "abstained_no_kb_coverage"


@pytest.mark.asyncio
async def test_abstention_queues_to_db(base_state, mock_get_session):
    from sqlalchemy import text as sa_text
    await _seed_platform_config(mock_get_session, abstention_threshold=0.60)

    mock_retriever = MagicMock()
    mock_retriever.probe_top_score = AsyncMock(return_value=(0.10, [0.1] * 768))

    bus_mock = AsyncMock()
    with patch("app.agents.nodes.abstention_node.HybridRetriever", return_value=mock_retriever), \
         patch("app.agents.nodes.abstention_node.ensure_tenant_collection", new=AsyncMock(return_value="resolved_tickets_test")), \
         patch("app.agents.nodes.abstention_node.notification_bus.broadcast_to_tenant", bus_mock):
        from app.agents.nodes.abstention_node import abstention_node
        await abstention_node(base_state)

    row = (await mock_get_session.execute(
        sa_text("SELECT abstained FROM low_confidence_queue WHERE tenant_id = :tenant AND ticket_id = 'TEST-100'"),
        {"tenant": TENANT},
    )).first()
    assert row is not None
    assert row[0] == 1
