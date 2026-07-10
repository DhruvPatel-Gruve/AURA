"""Dashboard routes — all tenant-scoped except health (process-wide metrics,
no ticket data) and manager/ticket-tree (documented separately below).

GET /dashboard/health           — system health metrics (any auth)
GET /dashboard/admin/health     — alias (any auth)
GET /dashboard/stats            — technician queue stats
GET /dashboard/technician/stats — alias
GET /dashboard/manager/sla
GET /dashboard/manager/resolution
GET /dashboard/manager/confidence
GET /dashboard/manager/team
GET /dashboard/manager/abstention
GET /dashboard/manager/collisions
GET /dashboard/manager/cost-savings
GET /dashboard/manager/approvals
GET /dashboard/manager/ticket-tree
GET /dashboard/manager/ticket-tree/tickets
"""

import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_any_auth, require_technician, require_manager
from app.db.sqlite import get_db
from app.models.api_schemas import SystemHealthResponse, TechnicianStats
from app.services.notification_bus import notification_bus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_START_TIME = time.monotonic()


def _date_range_clauses(
    column: str, date_from: str | None, date_to: str | None, params: dict,
) -> list[str]:
    """Return zero or more 'column >= :date_from' / 'column <= :date_to'
    clause fragments and populate params accordingly. Callers combine these
    with their own required clauses via ' AND '.join(...) — shared by every
    manager/* endpoint below so the one date selector on ManagerDashboard
    actually reaches every sub-query instead of only the two it happened to
    hit before.
    """
    clauses = []
    if date_from:
        clauses.append(f"{column} >= :date_from")
        params["date_from"] = date_from
    if date_to:
        clauses.append(f"{column} <= :date_to")
        params["date_to"] = date_to
    return clauses


# ── Health (shared implementation) ───────────────────────────────────────────
# Process-wide metrics (uptime, WS connections, Qdrant/Gemini latency) are
# not tenant data — no scoping needed there. The one tenant-specific field
# (last poll timestamp / polling interval) is read from the caller's own
# tenant's platform_config row.

async def _health_impl(db: AsyncSession, tenant_id: str) -> SystemHealthResponse:
    from app.db.qdrant_client import get_qdrant_client
    from app.rag.embedder import get_last_query_latency_ms
    from scheduler.scheduler import get_scheduler

    uptime = int(time.monotonic() - _START_TIME)
    ws_connections = notification_bus.connection_count
    gemini_latency_ms = get_last_query_latency_ms() or 0.0

    qdrant_ms = 0.0
    try:
        client = get_qdrant_client()
        t0 = time.monotonic()
        await client.get_collections()
        qdrant_ms = round((time.monotonic() - t0) * 1000, 1)
    except Exception:
        pass

    jsm_poll_last = None
    jsm_poll_next = None
    scheduler_running = False
    try:
        scheduler = get_scheduler()
        scheduler_running = scheduler.running
        job = scheduler.get_job("jsm_poller")
        if job:
            jsm_poll_next = job.next_run_time
    except Exception:
        pass

    result = await db.execute(
        sa_text("SELECT last_poll_timestamp, polling_interval_minutes FROM platform_config WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    row = result.first()
    polling_interval_minutes = 0
    if row:
        if row[0]:
            try:
                jsm_poll_last = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            except ValueError:
                pass
        if row[1] is not None:
            polling_interval_minutes = int(row[1])

    return SystemHealthResponse(
        api_uptime_seconds=uptime,
        gemini_latency_ms=gemini_latency_ms,
        qdrant_query_ms=qdrant_ms,
        ws_connections=ws_connections,
        jsm_poll_last_run=jsm_poll_last,
        jsm_poll_next_run=jsm_poll_next,
        scheduler_running=scheduler_running,
        polling_interval_minutes=polling_interval_minutes,
    )


@router.get("/health", response_model=SystemHealthResponse)
async def get_health(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
) -> SystemHealthResponse:
    return await _health_impl(db, current_user["tenant_id"])


@router.get("/admin/health", response_model=SystemHealthResponse)
async def get_admin_health(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
) -> SystemHealthResponse:
    return await _health_impl(db, current_user["tenant_id"])


# ── Technician stats (shared implementation) ──────────────────────────────────

async def _tech_stats_impl(db: AsyncSession, tenant_id: str) -> TechnicianStats:
    queue_row = await db.execute(
        sa_text("SELECT COUNT(*) FROM low_confidence_queue WHERE tenant_id = :tid AND resolved_at IS NULL"),
        {"tid": tenant_id},
    )
    queue_count = queue_row.scalar() or 0

    low_conf_row = await db.execute(
        sa_text(
            "SELECT COUNT(*) FROM low_confidence_queue "
            "WHERE tenant_id = :tid AND resolved_at IS NULL AND abstained = 0 AND resolution_action IS NULL"
        ),
        {"tid": tenant_id},
    )
    low_conf_pending = low_conf_row.scalar() or 0

    breach_row = await db.execute(
        sa_text("SELECT COUNT(*) FROM sla_events WHERE tenant_id = :tid AND breached_at IS NOT NULL"),
        {"tid": tenant_id},
    )
    sla_breach_count = breach_row.scalar() or 0

    return TechnicianStats(
        queue_count=queue_count,
        low_conf_pending=low_conf_pending,
        sla_breach_count=sla_breach_count,
    )


@router.get("/stats", response_model=TechnicianStats)
async def get_technician_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_technician)],
) -> TechnicianStats:
    return await _tech_stats_impl(db, current_user["tenant_id"])


