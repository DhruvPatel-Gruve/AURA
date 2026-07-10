"""Tests for the technician-facing rollback-comment / comment routes.

A technician who disagrees with a posted comment (auto-posted above the
confidence threshold, or previously approved/edited) can roll it back and
post a corrected reply — but only after acknowledging the ticket, and only
for their own team (admins bypass both, same as the queue actions).
"""

import json
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text

from app.core.security import require_technician
from app.db.sqlite import get_db
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_TECH = {"user_id": "test-tech", "tenant_id": TENANT, "email": "tech@example.com", "role": "technician", "team_id": ""}
_OTHER_TEAM_TECH = {"user_id": "test-tech-2", "tenant_id": TENANT, "email": "tech2@example.com", "role": "technician", "team_id": "hardware-team"}
_ADMIN_USER = {"user_id": "test-admin", "tenant_id": TENANT, "email": "admin@example.com", "role": "admin", "team_id": None}


def _lifespan_patches():
    return [
        patch("app.db.sqlite.init_db", new=AsyncMock()),
        patch("app.db.sqlite.close_db", new=AsyncMock()),
        patch("app.db.qdrant_client.init_qdrant", new=AsyncMock()),
        patch("app.db.qdrant_client.close_qdrant", new=AsyncMock()),
        patch("scheduler.scheduler.start", new=AsyncMock()),
        patch("scheduler.scheduler.stop", new=AsyncMock()),
    ]


async def _seed_posted_ticket(
    db, ticket_id: str, *, team_id: str = "", acknowledged: bool = True, with_active_rollback: bool = True,
):
    """A ticket that already carries a posted comment (action_taken =
    comment_posted) plus the rollback record comment_poster.post_and_track
    would have registered for it."""
    now = datetime.now(timezone.utc).isoformat()

    await db.execute(
        sa_text(
            "INSERT INTO category_config (category_id, tenant_id, name, team_id, auto_comment_enabled, sla_minutes, created_at, updated_at) "
            "VALUES (:cid, :tenant, 'Network', :team, 1, 480, :now, :now)"
        ),
        {"cid": str(uuid.uuid4()), "tenant": TENANT, "team": team_id, "now": now},
    )
    await db.execute(
        sa_text(
            "INSERT INTO audit_log (entry_id, tenant_id, ticket_id, action_taken, category, jsm_comment_id, audit_steps, created_at) "
            "VALUES (:eid, :tenant, :tid, 'comment_posted', 'Network', 'comment-orig', '[]', :now)"
        ),
        {"eid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "now": now},
    )
    await db.execute(
        sa_text(
            "INSERT OR IGNORE INTO users (user_id, tenant_id, email, hashed_password, role, display_name, is_active, created_at) "
            "VALUES (:uid, :tenant, :email, 'x', 'technician', :uid, 1, :now)"
        ),
        {"uid": _FAKE_TECH["user_id"], "tenant": TENANT, "email": _FAKE_TECH["email"], "now": now},
    )
    await db.execute(
        sa_text(
            "INSERT INTO ticket_assignments (assignment_id, tenant_id, ticket_id, assigned_to, team_id, assigned_at, acknowledged_at, is_current) "
            "VALUES (:aid, :tenant, :tid, :assignee, :team, :now, :ack, 1)"
        ),
        {
            "aid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "assignee": _FAKE_TECH["user_id"],
            "team": team_id, "now": now, "ack": now if acknowledged else None,
        },
    )
    if with_active_rollback:
        await db.execute(
            sa_text(
                "INSERT INTO rollback_store (action_id, tenant_id, ticket_id, action_type, rollback_call, actor, created_at) "
                "VALUES (:aid, :tenant, :tid, 'comment_posted', :rcall, 'AURA_AGENT', :now)"
            ),
            {
                "aid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id,
                "rcall": json.dumps({"method": "DELETE", "url": f"/tickets/{ticket_id}/comments/comment-orig", "body": None}),
                "now": now,
            },
        )
    await db.commit()


def _app(db_session, user):
    from app.main import create_app
    app = create_app()
    app.dependency_overrides[require_technician] = lambda: user
    app.dependency_overrides[get_db] = lambda: db_session
    return app


@pytest.mark.asyncio
async def test_rollback_comment_deletes_and_updates_audit_log(db_session):
    await _seed_posted_ticket(db_session, "KAN-20")

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.delete_comment = AsyncMock(return_value=True)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        stack.enter_context(patch("app.api.v1.routes.tickets.notification_bus.broadcast_to_all", new=AsyncMock()))
        app = _app(db_session, _FAKE_TECH)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/tickets/KAN-20/rollback-comment")

    assert response.status_code == 200
    mock_jsm.delete_comment.assert_called_once_with("KAN-20", "comment-orig")

    row = (await db_session.execute(
        sa_text("SELECT action_taken, jsm_comment_id FROM audit_log WHERE ticket_id = 'KAN-20'")
    )).first()
    assert row[0] == "rolled_back_by_technician"
    assert row[1] is None

    rb_row = (await db_session.execute(
        sa_text("SELECT rolled_back_at FROM rollback_store WHERE ticket_id = 'KAN-20'")
    )).first()
    assert rb_row[0] is not None


@pytest.mark.asyncio
async def test_rollback_comment_404_when_nothing_active(db_session):
    await _seed_posted_ticket(db_session, "KAN-21", with_active_rollback=False)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = _app(db_session, _FAKE_TECH)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/tickets/KAN-21/rollback-comment")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rollback_comment_409_when_not_acknowledged(db_session):
    await _seed_posted_ticket(db_session, "KAN-22", acknowledged=False)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = _app(db_session, _FAKE_TECH)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/tickets/KAN-22/rollback-comment")

    assert response.status_code == 409
    # Nothing should have been claimed/executed.
    row = (await db_session.execute(
        sa_text("SELECT rolled_back_at FROM rollback_store WHERE ticket_id = 'KAN-22'")
    )).first()
    assert row[0] is None


@pytest.mark.asyncio
async def test_rollback_comment_403_cross_team(db_session):
    await _seed_posted_ticket(db_session, "KAN-23", team_id="net-team")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = _app(db_session, _OTHER_TEAM_TECH)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/tickets/KAN-23/rollback-comment")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_rollback_without_acknowledging(db_session):
    await _seed_posted_ticket(db_session, "KAN-24", acknowledged=False)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.delete_comment = AsyncMock(return_value=True)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        stack.enter_context(patch("app.api.v1.routes.tickets.notification_bus.broadcast_to_all", new=AsyncMock()))
        app = _app(db_session, _ADMIN_USER)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/tickets/KAN-24/rollback-comment")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_post_ticket_comment_posts_and_syncs_audit_log(db_session):
    await _seed_posted_ticket(db_session, "KAN-25", with_active_rollback=False)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="comment-corrected")
    mock_jsm.get_ticket = AsyncMock(return_value=None)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        stack.enter_context(patch("app.api.v1.routes.tickets.notification_bus.broadcast_to_all", new=AsyncMock()))
        app = _app(db_session, _FAKE_TECH)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/tickets/KAN-25/comment",
                json={"edited_comment": "Here is the actually correct answer."},
            )

    assert response.status_code == 200
    mock_jsm.post_comment_markdown.assert_called_once_with("KAN-25", "Here is the actually correct answer.")

    row = (await db_session.execute(
        sa_text("SELECT action_taken, jsm_comment_id FROM audit_log WHERE ticket_id = 'KAN-25'")
    )).first()
    assert row[0] == "comment_posted"
    assert row[1] == "comment-corrected"

    convo = (await db_session.execute(
        sa_text("SELECT 1 FROM ticket_conversations WHERE ticket_id = 'KAN-25'")
    )).first()
    assert convo is not None


