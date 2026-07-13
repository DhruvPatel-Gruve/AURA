"""Audit logger — immutable append-only decision log for every agent pipeline run.

The audit_log table is the single source of truth for:
  - Manager analytics dashboards (resolution rate, confidence, abstention)
  - Admin audit log page (filterable, CSV-exportable)
  - Per-ticket AuditStepTimeline in the technician Ticket Detail view

Rules:
  - No UPDATE or DELETE ever touches audit_log. Rows are write-once.
  - Every pipeline run produces exactly one AuditEntry (written by audit_finalizer_node).
  - CSV export streams directly from SQLite — no in-memory accumulation.
"""

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.audit import AuditEntry, AuditStep

log = get_logger(__name__)

_PAGE_SIZE = 50


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Public API ────────────────────────────────────────────────────────────────

async def log_entry(db: AsyncSession, entry: AuditEntry) -> None:
    """Append one AuditEntry to the audit_log table. Never raises on duplicate
    entry_id — the INSERT is guarded with OR IGNORE so re-runs are safe.
    """
    await db.execute(
        sa_text(
            "INSERT OR IGNORE INTO audit_log ("
            "  entry_id, tenant_id, ticket_id, action_taken, priority, category,"
            "  auto_comment_enabled, confidence_score, abstained,"
            "  jsm_comment_id, rollback_ref, audit_steps, created_at"
            ") VALUES ("
            "  :entry_id, :tenant_id, :ticket_id, :action_taken, :priority, :category,"
            "  :auto_comment_enabled, :confidence_score, :abstained,"
            "  :jsm_comment_id, :rollback_ref, :audit_steps, :created_at"
            ")"
        ),
        {
            "entry_id": entry.entry_id or str(uuid.uuid4()),
            "tenant_id": entry.tenant_id,
            "ticket_id": entry.ticket_id,
            "action_taken": entry.action_taken,
            "priority": entry.priority,
            "category": entry.category,
            "auto_comment_enabled": (
                None if entry.auto_comment_enabled is None else int(entry.auto_comment_enabled)
            ),
            "confidence_score": entry.confidence_score,
            "abstained": int(entry.abstained),
            "jsm_comment_id": entry.jsm_comment_id,
            "rollback_ref": entry.rollback_ref,
            "audit_steps": json.dumps(
                [s.model_dump() if isinstance(s, AuditStep) else s
                 for s in entry.audit_steps]
            ),
            "created_at": entry.created_at.isoformat()
            if isinstance(entry.created_at, datetime)
            else _now_iso(),
        },
    )
    await db.commit()
    log.info("audit.logged", ticket_id=entry.ticket_id, action=entry.action_taken)


async def get_entries(
    db: AsyncSession,
    *,
    tenant_id: str,
    ticket_id: str | None = None,
    action_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
) -> dict[str, Any]:
    """Return a paginated list of audit entries matching the given filters.

    Returns:
        { items: list[dict], total: int, page: int, pages: int }
    """
    where, params = _build_filters(tenant_id, ticket_id, action_type, date_from, date_to)

    # Total count
    count_sql = f"SELECT COUNT(*) FROM audit_log{where}"
    count_result = await db.execute(sa_text(count_sql), params)
    total: int = count_result.scalar() or 0

    # Paginated rows
    offset = (page - 1) * _PAGE_SIZE
    rows_sql = (
        f"SELECT entry_id, ticket_id, action_taken, priority, category,"
        f"       auto_comment_enabled, confidence_score, abstained,"
        f"       jsm_comment_id, rollback_ref, audit_steps, created_at"
        f" FROM audit_log{where}"
        f" ORDER BY created_at DESC"
        f" LIMIT {_PAGE_SIZE} OFFSET {offset}"
    )
    rows_result = await db.execute(sa_text(rows_sql), params)
    items = [_row_to_dict(r) for r in rows_result.mappings().all()]

    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // _PAGE_SIZE)),  # ceiling division
    }


async def export_csv(
    db: AsyncSession,
    *,
    tenant_id: str,
    ticket_id: str | None = None,
    action_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> io.StringIO:
    """Stream all matching audit entries into a CSV StringIO buffer.

    The caller (FastAPI route) wraps this in a StreamingResponse.
    """
    where, params = _build_filters(tenant_id, ticket_id, action_type, date_from, date_to)
    sql = (
        f"SELECT entry_id, ticket_id, action_taken, priority, category,"
        f"       auto_comment_enabled, confidence_score, abstained,"
        f"       jsm_comment_id, created_at"
        f" FROM audit_log{where}"
        f" ORDER BY created_at ASC"
    )
    result = await db.execute(sa_text(sql), params)
    rows = result.mappings().all()

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "entry_id", "ticket_id", "action_taken", "priority", "category",
            "auto_comment_enabled", "confidence_score", "abstained",
            "jsm_comment_id", "created_at",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(row))

    buf.seek(0)
    return buf


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_filters(
    tenant_id: str,
    ticket_id: str | None = None,
    action_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[str, dict]:
    clauses: list[str] = ["tenant_id = :tenant_id"]
    params: dict = {"tenant_id": tenant_id}

    if ticket_id:
        clauses.append("ticket_id = :ticket_id")
        params["ticket_id"] = ticket_id
    if action_type:
        clauses.append("action_taken = :action_type")
        params["action_type"] = action_type
    if date_from:
        clauses.append("created_at >= :date_from")
        params["date_from"] = date_from.isoformat()
    if date_to:
        clauses.append("created_at <= :date_to")
        params["date_to"] = date_to.isoformat()

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _row_to_dict(row: Any) -> dict:
    d = dict(row)
    # Deserialise the JSON audit_steps blob so the API returns a proper list
    try:
        d["audit_steps"] = json.loads(d.get("audit_steps") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["audit_steps"] = []
    d["abstained"] = bool(d.get("abstained"))
    if "auto_comment_enabled" in d and d["auto_comment_enabled"] is not None:
        d["auto_comment_enabled"] = bool(d["auto_comment_enabled"])
    return d
