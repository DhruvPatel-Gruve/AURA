"""Tests for sla_node (Node 7)."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
def silence_bus():
    with patch(
        "app.agents.nodes.sla_node.notification_bus.broadcast_to_tenant",
        new=AsyncMock(return_value=None),
    ):
        yield


async def _seed_category_sla(db, sla_minutes: int, tenant_id: str = "test-tenant-1"):
    from sqlalchemy import text as sa_text
    await db.execute(
        sa_text(
            "INSERT INTO category_config "
            "(category_id, tenant_id, name, team_id, auto_comment_enabled, sla_minutes, created_at, updated_at) "
            "VALUES ('cat-sla', :tenant, 'Network', 'net', 0, :mins, '2024-01-01T00:00:00', '2024-01-01T00:00:00')"
        ),
        {"mins": sla_minutes, "tenant": tenant_id},
    )
    await db.commit()


def _state_with_created(created_iso: str) -> dict:
    return {
        "tenant_id": "test-tenant-1",
        "ticket_id": "TEST-SLA",
        "raw_ticket": {"summary": "Test", "description": "Test", "created": created_iso},
        "category": "Network",
        "assigned_team": "net",
        "query_embedding": [0.1] * 768,
        "audit_steps": [],
        "pipeline_halted": False,
        "halt_reason": None,
        "priority": "MEDIUM",
        "priority_method": "keyword_rule",
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


@pytest.mark.asyncio
async def test_sla_status_ok(mock_get_session):
    await _seed_category_sla(mock_get_session, sla_minutes=480)
    recent = datetime.now(timezone.utc) - timedelta(minutes=30)
    state = _state_with_created(recent.isoformat())

    from app.agents.nodes.sla_node import sla_node
    result = await sla_node(state)

    assert result["sla_status"] == "ok"
    assert result["sla_deadline"] is not None


@pytest.mark.asyncio
async def test_sla_status_warning(mock_get_session):
    await _seed_category_sla(mock_get_session, sla_minutes=60)
    # 50 min ago on a 60-min SLA → ~83% elapsed → warning
    created = datetime.now(timezone.utc) - timedelta(minutes=50)
    state = _state_with_created(created.isoformat())

    from app.agents.nodes.sla_node import sla_node
    result = await sla_node(state)

    assert result["sla_status"] == "warning"


@pytest.mark.asyncio
async def test_sla_status_breached(mock_get_session):
    await _seed_category_sla(mock_get_session, sla_minutes=30)
    # 60 min ago on a 30-min SLA → breached
    created = datetime.now(timezone.utc) - timedelta(hours=1)
    state = _state_with_created(created.isoformat())

    bus_mock = AsyncMock()
    with patch("app.agents.nodes.sla_node.notification_bus.broadcast_to_tenant", bus_mock):
        from app.agents.nodes.sla_node import sla_node
        result = await sla_node(state)

    assert result["sla_status"] == "breached"
    assert bus_mock.called
    assert bus_mock.call_args[0][1] == "SLA_BREACHED"
