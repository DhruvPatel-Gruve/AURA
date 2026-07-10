"""Tests for itsm_provider_state + get_itsm_client — each tenant's provider
choice must switch without a restart, and get_itsm_client() must validate
that tenant's required credential fields before handing back a client."""

import pytest
from sqlalchemy import text as sa_text

from app.core.crypto import encrypt
from app.services import itsm_provider_state
from app.services.itsm_client import get_itsm_client, init_itsm_credentials, refresh_tenant_credentials
from app.services.jsm_client import JSMClient
from app.services.zendesk_client import ZendeskClient


@pytest.fixture(autouse=True)
async def _reset_provider_cache(db_session, seeded_tenant):
    await itsm_provider_state.set(db_session, seeded_tenant, "jira")
    yield


async def _seed_jira_credentials(db_session, tenant_id: str) -> None:
    await db_session.execute(
        sa_text(
            "UPDATE platform_config SET jsm_base_url = 'https://x.atlassian.net', "
            "jsm_project_key = 'IT', jsm_api_email = 'a@b.com', "
            "jsm_api_token_encrypted = :tok WHERE tenant_id = :tid"
        ),
        {"tok": encrypt("tok"), "tid": tenant_id},
    )
    await db_session.commit()
    await refresh_tenant_credentials(db_session, tenant_id)


async def test_init_loads_persisted_provider(db_session, seeded_tenant):
    await db_session.execute(
        sa_text("UPDATE platform_config SET itsm_provider = 'zendesk' WHERE tenant_id = :tid"),
        {"tid": seeded_tenant},
    )
    await db_session.commit()

    await itsm_provider_state.init_itsm_provider(db_session)

    assert itsm_provider_state.get(seeded_tenant) == "zendesk"


async def test_set_switches_provider_without_restart(db_session, seeded_tenant):
    await _seed_jira_credentials(db_session, seeded_tenant)
    assert isinstance(get_itsm_client(seeded_tenant), JSMClient)

    await itsm_provider_state.set(db_session, seeded_tenant, "zendesk")
    await db_session.execute(
        sa_text(
            "UPDATE platform_config SET zen_subdomain = 'x', zen_api_email = 'a@b.com', "
            "zen_api_token_encrypted = :tok WHERE tenant_id = :tid"
        ),
        {"tok": encrypt("tok"), "tid": seeded_tenant},
    )
    await db_session.commit()
    await refresh_tenant_credentials(db_session, seeded_tenant)

    assert itsm_provider_state.get(seeded_tenant) == "zendesk"
    assert isinstance(get_itsm_client(seeded_tenant), ZendeskClient)


async def test_set_rejects_unknown_provider(db_session, seeded_tenant):
    with pytest.raises(ValueError, match="Unknown ITSM provider"):
        await itsm_provider_state.set(db_session, seeded_tenant, "servicenow")


async def test_get_itsm_client_raises_when_active_provider_misconfigured(db_session, seeded_tenant):
    await itsm_provider_state.set(db_session, seeded_tenant, "zendesk")
    # No zen_* credentials were ever seeded for this tenant — cache stays empty.
    await init_itsm_credentials(db_session)

    with pytest.raises(RuntimeError, match="ZEN_SUBDOMAIN|zen_subdomain"):
        get_itsm_client(seeded_tenant)
