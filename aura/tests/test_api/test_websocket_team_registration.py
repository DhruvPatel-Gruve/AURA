"""Regression test: WS connections must register with the user's real team_id.

Bug: websocket_endpoint hardcoded team_id=None on every connection, so
broadcast_to_team() (used by assignment_node, confidence_gate_node, etc.)
never matched any connected technician — assignment notifications were
silently swallowed even though the technician was online.
"""

import uuid
from contextlib import ExitStack, asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text as sa_text
from starlette.testclient import TestClient

from app.core.security import create_access_token


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
async def test_websocket_registers_with_real_team_id(db_session):
    from app.main import create_app

    user_id = str(uuid.uuid4())
    await db_session.execute(
        sa_text(
            "INSERT INTO users (user_id, email, hashed_password, display_name, role, "
            "team_id, created_at) "
            "VALUES (:uid, 'tech@example.com', 'x', 'Tech', 'technician', 'net-team', '2024-01-01T00:00:00')"
        ),
        {"uid": user_id},
    )
    await db_session.commit()

    token = create_access_token({"sub": user_id, "role": "technician"})

    @asynccontextmanager
    async def _session():
        yield db_session

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.api.v1.routes.websocket.get_session", _session))
        register_mock = stack.enter_context(
            patch("app.api.v1.routes.websocket.notification_bus.register", new=AsyncMock())
        )
        stack.enter_context(
            patch("app.api.v1.routes.websocket.notification_bus.unregister", new=AsyncMock())
        )

        app = create_app()
        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/ws/{user_id}?token={token}"):
            pass

    register_mock.assert_called_once()
    kwargs = register_mock.call_args.kwargs
    assert kwargs["team_id"] == "net-team"
    assert kwargs["role"] == "technician"
