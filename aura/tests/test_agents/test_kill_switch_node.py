"""Tests for kill_switch_node (Node 1)."""

import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_kill_switch_enabled_passes(base_state):
    with patch("app.agents.nodes.kill_switch_node.kill_switch.is_enabled", return_value=True):
        from app.agents.nodes.kill_switch_node import kill_switch_node
        result = kill_switch_node(base_state)

    assert result.get("pipeline_halted") is None or result.get("pipeline_halted") is False
    assert len(result["audit_steps"]) == 1
    assert result["audit_steps"][0]["node_name"] == "kill_switch_node"


@pytest.mark.asyncio
async def test_kill_switch_disabled_halts(base_state):
    with patch("app.agents.nodes.kill_switch_node.kill_switch.is_enabled", return_value=False):
        from app.agents.nodes.kill_switch_node import kill_switch_node
        result = kill_switch_node(base_state)

    assert result["pipeline_halted"] is True
    assert result["halt_reason"] == "kill_switch_active"
    assert result["action_taken"] == "halted_kill_switch"
    assert len(result["audit_steps"]) == 1
