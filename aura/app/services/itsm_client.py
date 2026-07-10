"""Provider-agnostic ITSM client interface + factory.

`ITSMClient` documents the exact method surface every concrete client
(JSMClient, ZendeskClient, ...) must provide — the 10 methods actually
called from outside their own client module today. It's a `Protocol`, not a
base class: JSMClient predates this file and already satisfies it
structurally, no inheritance needed.

`get_itsm_client(tenant_id)` is the single choke point everything else
should import instead of constructing `JSMClient()`/`ZendeskClient()`
directly — it reads that tenant's active provider + decrypted credentials
from an in-process cache (populated from platform_config, mirroring
kill_switch.py / itsm_provider_state.py's shape) so this stays a synchronous,
non-blocking call on the hot path, and validates the required credential
fields are present before handing back a client.
"""

import asyncio
from datetime import datetime
from typing import Protocol

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt
from app.core.logging import get_logger
from app.models.itsm import ITSMTicket
from app.services import itsm_provider_state

log = get_logger(__name__)


class ITSMClient(Protocol):
    async def __aenter__(self) -> "ITSMClient": ...
    async def __aexit__(self, *exc: object) -> None: ...

    async def search_tickets(self, since: datetime | None = None) -> list[ITSMTicket]: ...
    async def get_ticket(self, ticket_id: str) -> ITSMTicket | None: ...
    async def search_open_tickets(self, since: datetime | None = None) -> list[ITSMTicket]: ...
    async def post_comment_markdown(self, ticket_id: str, body_markdown: str) -> str: ...
    async def delete_comment(self, ticket_id: str, comment_id: str) -> bool: ...  # False = not supported by this provider, no-op
    async def assign_ticket(self, ticket_id: str, account_id: str) -> None: ...
    async def find_transition_id(self, ticket_id: str, target_status_name: str) -> str | None: ...
    async def transition_issue(self, ticket_id: str, transition_id: str) -> None: ...
    async def find_account_id_by_email(self, email: str) -> str | None: ...
    async def create_ticket(self, summary: str, description: str) -> str: ...


# In-process cache of each tenant's DECRYPTED credentials, keyed by
# tenant_id. Populated at startup (init_itsm_credentials) and refreshed
# whenever a tenant's connection is saved (setup wizard / admin config) —
# see refresh_tenant_credentials(). Never persisted outside this process;
# the encrypted form is what lives in the DB.
_credentials: dict[str, dict[str, str | None]] = {}
_lock = asyncio.Lock()

_CREDENTIAL_COLUMNS = (
    "jsm_base_url", "jsm_project_key", "jsm_api_email", "jsm_api_token_encrypted",
    "zen_subdomain", "zen_api_email", "zen_api_token_encrypted",
)

_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "jira": ("jsm_base_url", "jsm_project_key", "jsm_api_email", "jsm_api_token"),
    "zendesk": ("zen_subdomain", "zen_api_email", "zen_api_token"),
}


def _decrypt_row(row) -> dict[str, str | None]:
    return {
        "jsm_base_url": row["jsm_base_url"],
        "jsm_project_key": row["jsm_project_key"],
        "jsm_api_email": row["jsm_api_email"],
        "jsm_api_token": decrypt(row["jsm_api_token_encrypted"]),
        "zen_subdomain": row["zen_subdomain"],
        "zen_api_email": row["zen_api_email"],
        "zen_api_token": decrypt(row["zen_api_token_encrypted"]),
    }


async def init_itsm_credentials(db: AsyncSession) -> None:
    """Load every tenant's decrypted credentials into the in-process cache.
    Call once from the FastAPI lifespan after `init_db()`.
    """
    global _credentials
    result = await db.execute(
        sa_text(f"SELECT tenant_id, {', '.join(_CREDENTIAL_COLUMNS)} FROM platform_config")
    )
    async with _lock:
        _credentials = {row.tenant_id: _decrypt_row(row._mapping) for row in result}
    log.info("itsm_credentials.loaded", tenant_count=len(_credentials))


async def refresh_tenant_credentials(db: AsyncSession, tenant_id: str) -> None:
    """Re-read one tenant's row and update the cache — call after any write
    to that tenant's jsm_*/zen_* columns (wizard connection step, admin
    config update) so get_itsm_client() picks up the change immediately."""
    result = await db.execute(
        sa_text(
            f"SELECT {', '.join(_CREDENTIAL_COLUMNS)} FROM platform_config WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return
    async with _lock:
        _credentials[tenant_id] = _decrypt_row(row)
    log.info("itsm_credentials.refreshed", tenant_id=tenant_id)


def get_itsm_client(tenant_id: str) -> ITSMClient:
    """Return a not-yet-entered client for this tenant's active provider —
    use as `async with get_itsm_client(tenant_id) as itsm: ...`.
    """
    provider = itsm_provider_state.get(tenant_id)
    creds = _credentials.get(tenant_id, {})

    missing = [f for f in _REQUIRED_FIELDS[provider] if not creds.get(f)]
    if missing:
        raise RuntimeError(
            f"ITSM provider '{provider}' is selected for tenant {tenant_id!r} but not "
            f"configured — missing: {', '.join(missing)}. Complete the Setup Wizard's "
            f"connection step for this tenant."
        )

    if provider == "zendesk":
        from app.services.zendesk_client import ZendeskClient
        return ZendeskClient(
            subdomain=creds["zen_subdomain"],
            api_email=creds["zen_api_email"],
            api_token=creds["zen_api_token"],
        )

    from app.services.jsm_client import JSMClient
    return JSMClient(
        base_url=creds["jsm_base_url"],
        project_key=creds["jsm_project_key"],
        api_email=creds["jsm_api_email"],
        api_token=creds["jsm_api_token"],
    )
