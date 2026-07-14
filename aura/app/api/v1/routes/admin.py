"""Admin routes — restricted to role=admin, scoped to that admin's tenant.

Kill switch:    GET/POST /admin/kill-switch/enable|disable
Users CRUD:     GET|POST /admin/users, PATCH|DELETE /admin/users/{user_id}
Categories:     GET|POST /admin/categories, PATCH|DELETE /admin/categories/{id}
Rollback:       GET /admin/rollback, POST /admin/rollback/{action_id}/execute
Qdrant stats:   GET /admin/qdrant/stats
Audit:          GET /admin/audit-log, GET /admin/audit-log/export
"""

import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, require_admin, require_any_auth, require_manager
from app.db.sqlite import get_db
from app.models.api_schemas import (
    BrandingResponse,
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    DocumentListResponse,
    DocumentSummary,
    KillSwitchStatusResponse,
    OkResponse,
    PlatformConfigResponse,
    PlatformConfigUpdate,
    QdrantStatsResponse,
    ResetUserPasswordResponse,
    RollbackResponse,
    UserCreate,
    UserPublic,
    UserUpdate,
)
from app.services import audit_logger, kill_switch, rollback_store
from app.services.ai_config_service import get_ai_config
from app.services.notification_bus import notification_bus

router = APIRouter(prefix="/admin", tags=["admin"])

_NOW = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731


def _db_role(role: str) -> str:
    """Normalize frontend role to DB role (enduser → end_user)."""
    return "end_user" if role == "enduser" else role


def _api_role(role: str) -> str:
    """Normalize DB role to API role (end_user → enduser)."""
    return "enduser" if role == "end_user" else role


# ── Platform config ───────────────────────────────────────────────────────────

@router.get("/config", response_model=PlatformConfigResponse)
async def get_config(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> PlatformConfigResponse:
    result = await db.execute(
        sa_text(
            "SELECT aura_enabled, itsm_provider, confidence_threshold, abstention_threshold, "
            "       conversation_idle_timeout_hours, polling_interval_minutes, ingestion_interval_hours, "
            "       collision_timeout_minutes, assignment_timeout_minutes, "
            "       last_poll_timestamp, last_sync_timestamp, "
            "       setup_complete, current_wizard_step, "
            "       kill_switch_changed_by, kill_switch_changed_at, "
            "       company_name, company_logo, accent_color, "
            "       jsm_base_url, jsm_project_key, zen_subdomain, "
            "       embedding_provider, embedding_base_url, embedding_model, embedding_vector_size, "
            "       llm_base_url, llm_model "
            "FROM platform_config WHERE tenant_id = :tid"
        ),
        {"tid": current_user["tenant_id"]},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Platform config not initialised")
    ai_config = get_ai_config(current_user["tenant_id"])
    return PlatformConfigResponse(
        aura_enabled=bool(row["aura_enabled"]),
        itsm_provider=row["itsm_provider"],
        confidence_threshold=row["confidence_threshold"],
        abstention_threshold=row["abstention_threshold"],
        conversation_idle_timeout_hours=row["conversation_idle_timeout_hours"],
        polling_interval_minutes=row["polling_interval_minutes"],
        ingestion_interval_hours=row["ingestion_interval_hours"],
        collision_timeout_minutes=row["collision_timeout_minutes"],
        assignment_timeout_minutes=row["assignment_timeout_minutes"],
        last_poll_timestamp=datetime.fromisoformat(row["last_poll_timestamp"]) if row["last_poll_timestamp"] else None,
        last_sync_timestamp=datetime.fromisoformat(row["last_sync_timestamp"]) if row["last_sync_timestamp"] else None,
        setup_complete=bool(row["setup_complete"]),
        current_wizard_step=row["current_wizard_step"],
        kill_switch_changed_by=row["kill_switch_changed_by"],
        kill_switch_changed_at=datetime.fromisoformat(row["kill_switch_changed_at"]) if row["kill_switch_changed_at"] else None,
        company_name=row["company_name"],
        company_logo=row["company_logo"],
        accent_color=row["accent_color"],
        jsm_base_url=row["jsm_base_url"],
        jsm_project_key=row["jsm_project_key"],
        zen_subdomain=row["zen_subdomain"],
        embedding_provider=row["embedding_provider"],
        embedding_base_url=row["embedding_base_url"],
        embedding_model=row["embedding_model"],
        embedding_vector_size=row["embedding_vector_size"],
        embedding_configured=ai_config.embeddings_configured,
        llm_base_url=row["llm_base_url"],
        llm_model=row["llm_model"],
        llm_configured=ai_config.llm_configured,
    )


# ── Public branding endpoint (any authenticated user) ─────────────────────────

@router.get("/branding", response_model=BrandingResponse)
async def get_branding(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_any_auth)],
) -> BrandingResponse:
    result = await db.execute(
        sa_text("SELECT company_name, company_logo, accent_color, itsm_provider FROM platform_config WHERE tenant_id = :tid"),
        {"tid": current_user["tenant_id"]},
    )
    row = result.mappings().first()
    if not row:
        return BrandingResponse()
    return BrandingResponse(
        company_name=row["company_name"],
        company_logo=row["company_logo"],
        accent_color=row["accent_color"],
        itsm_provider=row["itsm_provider"] or "jira",
    )