@router.get("/technician/stats", response_model=TechnicianStats)
async def get_technician_stats_v2(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
) -> TechnicianStats:
    return await _tech_stats_impl(db, current_user["tenant_id"])


# ── Manager — SLA compliance ──────────────────────────────────────────────────

@router.get("/manager/sla")
async def get_manager_sla(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    date_from: str | None = Query(None),
    date_to:   str | None = Query(None),
    category:  str | None = Query(None),
) -> dict:
    tenant_id = current_user["tenant_id"]
    params: dict = {"tenant_id": tenant_id}
    clauses = ["tenant_id = :tenant_id", "category IS NOT NULL"]
    clauses += _date_range_clauses("created_at", date_from, date_to, params)
    if category:
        clauses.append("category = :category")
        params["category"] = category

    # Compliance by category
    rows = await db.execute(sa_text(
        "SELECT category, COUNT(*) as total, "
        "SUM(CASE WHEN breached_at IS NOT NULL THEN 1 ELSE 0 END) as breached "
        f"FROM sla_events WHERE {' AND '.join(clauses)} GROUP BY category"
    ), params)
    compliance_by_category = []
    for r in rows.mappings():
        total = r["total"] or 1
        breached = r["breached"] or 0
        compliance_by_category.append({
            "category": r["category"],
            "compliance_pct": round((total - breached) / total * 100, 1),
        })

    # Recent breach history — date range applies to when the breach happened
    breach_params: dict = {"tenant_id": tenant_id}
    breach_clauses = ["tenant_id = :tenant_id", "breached_at IS NOT NULL"]
    breach_clauses += _date_range_clauses("breached_at", date_from, date_to, breach_params)
    if category:
        breach_clauses.append("category = :category")
        breach_params["category"] = category
    breach_rows = await db.execute(sa_text(
        "SELECT ticket_id, category, breached_at FROM sla_events "
        f"WHERE {' AND '.join(breach_clauses)} ORDER BY breached_at DESC LIMIT 20"
    ), breach_params)
    breach_history = [
        {"ticket_id": r["ticket_id"], "category": r["category"] or "", "breached_at": r["breached_at"]}
        for r in breach_rows.mappings()
    ]

    # Upcoming deadlines (not yet breached) — inherently forward-looking, so
    # only the category filter applies here, not the date range.
    upcoming_params: dict = {"tenant_id": tenant_id}
    upcoming_clauses = ["tenant_id = :tenant_id", "breached_at IS NULL", "deadline > datetime('now')"]
    if category:
        upcoming_clauses.append("category = :category")
        upcoming_params["category"] = category
    deadline_rows = await db.execute(sa_text(
        "SELECT ticket_id, category, deadline FROM sla_events "
        f"WHERE {' AND '.join(upcoming_clauses)} ORDER BY deadline ASC LIMIT 10"
    ), upcoming_params)
    upcoming_deadlines = [
        {"ticket_id": r["ticket_id"], "summary": r["ticket_id"], "deadline": r["deadline"], "category": r["category"] or ""}
        for r in deadline_rows.mappings()
    ]

    return {
        "compliance_by_category": compliance_by_category,
        "breach_history":         breach_history,
        "upcoming_deadlines":     upcoming_deadlines,
    }


