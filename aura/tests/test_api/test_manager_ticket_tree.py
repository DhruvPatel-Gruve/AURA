"""Tests for GET /dashboard/manager/ticket-tree and its per-bucket leaf
endpoint — the aggregation backing the manager Ticket Tree canvas.

Seeds one ticket per resolution state across two categories and checks that
the counts, bucket derivation (auto vs human post, review, abstention,
halt), SLA rollups, and latest-audit-row-wins rule all land in the right
place for each of the three pivots.
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


async def _seed_audit(db, ticket_id, action, *, category=None, priority=None,
                      confidence=None, abstained=0, created_at="2030-01-02T00:00:00"):
    await db.execute(
        sa_text(
            "INSERT INTO audit_log (entry_id, tenant_id, ticket_id, action_taken, category, priority, "
            "confidence_score, abstained, audit_steps, created_at) "
            "VALUES (:eid, :tenant, :tid, :action, :cat, :pri, :conf, :abst, '[]', :now)"
        ),
        {"eid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "action": action, "cat": category,
         "pri": priority, "conf": confidence, "abst": abstained, "now": created_at},
    )


async def _seed_queue(db, ticket_id, *, resolution_action=None, resolved_at=None, abstained=0):
    await db.execute(
        sa_text(
            "INSERT INTO low_confidence_queue (queue_id, tenant_id, ticket_id, formatted_comment, "
            "abstained, team_id, queued_at, resolved_at, resolution_action) "
            "VALUES (:qid, :tenant, :tid, 'draft', :abst, 'team-net', '2030-01-02T00:00:00', :res_at, :res_act)"
        ),
        {"qid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "abst": abstained,
         "res_at": resolved_at, "res_act": resolution_action},
    )


async def _seed_sla(db, ticket_id, category, *, deadline="2031-01-01T00:00:00",
                    breached_at=None, warning_sent_at=None):
    await db.execute(
        sa_text(
            "INSERT INTO sla_events (sla_id, tenant_id, ticket_id, category, deadline, "
            "warning_sent_at, breached_at, created_at) "
            "VALUES (:sid, :tenant, :tid, :cat, :dl, :warn, :breach, '2030-01-02T00:00:00')"
        ),
        {"sid": str(uuid.uuid4()), "tenant": TENANT, "tid": ticket_id, "cat": category, "dl": deadline,
         "warn": warning_sent_at, "breach": breached_at},
    )


async def _seed_scenario(db):
    """5 tickets:
      NET-1  Network  comment_posted (no queue row)        -> resolved_auto, SLA breached, assigned+acked
      NET-2  Network  comment_posted (queue 'approved')    -> resolved_human, SLA ok
      NET-3  Network  held_low_confidence (queue open)     -> in_review, SLA warning
      HW-1   Hardware abstained_no_kb_coverage             -> abstained, no SLA
      ERR-1  (none)   pipeline_error                       -> Uncategorized / halted, no SLA
    NET-1 also gets an OLDER audit row with a different action to prove the
    latest row wins.
    """
    await db.execute(sa_text(
        "INSERT INTO category_config (category_id, tenant_id, name, auto_comment_enabled, sla_minutes, "
        "team_id, created_at, updated_at) VALUES "
        "('c1', :tenant, 'Network', 1, 480, 'team-net', '2030-01-01', '2030-01-01'), "
        "('c2', :tenant, 'Hardware', 0, 480, 'team-hw', '2030-01-01', '2030-01-01')"
    ), {"tenant": TENANT})
    await db.execute(sa_text(
        "INSERT INTO users (user_id, tenant_id, email, hashed_password, display_name, role, team_id, created_at) "
        "VALUES ('tech-1', :tenant, 'tech@example.com', 'x', 'Tech One', 'technician', 'team-net', '2030-01-01')"
    ), {"tenant": TENANT})

    await _seed_audit(db, "NET-1", "held_low_confidence", category="Network",
                      created_at="2030-01-01T00:00:00")  # older row — must lose
    await _seed_audit(db, "NET-1", "comment_posted", category="Network", priority="High", confidence=0.95)
    await _seed_audit(db, "NET-2", "comment_posted", category="Network", priority="Medium", confidence=0.72)
    await _seed_audit(db, "NET-3", "held_low_confidence", category="Network", priority="Low", confidence=0.55)
    await _seed_audit(db, "HW-1", "abstained_no_kb_coverage", category="Hardware", priority="High", abstained=1)
    await _seed_audit(db, "ERR-1", "pipeline_error")

    await _seed_queue(db, "NET-2", resolution_action="approved", resolved_at="2030-01-03T00:00:00")
    await _seed_queue(db, "NET-3")
    await _seed_sla(db, "NET-1", "Network", breached_at="2030-01-02T12:00:00")
    await _seed_sla(db, "NET-2", "Network")
    await _seed_sla(db, "NET-3", "Network", warning_sent_at="2030-01-02T06:00:00")

    await db.execute(sa_text(
        "INSERT INTO ticket_assignments (assignment_id, tenant_id, ticket_id, assigned_to, team_id, "
        "assigned_at, acknowledged_at, is_current) "
        "VALUES ('a1', :tenant, 'NET-1', 'tech-1', 'team-net', '2030-01-02T00:00:00', '2030-01-02T01:00:00', 1)"
    ), {"tenant": TENANT})
    await db.commit()


async def _get(db_session, path, params=None):
    from app.main import create_app

    with ExitStack() as stack:
        for p in _lifespan_patches():
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_manager] = lambda: _FAKE_MANAGER
        app.dependency_overrides[get_db] = lambda: db_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            return await ac.get(path, params=params or {})


def _group(body, key):
    return next(g for g in body["root"]["groups"] if g["key"] == key)


def _bucket(group, key):
    return next(b for b in group["buckets"] if b["key"] == key)


@pytest.mark.asyncio
async def test_category_status_tree_counts_and_buckets(db_session):
    await _seed_scenario(db_session)
    resp = await _get(db_session, "/api/v1/dashboard/manager/ticket-tree")
    assert resp.status_code == 200
    body = resp.json()

    root = body["root"]
    assert root["total"] == 5
    assert root["auto_resolved"] == 1
    assert root["human_resolved"] == 1
    assert root["in_review"] == 1
    assert root["abstained"] == 1
    assert root["breached"] == 1

    net = _group(body, "Network")
    assert net["total"] == 3
    # 3 tickets with SLA, 1 breached -> 66.7%
    assert net["sla_compliance_pct"] == 66.7
    assert _bucket(net, "resolved_auto")["total"] == 1
    assert _bucket(net, "resolved_human")["total"] == 1
    assert _bucket(net, "in_review")["total"] == 1

    hw = _group(body, "Hardware")
    assert _bucket(hw, "abstained")["total"] == 1
    assert hw["sla_compliance_pct"] is None  # no SLA rows in this group

    uncat = _group(body, "Uncategorized")
    assert _bucket(uncat, "halted")["total"] == 1


@pytest.mark.asyncio
async def test_latest_audit_row_wins(db_session):
    """NET-1 has an older held_low_confidence row — only the newer
    comment_posted row may count, and only once."""
    await _seed_scenario(db_session)
    body = (await _get(db_session, "/api/v1/dashboard/manager/ticket-tree")).json()
    net = _group(body, "Network")
    auto_bucket = _bucket(net, "resolved_auto")
    assert auto_bucket["total"] == 1

    leaves = (await _get(
        db_session, "/api/v1/dashboard/manager/ticket-tree/tickets",
        {"group_by": "category_status", "group": "Network", "bucket": "resolved_auto"},
    )).json()
    assert [t["ticket_id"] for t in leaves["items"]] == ["NET-1"]


@pytest.mark.asyncio
async def test_leaf_tickets_carry_derived_fields(db_session):
    await _seed_scenario(db_session)
    resp = await _get(
        db_session, "/api/v1/dashboard/manager/ticket-tree/tickets",
        {"group_by": "category_status", "group": "Network", "bucket": "resolved_auto"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    leaf = body["items"][0]
    assert leaf["ticket_id"] == "NET-1"
    assert leaf["sla_state"] == "breached"
    assert leaf["assignee_name"] == "Tech One"
    assert leaf["acknowledged"] is True
    assert leaf["confidence_score"] == 0.95
    assert leaf["team"] == "team-net"


@pytest.mark.asyncio
async def test_team_category_and_priority_sla_pivots(db_session):
    await _seed_scenario(db_session)

    body = (await _get(
        db_session, "/api/v1/dashboard/manager/ticket-tree", {"group_by": "team_category"},
    )).json()
    net_team = _group(body, "team-net")
    assert net_team["total"] == 3
    assert _bucket(net_team, "Network")["total"] == 3
    assert _group(body, "Unassigned")["total"] == 1  # ERR-1 has no category -> no team

    body = (await _get(
        db_session, "/api/v1/dashboard/manager/ticket-tree", {"group_by": "priority_sla"},
    )).json()
    # High before Medium before Low before None (priority order, not alpha)
    keys = [g["key"] for g in body["root"]["groups"]]
    assert keys.index("High") < keys.index("Medium") < keys.index("Low") < keys.index("None")
    high = _group(body, "High")
    assert high["total"] == 2  # NET-1 + HW-1
    assert _bucket(high, "breached")["total"] == 1
    assert _bucket(high, "none")["total"] == 1


@pytest.mark.asyncio
async def test_date_filter_and_empty_tree(db_session):
    await _seed_scenario(db_session)
    body = (await _get(
        db_session, "/api/v1/dashboard/manager/ticket-tree", {"date_from": "2035-01-01"},
    )).json()
    assert body["root"]["total"] == 0
    assert body["root"]["groups"] == []
    assert body["root"]["sla_compliance_pct"] is None


@pytest.mark.asyncio
async def test_invalid_group_by_rejected(db_session):
    resp = await _get(db_session, "/api/v1/dashboard/manager/ticket-tree", {"group_by": "bogus"})
    assert resp.status_code == 422
