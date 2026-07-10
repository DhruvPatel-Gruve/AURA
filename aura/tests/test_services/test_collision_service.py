"""Tests for app.services.collision_service."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

TENANT = "test-tenant-1"


@pytest.fixture(autouse=True)
def silence_bus():
    with patch(
        "app.services.collision_service.notification_bus.broadcast_to_team",
        new=AsyncMock(return_value=None),
    ):
        yield


async def _seed_user(db, user_id: str = "alice"):
    from sqlalchemy import text as sa_text
    await db.execute(
        sa_text(
            "INSERT OR IGNORE INTO users (user_id, tenant_id, email, display_name, hashed_password, role, created_at) "
            "VALUES (:uid, :tenant, :email, 'Test User', 'hash', 'technician', '2024-01-01T00:00:00')"
        ),
        {"uid": user_id, "email": f"{user_id}@test.com", "tenant": TENANT},
    )
    await db.commit()


@pytest.mark.asyncio
async def test_claim_creates_record(db_session):
    await _seed_user(db_session, "alice")
    from app.services import collision_service as cs
    result = await cs.claim(db_session, TENANT, ticket_id="T-1", user_id="alice")
    assert result["claimed"] is True
    assert result["claimed_by"] == "alice"
    assert "expires_at" in result


@pytest.mark.asyncio
async def test_claim_same_user_refreshes_expiry(db_session):
    await _seed_user(db_session, "alice")
    from app.services import collision_service as cs
    first = await cs.claim(db_session, TENANT, ticket_id="T-1", user_id="alice")
    second = await cs.claim(db_session, TENANT, ticket_id="T-1", user_id="alice")
    # expiry should be refreshed — second expires_at >= first
    first_exp = datetime.fromisoformat(first["expires_at"])
    second_exp = datetime.fromisoformat(second["expires_at"])
    assert second_exp >= first_exp


@pytest.mark.asyncio
async def test_claim_conflict_raises(db_session):
    await _seed_user(db_session, "alice")
    await _seed_user(db_session, "bob")
    from app.services import collision_service as cs
    await cs.claim(db_session, TENANT, ticket_id="T-1", user_id="alice")
    with pytest.raises(ValueError, match="already claimed"):
        await cs.claim(db_session, TENANT, ticket_id="T-1", user_id="bob")


@pytest.mark.asyncio
async def test_release_clears_claim(db_session):
    await _seed_user(db_session, "alice")
    from app.services import collision_service as cs
    await cs.claim(db_session, TENANT, ticket_id="T-1", user_id="alice")
    released = await cs.release(db_session, TENANT, ticket_id="T-1", user_id="alice")
    assert released is True
    claim = await cs.check_claim(db_session, TENANT, "T-1")
    assert claim is None


@pytest.mark.asyncio
async def test_check_claim_returns_none_when_unclaimed(db_session):
    from app.services import collision_service as cs
    claim = await cs.check_claim(db_session, TENANT, "T-999")
    assert claim is None


@pytest.mark.asyncio
async def test_expire_stale_claims(db_session):
    from sqlalchemy import text as sa_text
    import uuid

    await _seed_user(db_session, "alice")
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    await db_session.execute(
        sa_text(
            "INSERT INTO collision_claims (claim_id, tenant_id, ticket_id, claimed_by, claimed_at, expires_at) "
            "VALUES (:cid, :tenant, 'T-2', 'alice', :now, :exp)"
        ),
        {"cid": str(uuid.uuid4()), "tenant": TENANT, "now": past, "exp": past},
    )
    await db_session.commit()

    from app.services import collision_service as cs
    count = await cs.expire_stale_claims(db_session)
    assert count == 1
    claim = await cs.check_claim(db_session, TENANT, "T-2")
    assert claim is None