# ── Manager — Resolution analytics ───────────────────────────────────────────

@router.get("/manager/resolution")
async def get_manager_resolution(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    date_from: str | None = Query(None),
    date_to:   str | None = Query(None),
) -> dict:
    tenant_id = current_user["tenant_id"]
    params: dict = {"tenant_id": tenant_id}
    range_clauses = ["tenant_id = :tenant_id"] + _date_range_clauses("created_at", date_from, date_to, params)
    where = " WHERE " + " AND ".join(range_clauses)
    and_where = " AND " + " AND ".join(range_clauses)

    # Overall counts
    total_row = await db.execute(sa_text(f"SELECT COUNT(*) FROM audit_log{where}"), params)
    total = total_row.scalar() or 0

    auto_row = await db.execute(sa_text(
        f"SELECT COUNT(*) FROM audit_log WHERE abstained = 0{and_where}"
    ), params)
    auto_count = auto_row.scalar() or 0

    fcr_row = await db.execute(sa_text(
        "SELECT COUNT(*) FROM audit_log WHERE abstained = 0 "
        f"AND action_taken = 'comment_posted'{and_where}"
    ), params)
    fcr_count = fcr_row.scalar() or 0

    auto_pct = round(auto_count / total * 100, 1) if total else 0.0
    manual_pct = round((total - auto_count) / total * 100, 1) if total else 0.0
    first_contact_rate = round(fcr_count / total * 100, 1) if total else 0.0

    # Daily trend (last 30 days)
    trend_rows = await db.execute(sa_text(
        "SELECT DATE(created_at) as date, COUNT(*) as total, "
        "SUM(CASE WHEN abstained = 0 THEN 1 ELSE 0 END) as auto_count "
        "FROM audit_log WHERE tenant_id = :tenant_id GROUP BY DATE(created_at) ORDER BY date DESC LIMIT 30"
    ), {"tenant_id": tenant_id})
    trend_data = []
    for r in trend_rows.mappings():
        t = r["total"] or 1
        a = r["auto_count"] or 0
        trend_data.append({"date": r["date"], "auto_pct": round(a / t * 100, 1)})
    trend_data.reverse()

    return {
        "auto_pct":           auto_pct,
        "manual_pct":         manual_pct,
        "first_contact_rate": first_contact_rate,
        "trend_data":         trend_data,
    }


# ── Manager — Confidence analytics ───────────────────────────────────────────

@router.get("/manager/confidence")
async def get_manager_confidence(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    date_from: str | None = Query(None),
    date_to:   str | None = Query(None),
) -> dict:
    tenant_id = current_user["tenant_id"]
    cat_params: dict = {"tenant_id": tenant_id}
    cat_clauses = ["tenant_id = :tenant_id", "confidence_score IS NOT NULL", "category IS NOT NULL"]
    cat_clauses += _date_range_clauses("created_at", date_from, date_to, cat_params)

    # Avg by category
    cat_rows = await db.execute(sa_text(
        "SELECT category, AVG(confidence_score) as avg_score "
        f"FROM audit_log WHERE {' AND '.join(cat_clauses)} "
        "GROUP BY category ORDER BY avg_score DESC"
    ), cat_params)
    avg_by_category = [
        {"category": r["category"], "avg_score": round(r["avg_score"], 3)}
        for r in cat_rows.mappings()
    ]

    hist_params: dict = {"tenant_id": tenant_id}
    hist_clauses = ["tenant_id = :tenant_id", "confidence_score IS NOT NULL"]
    hist_clauses += _date_range_clauses("created_at", date_from, date_to, hist_params)

    # Histogram (10 buckets: 0-10%, 10-20%, ..., 90-100%)
    hist_rows = await db.execute(sa_text(
        "SELECT CAST(confidence_score * 10 AS INTEGER) as bucket, COUNT(*) as count "
        f"FROM audit_log WHERE {' AND '.join(hist_clauses)} GROUP BY bucket ORDER BY bucket"
    ), hist_params)
    bucket_labels = [f"{i*10}–{i*10+10}%" for i in range(10)]
    counts_by_bucket: dict[int, int] = {}
    for r in hist_rows.mappings():
        b = min(int(r["bucket"]), 9)
        counts_by_bucket[b] = (counts_by_bucket.get(b) or 0) + (r["count"] or 0)
    histogram_buckets = [
        {"bucket": bucket_labels[i], "count": counts_by_bucket.get(i, 0)}
        for i in range(10)
    ]

    # Trend (last 30 days)
    trend_rows = await db.execute(sa_text(
        "SELECT DATE(created_at) as date, AVG(confidence_score) as avg_score "
        "FROM audit_log WHERE tenant_id = :tenant_id AND confidence_score IS NOT NULL "
        "GROUP BY DATE(created_at) ORDER BY date DESC LIMIT 30"
    ), {"tenant_id": tenant_id})
    trend_data = [
        {"date": r["date"], "avg_score": round(r["avg_score"], 3)}
        for r in trend_rows.mappings()
    ]
    trend_data.reverse()

    return {
        "avg_by_category":   avg_by_category,
        "histogram_buckets": histogram_buckets,
        "trend_data":        trend_data,
    }


