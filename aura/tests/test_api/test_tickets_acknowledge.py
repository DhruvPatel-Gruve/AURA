"""Tests for POST /tickets/{ticket_id}/acknowledge — acknowledging a ticket
must transition it Open -> "in progress" on the real ITSM ticket, using the
active provider's own status name (Jira: "In Progress", Zendesk: "open"),
not just flip an internal flag."""

import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text

from app.core.security import require_technician
from app.db.sqlite import get_db
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_TECH = {
    "user_id": "test-tech",
    "tenant_id": TENANT,
    "email": "tech@example.com",
    "role": "technician",
    "team_id": "",
}


def _lifespan_patches():
    return [
        patch("app.db.sqlite.init_db", new=AsyncMock()),
        patch("app.db.sqlite.close_db", new=AsyncMock()),
        patch("app.db.qdrant_client.init_qdrant", new=AsyncMock()),
        patch("app.db.qdrant_client.close_qdrant", new=AsyncMock()),
        patch("scheduler.scheduler.start", new=AsyncMock()),
        patch("scheduler.scheduler.stop", new=AsyncMock()),
    ]


async def _seed_assignment(db, ticket_id: str, technician_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        sa_text(
            "INSERT OR IGNORE INTO users (user_id, tenant_id, email, hashed_password, role, display_name, is_active, created_at) "
            "VALUES (:uid, :tenant, :email, 'x', 'technician', :uid, 1, :now)"
        ),
        {"uid": technician_id, "tenant": TENANT, "email": f"{technician_id}@example.com", "now": now},
    )
    await db.execute(
        sa_text(
            "INSERT INTO ticket_assignments (assignment_id, tenant_id, ticket_id, assigned_to, team_id, assigned_at, is_current) "
            "VALUES (:aid, :tenant, :tid, :uid, '', :now, 1)"
        ),
        {"aid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "uid": technician_id, "now": now},
    )
    await db.commit()


@pytest.mark.asyncio
async def test_acknowledge_transitions_jira_ticket_to_in_progress(db_session):
    from app.main import create_app

    await _seed_assignment(db_session, "KAN-1", _FAKE_TECH["user_id"])

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.find_transition_id = AsyncMock(return_value="11")
    mock_jsm.transition_issue = AsyncMock(return_value=None)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/tickets/KAN-1/acknowledge")

    assert response.status_code == 200
    mock_jsm.find_transition_id.assert_called_once_with("KAN-1", "In Progress")
    mock_jsm.transition_issue.assert_called_once_with("KAN-1", "11")


@pytest.mark.asyncio
async def test_acknowledge_transitions_zendesk_ticket_to_in_progress(db_session):
    """Zendesk has no native "In Progress" status, but accounts can define
    it as a Custom Ticket Status — ZendeskClient.find_transition_id resolves
    that for us, so the caller (acknowledge) just asks for "In Progress"
    the same way it does on Jira."""
    from app.main import create_app
    from app.services import itsm_provider_state

    await itsm_provider_state.set(db_session, TENANT, "zendesk")
    await _seed_assignment(db_session, "42", _FAKE_TECH["user_id"])

    mock_zd = AsyncMock()
    mock_zd.__aenter__ = AsyncMock(return_value=mock_zd)
    mock_zd.__aexit__ = AsyncMock(return_value=None)
    mock_zd.find_transition_id = AsyncMock(return_value="custom:48466469619985")
    mock_zd.transition_issue = AsyncMock(return_value=None)

    try:
        with ExitStack() as stack:
            for p in _lifespan_patches():
                stack.enter_context(p)
            stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_zd))
            app = create_app()
            app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
            app.dependency_overrides[get_db] = lambda: db_session
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.post("/api/v1/tickets/42/acknowledge")

        assert response.status_code == 200
        mock_zd.find_transition_id.assert_called_once_with("42", "In Progress")
        mock_zd.transition_issue.assert_called_once_with("42", "custom:48466469619985")
    finally:
        await itsm_provider_state.set(db_session, TENANT, "jira")


@pytest.mark.asyncio
async def test_acknowledge_still_succeeds_when_transition_fails(db_session):
    """A failed ITSM transition must never block the acknowledge itself —
    it's best-effort, same guarantee transition_service already gives
    everywhere else it's used."""
    from app.main import create_app

    await _seed_assignment(db_session, "KAN-2", _FAKE_TECH["user_id"])

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.find_transition_id = AsyncMock(side_effect=Exception("Jira unreachable"))

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/tickets/KAN-2/acknowledge")

    assert response.status_code == 200

    row = (await db_session.execute(
        sa_text("SELECT acknowledged_at FROM ticket_assignments WHERE ticket_id = 'KAN-2'")
    )).first()
    assert row is not None and row[0] is not None


@pytest.mark.asyncio
async def test_acknowledge_returns_409_when_not_assigned_to_caller(db_session):
    from app.main import create_app

    await _seed_assignment(db_session, "KAN-3", "someone-else")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/tickets/KAN-3/acknowledge")

    assert response.status_code == 409
