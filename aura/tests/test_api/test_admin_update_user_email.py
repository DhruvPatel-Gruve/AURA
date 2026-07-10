"""Tests for PATCH /api/v1/admin/users/{user_id} email updates."""

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text

from app.core.security import require_admin
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_ADMIN = {"user_id": "test-admin", "tenant_id": TENANT, "email": "admin@aura.local", "role": "admin"}


def _lifespan_patches():
    return [
        patch("app.db.sqlite.init_db", new=AsyncMock()),
        patch("app.db.sqlite.close_db", new=AsyncMock()),
        patch("app.db.qdrant_client.init_qdrant", new=AsyncMock()),
        patch("app.db.qdrant_client.close_qdrant", new=AsyncMock()),
        patch("scheduler.scheduler.start", new=AsyncMock()),
        patch("scheduler.scheduler.stop", new=AsyncMock()),
    ]


async def _seed_user(db, *, email, jira_account_id=None):
    from app.db.sqlite import get_db
    user_id = str(uuid.uuid4())
    await db.execute(
        sa_text(
            "INSERT INTO users (user_id, tenant_id, email, hashed_password, display_name, role, "
            "jira_account_id, created_at) "
            "VALUES (:uid, :tenant, :email, 'x', 'Test User', 'technician', :jira, '2024-01-01T00:00:00')"
        ),
        {"uid": user_id, "tenant": TENANT, "email": email, "jira": jira_account_id},
    )
    await db.commit()
    return user_id


@pytest.mark.asyncio
async def test_update_email_clears_stale_jira_account_id(db_session):
    from app.db.sqlite import get_db
    from app.main import create_app

    user_id = await _seed_user(db_session, email="old@aura.local", jira_account_id="stale-acc-123")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.patch(
                f"/api/v1/admin/users/{user_id}",
                json={"email": "newreal@gmail.com"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "newreal@gmail.com"
    assert body["jira_account_id"] is None


@pytest.mark.asyncio
async def test_update_email_keeps_jira_account_id_when_explicitly_provided(db_session):
    from app.db.sqlite import get_db
    from app.main import create_app

    user_id = await _seed_user(db_session, email="old2@aura.local", jira_account_id="stale-acc-456")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.patch(
                f"/api/v1/admin/users/{user_id}",
                json={"email": "newreal2@gmail.com", "jira_account_id": "fresh-acc-789"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["jira_account_id"] == "fresh-acc-789"


@pytest.mark.asyncio
async def test_update_password_rehashes_and_allows_new_login(db_session):
    from app.core.security import verify_password
    from app.db.sqlite import get_db
    from app.main import create_app

    user_id = await _seed_user(db_session, email="reset-me@gmail.com")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.patch(
                f"/api/v1/admin/users/{user_id}",
                json={"password": "newpassword123"},
            )

    assert response.status_code == 200
    row = (await db_session.execute(
        sa_text("SELECT hashed_password FROM users WHERE user_id = :uid"), {"uid": user_id}
    )).first()
    assert verify_password("newpassword123", row[0])
    assert not verify_password("x", row[0])


@pytest.mark.asyncio
async def test_update_email_rejects_duplicate(db_session):
    from app.db.sqlite import get_db
    from app.main import create_app

    await _seed_user(db_session, email="taken@gmail.com")
    user_id = await _seed_user(db_session, email="other@aura.local")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.patch(
                f"/api/v1/admin/users/{user_id}",
                json={"email": "taken@gmail.com"},
            )

    assert response.status_code == 409
