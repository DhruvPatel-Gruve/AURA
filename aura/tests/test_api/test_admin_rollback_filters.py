"""Regression test: GET /admin/rollback previously had no date_from/date_to
params even though rollback_store.get_history() already supported them, and
the frontend discarded total/page/pages entirely (hard-capped at 50 visible
records with no way to page). This covers the backend half of that fix."""

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text

from app.core.security import require_admin
from app.db.sqlite import get_db
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_ADMIN = {
    "user_id": "test-admin",
    "tenant_id": TENANT,
    "email": "admin@example.com",
    "role": "admin",
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


async def _seed_rollback(db, ticket_id: str, created_at: str):
    await db.execute(
        sa_text(
            "INSERT INTO rollback_store (action_id, tenant_id, ticket_id, action_type, rollback_call, actor, created_at) "
            "VALUES (:aid, :tenant, :tid, 'comment_posted', '{}', 'AURA_AGENT', :now)"
        ),
        {"aid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "now": created_at},
    )
    await db.commit()


@pytest.mark.asyncio
async def test_rollback_date_from_narrows_results_and_returns_pagination(db_session):
    from app.main import create_app

    await _seed_rollback(db_session, "OLD-1", "2020-01-01T00:00:00")
    await _seed_rollback(db_session, "NEW-1", "2030-01-01T00:00:00")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/admin/rollback", params={"date_from": "2025-01-01"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["ticket_id"] == "NEW-1"
    assert "page" in body and "pages" in body
