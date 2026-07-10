"""JWT encoding/decoding, password hashing, and FastAPI RBAC dependency factories."""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.sqlite import get_db

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=True)


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    settings = get_settings()
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload["exp"] = expire
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.app_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


# ── Current-user dependency ───────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise exc
    except JWTError:
        raise exc

    result = await db.execute(
        sa_text(
            "SELECT user_id, tenant_id, email, display_name, role, team_id, is_active "
            "FROM users WHERE user_id = :uid"
        ),
        {"uid": user_id},
    )
    row = result.mappings().first()
    if row is None or not row["is_active"]:
        raise exc
    return dict(row)


# ── RBAC dependency factories ─────────────────────────────────────────────────

def require_role(*roles: str):
    """Return a FastAPI dependency that enforces membership in `roles`."""
    async def _guard(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    return _guard


# Pre-built guards — use these directly in route `Depends()` calls:
#   async def route(user: dict = Depends(require_admin)): ...
#
# require_master_admin is deliberately its own guard, not folded into any of
# the others below: master_admin is not scoped to a tenant (tenant_id is
# NULL) and has zero visibility into tenant data — it must never satisfy
# require_admin/require_any_auth, which every tenant-scoped route assumes
# carries a real tenant_id to filter by.
require_master_admin = require_role("master_admin")
require_admin       = require_role("admin")
require_manager     = require_role("manager", "admin")
require_technician  = require_role("technician", "admin")
require_any_auth    = require_role("admin", "manager", "technician", "end_user")
