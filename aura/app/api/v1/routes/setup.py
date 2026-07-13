"""Setup wizard routes — all scoped to the calling admin's tenant.

GET  /setup/status          — returns setup_complete + current_wizard_step
POST /setup/test-jsm        — validate JSM credentials without saving
POST /setup/test-zendesk    — validate Zendesk credentials without saving
POST /setup/wizard/save     — persist one wizard step
GET  /setup/wizard/progress — all saved step data
POST /setup/complete        — mark setup as done, persist connection credentials
                               + branding + categories + users + thresholds
"""

import json
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.core.security import get_current_user, require_admin
from app.db.sqlite import get_db
from app.models.api_schemas import (
    JSMTestRequest,
    JSMTestResponse,
    OkResponse,
    SetupStatusResponse,
    WizardProgressResponse,
    WizardStepSave,
    ZendeskTestRequest,
    ZendeskTestResponse,
)

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatusResponse)
async def get_setup_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
) -> SetupStatusResponse:
    """"Is setup complete" is now a per-tenant question, so this requires
    authentication (any role — the frontend checks it right after login,
    not before, unlike the pre-multi-tenancy flow where this was a public
    endpoint checked before anyone logged in). master_admin has no tenant
    and never sees a wizard, so it always reports complete.
    """
    tenant_id = current_user.get("tenant_id")
    if tenant_id is None:
        return SetupStatusResponse(setup_complete=True, current_step=1)

    result = await db.execute(
        sa_text("SELECT setup_complete, current_wizard_step FROM platform_config WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    row = result.first()
    return SetupStatusResponse(
        setup_complete=bool(row[0]) if row else False,
        current_step=int(row[1]) if row else 1,
    )


@router.post("/test-jsm", response_model=JSMTestResponse)
async def test_jsm_connection(
    body: JSMTestRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> JSMTestResponse:
    """Test JSM credentials — on success, encrypt and persist them
    immediately to this tenant's platform_config row. The raw token never
    touches wizard_progress; the frontend doesn't send it to /wizard/save."""
    import httpx
    from base64 import b64encode

    from app.core.url_safety import UnsafeURLError, assert_safe_external_url
    from app.services.jsm_client import JSMClient

    url = body.base_url.rstrip("/")

    try:
        await assert_safe_external_url(url)
    except UnsafeURLError as exc:
        return JSMTestResponse(success=False, error=str(exc))

    token = b64encode(f"{body.user_email}:{body.api_token}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    project_key = body.project_key.strip().upper()

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            # Validate credentials — /myself is the most reliable auth check
            me = await client.get(f"{url}/rest/api/3/myself", headers=headers)
            me.raise_for_status()

        # Total ticket count in the project (any status) — a plain "yes,
        # we're really connected to your data" signal. Deliberately not
        # filtered to resolved/Done tickets: a project with no Done tickets
        # yet would otherwise show a misleading 0 here even though it's
        # fully reachable. Uses the same Agile board endpoint the real
        # ingestion pipeline (search_tickets()) already relies on — NOT
        # the classic /rest/api/3/search platform endpoint, which
        # Atlassian sunset in 2025 (now returns 410 Gone on Cloud).
        async with JSMClient(
            base_url=url, project_key=project_key,
            api_email=body.user_email, api_token=body.api_token,
        ) as jsm:
            ticket_count = await jsm.count_tickets()
    except Exception as exc:
        return JSMTestResponse(success=False, error=str(exc))

    tenant_id = current_user["tenant_id"]
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        sa_text(
            "UPDATE platform_config SET jsm_base_url = :base_url, jsm_project_key = :project_key, "
            "jsm_api_email = :user_email, jsm_api_token_encrypted = :token, updated_at = :now "
            "WHERE tenant_id = :tid"
        ),
        {
            "base_url": url,
            "project_key": body.project_key.strip().upper(),
            "user_email": body.user_email.strip(),
            "token": encrypt(body.api_token),
            "now": now,
            "tid": tenant_id,
        },
    )
    await db.commit()

    from app.services import itsm_provider_state
    from app.services.itsm_client import refresh_tenant_credentials
    await itsm_provider_state.set(db, tenant_id, "jira")
    await refresh_tenant_credentials(db, tenant_id)

    return JSMTestResponse(success=True, ticket_count=ticket_count)


@router.post("/test-zendesk", response_model=ZendeskTestResponse)
async def test_zendesk_connection(
    body: ZendeskTestRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> ZendeskTestResponse:
    """Test Zendesk credentials — on success, encrypt and persist them
    immediately to this tenant's platform_config row. The raw token never
    touches wizard_progress; the frontend doesn't send it to /wizard/save."""
    import httpx
    from base64 import b64encode

    from app.core.url_safety import UnsafeURLError, assert_safe_external_url

    subdomain = body.subdomain.strip().removeprefix("https://").removesuffix(".zendesk.com").rstrip("/")
    url = f"https://{subdomain}.zendesk.com"

    try:
        await assert_safe_external_url(url)
    except UnsafeURLError as exc:
        return ZendeskTestResponse(success=False, error=str(exc))

    token = b64encode(f"{body.api_email}/token:{body.api_token}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            resp = await client.get(f"{url}/api/v2/tickets/count.json", headers=headers)
            resp.raise_for_status()
            ticket_count = resp.json().get("count", {}).get("value", 0)
    except Exception as exc:
        return ZendeskTestResponse(success=False, error=str(exc))

    tenant_id = current_user["tenant_id"]
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        sa_text(
            "UPDATE platform_config SET zen_subdomain = :subdomain, zen_api_email = :api_email, "
            "zen_api_token_encrypted = :token, updated_at = :now WHERE tenant_id = :tid"
        ),
        {
            "subdomain": subdomain,
            "api_email": body.api_email.strip(),
            "token": encrypt(body.api_token),
            "now": now,
            "tid": tenant_id,
        },
    )
    await db.commit()

    from app.services import itsm_provider_state
    from app.services.itsm_client import refresh_tenant_credentials
    await itsm_provider_state.set(db, tenant_id, "zendesk")
    await refresh_tenant_credentials(db, tenant_id)

    return ZendeskTestResponse(success=True, ticket_count=ticket_count)


@router.post("/wizard/save", response_model=OkResponse)
async def save_wizard_step(
    body: WizardStepSave,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> OkResponse:
    tenant_id = current_user["tenant_id"]
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        sa_text(
            "INSERT INTO wizard_progress (tenant_id, step_number, step_data, saved_at) "
            "VALUES (:tenant, :step, :data, :now) "
            "ON CONFLICT(tenant_id, step_number) DO UPDATE SET step_data = excluded.step_data, saved_at = excluded.saved_at"
        ),
        {"tenant": tenant_id, "step": body.step, "data": json.dumps(body.data), "now": now},
    )
    await db.execute(
        sa_text(
            "UPDATE platform_config SET current_wizard_step = MAX(current_wizard_step, :step), "
            "updated_at = :now WHERE tenant_id = :tenant"
        ),
        {"step": body.step + 1, "now": now, "tenant": tenant_id},
    )
    return OkResponse()


@router.get("/wizard/progress", response_model=WizardProgressResponse)
async def get_wizard_progress(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> WizardProgressResponse:
    result = await db.execute(
        sa_text(
            "SELECT step_number, step_data FROM wizard_progress "
            "WHERE tenant_id = :tid ORDER BY step_number"
        ),
        {"tid": current_user["tenant_id"]},
    )
    steps: dict[int, dict[str, Any]] = {}
    for row in result.all():
        try:
            steps[row[0]] = json.loads(row[1])
        except (json.JSONDecodeError, TypeError):
            steps[row[0]] = {}
    return WizardProgressResponse(steps=steps)


@router.post("/complete", response_model=OkResponse)
async def complete_setup(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> OkResponse:
    import uuid as _uuid
    from app.core.security import hash_password

    tenant_id = current_user["tenant_id"]
    now = datetime.now(timezone.utc).isoformat()

    # Load all saved wizard steps
    result = await db.execute(
        sa_text("SELECT step_number, step_data FROM wizard_progress WHERE tenant_id = :tid ORDER BY step_number"),
        {"tid": tenant_id},
    )
    steps: dict[int, dict] = {}
    for row in result.all():
        try:
            steps[row[0]] = json.loads(row[1])
        except (json.JSONDecodeError, TypeError):
            steps[row[0]] = {}

    # Step 2 (provider choice) and step 4 (connection credentials) are no
    # longer handled here — /setup/test-jsm and /setup/test-zendesk persist
    # both the encrypted credentials and the active provider immediately on
    # a successful test, so there's nothing left to read from wizard_progress
    # (the raw token is never sent to /wizard/save in the first place).

    # Step 3 → company branding (wrapped so a missing column never blocks launch)
    step2 = steps.get(3, {})
    if step2:
        branding_fields: list[str] = []
        branding_params: dict = {"now": now}
        if step2.get("company_name"):
            branding_fields.append("company_name = :company_name")
            branding_params["company_name"] = str(step2["company_name"])
        if step2.get("company_logo"):
            branding_fields.append("company_logo = :company_logo")
            branding_params["company_logo"] = str(step2["company_logo"])
        if step2.get("accent_color"):
            branding_fields.append("accent_color = :accent_color")
            branding_params["accent_color"] = str(step2["accent_color"])
        if branding_fields:
            branding_fields.append("updated_at = :now")
            try:
                await db.execute(
                    sa_text(f"UPDATE platform_config SET {', '.join(branding_fields)} WHERE tenant_id = :tid_"),
                    {**branding_params, "tid_": tenant_id},
                )
            except Exception:
                pass  # columns not yet migrated — branding can be set post-launch

    # Step 5 → category_config (INSERT OR IGNORE to stay idempotent)
    step3 = steps.get(5, {})
    for cat in step3.get("categories", []):
        name = str(cat.get("name", "")).strip()
        if not name:
            continue
        await db.execute(
            sa_text(
                "INSERT OR IGNORE INTO category_config "
                "(category_id, tenant_id, name, auto_comment_enabled, sla_minutes, team_id, created_at, updated_at) "
                "VALUES (:id, :tenant, :name, :enabled, :sla, :team, :now, :now)"
            ),
            {
                "id": str(_uuid.uuid4()),
                "tenant": tenant_id,
                "name": name,
                "enabled": int(bool(cat.get("auto_comment_enabled", False))),
                "sla": int(cat.get("sla_minutes", 480)),
                "team": "",
                "now": now,
            },
        )

    # Step 6 → users (INSERT OR IGNORE to stay idempotent)
    step4 = steps.get(6, {})
    for user in step4.get("users", []):
        email = str(user.get("email", "")).strip().lower()
        if not email:
            continue
        await db.execute(
            sa_text(
                "INSERT OR IGNORE INTO users "
                "(user_id, tenant_id, email, display_name, hashed_password, role, created_at) "
                "VALUES (:uid, :tenant, :email, :name, :pw, :role, :now)"
            ),
            {
                "uid": str(_uuid.uuid4()),
                "tenant": tenant_id,
                "email": email,
                "name": str(user.get("display_name", email)),
                "pw": hash_password(str(user.get("password", ""))),
                "role": str(user.get("role", "technician")),
                "now": now,
            },
        )

    # Step 7 → platform_config thresholds
    step5 = steps.get(7, {})
    if step5:
        fields: list[str] = []
        params: dict = {"now": now}
        mapping = {
            "confidence_threshold":            "confidence_threshold",
            "abstention_threshold":            "abstention_threshold",
            "conversation_idle_timeout_hours": "conversation_idle_timeout_hours",
            "polling_interval_minutes":        "polling_interval_minutes",
            "collision_timeout_minutes":       "collision_timeout_minutes",
        }
        for wizard_key, col in mapping.items():
            if wizard_key in step5:
                fields.append(f"{col} = :{col}")
                params[col] = step5[wizard_key]
        if fields:
            fields.append("updated_at = :now")
            await db.execute(
                sa_text(f"UPDATE platform_config SET {', '.join(fields)} WHERE tenant_id = :tid_"),
                {**params, "tid_": tenant_id},
            )

    # Mark setup complete
    await db.execute(
        sa_text("UPDATE platform_config SET setup_complete = 1, updated_at = :now WHERE tenant_id = :tid"),
        {"now": now, "tid": tenant_id},
    )
    await db.commit()
    return OkResponse()
