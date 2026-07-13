"""Tests for the technician approval routes (approve_suggestion /
edit_and_post_suggestion) posting via comment_poster.post_and_track.

Jira status transitions no longer happen on these routes at all — Open ->
In Progress happens unconditionally in jsm_poller when a ticket is first
picked up, regardless of category autonomy settings. These tests assert
that decoupling holds (no transition API calls from approve/edit) and that
conversation tracking starts/updates the same way auto-post does, using the
reporter_account_id captured on the queue row at write time.
"""

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


def _lifespan_patches():
    return [
        patch("app.db.sqlite.init_db", new=AsyncMock()),
        patch("app.db.sqlite.close_db", new=AsyncMock()),
        patch("app.db.qdrant_client.init_qdrant", new=AsyncMock()),
        patch("app.db.qdrant_client.close_qdrant", new=AsyncMock()),
        patch("scheduler.scheduler.start", new=AsyncMock()),
        patch("scheduler.scheduler.stop", new=AsyncMock()),
    ]


async def _seed_queue_entry(db, ticket_id: str, category: str, auto_comment_enabled: bool, reporter_account_id: str | None = "reporter-1", team_id: str = "", acknowledged: bool = True):
    queue_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        sa_text(
            "INSERT INTO low_confidence_queue "
            "(queue_id, tenant_id, ticket_id, formatted_comment, confidence_score, citations, "
            " abstained, team_id, reporter_account_id, queued_at) "
            "VALUES (:qid, :tenant, :tid, 'draft', 0.5, '[]', 0, :team, :rid, :now)"
        ),
        {"qid": queue_id, "tenant": TENANT, "tid": ticket_id, "team": team_id, "rid": reporter_account_id, "now": now},
    )
    await db.execute(
        sa_text(
            "INSERT INTO category_config (category_id, tenant_id, name, team_id, auto_comment_enabled, sla_minutes, created_at, updated_at) "
            "VALUES (:cid, :tenant, :cat, 'team', :enabled, 480, :now, :now)"
        ),
        {"cid": str(uuid.uuid4()), "tenant": TENANT, "cat": category, "enabled": int(auto_comment_enabled), "now": now},
    )
    await db.execute(
        sa_text(
            "INSERT INTO audit_log (entry_id, tenant_id, ticket_id, action_taken, category, audit_steps, created_at) "
            "VALUES (:eid, :tenant, :tid, 'held_low_confidence', :cat, '[]', :now)"
        ),
        {"eid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "cat": category, "now": now},
    )
    # ticket_assignments.assigned_to has a FK to users — seed the technician
    # so the assignment insert below doesn't violate it.
    await db.execute(
        sa_text(
            "INSERT OR IGNORE INTO users (user_id, tenant_id, email, hashed_password, role, display_name, is_active, created_at) "
            "VALUES (:uid, :tenant, :email, 'x', 'technician', :uid, 1, :now)"
        ),
        {"uid": _FAKE_TECH["user_id"], "tenant": TENANT, "email": _FAKE_TECH["email"], "now": now},
    )
    # A technician must acknowledge a ticket before posting a comment on it
    # (see _assert_ticket_acknowledged in tickets.py) — seed a current,
    # acknowledged assignment by default so existing approve/edit tests keep
    # exercising the posting path; tests for the gate itself pass acknowledged=False.
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
    await db.commit()
    return queue_id


@pytest.mark.asyncio
async def test_approve_posts_comment_and_starts_tracking(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-1", "Network", True)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="comment-1")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(f"/api/v1/tickets/queue/{queue_id}/approve")

    assert response.status_code == 200
    mock_jsm.post_comment_markdown.assert_called_once_with("KAN-1", "draft")
    mock_jsm.find_transition_id.assert_not_called()
    mock_jsm.transition_issue.assert_not_called()

    row = (await db_session.execute(
        sa_text("SELECT status, reporter_account_id, turn_count FROM ticket_conversations WHERE ticket_id = 'KAN-1'")
    )).first()
    assert row is not None
    assert row[0] == "active"
    assert row[1] == "reporter-1"
    assert row[2] == 1

    audit_row = (await db_session.execute(
        sa_text("SELECT action_taken, jsm_comment_id FROM audit_log WHERE ticket_id = 'KAN-1'")
    )).first()
    assert audit_row[0] == "comment_posted"
    assert audit_row[1] == "comment-1"


@pytest.mark.asyncio
async def test_approve_never_calls_transition_apis_when_toggle_disabled(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-2", "Network", False)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="comment-2")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(f"/api/v1/tickets/queue/{queue_id}/approve")

    assert response.status_code == 200
    mock_jsm.find_transition_id.assert_not_called()
    mock_jsm.transition_issue.assert_not_called()


@pytest.mark.asyncio
async def test_edit_and_post_starts_tracking(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-3", "Network", True)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="comment-3")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/tickets/queue/{queue_id}/edit",
                json={"edited_comment": "Edited resolution text"},
            )

    assert response.status_code == 200
    mock_jsm.post_comment_markdown.assert_called_once_with("KAN-3", "Edited resolution text")
    mock_jsm.transition_issue.assert_not_called()

    row = (await db_session.execute(
        sa_text("SELECT 1 FROM ticket_conversations WHERE ticket_id = 'KAN-3'")
    )).first()
    assert row is not None

    audit_row = (await db_session.execute(
        sa_text("SELECT action_taken, jsm_comment_id FROM audit_log WHERE ticket_id = 'KAN-3'")
    )).first()
    assert audit_row[0] == "comment_posted"
    assert audit_row[1] == "comment-3"


@pytest.mark.asyncio
async def test_reject_syncs_audit_log_action(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-5", "Network", True)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/tickets/queue/{queue_id}/reject",
                json={"reason": "Incorrect resolution"},
            )

    assert response.status_code == 200
    audit_row = (await db_session.execute(
        sa_text("SELECT action_taken FROM audit_log WHERE ticket_id = 'KAN-5'")
    )).first()
    assert audit_row[0] == "rejected_by_technician"


@pytest.mark.asyncio
async def test_approve_tracks_even_when_reporter_unknown(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-4", "Network", True, reporter_account_id=None)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="comment-4")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(f"/api/v1/tickets/queue/{queue_id}/approve")

    assert response.status_code == 200
    # Tracking still starts (idle-resolve should apply even without a known
    # reporter) — just with no reporter_account_id to match replies against.
    row = (await db_session.execute(
        sa_text("SELECT reporter_account_id FROM ticket_conversations WHERE ticket_id = 'KAN-4'")
    )).first()
    assert row is not None
    assert row[0] is None


# ── Cross-team ownership enforcement ────────────────────────────────────────────
# A technician can view every category's queue (GET /queue has no team filter)
# but may only act (approve/reject/edit) on items belonging to their own team.

_OTHER_TEAM_TECH = {"user_id": "test-tech-2", "tenant_id": TENANT, "email": "tech2@example.com", "role": "technician", "team_id": "hardware-team"}
_ADMIN_USER = {"user_id": "test-admin", "tenant_id": TENANT, "email": "admin@example.com", "role": "admin", "team_id": None}


@pytest.mark.asyncio
async def test_approve_rejects_technician_from_another_team(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-5", "Network", True, team_id="net-team")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _OTHER_TEAM_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(f"/api/v1/tickets/queue/{queue_id}/approve")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reject_rejects_technician_from_another_team(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-6", "Network", True, team_id="net-team")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _OTHER_TEAM_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(f"/api/v1/tickets/queue/{queue_id}/reject", json={"reason": "not mine"})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_edit_rejects_technician_from_another_team(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-7", "Network", True, team_id="net-team")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _OTHER_TEAM_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/tickets/queue/{queue_id}/edit",
                json={"edited_comment": "Trying to edit someone else's ticket"},
            )

    assert response.status_code == 403


# ── Acknowledge-before-post enforcement ─────────────────────────────────────
# A technician must acknowledge a ticket (the "I'm on it" signal that flips
# the real ticket to In Progress) before AURA's suggestion can be posted —
# otherwise a technician could approve/edit sight-unseen without ever having
# looked at the ticket.

@pytest.mark.asyncio
async def test_approve_blocked_when_not_acknowledged(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-9", "Network", True, acknowledged=False)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(f"/api/v1/tickets/queue/{queue_id}/approve")

    assert response.status_code == 409

    audit_row = (await db_session.execute(
        sa_text("SELECT action_taken FROM audit_log WHERE ticket_id = 'KAN-9'")
    )).first()
    assert audit_row[0] == "held_low_confidence"  # unchanged — never posted


@pytest.mark.asyncio
async def test_edit_and_post_blocked_when_not_acknowledged(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-10", "Network", True, acknowledged=False)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/tickets/queue/{queue_id}/edit",
                json={"edited_comment": "Trying to post without acknowledging"},
            )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_reject_allowed_without_acknowledging(db_session):
    """Reject never touches the real ticket, so it doesn't require acknowledgment."""
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-11", "Network", True, acknowledged=False)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _FAKE_TECH
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/tickets/queue/{queue_id}/reject",
                json={"reason": "Not applicable"},
            )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_approve_without_acknowledging(db_session):
    """Admins bypass the acknowledgment gate, same as the team-ownership check."""
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-12", "Network", True, acknowledged=False)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="comment-12")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _ADMIN_USER
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(f"/api/v1/tickets/queue/{queue_id}/approve")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_approve_across_any_team(db_session):
    from app.main import create_app

    queue_id = await _seed_queue_entry(db_session, "KAN-8", "Network", True, team_id="net-team")

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.post_comment_markdown = AsyncMock(return_value="comment-8")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        stack.enter_context(patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm))
        app = create_app()
        app.dependency_overrides[require_technician] = lambda: _ADMIN_USER
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(f"/api/v1/tickets/queue/{queue_id}/approve")

    assert response.status_code == 200
