"""Tests for collision_node (Node 5)."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_no_claim_continues(base_state, mock_get_session):
    with patch(
        "app.agents.nodes.collision_node.collision_service.check_claim",
        new=AsyncMock(return_value=None),
    ):
        from app.agents.nodes.collision_node import collision_node
        result = await collision_node(base_state)

    assert result["collision_detected"] is False
    assert len(result["audit_steps"]) == 1


@pytest.mark.asyncio
async def test_active_claim_noted_but_continues(base_state, mock_get_session):
    claim = {"claimed_by": "bob@test.com", "expires_at": "2099-01-01T00:00:00+00:00"}
    with patch(
        "app.agents.nodes.collision_node.collision_service.check_claim",
        new=AsyncMock(return_value=claim),
    ):
        from app.agents.nodes.collision_node import collision_node
        result = await collision_node(base_state)

    assert result["collision_detected"] is True
    assert result["claimed_by"] == "bob@test.com"
    # Collision node is informational — pipeline must NOT be halted
    assert not result.get("pipeline_halted")
