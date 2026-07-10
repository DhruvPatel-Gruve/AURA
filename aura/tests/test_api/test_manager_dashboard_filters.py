"""Regression tests for manager/* dashboard filter/sort/pagination fixes:
- date_from/date_to previously accepted but ignored on /manager/sla and
  /manager/resolution (now actually filter the SQL).
- /manager/collisions previously limited raw claim rows to 50 *before*
  grouping into collisions, which could silently drop a genuine multi-claim
  collision whose rows fell outside that window. Now groups first.
- /manager/approvals previously returned a flat, unfiltered, unsorted,
  hard-capped-at-100 list. Now supports team/status/confidence filters,
  sort_by/sort_dir, and real pagination.
"""

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text

from app.core.security import require_manager
from app.db.sqlite import get_db
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_MANAGER = {
    "user_id": "test-mgr", "tenant_id": TENANT, "email": "mgr@example.com",
    "role": "manager", "team_id": None,
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


def _app(db_session):
    from app.main import create_app
    app = create_app()
    app.dependency_overrides[require_manager] = lambda: _FAKE_MANAGER
    app.dependency_overrides[get_db] = lambda: db_session
    return app


async def _seed_sla_event(db, ticket_id: str, category: str, created_at: str, breached_at: str | None = None):
    await db.execute(
        sa_text(
            "INSERT INTO sla_events (sla_id, tenant_id, ticket_id, category, deadline, breached_at, created_at) "
            "VALUES (:sid, :tenant, :tid, :cat, '2099-01-01T00:00:00', :breached, :now)"
        ),
        {"sid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "cat": category, "breached": breached_at, "now": created_at},
    )
    await db.commit()


async def _seed_user(db, user_id: str):
    await db.execute(
        sa_text(
            "INSERT OR IGNORE INTO users (user_id, tenant_id, email, hashed_password, role, display_name, is_active, created_at) "
            "VALUES (:uid, :tenant, :email, 'x', 'technician', :uid, 1, '2024-01-01T00:00:00')"
        ),
        {"uid": user_id, "tenant": TENANT, "email": f"{user_id}@example.com"},
    )
    await db.commit()


async def _seed_claim(db, ticket_id: str, claimed_by: str, claimed_at: str):
    await db.execute(
        sa_text(
            "INSERT INTO collision_claims (claim_id, tenant_id, ticket_id, claimed_by, claimed_at, expires_at) "
            "VALUES (:cid, :tenant, :tid, :by, :now, '2099-01-01T00:00:00')"
        ),
        {"cid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "by": claimed_by, "now": claimed_at},
    )
    await db.commit()


async def _seed_queue_item(db, ticket_id: str, team_id: str, confidence: float, abstained: bool):
    await db.execute(
        sa_text(
            "INSERT INTO low_confidence_queue "
            "(queue_id, tenant_id, ticket_id, formatted_comment, confidence_score, citations, "
            " abstained, team_id, queued_at) "
            "VALUES (:qid, :tenant, :tid, 'draft', :conf, '[]', :abst, :team, :now)"
        ),
        {
            "qid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "conf": confidence,
            "abst": int(abstained), "team": team_id, "now": f"2025-01-{len(ticket_id):02d}T00:00:00",
        },
    )
    await db.commit()


@pytest.mark.asyncio
async def test_sla_date_from_narrows_compliance_by_category(db_session):
    await _seed_sla_event(db_session, "OLD-1", "Network", "2020-01-01T00:00:00")
    await _seed_sla_event(db_session, "NEW-1", "Network", "2030-01-01T00:00:00")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/dashboard/manager/sla", params={"date_from": "2025-01-01"})

    assert response.status_code == 200
    body = response.json()
    # Only NEW-1 should count toward the Network category total now.
    network = next(c for c in body["compliance_by_category"] if c["category"] == "Network")
    assert network["compliance_pct"] == 100.0


@pytest.mark.asyncio
async def test_collisions_grouped_before_limit(db_session):
    await _seed_user(db_session, "tech-a")
    await _seed_user(db_session, "tech-b")

    # 60 unrelated single-claim rows (would fill the old raw LIMIT 50 window)
    for i in range(60):
        await _seed_claim(db_session, f"FILLER-{i}", "tech-a", f"2025-06-{(i % 28) + 1:02d}T00:00:00")
    # A genuine collision whose claims are older than all the filler rows above.
    await _seed_claim(db_session, "COLLIDED-1", "tech-a", "2020-01-01T00:00:00")
    await _seed_claim(db_session, "COLLIDED-1", "tech-b", "2020-01-02T00:00:00")

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/dashboard/manager/collisions")

    assert response.status_code == 200
    body = response.json()
    collided_ids = {e["ticket_id"] for e in body["collision_events"]}
    assert "COLLIDED-1" in collided_ids


@pytest.mark.asyncio
async def test_approvals_filters_sorts_and_paginates(db_session):
    await _seed_queue_item(db_session, "T-1", "team-a", 0.9, abstained=False)
    await _seed_queue_item(db_session, "T-2", "team-b", 0.5, abstained=True)
    await _seed_queue_item(db_session, "T-3", "team-a", 0.7, abstained=False)

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = _app(db_session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/dashboard/manager/approvals",
                params={"team_id": "team-a", "sort_by": "confidence_score", "sort_dir": "desc", "page_size": 1},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2          # only team-a items
    assert len(body["items"]) == 1      # page_size=1
    assert body["items"][0]["ticket_id"] == "T-1"   # highest confidence first
