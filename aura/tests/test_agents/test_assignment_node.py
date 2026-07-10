"""Tests for assignment_node (Node 4b)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text as sa_text

from app.agents.nodes.assignment_node import assignment_node
from tests.conftest import SAMPLE_TENANT_ID as TENANT


async def _seed_technician(db, *, team_id="net-team", jira_account_id=None, is_active=1):
    user_id = str(uuid.uuid4())
    await db.execute(
        sa_text(
            "INSERT INTO users (user_id, tenant_id, email, hashed_password, display_name, role, "
            "team_id, is_active, jira_account_id, created_at) "
            "VALUES (:uid, :tenant, :email, 'x', 'Test Tech', 'technician', :team, :active, :jira, '2024-01-01T00:00:00')"
        ),
        {"uid": user_id, "tenant": TENANT, "email": "tech@example.com", "team": team_id, "active": is_active, "jira": jira_account_id},
    )
    await db.commit()
    return user_id


@pytest.mark.asyncio
async def test_skips_when_no_team_assigned(mock_get_session, base_state):
    state = dict(base_state, assigned_team=None)
    result = await assignment_node(state)
    assert result["assignment_status"] == "skipped_no_team"
    assert result["assigned_technician"] is None


@pytest.mark.asyncio
async def test_no_technician_on_team(mock_get_session, base_state):
    state = dict(base_state, assigned_team="ghost-team")
    result = await assignment_node(state)
    assert result["assignment_status"] == "no_technician_available"


@pytest.mark.asyncio
async def test_assigns_technician_with_existing_jira_account(mock_get_session, base_state):
    user_id = await _seed_technician(mock_get_session, jira_account_id="jira-acc-123")
    state = dict(base_state, assigned_team="net-team")

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.assign_ticket = AsyncMock(return_value=None)

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm), \
         patch("app.agents.nodes.assignment_node.notification_bus.send_to_user", new=AsyncMock()) as bus_mock:
        result = await assignment_node(state)

    assert result["assignment_status"] == "assigned"
    assert result["assigned_technician"] == user_id
    mock_jsm.assign_ticket.assert_called_once_with(state["ticket_id"], "jira-acc-123")
    bus_mock.assert_called_once()
    assert bus_mock.call_args.args[0] == user_id
    assert bus_mock.call_args.args[1] == "TICKET_ASSIGNED"

    row = (await mock_get_session.execute(
        sa_text(
            "SELECT assigned_to, is_current, acknowledged_at FROM ticket_assignments "
            "WHERE tenant_id = :tenant AND ticket_id = :tid"
        ),
        {"tenant": TENANT, "tid": state["ticket_id"]},
    )).mappings().first()
    assert row is not None
    assert row["assigned_to"] == user_id
    assert row["is_current"] == 1
    assert row["acknowledged_at"] is None


@pytest.mark.asyncio
async def test_resolves_and_caches_jira_account_by_email(mock_get_session, base_state):
    user_id = await _seed_technician(mock_get_session, jira_account_id=None)
    state = dict(base_state, assigned_team="net-team")

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.find_account_id_by_email = AsyncMock(return_value="resolved-acc-456")
    mock_jsm.assign_ticket = AsyncMock(return_value=None)

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm), \
         patch("app.agents.nodes.assignment_node.notification_bus.send_to_user", new=AsyncMock()):
        result = await assignment_node(state)

    assert result["assignment_status"] == "assigned"
    mock_jsm.assign_ticket.assert_called_once_with(state["ticket_id"], "resolved-acc-456")

    row = (await mock_get_session.execute(
        sa_text("SELECT jira_account_id FROM users WHERE user_id = :uid"), {"uid": user_id}
    )).first()
    assert row[0] == "resolved-acc-456"


@pytest.mark.asyncio
async def test_no_jira_account_mapped_when_lookup_fails(mock_get_session, base_state):
    await _seed_technician(mock_get_session, jira_account_id=None)
    state = dict(base_state, assigned_team="net-team")

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.find_account_id_by_email = AsyncMock(return_value=None)

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm):
        result = await assignment_node(state)

    assert result["assignment_status"] == "no_jira_account_mapped"
    mock_jsm.assign_ticket.assert_not_called()


@pytest.mark.asyncio
async def test_jsm_error_recorded_without_halting(mock_get_session, base_state):
    await _seed_technician(mock_get_session, jira_account_id="jira-acc-789")
    state = dict(base_state, assigned_team="net-team")

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.assign_ticket = AsyncMock(side_effect=Exception("403 Forbidden"))

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm):
        result = await assignment_node(state)

    assert result["assignment_status"] == "jsm_error"
    assert "pipeline_halted" not in result  # never sets a halt flag
