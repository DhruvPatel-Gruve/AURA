"""Assignment service — continuous human-in-the-loop ticket ownership.

Responsibilities:
  1. assign()             — pick the least-loaded active technician on a team.
  2. record_assignment()  — persist an assignment, superseding any prior one
                            for the same ticket (full history kept, like audit_log).
  3. acknowledge()        — technician confirms they've seen the ticket, which
                            cancels the reassignment timer.
  4. check_overdue()      — called by APScheduler every minute; reassigns
                            unacknowledged tickets past assignment_timeout_minutes
                            to another technician (least-loaded), or if none is
                            available, re-notifies the current technician and
                            escalates to admins once per overdue assignment.

WS events emitted (all targeted at the specific technician via send_to_user,
so the assignee gets a visible "assigned to you" notification/toast rather
than a team-wide broadcast):
  TICKET_REASSIGNED  { ticket_id, previous_technician, technician_id, team_id }
  ASSIGNMENT_OVERDUE { ticket_id, technician_id, team_id }  (sent to technician + once to admins)
"""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.notification_bus import notification_bus

log = get_logger(__name__)

_FALLBACK_TIMEOUT_MINUTES = 60

# Guards the read-decide-write critical section spanning assign() -> the
# external Jira assignee call -> record_assignment(). Without it, two
# tickets triaged for the same team milliseconds apart can both read
# "technician X has the fewest active assignments" before either has
# recorded theirs, double-booking X. SQLite has no row-level locking to
# lean on here, and the two DB calls happen in separate transactions
# (assignment_node opens a fresh `get_session()` per step), so the only
# correct fix within a single process is serializing the whole section.
# Callers: assignment_node.py's initial assignment, and this module's own
# check_overdue() reassignment path.
ASSIGNMENT_LOCK = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _parse_dt(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Public API ────────────────────────────────────────────────────────────────

async def assign(
    db: AsyncSession,
    tenant_id: str,
    team_id: str,
    exclude_user_id: str | None = None,
) -> dict | None:
    """Return the active technician on team_id with the fewest current assignments.

    Ties broken by user_id for determinism. Returns None if no eligible
    technician exists (e.g. team has no technicians, or only the excluded one).
    team_id alone isn't tenant-unique, so every query here is also scoped by
    tenant_id — two different tenants can both name a team "net-team".
    """
    query = (
        "SELECT u.user_id, u.display_name, u.email, u.jira_account_id, "
        "       COUNT(ta.assignment_id) AS active_count "
        "FROM users u "
        "LEFT JOIN ticket_assignments ta "
        "       ON ta.assigned_to = u.user_id AND ta.is_current = 1 AND ta.tenant_id = :tenant "
        "WHERE u.role = 'technician' AND u.team_id = :team AND u.tenant_id = :tenant AND u.is_active = 1 "
    )
    params: dict = {"team": team_id, "tenant": tenant_id}
    if exclude_user_id:
        query += "AND u.user_id != :exclude "
        params["exclude"] = exclude_user_id
    query += "GROUP BY u.user_id ORDER BY active_count ASC, u.user_id ASC LIMIT 1"

    result = await db.execute(sa_text(query), params)
    row = result.mappings().first()
    return dict(row) if row else None


async def record_assignment(
    db: AsyncSession,
    tenant_id: str,
    ticket_id: str,
    technician_id: str,
    team_id: str | None,
) -> None:
    """Persist a new current assignment, superseding any prior one for this ticket."""
    now_iso = _now_iso()
    await db.execute(
        sa_text(
            "UPDATE ticket_assignments SET is_current = 0, reassigned_at = :now "
            "WHERE tenant_id = :tenant AND ticket_id = :tid AND is_current = 1"
        ),
        {"now": now_iso, "tenant": tenant_id, "tid": ticket_id},
    )
    await db.execute(
        sa_text(
            "INSERT INTO ticket_assignments "
            "(assignment_id, tenant_id, ticket_id, assigned_to, team_id, assigned_at, is_current) "
            "VALUES (:aid, :tenant, :tid, :uid, :team, :now, 1)"
        ),
        {"aid": _uuid(), "tenant": tenant_id, "tid": ticket_id, "uid": technician_id, "team": team_id, "now": now_iso},
    )
    await db.commit()
    log.info("assignment.recorded", tenant_id=tenant_id, ticket_id=ticket_id, technician_id=technician_id, team_id=team_id)


async def acknowledge(db: AsyncSession, tenant_id: str, ticket_id: str, user_id: str) -> bool:
    """Mark the current assignment as acknowledged by user_id.

    Returns False if there's no current assignment, it's assigned to someone
    else, or it's already acknowledged.
    """
    result = await db.execute(
        sa_text(
            "UPDATE ticket_assignments SET acknowledged_at = :now "
            "WHERE tenant_id = :tenant AND ticket_id = :tid AND assigned_to = :uid "
            "  AND is_current = 1 AND acknowledged_at IS NULL"
        ),
        {"now": _now_iso(), "tenant": tenant_id, "tid": ticket_id, "uid": user_id},
    )
    await db.commit()
    return result.rowcount > 0


async def check_overdue(db: AsyncSession, tenant_id: str) -> None:
    """Scan one tenant's unacknowledged current assignments and
    reassign/escalate as needed.

    Called once per active tenant, per minute, by
    scheduler/jobs/assignment_timeout_checker.py.
    """
    now = _now()

    row = (await db.execute(
        sa_text("SELECT assignment_timeout_minutes FROM platform_config WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )).first()
    timeout_minutes = row[0] if row and row[0] is not None else _FALLBACK_TIMEOUT_MINUTES

    result = await db.execute(
        sa_text(
            "SELECT assignment_id, ticket_id, assigned_to, team_id, assigned_at, escalated_at "
            "FROM ticket_assignments WHERE tenant_id = :tid AND is_current = 1 AND acknowledged_at IS NULL"
        ),
        {"tid": tenant_id},
    )
    rows = result.mappings().all()

    for row in rows:
        assigned_at = _parse_dt(row["assigned_at"])
        elapsed_minutes = (now - assigned_at).total_seconds() / 60
        if elapsed_minutes < timeout_minutes:
            continue

        ticket_id = row["ticket_id"]
        team_id = row["team_id"]
        current_technician = row["assigned_to"]

        reassigned = False
        if team_id:
            async with ASSIGNMENT_LOCK:
                next_tech = await assign(db, tenant_id, team_id=team_id, exclude_user_id=current_technician)
                if next_tech:
                    jira_account_id = await resolve_jira_account(db, next_tech)
                    if jira_account_id:
                        try:
                            from app.services.itsm_client import get_itsm_client
                            async with get_itsm_client(tenant_id) as itsm:
                                await itsm.assign_ticket(ticket_id, jira_account_id)
                            await record_assignment(db, tenant_id, ticket_id, next_tech["user_id"], team_id)
                            await notification_bus.send_to_user(
                                next_tech["user_id"],
                                "TICKET_REASSIGNED",
                                {
                                    "ticket_id": ticket_id,
                                    "previous_technician": current_technician,
                                    "technician_id": next_tech["user_id"],
                                    "team_id": team_id,
                                },
                            )
                            log.warning(
                                "assignment.reassigned",
                                ticket_id=ticket_id,
                                from_technician=current_technician,
                                to_technician=next_tech["user_id"],
                            )
                            reassigned = True
                        except Exception as exc:
                            log.error("assignment.reassign_failed", ticket_id=ticket_id, error=str(exc))

        if reassigned:
            continue

        # No alternative technician (or reassignment failed) — re-notify the
        # current technician every cycle, but escalate to admins only once.
        await notification_bus.send_to_user(
            current_technician,
            "ASSIGNMENT_OVERDUE",
            {"ticket_id": ticket_id, "technician_id": current_technician, "team_id": team_id},
        )
        if row["escalated_at"] is None:
            await notification_bus.broadcast_to_admins(
                tenant_id,
                "ASSIGNMENT_OVERDUE",
                {"ticket_id": ticket_id, "technician_id": current_technician, "team_id": team_id},
            )
            await db.execute(
                sa_text(
                    "UPDATE ticket_assignments SET escalated_at = :now WHERE assignment_id = :aid"
                ),
                {"now": now.isoformat(), "aid": row["assignment_id"]},
            )
            log.warning("assignment.escalated", ticket_id=ticket_id, technician_id=current_technician)

    await db.commit()


# ── Internal helpers ──────────────────────────────────────────────────────────

async def resolve_jira_account(db: AsyncSession, technician: dict) -> str | None:
    """Return technician's jira_account_id, resolving and caching by email if unset."""
    if technician.get("jira_account_id"):
        return technician["jira_account_id"]

    try:
        from app.services.itsm_client import get_itsm_client
        async with get_itsm_client() as itsm:
            jira_account_id = await itsm.find_account_id_by_email(technician["email"])
    except Exception as exc:
        log.error("assignment.jira_lookup_failed", technician_id=technician["user_id"], error=str(exc))
        return None

    if jira_account_id:
        await db.execute(
            sa_text("UPDATE users SET jira_account_id = :jid WHERE user_id = :uid"),
            {"jid": jira_account_id, "uid": technician["user_id"]},
        )
    return jira_account_id
