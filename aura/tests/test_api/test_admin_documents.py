"""Tests for GET/DELETE /api/v1/admin/documents."""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import require_admin
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_ADMIN = {"user_id": "test-admin", "tenant_id": TENANT, "email": "admin@aura.local", "role": "admin"}


def _make_client() -> MagicMock:
    """MagicMock Qdrant client pre-wired so ensure_tenant_collection() (called
    by every documents route) can run without hitting real Qdrant: it needs
    get_collections()/create_collection() awaitable, and the module-level
    _ensured_collections cache cleared so this test doesn't inherit a
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


def _make_point(doc_id: str, filename: str, uploaded_at: str | None):
    point = MagicMock()
    point.payload = {"doc_id": doc_id, "filename": filename, "uploaded_at": uploaded_at}
    return point


@pytest.mark.asyncio
async def test_list_documents_aggregates_chunks_by_doc_id():
    from app.main import create_app

    client = _make_client()
    client.scroll = AsyncMock(
        return_value=(
            [
                _make_point("doc1", "guide.pdf", "2024-01-10T08:00:00+00:00"),
                _make_point("doc1", "guide.pdf", "2024-01-10T08:00:00+00:00"),
                _make_point("doc2", "policy.docx", "2024-01-11T09:00:00+00:00"),
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
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/admin/documents")

    assert response.status_code == 200
    docs = {d["doc_id"]: d for d in response.json()["documents"]}
    assert docs["doc1"]["chunk_count"] == 2
    assert docs["doc1"]["filename"] == "guide.pdf"
    assert docs["doc2"]["chunk_count"] == 1


@pytest.mark.asyncio
async def test_list_documents_paginates_via_scroll_offset():
    from app.main import create_app

    client = _make_client()
    client.scroll = AsyncMock(
        side_effect=[
            ([_make_point("doc1", "guide.pdf", None)], "next-offset"),
            ([_make_point("doc2", "policy.docx", None)], None),
        ]
    )

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.db.qdrant_client._client", client))
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/admin/documents")

    assert response.status_code == 200
    assert client.scroll.call_count == 2
    assert {d["doc_id"] for d in response.json()["documents"]} == {"doc1", "doc2"}


@pytest.mark.asyncio
async def test_delete_document_filters_by_doc_id():
    from app.main import create_app

    client = _make_client()
    client.delete = AsyncMock(return_value=None)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.db.qdrant_client._client", client))
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.delete("/api/v1/admin/documents/doc1")

    assert response.status_code == 200
    client.delete.assert_called_once()
    kwargs = client.delete.call_args.kwargs
    condition = kwargs["points_selector"].filter.must[0]
    assert condition.key == "doc_id"
    assert condition.match.value == "doc1"


@pytest.mark.asyncio
async def test_documents_endpoints_require_admin():
    from app.main import create_app

    client = MagicMock()

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.db.qdrant_client._client", client))
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            list_resp = await ac.get("/api/v1/admin/documents")
            delete_resp = await ac.delete("/api/v1/admin/documents/doc1")

    assert list_resp.status_code == 401
    assert delete_resp.status_code == 401
