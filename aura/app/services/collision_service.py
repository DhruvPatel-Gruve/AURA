"""Collision service — ticket claim locking to prevent duplicated technician effort.

A "claim" is a soft lock a technician places on a ticket via the UI ("Claim" button).
It signals to other technicians and to AURA that this ticket is actively being worked.

Behaviour in the agent pipeline (Node 5 — collision_node):
  - If a claim exists: pipeline CONTINUES (informational only). The AURASuggestion
    panel shows who has claimed the ticket and disables the "Approve & Post" button
    so only the claiming technician can act.
  - If no claim: pipeline continues normally.

Claims auto-expire after `collision_timeout_minutes` (default 30 min, admin-
configurable). The scheduler calls `expire_stale_claims()` every 5 minutes.

WS events emitted:
  TICKET_CLAIMED   — on successful claim
  TICKET_UNCLAIMED — on explicit release or expiry
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.notification_bus import notification_bus

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


# ── Public API ────────────────────────────────────────────────────────────────

async def claim(
    db: AsyncSession,
    tenant_id: str,
    ticket_id: str,
    user_id: str,
    team_id: str | None = None,
    timeout_minutes: int | None = None,
) -> dict:
    """Place a claim on a ticket for the given user.

    If the ticket is already claimed by *another* user, raises ValueError.
    If the same user re-claims, their existing claim's expiry is refreshed.

    Returns:
        { claimed: bool, claimed_by: str, expires_at: ISO str }
    """
    settings = get_settings()
    timeout = timeout_minutes or settings.collision_timeout_minutes

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=timeout)

    # Check for an existing active claim
    existing = await _get_active_claim(db, tenant_id, ticket_id)

    if existing and existing["claimed_by"] != user_id:
        raise ValueError(
            f"Ticket {ticket_id} is already claimed by {existing['claimed_by']}"
        )

    if existing and existing["claimed_by"] == user_id:
        # Refresh expiry for same user
        await db.execute(
            sa_text(
                "UPDATE collision_claims SET expires_at = :exp "
                "WHERE tenant_id = :tenant AND ticket_id = :tid AND claimed_by = :uid AND released_at IS NULL"
            ),
            {"exp": expires_at.isoformat(), "tenant": tenant_id, "tid": ticket_id, "uid": user_id},
        )
    else:
        # New claim
        await db.execute(
            sa_text(
                "INSERT INTO collision_claims "
                "(claim_id, tenant_id, ticket_id, claimed_by, claimed_at, expires_at) "
                "VALUES (:cid, :tenant, :tid, :uid, :cat, :exp)"
            ),
            {
                "cid": _uuid(),
                "tenant": tenant_id,
                "tid": ticket_id,
                "uid": user_id,
                "cat": now.isoformat(),
                "exp": expires_at.isoformat(),
            },
        )

    await db.commit()

    result = {
        "claimed": True,
        "claimed_by": user_id,
        "expires_at": expires_at.isoformat(),
    }

    # Notify the team so other technicians' UIs update instantly
    if team_id:
        await notification_bus.broadcast_to_team(
            tenant_id,
            team_id,
            "TICKET_CLAIMED",
            {"ticket_id": ticket_id, "claimed_by": user_id, "expires_at": expires_at.isoformat()},
        )

    log.info("collision.claimed", tenant_id=tenant_id, ticket_id=ticket_id, user_id=user_id)
    return result


async def release(
    db: AsyncSession,
    tenant_id: str,
    ticket_id: str,
    user_id: str,
    team_id: str | None = None,
) -> bool:
    """Release a claim. Only the claiming user can release their own claim.

    Returns True if a claim was released, False if no active claim existed.
    """
    result = await db.execute(
        sa_text(
            "UPDATE collision_claims SET released_at = :now "
            "WHERE tenant_id = :tenant AND ticket_id = :tid AND claimed_by = :uid AND released_at IS NULL"
        ),
        {"now": _now_iso(), "tenant": tenant_id, "tid": ticket_id, "uid": user_id},
    )
    await db.commit()

    released = result.rowcount > 0
    if released:
        if team_id:
            await notification_bus.broadcast_to_team(
                tenant_id,
                team_id,
                "TICKET_UNCLAIMED",
                {"ticket_id": ticket_id},
            )
        log.info("collision.released", tenant_id=tenant_id, ticket_id=ticket_id, user_id=user_id)

    return released


async def check_claim(
    db: AsyncSession,
    tenant_id: str,
    ticket_id: str,
) -> Optional[dict]:
    """Return the active claim for a ticket, or None if unclaimed.

    Returns:
        { claimed_by: str, expires_at: str } | None
    """
    return await _get_active_claim(db, tenant_id, ticket_id)


async def expire_stale_claims(db: AsyncSession) -> int:
    """Mark all claims whose expiry has passed as released.

    Called by the APScheduler sla_checker job every 5 minutes.
    Returns the number of claims expired.
    """
    now_iso = _now_iso()
    result = await db.execute(
        sa_text(
            "UPDATE collision_claims SET released_at = :now "
            "WHERE released_at IS NULL AND expires_at < :now"
        ),
        {"now": now_iso},
    )
    await db.commit()

    count = result.rowcount
    if count:
        log.info("collision.expired_stale", count=count)
    return count


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_active_claim(
    db: AsyncSession,
    tenant_id: str,
    ticket_id: str,
) -> Optional[dict]:
    """Fetch the active (non-expired, non-released) claim for a ticket."""
    now_iso = _now_iso()
    result = await db.execute(
        sa_text(
            "SELECT claimed_by, expires_at FROM collision_claims "
            "WHERE tenant_id = :tenant AND ticket_id = :tid "
            "  AND released_at IS NULL "
            "  AND expires_at > :now "
            "LIMIT 1"
        ),
        {"tenant": tenant_id, "tid": ticket_id, "now": now_iso},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return {"claimed_by": row["claimed_by"], "expires_at": row["expires_at"]}
