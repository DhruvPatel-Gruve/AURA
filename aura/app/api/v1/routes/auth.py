"""Authentication routes.

POST /auth/login            — email + password → access token + httpOnly refresh cookie
POST /auth/refresh          — swap refresh cookie for new access token
POST /auth/logout           — revoke session, clear cookie
GET  /auth/me               — current user profile
POST /auth/change-password  — self-service password change (any authenticated role)
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.sqlite import get_db
from app.models.api_schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    OkResponse,
    TokenRefreshResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
_settings = get_settings()

_REFRESH_COOKIE = "aura_refresh"


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
@limiter.limit(_settings.rate_limit_login)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    result = await db.execute(
        sa_text(
            "SELECT u.user_id, u.tenant_id, u.email, u.display_name, u.role, u.team_id, "
            "       u.hashed_password, u.is_active, pc.setup_complete AS setup_complete, "
            "       t.status AS tenant_status "
            "FROM users u "
            "LEFT JOIN platform_config pc ON pc.tenant_id = u.tenant_id "
            "LEFT JOIN tenants t ON t.tenant_id = u.tenant_id "
            "WHERE u.email = :email"
        ),
        {"email": body.email.lower().strip()},
    )
    row = result.mappings().first()

    if not row or not row["is_active"] or not verify_password(body.password, row["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # master_admin has tenant_status=NULL (no tenant) — never blocked here.
    if row["tenant_status"] == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account's organization has been suspended. Contact your platform administrator.",
        )

    # Stamp last_login
    await db.execute(
        sa_text("UPDATE users SET last_login = :now WHERE user_id = :uid"),
        {"now": datetime.now(timezone.utc).isoformat(), "uid": row["user_id"]},
    )

    # Create sessions row (refresh token)
    refresh_token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days)
    await db.execute(
        sa_text(
            "INSERT INTO sessions (session_id, user_id, expires_at, created_at) "
            "VALUES (:sid, :uid, :exp, :now)"
        ),
        {
            "sid": refresh_token,
            "uid": row["user_id"],
            "exp": expires_at.isoformat(),
            "now": datetime.now(timezone.utc).isoformat(),
        },
    )

    api_role = "enduser" if row["role"] == "end_user" else row["role"]
    access_token = create_access_token({"sub": row["user_id"], "role": api_role})

    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        path="/api/v1/auth",
    )

    # master_admin has tenant_id=NULL, so the platform_config LEFT JOIN never
    # matches — setup is a per-tenant concept that doesn't apply to them.
    setup_complete = True if row["tenant_id"] is None else bool(row["setup_complete"])

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        role=api_role,
        user_id=row["user_id"],
        setup_complete=setup_complete,
    )


# ── Refresh ───────────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenRefreshResponse)
@limiter.limit(_settings.rate_limit_refresh)
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    aura_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenRefreshResponse:
    if not aura_refresh:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    now = datetime.now(timezone.utc).isoformat()
    result = await db.execute(
        sa_text(
            "SELECT s.session_id, s.user_id, s.revoked, s.expires_at, u.role, u.is_active "
            "FROM sessions s JOIN users u ON u.user_id = s.user_id "
            "WHERE s.session_id = :sid"
        ),
        {"sid": aura_refresh},
    )
    row = result.mappings().first()

    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalid or expired")

    # Reuse detection: a revoked refresh token being presented again means it
    # was rotated away (normal reuse of a stale cookie) OR stolen and replayed
    # after the legitimate client already rotated past it. Either way, the
    # safe response is to kill every session for this user and force a fresh
    # login — never silently re-issue a token for an already-rotated session.
    if row["revoked"]:
        await db.execute(
            sa_text("UPDATE sessions SET revoked = 1 WHERE user_id = :uid"),
            {"uid": row["user_id"]},
        )
        await db.commit()
        response.delete_cookie(key=_REFRESH_COOKIE, path="/api/v1/auth")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token already used — all sessions revoked for safety",
        )

    if row["expires_at"] <= now or not row["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalid or expired")

    # Rotate: revoke the presented token and issue a brand new one. Limits
    # the blast radius of a leaked cookie to a single use before detection.
    await db.execute(
        sa_text("UPDATE sessions SET revoked = 1 WHERE session_id = :sid"),
        {"sid": row["session_id"]},
    )
    new_refresh_token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days)
    await db.execute(
        sa_text(
            "INSERT INTO sessions (session_id, user_id, expires_at, created_at) "
            "VALUES (:sid, :uid, :exp, :now)"
        ),
        {"sid": new_refresh_token, "uid": row["user_id"], "exp": expires_at.isoformat(), "now": now},
    )
    await db.commit()

    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=new_refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        path="/api/v1/auth",
    )

    api_role = "enduser" if row["role"] == "end_user" else row["role"]
    access_token = create_access_token({"sub": row["user_id"], "role": api_role})
    return TokenRefreshResponse(access_token=access_token)


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout", response_model=OkResponse)
async def logout(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    aura_refresh: Annotated[str | None, Cookie()] = None,
) -> OkResponse:
    if aura_refresh:
        await db.execute(
            sa_text("UPDATE sessions SET revoked = 1 WHERE session_id = :sid"),
            {"sid": aura_refresh},
        )
    response.delete_cookie(key=_REFRESH_COOKIE, path="/api/v1/auth")
    return OkResponse()


# ── Current user ──────────────────────────────────────────────────────────────

@router.get("/me", response_model=dict)
async def me(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    return {
        "user_id": current_user["user_id"],
        "email": current_user["email"],
        "display_name": current_user["display_name"],
        "role": current_user["role"],
        "team_id": current_user.get("team_id"),
        "tenant_id": current_user.get("tenant_id"),
    }


# ── Change password ──────────────────────────────────────────────────────────

@router.post("/change-password", response_model=OkResponse)
@limiter.limit(_settings.rate_limit_login)
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
) -> OkResponse:
    """Self-service password change — every role (including master_admin)
    goes through this. Requires the current password, rehashes the new one
    with bcrypt (passwords are hashed, one-way, never reversibly encrypted
    like ITSM API tokens — that's the correct approach for credentials
    nobody, including AURA itself, should ever be able to read back)."""
    row = (await db.execute(
        sa_text("SELECT hashed_password FROM users WHERE user_id = :uid"),
        {"uid": current_user["user_id"]},
    )).first()
    if row is None or not verify_password(body.current_password, row[0]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    await db.execute(
        sa_text("UPDATE users SET hashed_password = :pw WHERE user_id = :uid"),
        {"pw": hash_password(body.new_password), "uid": current_user["user_id"]},
    )
    # Revoke every refresh-token session for this user — standard hygiene
    # after a password change; forces re-login everywhere else.
    await db.execute(
        sa_text("UPDATE sessions SET revoked = 1 WHERE user_id = :uid"),
        {"uid": current_user["user_id"]},
    )
    await db.commit()
    return OkResponse()
