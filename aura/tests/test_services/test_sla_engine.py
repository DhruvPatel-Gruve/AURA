"""Tests for app.services.sla_engine."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

TENANT = "test-tenant-1"


@pytest.fixture(autouse=True)
def silence_bus():
    with patch(
        "app.services.sla_engine.notification_bus.broadcast_to_tenant",
        new=AsyncMock(return_value=None),
    ):
        yield


def _now():
    return datetime.now(timezone.utc)


def test_compute_deadline():
    from app.services.sla_engine import compute_deadline
    created = _now()
    deadline = compute_deadline(created, sla_minutes=60)
    assert abs((deadline - created).total_seconds() - 3600) < 1


def test_compute_elapsed_pct_midway():
    from app.services.sla_engine import compute_deadline, compute_elapsed_pct
    # Create a ticket that started 30 min ago with 60-min SLA → ~50% elapsed
    created = _now() - timedelta(minutes=30)
    deadline = compute_deadline(created, sla_minutes=60)
    pct = compute_elapsed_pct(created, deadline)
    assert 45.0 < pct < 55.0


def test_compute_elapsed_pct_breached():
    from app.services.sla_engine import compute_deadline, compute_elapsed_pct
    created = _now() - timedelta(hours=3)
    deadline = compute_deadline(created, sla_minutes=60)  # deadline was 2h ago
    pct = compute_elapsed_pct(created, deadline)
    assert pct > 100.0


@pytest.mark.asyncio
async def test_register_and_compute_status(db_session):
    from app.services.sla_engine import register, compute_status, compute_deadline
    created = _now() - timedelta(minutes=10)
    deadline = compute_deadline(created, sla_minutes=60)

    await register(db_session, TENANT, "T-10", "Network", deadline, "ok")
    status = await compute_status(db_session, TENANT, "T-10")

    assert status["ticket_id"] == "T-10"
    assert status["status"] in ("ok", "warning", "breached")
    assert 0.0 <= status["elapsed_pct"]


@pytest.mark.asyncio
async def test_register_upsert_is_idempotent(db_session):
    from sqlalchemy import text as sa_text
    from app.services.sla_engine import register, compute_deadline
    created = _now()
    deadline = compute_deadline(created, sla_minutes=480)

    await register(db_session, TENANT, "T-20", "Hardware", deadline, "ok")
    await register(db_session, TENANT, "T-20", "Software", deadline, "ok")  # upsert

    rows = (await db_session.execute(
        sa_text("SELECT COUNT(*) FROM sla_events WHERE tenant_id = :tid AND ticket_id = 'T-20'"),
        {"tid": TENANT},
    )).scalar()
    assert rows == 1


@pytest.mark.asyncio
async def test_check_all_active_fires_breach_event(db_session):
    from sqlalchemy import text as sa_text
    import uuid

    past = (_now() - timedelta(hours=2)).isoformat()
    await db_session.execute(
        sa_text(
            "INSERT INTO sla_events (sla_id, tenant_id, ticket_id, category, deadline, created_at) "
            "VALUES (:sid, :tenant, 'T-30', 'Network', :past, :past)"
        ),
        {"sid": str(uuid.uuid4()), "tenant": TENANT, "past": past},
    )
    await db_session.commit()

    bus_mock = AsyncMock()
    with patch("app.services.sla_engine.notification_bus.broadcast_to_tenant", bus_mock):
        from app.services.sla_engine import check_all_active
        await check_all_active(db_session)

    assert bus_mock.called
    event_name = bus_mock.call_args[0][1]
    assert event_name == "SLA_BREACHED"
