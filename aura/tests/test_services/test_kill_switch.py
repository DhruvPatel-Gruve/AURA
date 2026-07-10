"""Tests for app.services.kill_switch."""

import pytest
from unittest.mock import AsyncMock, patch

TENANT = "test-tenant-1"


@pytest.fixture(autouse=True)
def reset_kill_switch():
    """Reset the in-process cache before each test."""
    import app.services.kill_switch as ks
    ks._enabled = {}
    yield
    ks._enabled = {}


@pytest.fixture(autouse=True)
def silence_bus():
    with patch(
        "app.services.kill_switch.notification_bus.broadcast_to_tenant",
        new=AsyncMock(return_value=None),
    ):
        yield


@pytest.mark.asyncio
async def test_init_loads_enabled_state(db_session):
    from app.services import kill_switch as ks
    await ks.init_kill_switch(db_session)
    assert ks.is_enabled(TENANT) is True


@pytest.mark.asyncio
async def test_init_loads_disabled_state(db_session):
    from sqlalchemy import text as sa_text
    await db_session.execute(
        sa_text("UPDATE platform_config SET aura_enabled = 0 WHERE tenant_id = :tid"),
        {"tid": TENANT},
    )
    await db_session.commit()

    from app.services import kill_switch as ks
    await ks.init_kill_switch(db_session)
    assert ks.is_enabled(TENANT) is False


@pytest.mark.asyncio
async def test_disable_sets_cache_and_db(db_session):
    from sqlalchemy import text as sa_text
    from app.services import kill_switch as ks

    await ks.disable(db_session, TENANT, changed_by="admin@test.com")

    assert ks.is_enabled(TENANT) is False
    row = (await db_session.execute(
        sa_text("SELECT aura_enabled FROM platform_config WHERE tenant_id = :tid"), {"tid": TENANT},
    )).first()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_enable_restores_cache_and_db(db_session):
    from sqlalchemy import text as sa_text
    from app.services import kill_switch as ks
    ks._enabled[TENANT] = False

    await ks.enable(db_session, TENANT, changed_by="admin@test.com")

    assert ks.is_enabled(TENANT) is True
    row = (await db_session.execute(
        sa_text("SELECT aura_enabled FROM platform_config WHERE tenant_id = :tid"), {"tid": TENANT},
    )).first()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_get_status_returns_row(db_session):
    from app.services import kill_switch as ks
    status = await ks.get_status(db_session, TENANT)
    assert "enabled" in status
    assert status["enabled"] is True
