"""Tests for confidence_gate_node (Node 10)."""

import pytest
from sqlalchemy import text as sa_text
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import SAMPLE_TENANT_ID as TENANT


async def _seed_platform_config(db, confidence_threshold: float = 0.90):
    await db.execute(
        sa_text(
            "UPDATE platform_config SET confidence_threshold = :conf, "
            "abstention_threshold = 0.60 WHERE tenant_id = :tenant"
        ),
        {"conf": confidence_threshold, "tenant": TENANT},
    )
    await db.commit()


def _state_with_confidence(confidence: float, auto_comment_enabled: bool = False) -> dict:
    return {
        "tenant_id": TENANT,
        "ticket_id": "TEST-CG",
        "raw_ticket": {"summary": "Test"},
        "confidence_score": confidence,
        "formatted_comment": "**AURA Suggested Resolution**\n\nDo X then Y.",
        "citations": ["OLD-1"],
        "assigned_team": "net-team",
        "audit_steps": [],
        "pipeline_halted": False,
        "halt_reason": None,
        "priority": "MEDIUM",
        "priority_method": "keyword_rule",
        "query_embedding": [0.1] * 768,
        "category": "Network",
        "collision_detected": False,
        "claimed_by": None,
        "auto_comment_enabled": auto_comment_enabled,
        "sla_deadline": None,
        "sla_status": None,
        "abstained": False,
        "abstention_reason": None,
        "top_retrieval_score": None,
        "retrieved_chunks": None,
        "llm_raw_response": None,
        "action_taken": None,
        "jsm_comment_id": None,
    }


@pytest.fixture(autouse=True)
def silence_bus():
    with patch(
        "app.agents.nodes.confidence_gate_node.notification_bus.broadcast_to_team",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.agents.nodes.confidence_gate_node.notification_bus.broadcast_to_admins",
        new=AsyncMock(return_value=None),
    ):
        yield


@pytest.mark.asyncio
async def test_path_a_auto_posts_when_high_confidence(mock_get_session):
    await _seed_platform_config(mock_get_session, 0.90)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="comment-id-abc")

    bus_mock = AsyncMock()
    with patch("app.agents.nodes.confidence_gate_node.notification_bus.broadcast_to_team", bus_mock):
        with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm):
            from app.agents.nodes.confidence_gate_node import confidence_gate_node
            result = await confidence_gate_node(_state_with_confidence(0.95, auto_comment_enabled=True))

    assert result["action_taken"] == "comment_posted"
    assert result["jsm_comment_id"] == "comment-id-abc"
    bus_mock.assert_called_once()
    assert bus_mock.call_args.args[0] == TENANT
    assert bus_mock.call_args.args[1] == "net-team"


@pytest.mark.asyncio
async def test_path_b_holds_when_low_confidence(mock_get_session):
    await _seed_platform_config(mock_get_session, 0.90)

    from app.agents.nodes.confidence_gate_node import confidence_gate_node
    result = await confidence_gate_node(_state_with_confidence(0.65, auto_comment_enabled=True))

    assert result["action_taken"] == "held_low_confidence"
    assert "jsm_comment_id" not in result or result.get("jsm_comment_id") is None


@pytest.mark.asyncio
async def test_toggle_off_always_holds_regardless_of_confidence(mock_get_session):
    await _seed_platform_config(mock_get_session, 0.90)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="comment-id-abc")

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm):
        from app.agents.nodes.confidence_gate_node import confidence_gate_node
        result = await confidence_gate_node(_state_with_confidence(0.99, auto_comment_enabled=False))

    assert result["action_taken"] == "held_low_confidence"
    mock_jsm.post_comment_markdown.assert_not_called()


@pytest.mark.asyncio
async def test_notifies_admins_when_no_team_assigned(mock_get_session):
    await _seed_platform_config(mock_get_session, 0.90)

    state = _state_with_confidence(0.65, auto_comment_enabled=True)
    state["assigned_team"] = None

    admins_mock = AsyncMock()
    with patch("app.agents.nodes.confidence_gate_node.notification_bus.broadcast_to_admins", admins_mock), \
         patch("app.agents.nodes.confidence_gate_node.notification_bus.broadcast_to_team") as team_mock:
        from app.agents.nodes.confidence_gate_node import confidence_gate_node
        result = await confidence_gate_node(state)

    assert result["action_taken"] == "held_low_confidence"
    admins_mock.assert_called_once()
    team_mock.assert_not_called()


@pytest.mark.asyncio
async def test_jsm_failure_downgrades_to_hold(mock_get_session):
    await _seed_platform_config(mock_get_session, 0.90)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(side_effect=Exception("JSM 503"))

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm):
        from app.agents.nodes.confidence_gate_node import confidence_gate_node
        result = await confidence_gate_node(_state_with_confidence(0.95, auto_comment_enabled=True))

    assert result["action_taken"] == "held_low_confidence"


@pytest.mark.asyncio
async def test_path_a_starts_conversation_tracking_when_reporter_known(mock_get_session):
    await _seed_platform_config(mock_get_session, 0.90)

    state = _state_with_confidence(0.95, auto_comment_enabled=True)
    state["raw_ticket"] = {"summary": "Test", "status": "Open", "reporter_account_id": "reporter-123"}

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="comment-id-abc")

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm):
        from app.agents.nodes.confidence_gate_node import confidence_gate_node
        await confidence_gate_node(state)

    row = (await mock_get_session.execute(
        sa_text(
            "SELECT reporter_account_id, turn_count FROM ticket_conversations "
            "WHERE tenant_id = :tenant AND ticket_id = 'TEST-CG'"
        ),
        {"tenant": TENANT},
    )).first()
    assert row is not None
    assert row[0] == "reporter-123"
    assert row[1] == 1