# ── Manager — Team performance ────────────────────────────────────────────────

@router.get("/manager/team")
async def get_manager_team(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    date_from: str | None = Query(None),
    date_to:   str | None = Query(None),
) -> list:
    tenant_id = current_user["tenant_id"]
    params: dict = {"tenant_id": tenant_id}
    # Date range goes in the JOIN condition, not WHERE — a WHERE filter on
    # lc.queued_at would turn this into an inner join for that predicate and
    # drop technicians who simply have zero tickets in the window (or ever).
    lc_range = _date_range_clauses("lc.queued_at", date_from, date_to, params)
    lc_join = "LEFT JOIN low_confidence_queue lc ON lc.resolved_by = u.user_id AND lc.tenant_id = :tenant_id"
    if lc_range:
        lc_join += " AND " + " AND ".join(lc_range)

    claim_params: dict = {"tenant_id": tenant_id}
    claim_range = ["tenant_id = :tenant_id"] + _date_range_clauses("claimed_at", date_from, date_to, claim_params)
    claim_where = " WHERE " + " AND ".join(claim_range)
    params.update(claim_params)

    rows = await db.execute(sa_text(
        "SELECT u.user_id, u.display_name, "
        "  COUNT(lc.queue_id) as ticket_count, "
        "  SUM(CASE WHEN lc.resolution_action = 'edited_and_posted' THEN 1 ELSE 0 END) as corrections, "
        "  claim_stats.avg_claim_ms as avg_claim_ms "
        "FROM users u "
        f"{lc_join} "
        "LEFT JOIN ("
        "  SELECT claimed_by, "
        "         AVG((julianday(COALESCE(released_at, expires_at)) - julianday(claimed_at)) * 86400000) as avg_claim_ms "
        f"  FROM collision_claims{claim_where} GROUP BY claimed_by"
        ") claim_stats ON claim_stats.claimed_by = u.user_id "
        "WHERE u.tenant_id = :tenant_id AND u.role = 'technician' AND u.is_active = 1 "
        "GROUP BY u.user_id, u.display_name, claim_stats.avg_claim_ms ORDER BY ticket_count DESC"
    ), params)
    result = []
    for r in rows.mappings():
        tc = r["ticket_count"] or 0
        corr = r["corrections"] or 0
        result.append({
            "technician_id":   r["user_id"],
            "name":            r["display_name"],
            "ticket_count":    tc,
            "avg_claim_ms":    round(r["avg_claim_ms"]) if r["avg_claim_ms"] is not None else 0,
            "correction_rate": round(corr / tc * 100, 1) if tc > 0 else 0.0,
        })
    return result


# ── Manager — Abstention report ───────────────────────────────────────────────

