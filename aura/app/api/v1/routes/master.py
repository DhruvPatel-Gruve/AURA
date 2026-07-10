"""Master admin routes — tenant provisioning only.

GET   /master/tenants                          — list every tenant
POST  /master/tenants                          — create a tenant + seed its first admin
PATCH /master/tenants/{tenant_id}               — rename / suspend / reactivate
POST  /master/tenants/{tenant_id}/reset-admin   — issue a new temporary password
                                                   for that tenant's admin account

Deliberately the entire master_admin surface — no ticket/audit/SLA data is
ever exposed here, matching the "sole purpose is account/tenant provisioning"
scope. master_admin has no tenant_id of its own, so none of these routes
take one from the caller — tenant_id is always the path/body parameter
identifying which *tenant's* account is being managed.
"""

import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, require_master_admin
from app.db.sqlite import get_db
from app.models.api_schemas import (
    ResetTenantAdminResponse,
    TenantCreate,
    TenantCreateResponse,
    TenantSummary,
    TenantUpdate,
)

router = APIRouter(prefix="/master", tags=["master"])

_NOW = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731


def _generate_temp_password() -> str:
    """URL-safe, human-typeable-enough temporary password — the master admin
    hands this to the client once; there is no way to retrieve it again
    after this response (only bcrypt hashes are stored)."""
    return secrets.token_urlsafe(12)


async def _row_to_summary(db: AsyncSession, row) -> TenantSummary:
    admin_row = (await db.execute(
        sa_text(
            "SELECT email FROM users WHERE tenant_id = :tid AND role = 'admin' "
            "ORDER BY created_at ASC LIMIT 1"
        ),
        {"tid": row["tenant_id"]},
    )).first()
    user_count = (await db.execute(
        sa_text("SELECT COUNT(*) FROM users WHERE tenant_id = :tid"),
        {"tid": row["tenant_id"]},
    )).scalar() or 0
    # itsm_provider comes from platform_config, not tenants — that's the row
    # the Setup Wizard actually updates when the tenant's admin picks a
    # provider, so this reflects the real, current choice (or the harmless
    # 'jira' placeholder default before they've completed that step).
    config_row = (await db.execute(
        sa_text("SELECT setup_complete, itsm_provider FROM platform_config WHERE tenant_id = :tid"),
        {"tid": row["tenant_id"]},
    )).first()

    return TenantSummary(
        tenant_id=row["tenant_id"],
        name=row["name"],
        status=row["status"],
        itsm_provider=config_row[1] if config_row else row["itsm_provider"],
        created_at=datetime.fromisoformat(row["created_at"]),
        admin_email=admin_row[0] if admin_row else None,
        user_count=user_count,
        setup_complete=bool(config_row[0]) if config_row else False,
    )


@router.get("/tenants", response_model=list[TenantSummary])
async def list_tenants(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[dict, Depends(require_master_admin)],
) -> list[TenantSummary]:
    rows = (await db.execute(
        sa_text("SELECT tenant_id, name, status, itsm_provider, created_at FROM tenants ORDER BY created_at DESC")
    )).mappings().all()
    return [await _row_to_summary(db, r) for r in rows]


@router.post("/tenants", response_model=TenantCreateResponse, status_code=201)
async def create_tenant(
    body: TenantCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[dict, Depends(require_master_admin)],
) -> TenantCreateResponse:
    now = _NOW()
    tenant_id = str(uuid.uuid4())
    admin_email = body.admin_email.lower().strip()

    existing = (await db.execute(
        sa_text("SELECT 1 FROM users WHERE email = :email"), {"email": admin_email},
    )).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered to another account")

    # itsm_provider is left at its schema default ('jira') on both rows —
    # the tenant's own admin picks the real provider (and enters its
    # credentials) in the Setup Wizard's connection step.
    await db.execute(
        sa_text(
            "INSERT INTO tenants (tenant_id, name, status, created_at, updated_at) "
            "VALUES (:tid, :name, 'active', :now, :now)"
        ),
        {"tid": tenant_id, "name": body.name.strip(), "now": now},
    )
    await db.execute(
        sa_text("INSERT INTO platform_config (tenant_id, updated_at) VALUES (:tid, :now)"),
        {"tid": tenant_id, "now": now},
    )

    temp_password = _generate_temp_password()
    admin_user_id = str(uuid.uuid4())
    await db.execute(
        sa_text(
            "INSERT INTO users (user_id, tenant_id, email, display_name, hashed_password, role, created_at) "
            "VALUES (:uid, :tid, :email, :name, :pw, 'admin', :now)"
        ),
        {
            "uid": admin_user_id, "tid": tenant_id, "email": admin_email,
            "name": body.admin_display_name.strip(), "pw": hash_password(temp_password), "now": now,
        },
    )
    await db.commit()

    # Warm the (still-empty) credentials cache immediately — otherwise the
    # first get_itsm_client() call for this tenant would miss until the next
    # process restart. No provider to cache yet; itsm_provider_state.get()
    # already defaults an unknown tenant_id to 'jira' until the wizard picks.
    from app.services.itsm_client import refresh_tenant_credentials
    await refresh_tenant_credentials(db, tenant_id)

    row = (await db.execute(
        sa_text("SELECT tenant_id, name, status, itsm_provider, created_at FROM tenants WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )).mappings().first()

    return TenantCreateResponse(
        tenant=await _row_to_summary(db, row),
        admin_email=admin_email,
        temporary_password=temp_password,
    )


@router.patch("/tenants/{tenant_id}", response_model=TenantSummary)
async def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[dict, Depends(require_master_admin)],
) -> TenantSummary:
    updates: list[str] = []
    params: dict = {"tid": tenant_id, "now": _NOW()}
    if body.name is not None:
        updates.append("name = :name")
        params["name"] = body.name.strip()
    if body.status is not None:
        updates.append("status = :status")
        params["status"] = body.status
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")
    updates.append("updated_at = :now")

    result = await db.execute(
        sa_text(f"UPDATE tenants SET {', '.join(updates)} WHERE tenant_id = :tid"), params,
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await db.commit()

    row = (await db.execute(
        sa_text("SELECT tenant_id, name, status, itsm_provider, created_at FROM tenants WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )).mappings().first()
    return await _row_to_summary(db, row)


@router.post("/tenants/{tenant_id}/reset-admin", response_model=ResetTenantAdminResponse)
async def reset_tenant_admin_password(
    tenant_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[dict, Depends(require_master_admin)],
) -> ResetTenantAdminResponse:
    """Issue a fresh temporary password for this tenant's earliest-created
    admin account — for when a client has locked themselves out and has no
    other admin to reset it for them."""
    admin_row = (await db.execute(
        sa_text(
            "SELECT user_id, email FROM users WHERE tenant_id = :tid AND role = 'admin' "
            "ORDER BY created_at ASC LIMIT 1"
        ),
        {"tid": tenant_id},
    )).first()
    if admin_row is None:
        raise HTTPException(status_code=404, detail="This tenant has no admin account to reset")

    temp_password = _generate_temp_password()
    await db.execute(
        sa_text("UPDATE users SET hashed_password = :pw WHERE user_id = :uid"),
        {"pw": hash_password(temp_password), "uid": admin_row[0]},
    )
    await db.commit()

    return ResetTenantAdminResponse(admin_email=admin_row[1], temporary_password=temp_password)
