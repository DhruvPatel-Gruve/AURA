"""Tests for GET /api/v1/admin/qdrant/stats."""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import require_admin
from app.db.sqlite import get_db
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_ADMIN = {"user_id": "test-admin", "tenant_id": TENANT, "email": "admin@aura.local", "role": "admin"}


def _make_client() -> MagicMock:
    """MagicMock Qdrant client pre-wired so ensure_tenant_collection() (called
    by the qdrant/stats route) can run without hitting real Qdrant: it needs
    get_collections()/create_collection() awaitable, and the module-level
    _ensured_collections cache cleared so this test doesn't inherit an
    "already ensured" skip from another test's collection name.
    """
    from app.db import qdrant_client as _qdrant_client_module

    _qdrant_client_module._ensured_collections.clear()
    client = MagicMock()
    client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    client.create_collection = AsyncMock(return_value=None)
    return client


def _lifespan_patches():
    return [
        patch("app.db.sqlite.init_db", new=AsyncMock()),
        patch("app.db.sqlite.close_db", new=AsyncMock()),
        patch("app.db.qdrant_client.init_qdrant", new=AsyncMock()),
        patch("app.db.qdrant_client.close_qdrant", new=AsyncMock()),
        patch("scheduler.scheduler.start", new=AsyncMock()),
        patch("scheduler.scheduler.stop", new=AsyncMock()),
    ]


def _point(**payload):
    p = MagicMock()
    p.payload = payload
    return p


@pytest.mark.asyncio
async def test_qdrant_stats_counts_distinct_documents_and_tickets(db_session):
    from app.main import create_app

    client = _make_client()
    client.get_collection = AsyncMock(return_value=MagicMock(points_count=6))
    client.scroll = AsyncMock(
        return_value=(
            [
                # ticket TEST-001 has 3 chunks (title_desc, comments, resolution)
                _point(source_type="ticket", ticket_id="TEST-001"),
                _point(source_type="ticket", ticket_id="TEST-001"),
                _point(source_type="ticket", ticket_id="TEST-001"),
                # ticket TEST-002 has 1 chunk
                _point(source_type="ticket", ticket_id="TEST-002"),
                # document doc1 has 2 chunks
                _point(source_type="document", doc_id="doc1"),
                _point(source_type="document", doc_id="doc1"),
            ],
            None,
        )
    )

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.db.qdrant_client._client", client))
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/admin/qdrant/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["documents_count"] == 1
    assert body["tickets_count"] == 2
    assert body["total_chunks"] == 6


@pytest.mark.asyncio
async def test_qdrant_stats_paginates_via_scroll_offset(db_session):
    from app.main import create_app

    client = _make_client()
    client.get_collection = AsyncMock(return_value=MagicMock(points_count=2))
    client.scroll = AsyncMock(
        side_effect=[
            ([_point(source_type="document", doc_id="doc1")], "next-offset"),
            ([_point(source_type="ticket", ticket_id="TEST-001")], None),
        ]
    )

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.db.qdrant_client._client", client))
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/admin/qdrant/stats")

    assert response.status_code == 200
    assert client.scroll.call_count == 2
    body = response.json()
    assert body["documents_count"] == 1
    assert body["tickets_count"] == 1


@pytest.mark.asyncio
async def test_qdrant_stats_empty_collection(db_session):
    from app.main import create_app

    client = _make_client()
    client.get_collection = AsyncMock(return_value=MagicMock(points_count=0))
    client.scroll = AsyncMock(return_value=([], None))

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.db.qdrant_client._client", client))
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/admin/qdrant/stats")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "documents_count": 0,
        "tickets_count": 0,
        "total_chunks": 0,
        "last_sync": None,
        "coverage_by_category": {},
    }