@router.get("/manager/abstention")
async def get_manager_abstention(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    date_from: str | None = Query(None),
    date_to:   str | None = Query(None),
    sort_by:   str = Query("rate", pattern="^(rate|count)$"),
) -> list:
    params: dict = {"tenant_id": current_user["tenant_id"]}
    clauses = ["tenant_id = :tenant_id", "category IS NOT NULL"]
    clauses += _date_range_clauses("created_at", date_from, date_to, params)
    rows = await db.execute(sa_text(
        "SELECT category, COUNT(*) as total, "
        "SUM(CASE WHEN abstained = 1 THEN 1 ELSE 0 END) as abstained_count "
        f"FROM audit_log WHERE {' AND '.join(clauses)} "
        "GROUP BY category ORDER BY abstained_count DESC"
    ), params)
    result = []
    for r in rows.mappings():
        total = r["total"] or 1
        abstained = r["abstained_count"] or 0
        rate = round(abstained / total * 100, 1)
        severity = "high" if rate > 30 else ("medium" if rate > 10 else "low")
        result.append({
            "category":        r["category"],
            "abstention_rate": rate,
            "abstained_count": abstained,
            "gap_severity":    severity,
        })
    # sort_by=count preserves the backend's natural ORDER BY abstained_count
    # DESC above; sort_by=rate re-sorts by the displayed percentage, which
    # can disagree with raw count once category volumes differ.
    if sort_by == "rate":
        result.sort(key=lambda r: r["abstention_rate"], reverse=True)
    return result


# ── Manager — Collisions ──────────────────────────────────────────────────────

@router.get("/manager/collisions")
async def get_manager_collisions(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    date_from: str | None = Query(None),
    date_to:   str | None = Query(None),
) -> dict:
    # Collision events (tickets claimed by multiple users). Grouping must
    # happen in SQL before any LIMIT — grouping in Python after a
    # "LIMIT 50 raw claim rows" (the old approach) could silently drop a
    # genuine multi-claim collision whose rows fell outside the most recent
    # 50 raw claims. Group first, then cap the number of *collision events*
    # returned, not the number of raw claim rows scanned.
    col_params: dict = {"tenant_id": current_user["tenant_id"]}
    col_clauses = ["tenant_id = :tenant_id"] + _date_range_clauses("claimed_at", date_from, date_to, col_params)
    col_where = " WHERE " + " AND ".join(col_clauses)
    col_rows = await db.execute(sa_text(
        "SELECT ticket_id, GROUP_CONCAT(claimed_by) as claimants, "
        "       COUNT(*) as claim_count, MAX(claimed_at) as last_claimed_at "
        f"FROM collision_claims{col_where} "
        "GROUP BY ticket_id HAVING COUNT(*) > 1 "
        "ORDER BY last_claimed_at DESC LIMIT 50"
    ), col_params)
    collision_events = [
        {
            "ticket_id":  r["ticket_id"],
            "claimants":  (r["claimants"] or "").split(","),
            "created_at": r["last_claimed_at"],
        }
        for r in col_rows.mappings()
    ]

    return {"collision_events": collision_events}


# ── Manager — Cost savings ────────────────────────────────────────────────────

@router.get("/manager/cost-savings")
async def get_manager_cost_savings(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    date_from: str | None = Query(None),
    date_to:   str | None = Query(None),
) -> dict:
    tenant_id = current_user["tenant_id"]
    params: dict = {"tenant_id": tenant_id}
    clauses = ["tenant_id = :tenant_id", "abstained = 0"]
    clauses += _date_range_clauses("created_at", date_from, date_to, params)

    # Assume: each zero-touch resolution saves 30 min at $50/hr = $25
    count_row = await db.execute(sa_text(
        f"SELECT COUNT(*) FROM audit_log WHERE {' AND '.join(clauses)}"
    ), params)
    zero_touch = count_row.scalar() or 0

    # Weekly trend (last 8 weeks)
    trend_rows = await db.execute(sa_text(
        "SELECT strftime('%Y-%W', created_at) as week, "
        "SUM(CASE WHEN abstained = 0 THEN 1 ELSE 0 END) as zero_touch "
        "FROM audit_log WHERE tenant_id = :tenant_id GROUP BY week ORDER BY week DESC LIMIT 8"
    ), {"tenant_id": tenant_id})
    trend_data = [
        {"date": r["week"], "zero_touch": r["zero_touch"] or 0}
        for r in trend_rows.mappings()
    ]
    trend_data.reverse()

    return {
        "hours_saved":         round(zero_touch * 0.5, 1),
        "cost_reduction":      round(zero_touch * 25, 2),
        "zero_touch_per_week": round(zero_touch / max(len(trend_data), 1), 1),
        "trend_data":          trend_data,
    }


