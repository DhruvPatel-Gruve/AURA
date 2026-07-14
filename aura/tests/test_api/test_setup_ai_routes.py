"""Tests for POST /setup/test-embedding-connection and /setup/test-llm-connection."""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text

from app.core.security import require_admin
from app.db.sqlite import get_db
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


def _app(db_session):
    from app.main import create_app
    app = create_app()
    app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
    app.dependency_overrides[get_db] = lambda: db_session
    return app


def _embed_response(vector: list[float]):
    return {"embedding": vector}


# ── /setup/test-embedding-connection ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_embedding_connection_gemini_success(db_session):
    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.rag.embedder.genai.configure"))
        stack.enter_context(patch("app.rag.embedder.genai.embed_content", return_value=_embed_response([0.1] * 768)))
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/setup/test-embedding-connection",
                json={"provider": "gemini", "api_key": "fake-key"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["vector_size"] == 768

    row = (await db_session.execute(
        sa_text("SELECT embedding_provider, embedding_model, embedding_vector_size FROM platform_config WHERE tenant_id = :tid"),
        {"tid": TENANT},
    )).mappings().first()
    assert row["embedding_provider"] == "gemini"
    assert row["embedding_model"] == "models/gemini-embedding-2"
    assert row["embedding_vector_size"] == 768


@pytest.mark.asyncio
async def test_embedding_connection_openai_compatible_vector_size_mismatch_fails(db_session):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.core.url_safety.assert_safe_ai_endpoint_url", new=AsyncMock()))
        stack.enter_context(patch("openai.AsyncOpenAI", return_value=mock_client))
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/setup/test-embedding-connection",
                json={
                    "provider": "openai_compatible",
                    "api_key": "fake-key",
                    "base_url": "http://localhost:8080/v1",
                    "model": "text-embedding-3-small",
                    "vector_size": 768,   # actual model returns 1536 — mismatch
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "1536" in body["error"]
    assert "768" in body["error"]

    row = (await db_session.execute(
        sa_text("SELECT embedding_provider FROM platform_config WHERE tenant_id = :tid"),
        {"tid": TENANT},
    )).mappings().first()
    assert row["embedding_provider"] is None  # never persisted on failure


@pytest.mark.asyncio
async def test_embedding_connection_openai_compatible_success(db_session):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.core.url_safety.assert_safe_ai_endpoint_url", new=AsyncMock()))
        stack.enter_context(patch("openai.AsyncOpenAI", return_value=mock_client))
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/setup/test-embedding-connection",
                json={
                    "provider": "openai_compatible",
                    "api_key": "fake-key",
                    "base_url": "http://localhost:8080/v1",
                    "model": "text-embedding-3-small",
                    "vector_size": 1536,
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["vector_size"] == 1536

    row = (await db_session.execute(
        sa_text("SELECT embedding_provider, embedding_base_url, embedding_model, embedding_vector_size "
                "FROM platform_config WHERE tenant_id = :tid"),
        {"tid": TENANT},
    )).mappings().first()
    assert row["embedding_provider"] == "openai_compatible"
    assert row["embedding_base_url"] == "http://localhost:8080/v1"
    assert row["embedding_model"] == "text-embedding-3-small"
    assert row["embedding_vector_size"] == 1536


# ── /setup/test-llm-connection ─────────────────────────────────────────────────

def _llm_response(text: str):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    return resp


@pytest.mark.asyncio
async def test_llm_connection_success(db_session):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_llm_response("ready"))

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.core.url_safety.assert_safe_ai_endpoint_url", new=AsyncMock()))
        stack.enter_context(patch("openai.AsyncOpenAI", return_value=mock_client))
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/setup/test-llm-connection",
                json={"base_url": "http://localhost:11434/v1", "model": "qwen3:8b"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["sample_reply"] == "ready"

    row = (await db_session.execute(
        sa_text("SELECT llm_base_url, llm_model FROM platform_config WHERE tenant_id = :tid"),
        {"tid": TENANT},
    )).mappings().first()
    assert row["llm_base_url"] == "http://localhost:11434/v1"
    assert row["llm_model"] == "qwen3:8b"


@pytest.mark.asyncio
async def test_llm_connection_failure_not_persisted(db_session):
    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.core.url_safety.assert_safe_ai_endpoint_url", new=AsyncMock()))
        stack.enter_context(patch("openai.AsyncOpenAI", side_effect=Exception("connection refused")))
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/setup/test-llm-connection",
                json={"base_url": "http://localhost:11434/v1", "model": "qwen3:8b"},
            )

    assert response.status_code == 200
    assert response.json()["success"] is False

    row = (await db_session.execute(
        sa_text("SELECT llm_base_url FROM platform_config WHERE tenant_id = :tid"),
        {"tid": TENANT},
    )).mappings().first()
    assert row["llm_base_url"] is None


# ── Relaxed URL guard for AI endpoints ─────────────────────────────────────────

def test_ai_endpoint_guard_allows_http_public_ip():
    from app.core.url_safety import _check_ai_endpoint_sync
    _check_ai_endpoint_sync("http://79.135.120.213:8200/v1")   # must not raise


def test_ai_endpoint_guard_allows_localhost():
    from app.core.url_safety import _check_ai_endpoint_sync
    _check_ai_endpoint_sync("http://localhost:11434/v1")       # local Ollama — must not raise


def test_ai_endpoint_guard_blocks_cloud_metadata_address():
    from app.core.url_safety import UnsafeURLError, _check_ai_endpoint_sync
    with pytest.raises(UnsafeURLError):
        _check_ai_endpoint_sync("http://169.254.169.254/latest/meta-data")


def test_ai_endpoint_guard_blocks_non_http_scheme():
    from app.core.url_safety import UnsafeURLError, _check_ai_endpoint_sync
    with pytest.raises(UnsafeURLError):
        _check_ai_endpoint_sync("file:///etc/passwd")


# ── Secrets never touch wizard_progress ────────────────────────────────────────

@pytest.mark.asyncio
async def test_raw_api_key_never_appears_in_wizard_progress(db_session):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_llm_response("ready"))
    secret_key = "super-secret-llm-api-key-should-never-be-stored-in-wizard-progress"

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.core.url_safety.assert_safe_ai_endpoint_url", new=AsyncMock()))
        stack.enter_context(patch("openai.AsyncOpenAI", return_value=mock_client))
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post(
                "/api/v1/setup/test-llm-connection",
                json={"base_url": "http://localhost:11434/v1", "model": "qwen3:8b", "api_key": secret_key},
            )
            await ac.post(
                "/api/v1/setup/wizard/save",
                json={"step": 5, "data": {"llm_tested": True, "embeddings_tested": True}},
            )

    rows = (await db_session.execute(
        sa_text("SELECT step_data FROM wizard_progress WHERE tenant_id = :tid"),
        {"tid": TENANT},
    )).all()
    for row in rows:
        assert secret_key not in row[0]

    row = (await db_session.execute(
        sa_text("SELECT llm_api_key_encrypted FROM platform_config WHERE tenant_id = :tid"),
        {"tid": TENANT},
    )).mappings().first()
    assert row["llm_api_key_encrypted"] is not None
    assert secret_key not in row["llm_api_key_encrypted"]   # stored encrypted, not plaintext
