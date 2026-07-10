"""Regression test: GET /admin/audit-log and its CSV export accepted
date_from/date_to in the frontend but silently dropped them server-side —
the route never declared the params even though audit_logger.get_entries()/
export_csv() already supported them."""

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text

from app.core.security import require_admin, require_manager
from app.db.sqlite import get_db
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_MANAGER = {
    "user_id": "test-mgr", "tenant_id": TENANT, "email": "mgr@example.com",
    "role": "manager", "team_id": None,
}
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


async def _seed_entry(db, ticket_id: str, created_at: str):
    await db.execute(
        sa_text(
            "INSERT INTO audit_log (entry_id, tenant_id, ticket_id, action_taken, audit_steps, created_at) "
            "VALUES (:eid, :tenant, :tid, 'comment_posted', '[]', :now)"
        ),
        {"eid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "now": created_at},
    )
    await db.commit()


@pytest.mark.asyncio
async def test_date_from_narrows_audit_log_results(db_session):
    from app.main import create_app

    await _seed_entry(db_session, "OLD-1", "2020-01-01T00:00:00")
    await _seed_entry(db_session, "NEW-1", "2030-01-01T00:00:00")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_manager] = lambda: _FAKE_MANAGER
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/admin/audit-log", params={"date_from": "2025-01-01"}
            )

    assert response.status_code == 200
    body = response.json()
    ticket_ids = {item["ticket_id"] for item in body["items"]}
    assert ticket_ids == {"NEW-1"}


@pytest.mark.asyncio
async def test_date_range_narrows_csv_export(db_session):
    from app.main import create_app

    await _seed_entry(db_session, "OLD-1", "2020-01-01T00:00:00")
    await _seed_entry(db_session, "NEW-1", "2030-01-01T00:00:00")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/admin/audit/export", params={"date_to": "2025-01-01"}
            )

    assert response.status_code == 200
    assert "OLD-1" in response.text
    assert "NEW-1" not in response.text
