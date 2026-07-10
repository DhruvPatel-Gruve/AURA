"""Regression test for GET /admin/audit/export — previously called
audit_logger.export_csv(db, filters) positionally against a keyword-only
signature, raising an unconditional TypeError on every request."""

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import require_admin
from app.db.sqlite import get_db
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_ADMIN = {
    "user_id": "test-admin", "tenant_id": TENANT, "email": "admin@example.com",
    "role": "admin", "team_id": None,
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


@pytest.mark.asyncio
async def test_export_audit_succeeds(db_session):
    from app.main import create_app

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/admin/audit/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    # Header row must be present even with zero audit_log rows
    assert "entry_id" in response.text


@pytest.mark.asyncio
async def test_export_audit_with_filters_succeeds(db_session):
    from app.main import create_app

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/admin/audit/export",
                params={"ticket_id": "KAN-1", "action_type": "comment_posted"},
            )

    assert response.status_code == 200