@router.put("/config", response_model=PlatformConfigResponse)
async def update_config(
    body: PlatformConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> PlatformConfigResponse:
    tenant_id = current_user["tenant_id"]
    updates: list[str] = []
    params: dict = {"now": _NOW()}

    if body.confidence_threshold is not None:
        updates.append("confidence_threshold = :confidence_threshold")
        params["confidence_threshold"] = body.confidence_threshold
    if body.abstention_threshold is not None:
        updates.append("abstention_threshold = :abstention_threshold")
        params["abstention_threshold"] = body.abstention_threshold
    if body.conversation_idle_timeout_hours is not None:
        updates.append("conversation_idle_timeout_hours = :conversation_idle_timeout_hours")
        params["conversation_idle_timeout_hours"] = body.conversation_idle_timeout_hours
    if body.polling_interval_minutes is not None:
        updates.append("polling_interval_minutes = :polling_interval_minutes")
        params["polling_interval_minutes"] = body.polling_interval_minutes
    if body.ingestion_interval_hours is not None:
        updates.append("ingestion_interval_hours = :ingestion_interval_hours")
        params["ingestion_interval_hours"] = body.ingestion_interval_hours
    if body.collision_timeout_minutes is not None:
        updates.append("collision_timeout_minutes = :collision_timeout_minutes")
        params["collision_timeout_minutes"] = body.collision_timeout_minutes
    if body.assignment_timeout_minutes is not None:
        updates.append("assignment_timeout_minutes = :assignment_timeout_minutes")
        params["assignment_timeout_minutes"] = body.assignment_timeout_minutes

    if updates:
        updates.append("updated_at = :now")
        params["tid"] = tenant_id
        await db.execute(
            sa_text(f"UPDATE platform_config SET {', '.join(updates)} WHERE tenant_id = :tid"),
            params,
        )
        await db.commit()

    # NOTE: polling_interval_minutes / ingestion_interval_hours are stored
    # per-tenant but no longer drive a live APScheduler reschedule — the
    # jsm_poller / ingestion_sync jobs are single global jobs that loop over
    # every tenant on one shared cadence (see scheduler/jobs/*.py), so
    # rescheduling them from one tenant's preference would silently change
    # every other tenant's polling cadence too. These values are effectively
    # advisory/display-only until per-tenant scheduling is built.

    return await get_config(db, current_user)


# ── Kill switch ───────────────────────────────────────────────────────────────

@router.get("/kill-switch", response_model=KillSwitchStatusResponse)
async def get_kill_switch(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> KillSwitchStatusResponse:
    status = await kill_switch.get_status(db, current_user["tenant_id"])
    return KillSwitchStatusResponse(
        enabled=status["enabled"],
        changed_at=datetime.fromisoformat(status["changed_at"]) if status.get("changed_at") else None,
        changed_by=status.get("changed_by"),
    )


@router.post("/kill-switch/enable", response_model=KillSwitchStatusResponse)
async def enable_kill_switch(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> KillSwitchStatusResponse:
    await kill_switch.enable(db, current_user["tenant_id"], changed_by=current_user["user_id"])
    return await get_kill_switch(db, current_user)


@router.post("/kill-switch/disable", response_model=KillSwitchStatusResponse)
async def disable_kill_switch(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> KillSwitchStatusResponse:
    await kill_switch.disable(db, current_user["tenant_id"], changed_by=current_user["user_id"])
    return await get_kill_switch(db, current_user)


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserPublic])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> list[UserPublic]:
    result = await db.execute(
        sa_text(
            "SELECT user_id, email, display_name, role, team_id, is_active, last_login, jira_account_id "
            "FROM users WHERE tenant_id = :tid ORDER BY created_at DESC"
        ),
        {"tid": current_user["tenant_id"]},
    )
    return [
        UserPublic(
            user_id=r["user_id"],
            email=r["email"],
            display_name=r["display_name"],
            role=_api_role(r["role"]),
            team_id=r["team_id"],
            is_active=bool(r["is_active"]),
            last_login=datetime.fromisoformat(r["last_login"]) if r["last_login"] else None,
            jira_account_id=r["jira_account_id"],
        )
        for r in result.mappings()
    ]


@router.post("/users", response_model=UserPublic, status_code=201)
async def create_user(
    body: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> UserPublic:
    tenant_id = current_user["tenant_id"]

    # Email is globally unique (not per-tenant) — login resolves a user by
    # email alone with no tenant context yet, so two tenants can never share one.
    existing = await db.execute(
        sa_text("SELECT 1 FROM users WHERE email = :email"),
        {"email": body.email.lower()},
    )
    if existing.first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user_id = str(uuid.uuid4())
    now = _NOW()
    await db.execute(
        sa_text(
            "INSERT INTO users (user_id, tenant_id, email, display_name, hashed_password, role, team_id, jira_account_id, created_at) "
            "VALUES (:uid, :tenant, :email, :name, :pw, :role, :team, :jira_account_id, :now)"
        ),
        {
            "uid": user_id,
            "tenant": tenant_id,
            "email": body.email.lower(),
            "name": body.display_name,
            "pw": hash_password(body.password),
            "role": _db_role(body.role),
            "team": body.team_id,
            "jira_account_id": body.jira_account_id,
            "now": now,
        },
    )
    return UserPublic(
        user_id=user_id,
        email=body.email.lower(),
        display_name=body.display_name,
        role=_api_role(_db_role(body.role)),
        team_id=body.team_id,
        is_active=True,
        jira_account_id=body.jira_account_id,
    )


@router.patch("/users/{user_id}", response_model=UserPublic)
async def update_user(
    user_id: str,
    body: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> UserPublic:
    tenant_id = current_user["tenant_id"]
    updates: list[str] = []
    params: dict = {"uid": user_id, "tenant": tenant_id}

    if body.email is not None:
        new_email = body.email.lower()
        existing = await db.execute(
            sa_text("SELECT 1 FROM users WHERE email = :email AND user_id != :uid"),
            {"email": new_email, "uid": user_id},
        )
        if existing.first():
            raise HTTPException(status_code=409, detail="Email already registered")
        updates.append("email = :email")
        params["email"] = new_email
        # A changed email may belong to a different real Jira account than
        # whatever was previously cached — clear it so assignment_node
        # re-resolves by the new email instead of assigning the wrong person,
        # unless the caller explicitly provided a new jira_account_id too.
        if body.jira_account_id is None:
            updates.append("jira_account_id = NULL")
    if body.password is not None:
        updates.append("hashed_password = :hashed_password")
        params["hashed_password"] = hash_password(body.password)
    if body.display_name is not None:
        updates.append("display_name = :display_name")
        params["display_name"] = body.display_name
    if body.role is not None:
        updates.append("role = :role")
        params["role"] = _db_role(body.role)
    if body.team_id is not None:
        updates.append("team_id = :team_id")
        params["team_id"] = body.team_id
    if body.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = int(body.is_active)
    if body.jira_account_id is not None:
        updates.append("jira_account_id = :jira_account_id")
        params["jira_account_id"] = body.jira_account_id

    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    result = await db.execute(
        sa_text(f"UPDATE users SET {', '.join(updates)} WHERE user_id = :uid AND tenant_id = :tenant"),
        params,
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        sa_text(
            "SELECT user_id, email, display_name, role, team_id, is_active, last_login, jira_account_id "
            "FROM users WHERE user_id = :uid"
        ),
        {"uid": user_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    # The edited user may be logged in right now with the old display_name/
    # email/role cached in their frontend session — push the fresh values so
    # their own UI updates live instead of staying stale until next login.
    await notification_bus.send_to_user(
        user_id,
        "USER_UPDATED",
        {
            "user_id": row["user_id"],
            "display_name": row["display_name"],
            "email": row["email"],
            "role": _api_role(row["role"]),
            "team_id": row["team_id"],
        },
    )

    return UserPublic(
        user_id=row["user_id"],
        email=row["email"],
        display_name=row["display_name"],
        role=_api_role(row["role"]),
        team_id=row["team_id"],
        is_active=bool(row["is_active"]),
        last_login=datetime.fromisoformat(row["last_login"]) if row["last_login"] else None,
        jira_account_id=row["jira_account_id"],
    )


@router.delete("/users/{user_id}", response_model=OkResponse)
async def delete_user(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> OkResponse:
    if user_id == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    result = await db.execute(
        sa_text("DELETE FROM users WHERE user_id = :uid AND tenant_id = :tenant"),
        {"uid": user_id, "tenant": current_user["tenant_id"]},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return OkResponse()


@router.post("/users/{user_id}/reset-password", response_model=ResetUserPasswordResponse)
async def reset_user_password(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> ResetUserPasswordResponse:
    """Issue a fresh one-time temporary password for a user in this tenant.

    There is no way to recover a user's actual password — it's stored as a
    bcrypt hash, never reversible — so this is the only way an admin can get
    someone back into a locked-out account: overwrite it with a new one and
    hand it to them directly.
    """
    row = (await db.execute(
        sa_text("SELECT email FROM users WHERE user_id = :uid AND tenant_id = :tenant"),
        {"uid": user_id, "tenant": current_user["tenant_id"]},
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    temp_password = secrets.token_urlsafe(12)
    await db.execute(
        sa_text("UPDATE users SET hashed_password = :pw WHERE user_id = :uid"),
        {"pw": hash_password(temp_password), "uid": user_id},
    )
    # Revoke this user's sessions — same hygiene as the self-service
    # change-password endpoint, so a stolen/shared session doesn't survive
    # a reset intended to lock someone else out.
    await db.execute(
        sa_text("UPDATE sessions SET revoked = 1 WHERE user_id = :uid"),
        {"uid": user_id},
    )

    return ResetUserPasswordResponse(email=row[0], temporary_password=temp_password)


# ── Categories ────────────────────────────────────────────────────────────────

@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
) -> list[CategoryResponse]:
    result = await db.execute(
        sa_text(
            "SELECT category_id, name, auto_comment_enabled, sla_minutes, team_id "
            "FROM category_config WHERE tenant_id = :tid ORDER BY name"
        ),
        {"tid": current_user["tenant_id"]},
    )
    return [
        CategoryResponse(**{**dict(r), "auto_comment_enabled": bool(r["auto_comment_enabled"])})
        for r in result.mappings()
    ]


@router.post("/categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    body: CategoryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> CategoryResponse:
    cat_id = str(uuid.uuid4())
    try:
        await db.execute(
            sa_text(
                "INSERT INTO category_config (category_id, tenant_id, name, auto_comment_enabled, sla_minutes, team_id, created_at, updated_at) "
                "VALUES (:id, :tenant, :name, :enabled, :sla, :team, :now, :now)"
            ),
            {"id": cat_id, "tenant": current_user["tenant_id"], "name": body.name, "enabled": int(body.auto_comment_enabled),
             "sla": body.sla_minutes, "team": body.team_id, "now": _NOW()},
        )
    except Exception:
        raise HTTPException(status_code=409, detail=f"Category '{body.name}' already exists")
    return CategoryResponse(
        category_id=cat_id, name=body.name, auto_comment_enabled=body.auto_comment_enabled,
        sla_minutes=body.sla_minutes, team_id=body.team_id,
    )


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    body: CategoryUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> CategoryResponse:
    updates: list[str] = []
    params: dict = {"cid": category_id, "tenant": current_user["tenant_id"]}

    if body.name is not None:
        updates.append("name = :name"); params["name"] = body.name
    if body.auto_comment_enabled is not None:
        updates.append("auto_comment_enabled = :enabled"); params["enabled"] = int(body.auto_comment_enabled)
    if body.sla_minutes is not None:
        updates.append("sla_minutes = :sla"); params["sla"] = body.sla_minutes
    if body.team_id is not None:
        updates.append("team_id = :team"); params["team"] = body.team_id

    if updates:
        result = await db.execute(
            sa_text(f"UPDATE category_config SET {', '.join(updates)} WHERE category_id = :cid AND tenant_id = :tenant"),
            params,
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Category not found")

    result = await db.execute(
        sa_text(
            "SELECT category_id, name, auto_comment_enabled, sla_minutes, team_id "
            "FROM category_config WHERE category_id = :cid AND tenant_id = :tenant"
        ),
        {"cid": category_id, "tenant": current_user["tenant_id"]},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Category not found")
    return CategoryResponse(**{**dict(row), "auto_comment_enabled": bool(row["auto_comment_enabled"])})


@router.delete("/categories/{category_id}", response_model=OkResponse)
async def delete_category(
    category_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> OkResponse:
    await db.execute(
        sa_text("DELETE FROM category_config WHERE category_id = :cid AND tenant_id = :tenant"),
        {"cid": category_id, "tenant": current_user["tenant_id"]},
    )
    return OkResponse()


# ── Rollback ──────────────────────────────────────────────────────────────────

@router.get("/rollback")
async def list_rollbacks(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
    ticket_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> dict:
    return await rollback_store.get_history(
        db, tenant_id=current_user["tenant_id"], ticket_id=ticket_id,
        date_from=date_from, date_to=date_to, page=page,
    )


@router.post("/rollback/{action_id}", response_model=RollbackResponse)
@router.post("/rollback/{action_id}/execute", response_model=RollbackResponse)
async def execute_rollback(
    action_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> RollbackResponse:
    try:
        result = await rollback_store.execute(
            db, current_user["tenant_id"], action_id, triggered_by=current_user["user_id"],
        )
        return RollbackResponse(success=result["success"], details=result["details"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── Qdrant stats + rebuild ────────────────────────────────────────────────────

@router.get("/qdrant/stats", response_model=QdrantStatsResponse)
async def qdrant_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> QdrantStatsResponse:
    from app.db.qdrant_client import ensure_tenant_collection, get_qdrant_client

    tenant_id = current_user["tenant_id"]
    client = get_qdrant_client()
    collection = await ensure_tenant_collection(tenant_id)
    col = await client.get_collection(collection)
    total_chunks = col.points_count or 0

    # points_count is a raw chunk count (a single document/ticket produces
    # several chunks), so it can't answer "how many documents/tickets are
    # indexed?" — scroll payloads and dedupe by doc_id / ticket_id instead.
    doc_ids: set[str] = set()
    ticket_ids: set[str] = set()
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=collection,
            limit=256,
            offset=offset,
            with_payload=["source_type", "doc_id", "ticket_id"],
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            source_type = payload.get("source_type")
            if source_type == "document" and payload.get("doc_id"):
                doc_ids.add(payload["doc_id"])
            elif source_type == "ticket" and payload.get("ticket_id"):
                ticket_ids.add(payload["ticket_id"])
        if offset is None:
            break

    result = await db.execute(
        sa_text("SELECT last_sync_timestamp FROM platform_config WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    row = result.first()
    last_sync = datetime.fromisoformat(row[0]) if row and row[0] else None

    return QdrantStatsResponse(
        documents_count=len(doc_ids),
        tickets_count=len(ticket_ids),
        total_chunks=total_chunks,
        last_sync=last_sync,
    )


@router.post("/qdrant-rebuild", response_model=OkResponse)
async def rebuild_qdrant_index(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
) -> OkResponse:
    from app.core.config import get_settings
    from app.db.qdrant_client import _ensure_collection, ensure_tenant_collection, get_qdrant_client

    tenant_id = current_user["tenant_id"]
    settings = get_settings()
    client = get_qdrant_client()
    collection = await ensure_tenant_collection(tenant_id)

    # Drop and recreate this tenant's collection only.
    await client.delete_collection(collection)
    await _ensure_collection(collection, settings.qdrant_vector_size)

    # Reset the sync cursor so next ingestion re-indexes everything
    await db.execute(
        sa_text("UPDATE platform_config SET last_sync_timestamp = NULL, updated_at = :now WHERE tenant_id = :tid"),
        {"now": _NOW(), "tid": tenant_id},
    )
    await db.commit()

    return OkResponse()


# ── Uploaded documents (list + delete) ─────────────────────────────────────────

@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    current_user: Annotated[dict, Depends(require_admin)],
) -> DocumentListResponse:
    """List all uploaded knowledge-base documents, grouped by doc_id.

    Scrolls this tenant's collection for source_type=document points and
    aggregates them client-side (Qdrant has no native GROUP BY).
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from app.db.qdrant_client import ensure_tenant_collection, get_qdrant_client

    client = get_qdrant_client()
    collection = await ensure_tenant_collection(current_user["tenant_id"])

    docs: dict[str, dict] = {}
    offset = None
    doc_filter = Filter(must=[FieldCondition(key="source_type", match=MatchValue(value="document"))])

    while True:
        points, offset = await client.scroll(
            collection_name=collection,
            scroll_filter=doc_filter,
            limit=256,
            offset=offset,
            with_payload=["doc_id", "filename", "uploaded_at"],
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            doc_id = payload.get("doc_id")
            if not doc_id:
                continue
            entry = docs.setdefault(
                doc_id,
                {
                    "doc_id": doc_id,
                    "filename": payload.get("filename") or "unknown",
                    "chunk_count": 0,
                    "uploaded_at": payload.get("uploaded_at"),
                },
            )
            entry["chunk_count"] += 1
        if offset is None:
            break

    summaries = [
        DocumentSummary(
            doc_id=d["doc_id"],
            filename=d["filename"],
            chunk_count=d["chunk_count"],
            uploaded_at=datetime.fromisoformat(d["uploaded_at"]) if d["uploaded_at"] else None,
        )
        for d in docs.values()
    ]
    summaries.sort(key=lambda s: s.uploaded_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return DocumentListResponse(documents=summaries)


@router.delete("/documents/{doc_id}", response_model=OkResponse)
async def delete_document(
    doc_id: str,
    current_user: Annotated[dict, Depends(require_admin)],
) -> OkResponse:
    """Delete all Qdrant points belonging to a single uploaded document, in
    this tenant's collection only."""
    from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

    from app.db.qdrant_client import ensure_tenant_collection, get_qdrant_client

    client = get_qdrant_client()
    collection = await ensure_tenant_collection(current_user["tenant_id"])

    await client.delete(
        collection_name=collection,
        points_selector=FilterSelector(
            filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])
        ),
    )
    return OkResponse()


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit-log")
@router.get("/audit")
async def get_audit(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_manager)],
    ticket_id: str | None = None,
    action_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> dict:
    return await audit_logger.get_entries(
        db, tenant_id=current_user["tenant_id"], ticket_id=ticket_id, action_type=action_type,
        date_from=date_from, date_to=date_to, page=page,
    )


@router.get("/audit-log/export")
@router.get("/audit/export")
async def export_audit(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(require_admin)],
    ticket_id: str | None = None,
    action_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> StreamingResponse:
    buffer = await audit_logger.export_csv(
        db, tenant_id=current_user["tenant_id"], ticket_id=ticket_id, action_type=action_type,
        date_from=date_from, date_to=date_to,
    )
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=aura_audit.csv"},
    )
