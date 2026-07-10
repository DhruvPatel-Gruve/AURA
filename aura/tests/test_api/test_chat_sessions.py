"""Regression tests for Live Chat session-scoped memory + explicit close.

Previously chat_messages had no session/conversation concept at all — the
LLM prompt was fed the caller's last 10 messages ever sent, regardless of
topic or age, with no way to reset. Now messages are scoped to a
chat_sessions row; closing it means the next message starts with zero
memory of the closed conversation.
"""

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

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


def _mock_llm_response(text: str):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text))]
    return resp


def _app(db_session):
    from app.main import create_app
    app = create_app()
    app.dependency_overrides[require_any_auth] = lambda: _FAKE_USER
    app.dependency_overrides[get_db] = lambda: db_session
    return app


@pytest.mark.asyncio
async def test_consecutive_messages_share_a_session_and_prior_turn_is_in_prompt(db_session):
    await _seed_user(db_session, "test-user")

    captured_messages = []

    async def fake_create(*, model, messages, max_tokens, temperature):
        captured_messages.append(messages)
        return _mock_llm_response("ok")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=fake_create)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.api.v1.routes.chat.AsyncOpenAI", return_value=mock_client))
        stack.enter_context(patch.object(
            __import__("app.rag.retriever", fromlist=["HybridRetriever"]).HybridRetriever,
            "retrieve", new=AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.api.v1.routes.chat.ensure_tenant_collection",
            new=AsyncMock(return_value=f"resolved_tickets_{TENANT}"),
        ))
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r1 = await ac.post("/api/v1/chat", json={"message": "My VPN won't connect"})
            r2 = await ac.post("/api/v1/chat", json={"message": "What did I just ask?"})

    assert r1.status_code == 200 and r2.status_code == 200
    sid1, sid2 = r1.json()["session_id"], r2.json()["session_id"]
    assert sid1 == sid2  # same conversation reused

    # Second LLM call's prompt must include the first turn's content.
    second_call_messages = captured_messages[1]
    assert any("My VPN won't connect" in m["content"] for m in second_call_messages)


@pytest.mark.asyncio
async def test_close_starts_a_fresh_session_with_no_memory(db_session):
    await _seed_user(db_session, "test-user")

    captured_messages = []

    async def fake_create(*, model, messages, max_tokens, temperature):
        captured_messages.append(messages)
        return _mock_llm_response("ok")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=fake_create)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.api.v1.routes.chat.AsyncOpenAI", return_value=mock_client))
        stack.enter_context(patch.object(
            __import__("app.rag.retriever", fromlist=["HybridRetriever"]).HybridRetriever,
            "retrieve", new=AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.api.v1.routes.chat.ensure_tenant_collection",
            new=AsyncMock(return_value=f"resolved_tickets_{TENANT}"),
        ))
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r1 = await ac.post("/api/v1/chat", json={"message": "secret topic A"})
            close_resp = await ac.post("/api/v1/chat/close")
            r2 = await ac.post("/api/v1/chat", json={"message": "unrelated topic B"})

    assert close_resp.status_code == 200
    assert close_resp.json()["closed"] is True

    sid1, sid2 = r1.json()["session_id"], r2.json()["session_id"]
    assert sid1 != sid2  # new conversation after close

    # Second conversation's prompt must NOT contain anything from the closed one.
    second_call_messages = captured_messages[1]
    assert not any("secret topic A" in m["content"] for m in second_call_messages)

    # Old messages are still in the DB (never deleted), just out of scope.
    row = (await db_session.execute(
        sa_text("SELECT COUNT(*) FROM chat_messages WHERE tenant_id = :tenant AND session_id = :sid"),
        {"tenant": TENANT, "sid": sid1},
    )).first()
    assert row[0] == 2  # user + assistant turn from the closed session


@pytest.mark.asyncio
async def test_history_after_close_is_empty_with_null_session(db_session):
    await _seed_user(db_session, "test-user")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_mock_llm_response("ok"))

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.api.v1.routes.chat.AsyncOpenAI", return_value=mock_client))
        stack.enter_context(patch.object(
            __import__("app.rag.retriever", fromlist=["HybridRetriever"]).HybridRetriever,
            "retrieve", new=AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.api.v1.routes.chat.ensure_tenant_collection",
            new=AsyncMock(return_value=f"resolved_tickets_{TENANT}"),
        ))
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.post("/api/v1/chat", json={"message": "hello"})
            await ac.post("/api/v1/chat/close")
            history = await ac.get("/api/v1/chat/history")

    body = history.json()
    assert body["session_id"] is None
    assert body["messages"] == []
