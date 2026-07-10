"""Tests for audit_finalizer_node (Node 11 — terminal)."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_finalizer_persists_audit_entry(base_state, mock_get_session):
    from sqlalchemy import text as sa_text

    state = {
        **base_state,
        "action_taken": "held_low_confidence",
        "priority": "HIGH",
        "category": "Network",
        "auto_comment_enabled": False,
        "confidence_score": 0.75,
        "abstained": False,
        "audit_steps": [
            {
                "node_name": "kill_switch_node",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "decision": "Kill switch ON",
                "metadata": {},
            }
        ],
    }

    from app.agents.nodes.audit_finalizer_node import audit_finalizer_node
    result = await audit_finalizer_node(state)

    assert result == {}  # terminal node returns empty dict

    row = (await mock_get_session.execute(
        sa_text("SELECT action_taken, ticket_id FROM audit_log WHERE ticket_id = 'TEST-100'")
    )).first()
    assert row is not None
    assert row[0] == "held_low_confidence"


@pytest.mark.asyncio
async def test_finalizer_assembles_audit_steps(base_state, mock_get_session):
    from sqlalchemy import text as sa_text

    steps = [
        {"node_name": "kill_switch_node", "timestamp": "2024-01-01T00:00:00+00:00", "decision": "pass", "metadata": {}},
        {"node_name": "priority_scorer_node", "timestamp": "2024-01-01T00:00:01+00:00", "decision": "HIGH", "metadata": {}},
    ]
    state = {**base_state, "action_taken": "comment_posted", "audit_steps": steps}

    from app.agents.nodes.audit_finalizer_node import audit_finalizer_node
    await audit_finalizer_node(state)

    row = (await mock_get_session.execute(
        sa_text("SELECT audit_steps FROM audit_log WHERE ticket_id = 'TEST-100'")
    )).first()
    assert row is not None
    import json
    loaded = json.loads(row[0])
    assert len(loaded) == 2
    assert loaded[0]["node_name"] == "kill_switch_node"