@pytest.mark.asyncio
async def test_post_ticket_comment_409_when_not_acknowledged(db_session):
    await _seed_posted_ticket(db_session, "KAN-26", acknowledged=False, with_active_rollback=False)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = _app(db_session, _FAKE_TECH)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/tickets/KAN-26/comment",
                json={"edited_comment": "Should not be allowed."},
            )

    assert response.status_code == 409


# ── Ticket detail exposes comments + rollback_action_id ─────────────────────

@pytest.mark.asyncio
async def test_ticket_detail_includes_comments_and_rollback_action_id(db_session):
    from app.core.security import require_any_auth
    from app.models.jsm import JSMComment, JSMTicket

    await _seed_posted_ticket(db_session, "KAN-27")

    live_ticket = JSMTicket(
        ticket_id="KAN-27",
        summary="VPN drops",
        description="Details here",
        comments=[
            JSMComment(author="AURA", body="Try restarting the VPN client.", created=datetime.now(timezone.utc)),
        ],
        priority="Medium",
        status="Open",
        created=datetime.now(timezone.utc),
        reporter_account_id="reporter-1",
    )
    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.get_ticket = AsyncMock(return_value=live_ticket)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        from app.main import create_app
        app = create_app()
        app.dependency_overrides[require_any_auth] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/tickets/KAN-27")

    assert response.status_code == 200
    body = response.json()
    assert len(body["comments"]) == 1
    assert body["comments"][0]["author"] == "AURA"
    assert body["comments"][0]["body"] == "Try restarting the VPN client."
    assert body["rollback_action_id"] is not None
