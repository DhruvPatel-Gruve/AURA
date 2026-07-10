"""Tests for app.services.rollback_store — focused on the ticket_transitioned
dispatch branch added alongside the status-transition feature."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services import rollback_store

TENANT = "test-tenant-1"


@pytest.mark.asyncio
async def test_register_and_execute_ticket_transitioned(db_session):
    action_id = await rollback_store.register(
        db_session,
        tenant_id=TENANT,
        action_type="ticket_transitioned",
        ticket_id="KAN-1",
        rollback_call={
            "method": "POST",
            "url": "/rest/api/3/issue/KAN-1/transitions",
            "body": {"transition": {"id": "5"}},
        },
        actor="AURA_AGENT",
    )

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.transition_issue = AsyncMock(return_value=None)

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm):
        result = await rollback_store.execute(db_session, TENANT, action_id, triggered_by="admin-1")

    assert result["success"] is True
    mock_jsm.transition_issue.assert_called_once_with("KAN-1", "5")


@pytest.mark.asyncio
async def test_execute_ticket_transitioned_missing_id_raises(db_session):
    action_id = await rollback_store.register(
        db_session,
        tenant_id=TENANT,
        action_type="ticket_transitioned",
        ticket_id="KAN-1",
        rollback_call={"method": "POST", "url": "...", "body": {}},
        actor="AURA_AGENT",
    )

    with pytest.raises(ValueError, match="Cannot extract transition id"):
        await rollback_store.execute(db_session, TENANT, action_id, triggered_by="admin-1")


@pytest.mark.asyncio
async def test_execute_guards_against_double_rollback(db_session):
    action_id = await rollback_store.register(
        db_session,
        tenant_id=TENANT,
        action_type="ticket_transitioned",
        ticket_id="KAN-1",
        rollback_call={"body": {"transition": {"id": "5"}}},
        actor="AURA_AGENT",
    )

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.transition_issue = AsyncMock(return_value=None)

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm):
        await rollback_store.execute(db_session, TENANT, action_id, triggered_by="admin-1")
        with pytest.raises(ValueError, match="already been rolled back"):
            await rollback_store.execute(db_session, TENANT, action_id, triggered_by="admin-1")


@pytest.mark.asyncio
async def test_execute_only_dispatches_once_even_if_reinvoked_before_first_commit(db_session):
    """Regression test: execute() must claim the row (atomic conditional
    UPDATE) BEFORE calling _dispatch(), not after — otherwise two calls that
    both pass the initial SELECT check race to dispatch the reverse Jira
    call twice. Simulated here by making _dispatch itself attempt the second
    execute() call while the first is "in flight" from the dispatcher's
    point of view."""
    action_id = await rollback_store.register(
        db_session,
        tenant_id=TENANT,
        action_type="ticket_transitioned",
        ticket_id="KAN-1",
        rollback_call={"body": {"transition": {"id": "5"}}},
        actor="AURA_AGENT",
    )

    dispatch_calls = []

    async def fake_dispatch(tenant_id, ticket_id, action_type, rollback_call):
        dispatch_calls.append(action_id)
        # A second caller attempting the same rollback while the first is
        # mid-dispatch must be rejected — the claim already happened.
        with pytest.raises(ValueError, match="already been rolled back"):
            await rollback_store.execute(db_session, TENANT, action_id, triggered_by="admin-2")
        return "dispatched"

    with patch("app.services.rollback_store._dispatch", fake_dispatch):
        result = await rollback_store.execute(db_session, TENANT, action_id, triggered_by="admin-1")

    assert result["success"] is True
    assert len(dispatch_calls) == 1
