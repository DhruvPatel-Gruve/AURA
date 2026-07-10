"""Active ITSM provider — which backend (Jira, Zendesk, ...) each tenant
currently talks to. Mirrors kill_switch.py's shape exactly: persisted per
tenant in `platform_config`, mirrored in an in-process cache (keyed by
tenant_id) so `get()` never blocks on a DB round-trip on the hot path, and
`set()` updates both atomically so a provider switch takes effect
immediately — no restart needed.

Provider *credentials* (JSM_*, ZEN_*) also live in `platform_config` now,
encrypted at rest (app/core/crypto.py) — see app/services/itsm_client.py for
where they're decrypted and turned into a concrete client.
"""

import asyncio

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

log = get_logger(__name__)

_DEFAULT_PROVIDER = "jira"
_VALID_PROVIDERS = ("jira", "zendesk")

# In-process cache — read without acquiring _lock; writes use _lock.
_providers: dict[str, str] = {}
_lock = asyncio.Lock()


async def init_itsm_provider(db: AsyncSession) -> None:
    """Load every tenant's persisted provider choice into the in-process
    cache. Call once from the FastAPI lifespan after `init_db()`.
    """
    global _providers
    result = await db.execute(sa_text("SELECT tenant_id, itsm_provider FROM platform_config"))
    _providers = {
        row[0]: row[1] if row[1] in _VALID_PROVIDERS else _DEFAULT_PROVIDER
        for row in result.all()
    }
    log.info("itsm_provider.loaded", tenant_count=len(_providers))


def get(tenant_id: str) -> str:
    """Return the active provider ("jira" | "zendesk") for one tenant from
    the in-process cache. Safe to call from any context without awaiting —
    never blocks. A tenant not yet in the cache (created after this
    process's last load) defaults to "jira".
    """
    return _providers.get(tenant_id, _DEFAULT_PROVIDER)


async def set(db: AsyncSession, tenant_id: str, provider: str) -> None:
    """Switch a tenant's active provider and persist the change. Takes
    effect on the very next get_itsm_client() call — no restart required."""
    if provider not in _VALID_PROVIDERS:
        raise ValueError(f"Unknown ITSM provider: {provider!r} (expected one of {_VALID_PROVIDERS})")

    async with _lock:
        await db.execute(
            sa_text("UPDATE platform_config SET itsm_provider = :provider WHERE tenant_id = :tid"),
            {"provider": provider, "tid": tenant_id},
        )
        await db.commit()
        _providers[tenant_id] = provider
    log.info("itsm_provider.changed", tenant_id=tenant_id, provider=provider)