# ── Manager — Approval queue ──────────────────────────────────────────────────

_APPROVALS_SORT_COLUMNS = {
    "queued_at":        "queued_at",
    "confidence_score": "confidence_score",
    "team_id":          "team_id",
}


@router.get("/manager/approvals")
async def get_manager_approvals(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    team_id:        str | None = Query(None),
    status:         str | None = Query(None, pattern="^(abstained|low_confidence)$"),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    sort_by:        str = Query("queued_at", pattern="^(queued_at|confidence_score|team_id)$"),
    sort_dir:       str = Query("asc", pattern="^(asc|desc)$"),
    page:           Annotated[int, Query(ge=1)] = 1,
    page_size:      Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    clauses = ["tenant_id = :tenant_id", "resolved_at IS NULL"]
    params: dict = {"tenant_id": current_user["tenant_id"]}
    if team_id:
        clauses.append("team_id = :team_id")
        params["team_id"] = team_id
    if status == "abstained":
        clauses.append("abstained = 1")
    elif status == "low_confidence":
        clauses.append("abstained = 0")
    if min_confidence is not None:
        clauses.append("confidence_score >= :min_confidence")
        params["min_confidence"] = min_confidence
    where = " WHERE " + " AND ".join(clauses)

    total_row = await db.execute(sa_text(f"SELECT COUNT(*) FROM low_confidence_queue{where}"), params)
    total = total_row.scalar() or 0

    order_col = _APPROVALS_SORT_COLUMNS[sort_by]
    order_dir = "ASC" if sort_dir == "asc" else "DESC"
    offset = (page - 1) * page_size
    rows = await db.execute(sa_text(
        "SELECT queue_id, ticket_id, confidence_score, abstained, team_id, queued_at "
        f"FROM low_confidence_queue{where} "
        f"ORDER BY {order_col} {order_dir} LIMIT {page_size} OFFSET {offset}"
    ), params)
    items = [
        {
            "queue_id":        r["queue_id"],
            "ticket_id":       r["ticket_id"],
            "confidence_score": r["confidence_score"],
            "abstained":       bool(r["abstained"]),
            "team_id":         r["team_id"],
            "queued_at":       r["queued_at"],
        }
        for r in rows.mappings()
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ── Manager — Ticket tree ─────────────────────────────────────────────────────
# Hierarchical aggregation backing the interactive Ticket Tree canvas.
# One shared row-fetch derives every dimension (category, team, priority,
# resolution state, SLA state) per ticket, so the tree endpoint (aggregate
# counts) and the /tickets endpoint (leaf pages, fetched lazily as buckets
# expand) can never disagree about which bucket a ticket belongs to.

_TREE_GROUP_BYS = ("category_status", "team_category", "priority_sla")

# Resolution-state bucket vocabulary, in display order. Derived from
# audit_log.action_taken (see _derive_resolution_state) — the full set of
# values the pipeline + technician routes actually write.
_RESOLUTION_STATES: list[tuple[str, str]] = [
    ("resolved_auto",  "Auto-resolved"),
    ("resolved_human", "Human-approved"),
    ("in_review",      "In review"),
    ("abstained",      "Abstained"),
    ("rejected",       "Rejected"),
    ("rolled_back",    "Rolled back"),
    ("halted",         "Halted / Error"),
]

_SLA_STATES: list[tuple[str, str]] = [
    ("breached", "SLA breached"),
    ("warning",  "SLA warning"),
    ("ok",       "Within SLA"),
    ("none",     "No SLA"),
]

_PRIORITY_ORDER = {"Highest": 0, "Critical": 1, "High": 2, "Medium": 3, "Low": 4, "Lowest": 5}


def _derive_resolution_state(action_taken: str | None, abstained: int | None, q_action: str | None) -> str:
    if action_taken == "comment_posted":
        # Technician approve/edit routes stamp the queue row's
        # resolution_action before syncing action_taken — that's what
        # separates a human-approved post from a fully autonomous one.
        return "resolved_human" if q_action in ("approved", "edited_and_posted") else "resolved_auto"
    if action_taken == "rejected_by_technician":
        return "rejected"
    if action_taken == "rolled_back_by_technician":
        return "rolled_back"
    if abstained or action_taken == "abstained_no_kb_coverage":
        return "abstained"
    if action_taken == "held_low_confidence":
        return "in_review"
    return "halted"  # halted_kill_switch / pipeline_error / unknown


async def _fetch_tree_rows(
    db: AsyncSession, tenant_id: str, date_from: str | None, date_to: str | None,
) -> list[dict]:
    """One derived row per ticket (latest audit_log entry wins), with every
    tree dimension precomputed. Aggregation happens in Python — per-instance
    audit volume is small, and one derivation site beats three pivot-specific
    SQL variants drifting apart.
    """
    params: dict = {"tenant_id": tenant_id}
    clauses = [
        "a.tenant_id = :tenant_id",
        "a.entry_id = (SELECT entry_id FROM audit_log a2 WHERE a2.tenant_id = a.tenant_id AND a2.ticket_id = a.ticket_id "
        "ORDER BY a2.created_at DESC LIMIT 1)",
    ]
    clauses += _date_range_clauses("a.created_at", date_from, date_to, params)

    rows = await db.execute(sa_text(
        "SELECT a.ticket_id, a.action_taken, a.priority, a.category, a.abstained, "
        "       a.confidence_score, a.created_at, "
        "       ts.status AS workflow_status, "
        "       se.deadline AS sla_deadline, se.breached_at, se.warning_sent_at, "
        "       (SELECT cc.team_id FROM category_config cc WHERE cc.tenant_id = a.tenant_id AND cc.name = a.category) AS team_id, "
        "       (SELECT u.display_name FROM users u JOIN ticket_assignments ta ON ta.assigned_to = u.user_id "
        "        WHERE ta.tenant_id = a.tenant_id AND ta.ticket_id = a.ticket_id AND ta.is_current = 1 "
        "        ORDER BY ta.assigned_at DESC LIMIT 1) AS assignee_name, "
        "       (SELECT ta.acknowledged_at FROM ticket_assignments ta "
        "        WHERE ta.tenant_id = a.tenant_id AND ta.ticket_id = a.ticket_id AND ta.is_current = 1 "
        "        ORDER BY ta.assigned_at DESC LIMIT 1) AS acknowledged_at, "
        "       lc.resolution_action AS q_action "
        "FROM audit_log a "
        "LEFT JOIN ticket_status ts ON ts.tenant_id = a.tenant_id AND ts.ticket_id = a.ticket_id "
        "LEFT JOIN sla_events se ON se.tenant_id = a.tenant_id AND se.ticket_id = a.ticket_id "
        "LEFT JOIN low_confidence_queue lc ON lc.tenant_id = a.tenant_id AND lc.ticket_id = a.ticket_id "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY a.created_at DESC"
    ), params)

    derived = []
    for r in rows.mappings():
        if r["breached_at"] is not None:
            sla_state = "breached"
        elif r["warning_sent_at"] is not None:
            sla_state = "warning"
        elif r["sla_deadline"] is not None:
            sla_state = "ok"
        else:
            sla_state = "none"
        derived.append({
            "ticket_id":        r["ticket_id"],
            "category":         r["category"] or "Uncategorized",
            "team":             r["team_id"] or "Unassigned",
            "priority":         r["priority"] or "None",
            "resolution_state": _derive_resolution_state(r["action_taken"], r["abstained"], r["q_action"]),
            "sla_state":        sla_state,
            "sla_deadline":     r["sla_deadline"],
            "workflow_status":  r["workflow_status"],
            "confidence_score": r["confidence_score"],
            "assignee_name":    r["assignee_name"],
            "acknowledged":     r["acknowledged_at"] is not None,
            "created_at":       r["created_at"],
        })
    return derived


_TREE_DIMENSIONS = {
    # group_by → (level-1 row key, level-2 row key)
    "category_status": ("category", "resolution_state"),
    "team_category":   ("team", "category"),
    "priority_sla":    ("priority", "sla_state"),
}


def _bucket_label(group_by: str, bucket_key: str) -> str:
    if group_by == "category_status":
        return dict(_RESOLUTION_STATES).get(bucket_key, bucket_key)
    if group_by == "priority_sla":
        return dict(_SLA_STATES).get(bucket_key, bucket_key)
    return bucket_key  # team_category: bucket is a category name, already a label


def _node_stats(rows: list[dict]) -> dict:
    total = len(rows)
    with_sla = [r for r in rows if r["sla_state"] != "none"]
    breached = sum(1 for r in rows if r["sla_state"] == "breached")
    confs = [r["confidence_score"] for r in rows if r["confidence_score"] is not None]
    return {
        "total":              total,
        "auto_resolved":      sum(1 for r in rows if r["resolution_state"] == "resolved_auto"),
        "human_resolved":     sum(1 for r in rows if r["resolution_state"] == "resolved_human"),
        "in_review":          sum(1 for r in rows if r["resolution_state"] == "in_review"),
        "abstained":          sum(1 for r in rows if r["resolution_state"] == "abstained"),
        "breached":           breached,
        "warning":            sum(1 for r in rows if r["sla_state"] == "warning"),
        "sla_compliance_pct": round((len(with_sla) - breached) / len(with_sla) * 100, 1) if with_sla else None,
        "avg_confidence":     round(sum(confs) / len(confs), 3) if confs else None,
    }


def _sort_group_keys(group_by: str, keys: list[str]) -> list[str]:
    if group_by == "priority_sla":
        return sorted(keys, key=lambda k: (_PRIORITY_ORDER.get(k, 98), k))
    return sorted(keys, key=str.lower)


def _sorted_bucket_keys(group_by: str, keys: set[str]) -> list[str]:
    if group_by == "category_status":
        order = [k for k, _ in _RESOLUTION_STATES]
        return [k for k in order if k in keys]
    if group_by == "priority_sla":
        order = [k for k, _ in _SLA_STATES]
        return [k for k in order if k in keys]
    return sorted(keys, key=str.lower)


@router.get("/manager/ticket-tree")
async def get_manager_ticket_tree(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    group_by:  str = Query("category_status", pattern="^(category_status|team_category|priority_sla)$"),
    date_from: str | None = Query(None),
    date_to:   str | None = Query(None),
) -> dict:
    """Counts-only hierarchy: root → groups → buckets. Leaf tickets are
    fetched per-bucket via /manager/ticket-tree/tickets as the user expands,
    keeping this payload constant-size regardless of ticket volume.
    """
    rows = await _fetch_tree_rows(db, current_user["tenant_id"], date_from, date_to)
    level1_key, level2_key = _TREE_DIMENSIONS[group_by]

    groups_map: dict[str, list[dict]] = {}
    for r in rows:
        groups_map.setdefault(r[level1_key], []).append(r)

    groups = []
    for gkey in _sort_group_keys(group_by, list(groups_map.keys())):
        grows = groups_map[gkey]
        buckets_map: dict[str, list[dict]] = {}
        for r in grows:
            buckets_map.setdefault(r[level2_key], []).append(r)
        buckets = [
            {
                "key":   bkey,
                "label": _bucket_label(group_by, bkey),
                **_node_stats(buckets_map[bkey]),
            }
            for bkey in _sorted_bucket_keys(group_by, set(buckets_map.keys()))
        ]
        groups.append({"key": gkey, "label": gkey, **_node_stats(grows), "buckets": buckets})

    return {
        "group_by": group_by,
        "root": {**_node_stats(rows), "groups": groups},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/manager/ticket-tree/tickets")
async def get_manager_ticket_tree_tickets(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    group_by:  str = Query("category_status", pattern="^(category_status|team_category|priority_sla)$"),
    group:     str = Query(...),
    bucket:    str = Query(...),
    date_from: str | None = Query(None),
    date_to:   str | None = Query(None),
    page:      Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict:
    """Leaf tickets for one expanded bucket, newest first."""
    rows = await _fetch_tree_rows(db, current_user["tenant_id"], date_from, date_to)
    level1_key, level2_key = _TREE_DIMENSIONS[group_by]
    matching = [r for r in rows if r[level1_key] == group and r[level2_key] == bucket]
    start = (page - 1) * page_size
    return {
        "items": matching[start:start + page_size],
        "total": len(matching),
        "page": page,
        "page_size": page_size,
    }
