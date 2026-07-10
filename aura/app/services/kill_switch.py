"""Kill switch service — master circuit breaker for the AURA agent pipeline.

One switch per tenant, stored in that tenant's `platform_config` row and
mirrored in an in-process cache (keyed by tenant_id) so `is_enabled()` never
blocks on a DB round-trip during the hot path of every incoming ticket.

Cache invalidation happens in two ways:
  1. Explicit: `enable()` / `disable()` update both SQLite and the cache atomically.
  2. Startup: `init_kill_switch()` loads every active tenant's state once from
     the FastAPI lifespan so the cache reflects whatever was persisted before
     the last restart. A tenant created after startup is lazily cached on
     its first `is_enabled()` miss — see `_DEFAULT_ENABLED`.

WebSocket events broadcast on every state change (to that tenant's users
only — see notification_bus):
  KILL_SWITCH_ACTIVATED   — aura_enabled flipped to False
  KILL_SWITCH_DEACTIVATED — aura_enabled flipped to True
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.notification_bus import notification_bus

log = get_logger(__name__)

# A tenant not yet present in the cache (created after this process's last
# init_kill_switch() sweep) defaults to enabled — matches platform_config's
# own column default, so a brand-new tenant starts with AURA running.
_DEFAULT_ENABLED = True

# In-process cache — read without acquiring _lock; writes use _lock.
_enabled: dict[str, bool] = {}
_lock = asyncio.Lock()


# ── Startup initialisation ────────────────────────────────────────────────────

async def init_kill_switch(db: AsyncSession) -> None:
    """Load every tenant's persisted kill-switch state into the in-process
    cache. Call once from the FastAPI lifespan after `init_db()`.
    """
    global _enabled
    result = await db.execute(sa_text("SELECT tenant_id, aura_enabled FROM platform_config"))
    _enabled = {row[0]: bool(row[1]) for row in result.all()}
    log.info("kill_switch.loaded", tenant_count=len(_enabled))


# ── Public API ────────────────────────────────────────────────────────────────

def is_enabled(tenant_id: str) -> bool:
    """Return the current kill-switch state for one tenant from the
    in-process cache. Safe to call from any async context without
    awaiting — it never blocks.
    """
    return _enabled.get(tenant_id, _DEFAULT_ENABLED)


async def enable(db: AsyncSession, tenant_id: str, changed_by: str) -> None:
    """Turn this tenant's agent pipeline ON and persist the change."""
    await _set_state(db, tenant_id, enabled=True, changed_by=changed_by)
    await notification_bus.broadcast_to_tenant(
        tenant_id, "KILL_SWITCH_DEACTIVATED",
        {"changed_by": changed_by, "timestamp": _now_iso()},
    )
    log.info("kill_switch.enabled", tenant_id=tenant_id, changed_by=changed_by)


async def disable(db: AsyncSession, tenant_id: str, changed_by: str) -> None:
    """Turn this tenant's agent pipeline OFF and persist the change."""
    await _set_state(db, tenant_id, enabled=False, changed_by=changed_by)
    await notification_bus.broadcast_to_tenant(
        tenant_id, "KILL_SWITCH_ACTIVATED",
        {"changed_by": changed_by, "timestamp": _now_iso()},
    )
    log.info("kill_switch.disabled", tenant_id=tenant_id, changed_by=changed_by)


async def get_status(db: AsyncSession, tenant_id: str) -> dict:
    """Return the full kill-switch status row for the admin API."""
    result = await db.execute(
        sa_text(
            "SELECT aura_enabled, kill_switch_changed_by, kill_switch_changed_at "
            "FROM platform_config WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return {"enabled": is_enabled(tenant_id), "changed_by": None, "changed_at": None}
    return {
        "enabled": bool(row["aura_enabled"]),
        "changed_by": row["kill_switch_changed_by"],
        "changed_at": row["kill_switch_changed_at"],
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _set_state(db: AsyncSession, tenant_id: str, *, enabled: bool, changed_by: str) -> None:
    now = _now_iso()
    async with _lock:
        await db.execute(
            sa_text(
                "UPDATE platform_config "
                "SET aura_enabled = :enabled, "
                "    kill_switch_changed_by = :changed_by, "
                "    kill_switch_changed_at = :changed_at, "
                "    updated_at = :updated_at "
                "WHERE tenant_id = :tid"
            ),
            {
                "enabled": int(enabled),
                "changed_by": changed_by,
                "changed_at": now,
                "updated_at": now,
                "tid": tenant_id,
            },
        )
        await db.commit()
        _enabled[tenant_id] = enabled


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
