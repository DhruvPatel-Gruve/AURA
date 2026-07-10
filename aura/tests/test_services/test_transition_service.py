"""Tests for app.services.transition_service."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.services import transition_service

TENANT = "test-tenant-1"


@pytest.mark.asyncio
async def test_try_transition_success_registers_reverse_rollback(db_session):
    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.find_transition_id = AsyncMock(side_effect=["11", "5"])
    mock_jsm.transition_issue = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _session():
        yield db_session

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm), \
         patch("app.services.transition_service.get_session", _session):
        result = await transition_service.try_transition(TENANT, "KAN-1", "In Progress", "Open")

    assert result is True
    mock_jsm.transition_issue.assert_called_once_with("KAN-1", "11")

    from sqlalchemy import text as sa_text
    row = (await db_session.execute(
        sa_text("SELECT action_type, rollback_call FROM rollback_store WHERE tenant_id = :tid AND ticket_id = 'KAN-1'"),
        {"tid": TENANT},
    )).mappings().first()
    assert row is not None
    assert row["action_type"] == "ticket_transitioned"
    assert '"id": "5"' in row["rollback_call"]


@pytest.mark.asyncio
async def test_try_transition_returns_false_when_unreachable():
    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.find_transition_id = AsyncMock(return_value=None)

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm):
        result = await transition_service.try_transition(TENANT, "KAN-1", "In Progress", "Open")

    assert result is False
    mock_jsm.transition_issue.assert_not_called()


@pytest.mark.asyncio
async def test_try_transition_no_rollback_when_original_status_unknown(db_session):
    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.find_transition_id = AsyncMock(return_value="11")
    mock_jsm.transition_issue = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _session():
        yield db_session

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm), \
         patch("app.services.transition_service.get_session", _session):
        result = await transition_service.try_transition(TENANT, "KAN-1", "In Progress", None)

    assert result is True
    # Only one find_transition_id call (for the target) — no reverse lookup attempted
    mock_jsm.find_transition_id.assert_called_once_with("KAN-1", "In Progress")

    from sqlalchemy import text as sa_text
    row = (await db_session.execute(
        sa_text("SELECT status FROM ticket_status WHERE tenant_id = :tid AND ticket_id = 'KAN-1'"),
        {"tid": TENANT},
    )).first()
    assert row is not None and row[0] == "In Progress"


@pytest.mark.asyncio
async def test_try_transition_swallows_errors():
    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.find_transition_id = AsyncMock(side_effect=Exception("boom"))

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm):
        result = await transition_service.try_transition(TENANT, "KAN-1", "In Progress", "Open")

    assert result is False
