"""Tests for app.services.assignment_service."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text as sa_text

from app.services import assignment_service

TENANT = "test-tenant-1"


def _now():
    return datetime.now(timezone.utc)


async def _seed_technician(db, *, team_id="net-team", jira_account_id=None, is_active=1, email="tech@example.com"):
    user_id = str(uuid.uuid4())
    await db.execute(
        sa_text(
            "INSERT INTO users (user_id, tenant_id, email, hashed_password, display_name, role, "
            "team_id, is_active, jira_account_id, created_at) "
            "VALUES (:uid, :tenant, :email, 'x', 'Test Tech', 'technician', :team, :active, :jira, '2024-01-01T00:00:00')"
        ),
        {"uid": user_id, "tenant": TENANT, "email": email, "team": team_id, "active": is_active, "jira": jira_account_id},
    )
    await db.commit()
    return user_id


async def _insert_assignment(db, ticket_id, technician_id, team_id="net-team", assigned_at=None, is_current=1, acknowledged_at=None, escalated_at=None):
    await db.execute(
        sa_text(
            "INSERT INTO ticket_assignments "
            "(assignment_id, tenant_id, ticket_id, assigned_to, team_id, assigned_at, is_current, acknowledged_at, escalated_at) "
            "VALUES (:aid, :tenant, :tid, :uid, :team, :assigned_at, :current, :ack, :esc)"
        ),
        {
            "aid": str(uuid.uuid4()),
            "tenant": TENANT,
            "tid": ticket_id,
            "uid": technician_id,
            "team": team_id,
            "assigned_at": (assigned_at or _now()).isoformat(),
            "current": is_current,
            "ack": acknowledged_at,
            "esc": escalated_at,
        },
    )
    await db.commit()


@pytest.mark.asyncio
async def test_assign_picks_least_loaded_technician(db_session):
    busy = await _seed_technician(db_session, email="busy@example.com")
    idle = await _seed_technician(db_session, email="idle@example.com")
    await _insert_assignment(db_session, "T-1", busy)
    await _insert_assignment(db_session, "T-2", busy)

    result = await assignment_service.assign(db_session, TENANT, team_id="net-team")

    assert result["user_id"] == idle


@pytest.mark.asyncio
async def test_assign_excludes_given_technician(db_session):
    only_one = await _seed_technician(db_session)

    result = await assignment_service.assign(db_session, TENANT, team_id="net-team", exclude_user_id=only_one)

    assert result is None


@pytest.mark.asyncio
async def test_assign_returns_none_when_no_technician_on_team(db_session):
    result = await assignment_service.assign(db_session, TENANT, team_id="ghost-team")
    assert result is None


@pytest.mark.asyncio
async def test_record_assignment_supersedes_prior_current_row(db_session):
    tech_a = await _seed_technician(db_session, email="a@example.com")
    tech_b = await _seed_technician(db_session, email="b@example.com")

    await assignment_service.record_assignment(db_session, TENANT, "T-5", tech_a, "net-team")
    await assignment_service.record_assignment(db_session, TENANT, "T-5", tech_b, "net-team")

    rows = (await db_session.execute(
        sa_text("SELECT assigned_to, is_current, reassigned_at FROM ticket_assignments WHERE ticket_id = 'T-5' ORDER BY assigned_at")
    )).mappings().all()

    assert len(rows) == 2
    assert rows[0]["assigned_to"] == tech_a
    assert rows[0]["is_current"] == 0
    assert rows[0]["reassigned_at"] is not None
    assert rows[1]["assigned_to"] == tech_b
    assert rows[1]["is_current"] == 1


@pytest.mark.asyncio
async def test_acknowledge_succeeds_for_assigned_user(db_session):
    tech = await _seed_technician(db_session)
    await assignment_service.record_assignment(db_session, TENANT, "T-6", tech, "net-team")

    ok = await assignment_service.acknowledge(db_session, TENANT, "T-6", tech)

    assert ok is True
    row = (await db_session.execute(
        sa_text("SELECT acknowledged_at FROM ticket_assignments WHERE ticket_id = 'T-6'")
    )).first()
    assert row[0] is not None


@pytest.mark.asyncio
async def test_acknowledge_fails_for_wrong_user(db_session):
    tech = await _seed_technician(db_session)
    other = str(uuid.uuid4())
    await assignment_service.record_assignment(db_session, TENANT, "T-7", tech, "net-team")

    ok = await assignment_service.acknowledge(db_session, TENANT, "T-7", other)

    assert ok is False


@pytest.mark.asyncio
async def test_resolve_jira_account_returns_existing_without_lookup(db_session):
    tech = {"user_id": "u1", "email": "x@example.com", "jira_account_id": "already-set"}
    with patch("app.services.itsm_client.get_itsm_client") as mock_cls:
        result = await assignment_service.resolve_jira_account(db_session, tech)
    assert result == "already-set"
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_check_overdue_reassigns_to_least_loaded_alternative(db_session):
    stuck = await _seed_technician(db_session, email="stuck@example.com", jira_account_id="acc-stuck")
    fresh = await _seed_technician(db_session, email="fresh@example.com", jira_account_id="acc-fresh")

    old_assigned_at = _now() - timedelta(minutes=120)
    await _insert_assignment(db_session, "T-8", stuck, assigned_at=old_assigned_at)

    mock_jsm = AsyncMock()
    mock_jsm.__aenter__ = AsyncMock(return_value=mock_jsm)
    mock_jsm.__aexit__ = AsyncMock(return_value=None)
    mock_jsm.assign_ticket = AsyncMock(return_value=None)

    with patch("app.services.itsm_client.get_itsm_client", return_value=mock_jsm), \
         patch("app.services.assignment_service.notification_bus.send_to_user", new=AsyncMock()) as user_mock:
        await assignment_service.check_overdue(db_session, TENANT)

    mock_jsm.assign_ticket.assert_called_once_with("T-8", "acc-fresh")
    user_mock.assert_called_once()
    assert user_mock.call_args[0][0] == fresh
    assert user_mock.call_args[0][1] == "TICKET_REASSIGNED"

    current = (await db_session.execute(
        sa_text("SELECT assigned_to FROM ticket_assignments WHERE ticket_id = 'T-8' AND is_current = 1")
    )).first()
    assert current[0] == fresh


@pytest.mark.asyncio
async def test_check_overdue_renotifies_and_escalates_once_when_no_alternative(db_session):
    only_one = await _seed_technician(db_session, jira_account_id="acc-only")
    old_assigned_at = _now() - timedelta(minutes=120)
    await _insert_assignment(db_session, "T-9", only_one, assigned_at=old_assigned_at)

    with patch("app.services.assignment_service.notification_bus.send_to_user", new=AsyncMock()) as user_mock, \
         patch("app.services.assignment_service.notification_bus.broadcast_to_admins", new=AsyncMock()) as admin_mock:
        await assignment_service.check_overdue(db_session, TENANT)
        await assignment_service.check_overdue(db_session, TENANT)  # second cycle — should not escalate again

    assert user_mock.call_count == 2  # re-notified every cycle
    assert admin_mock.call_count == 1  # escalated only once

    row = (await db_session.execute(
        sa_text("SELECT escalated_at FROM ticket_assignments WHERE ticket_id = 'T-9' AND is_current = 1")
    )).first()
    assert row[0] is not None


@pytest.mark.asyncio
async def test_check_overdue_ignores_recent_assignments(db_session):
    tech = await _seed_technician(db_session, jira_account_id="acc-1")
    await _insert_assignment(db_session, "T-10", tech, assigned_at=_now())

    with patch("app.services.assignment_service.notification_bus.send_to_user", new=AsyncMock()) as user_mock:
        await assignment_service.check_overdue(db_session, TENANT)

    user_mock.assert_not_called()


@pytest.mark.asyncio
async def test_check_overdue_ignores_acknowledged_assignments(db_session):
    tech = await _seed_technician(db_session, jira_account_id="acc-1")
    old_assigned_at = _now() - timedelta(minutes=120)
    await _insert_assignment(db_session, "T-11", tech, assigned_at=old_assigned_at, acknowledged_at=_now().isoformat())

    with patch("app.services.assignment_service.notification_bus.send_to_user", new=AsyncMock()) as user_mock:
        await assignment_service.check_overdue(db_session, TENANT)

    user_mock.assert_not_called()
