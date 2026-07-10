"""Regression tests for POST /tickets/submit.

Previously every submission failed: create_ticket() sent the reporter's
free-text category_hint (e.g. "Access & Permissions") straight through as
the Jira `issuetype.name`, which Jira rejects with 400 since it isn't a real
issue type for the project. The route also had no try/except, so that 400
became an unhandled 500 with no detail — surfaced to the end user as a
generic toast with no way to diagnose it.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text

from app.core.security import require_any_auth
from app.db.sqlite import get_db
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_USER = {
    "user_id": "test-user",
    "tenant_id": TENANT,
    "email": "user@example.com",
    "role": "end_user",
    "team_id": None,
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


async def _seed_user(db, user_id: str):
    await db.execute(
        sa_text(
            "INSERT OR IGNORE INTO users (user_id, tenant_id, email, hashed_password, role, display_name, is_active, created_at) "
            "VALUES (:uid, :tenant, :email, 'x', 'end_user', :uid, 1, '2024-01-01T00:00:00')"
        ),
        {"uid": user_id, "tenant": TENANT, "email": f"{user_id}@example.com"},
    )
    await db.commit()


@pytest.mark.asyncio
async def test_submit_never_sends_category_hint_as_issuetype(db_session):
    from app.main import create_app

    await _seed_user(db_session, "test-user")

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.create_ticket = AsyncMock(return_value="KAN-99")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        app = create_app()
        app.dependency_overrides[require_any_auth] = lambda: _FAKE_USER
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/tickets/submit",
                json={
                    "summary": "VPN not connecting",
                    "description": "Getting a timeout every time I try to connect.",
                    "category_hint": "Access & Permissions",
                },
            )

    assert response.status_code == 200
    assert response.json()["ticket_id"] == "KAN-99"
    # create_ticket must never be called with a `category` kwarg — that was
    # the bug (a free-text hint sent straight through as a Jira issuetype).
    mock_jsm.create_ticket.assert_called_once()
    assert "category" not in mock_jsm.create_ticket.call_args.kwargs
    # The hint should be folded into the description instead of dropped.
    assert "Access & Permissions" in mock_jsm.create_ticket.call_args.kwargs["description"]

    row = (await db_session.execute(
        sa_text("SELECT ticket_id FROM user_submitted_tickets WHERE ticket_id = 'KAN-99'")
    )).first()
    assert row is not None


@pytest.mark.asyncio
async def test_submit_returns_diagnosable_error_on_jira_rejection(db_session):
    from app.main import create_app

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    bad_response = httpx.Response(400, request=httpx.Request("POST", "https://x.atlassian.net/rest/api/3/issue"))
    mock_jsm.create_ticket = AsyncMock(
        side_effect=httpx.HTTPStatusError("Bad Request", request=bad_response.request, response=bad_response)
    )

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        app = create_app()
        app.dependency_overrides[require_any_auth] = lambda: _FAKE_USER
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/tickets/submit",
                json={"summary": "test", "description": "test description"},
            )

    # Must be a handled error with a real detail message, not a bare
    # unhandled-exception 500 with no body.
    assert response.status_code == 502
    assert "detail" in response.json()
