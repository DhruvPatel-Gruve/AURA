"""SLA Engine — deadline tracking and breach alerting.

Responsibilities:
  1. register()         — called by sla_node to store a ticket's deadline in sla_events.
  2. compute_status()   — returns whether a ticket is on-track, at-risk, or breached.
  3. check_all_active() — called by APScheduler every minute; scans all open SLA events
                          and fires WS alerts at two thresholds:
                            75 % elapsed → SLA_WARNING  (amber)
                            100% elapsed → SLA_BREACHED (red)
                          Warning and breach alerts are each sent only once per ticket
                          (guarded by warning_sent_at / breached_at columns).

WS events emitted:
  SLA_WARNING  { ticket_id, sla_deadline, elapsed_pct, category }
  SLA_BREACHED { ticket_id, sla_deadline, elapsed_pct, category }
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.notification_bus import notification_bus

log = get_logger(__name__)

SLAStatus = Literal["ok", "warning", "breached"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


def _parse_dt(iso: str) -> datetime:
    """Parse an ISO-8601 string that may or may not carry timezone info."""
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Public API ────────────────────────────────────────────────────────────────

async def register(
    db: AsyncSession,
    tenant_id: str,
    ticket_id: str,
    category: str,
    deadline: datetime,
    status: SLAStatus,
) -> None:
    """Upsert an SLA event row for a ticket.

    Safe to call multiple times — subsequent calls update the existing row
    rather than inserting a duplicate (UNIQUE constraint on (tenant_id, ticket_id)).
    """
    now_iso = _now_iso()
    await db.execute(
        sa_text(
            "INSERT INTO sla_events (sla_id, tenant_id, ticket_id, category, deadline, created_at) "
            "VALUES (:sid, :tenant, :tid, :cat, :dl, :now) "
            "ON CONFLICT(tenant_id, ticket_id) DO UPDATE SET "
            "  category = excluded.category, "
            "  deadline = excluded.deadline, "
            "  created_at = excluded.created_at"
        ),
        {
            "sid": _uuid(),
            "tenant": tenant_id,
            "tid": ticket_id,
            "cat": category,
            "dl": deadline.isoformat(),
            "now": now_iso,
        },
    )
    await db.commit()
    log.debug("sla.registered", tenant_id=tenant_id, ticket_id=ticket_id, deadline=deadline.isoformat(), status=status)


async def compute_status(
    db: AsyncSession,
    tenant_id: str,
    ticket_id: str,
) -> dict:
    """Return the current SLA status for a ticket.

    Returns:
        {
          ticket_id: str,
          deadline:  str (ISO-8601),
          elapsed_pct: float,
          status: "ok" | "warning" | "breached",
        }
    """
    result = await db.execute(
        sa_text(
            "SELECT ticket_id, category, deadline, created_at "
            "FROM sla_events WHERE tenant_id = :tenant AND ticket_id = :tid"
        ),
        {"tenant": tenant_id, "tid": ticket_id},
    )
    row = result.mappings().first()
    if row is None:
        return {"ticket_id": ticket_id, "deadline": None, "elapsed_pct": 0.0, "status": "ok"}

    deadline = _parse_dt(row["deadline"])
    registered_at = _parse_dt(row["created_at"])
    now = _now()

    total_seconds = (deadline - registered_at).total_seconds()
    elapsed_seconds = (now - registered_at).total_seconds()
    elapsed_pct = (elapsed_seconds / total_seconds * 100) if total_seconds > 0 else 100.0

    status: SLAStatus = _pct_to_status(elapsed_pct)

    return {
        "ticket_id": ticket_id,
        "category": row["category"],
        "deadline": deadline.isoformat(),
        "elapsed_pct": round(elapsed_pct, 2),
        "status": status,
    }


async def check_all_active(db: AsyncSession) -> None:
    """Scan every unresolved SLA event and send WS alerts at breach thresholds.

    Called by APScheduler every minute. Each alert fires at most once:
      - warning_sent_at is set when the 75% warning fires
      - breached_at is set when the 100% breach fires
    """
    now = _now()
    now_iso = now.isoformat()

    result = await db.execute(
        sa_text(
            "SELECT sla_id, tenant_id, ticket_id, category, deadline, created_at, "
            "       warning_sent_at, breached_at "
            "FROM sla_events"
        )
    )
    rows = result.mappings().all()

    for row in rows:
        deadline = _parse_dt(row["deadline"])
        registered_at = _parse_dt(row["created_at"])

        total_seconds = (deadline - registered_at).total_seconds()
        elapsed_seconds = (now - registered_at).total_seconds()
        elapsed_pct = (elapsed_seconds / total_seconds * 100) if total_seconds > 0 else 100.0

        tenant_id = row["tenant_id"]
        tid = row["ticket_id"]
        cat = row["category"]

        if elapsed_pct >= 100.0 and row["breached_at"] is None:
            # First breach detection — fire alert and stamp the row
            await notification_bus.broadcast_to_tenant(
                tenant_id,
                "SLA_BREACHED",
                {
                    "ticket_id": tid,
                    "sla_deadline": deadline.isoformat(),
                    "elapsed_pct": round(elapsed_pct, 2),
                    "category": cat,
                },
            )
            await db.execute(
                sa_text(
                    "UPDATE sla_events SET breached_at = :now WHERE sla_id = :sid"
                ),
                {"now": now_iso, "sid": row["sla_id"]},
            )
            log.warning("sla.breached", ticket_id=tid, elapsed_pct=round(elapsed_pct, 2))

        elif 75.0 <= elapsed_pct < 100.0 and row["warning_sent_at"] is None:
            # First warning threshold crossed
            await notification_bus.broadcast_to_tenant(
                tenant_id,
                "SLA_WARNING",
                {
                    "ticket_id": tid,
                    "sla_deadline": deadline.isoformat(),
                    "elapsed_pct": round(elapsed_pct, 2),
                    "category": cat,
                },
            )
            await db.execute(
                sa_text(
                    "UPDATE sla_events SET warning_sent_at = :now WHERE sla_id = :sid"
                ),
                {"now": now_iso, "sid": row["sla_id"]},
            )
            log.info("sla.warning", ticket_id=tid, elapsed_pct=round(elapsed_pct, 2))

    await db.commit()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _pct_to_status(elapsed_pct: float) -> SLAStatus:
    if elapsed_pct >= 100.0:
        return "breached"
    if elapsed_pct >= 75.0:
        return "warning"
    return "ok"


def compute_deadline(created_at: datetime, sla_minutes: int) -> datetime:
    """Pure helper used by sla_node to calculate deadline before calling register()."""
    return created_at + timedelta(minutes=sla_minutes)


def compute_elapsed_pct(created_at: datetime, deadline: datetime) -> float:
    """Return how far through the SLA window we are (0–100+)."""
    now = _now()
    total = (deadline - created_at).total_seconds()
    elapsed = (now - created_at).total_seconds()
    return (elapsed / total * 100) if total > 0 else 100.0
