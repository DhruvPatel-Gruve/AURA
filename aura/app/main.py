"""AURA FastAPI application factory.

Startup order (lifespan):
  1. Configure structlog
  2. Initialise SQLite (run migrations)
  3. Initialise Qdrant (ensure collections exist)
  4. Seed platform_config thresholds + default admin user (idempotent)
  5. Warm kill-switch in-process cache
  6. Start APScheduler (ingestion_sync, jsm_poller, sla_checker)

Shutdown order (lifespan):
  1. Stop APScheduler (waits for in-flight jobs)
  2. Close Qdrant connection
  3. Dispose SQLite engine
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import limiter
from app.core.security_headers import SecurityHeadersMiddleware

_READY_CHECK_TIMEOUT_SECONDS = 3.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── Startup ───────────────────────────────────────────────────────────────
    configure_logging()
    log = get_logger(__name__)
    settings = get_settings()

    log.info("aura.startup", env=settings.app_env, version="1.0.0")

    from app.db.sqlite import init_db, close_db, get_session
    from app.db.qdrant_client import init_qdrant, close_qdrant
    from scheduler.scheduler import start as start_scheduler, stop as stop_scheduler

    await init_db()
    await init_qdrant()

    async with get_session() as db:
        await _seed_master_admin(db, settings)

        from app.services.kill_switch import init_kill_switch
        await init_kill_switch(db)

        from app.services.itsm_provider_state import init_itsm_provider
        await init_itsm_provider(db)

        from app.services.itsm_client import init_itsm_credentials
        await init_itsm_credentials(db)

    await start_scheduler()

    log.info("aura.ready")
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    log.info("aura.shutdown")
    await stop_scheduler()
    await close_qdrant()
    await close_db()
    log.info("aura.stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AURA — Agentic Unified Resolution Assistant",
        description="AI-powered ITSM platform: knowledge ingestion + LangGraph agent pipeline",
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # ── Security headers ──────────────────────────────────────────────────────
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    from app.api.v1.router import api_router
    app.include_router(api_router)

    # ── Health checks ─────────────────────────────────────────────────────────
    # /health       — liveness: "is the process alive and serving requests?"
    #                 Never checks downstream deps — a Qdrant/Ollama outage
    #                 must NOT cause an orchestrator to kill/restart this pod,
    #                 since restarting fixes nothing and just adds churn.
    # /health/ready — readiness: "can this instance actually serve traffic?"
    #                 Checks SQLite, Qdrant, and Ollama with a short timeout
    #                 each. A load balancer should stop routing traffic here
    #                 (but not restart the process) when this returns 503.
    @app.get("/health", tags=["system"], include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok", "version": "1.0.0"}

    @app.get("/health/ready", tags=["system"], include_in_schema=False)
    async def health_ready() -> dict:
        from fastapi.responses import JSONResponse

        checks = await _run_readiness_checks()
        overall_ok = all(c["ok"] for c in checks.values())
        body = {"status": "ready" if overall_ok else "not_ready", "checks": checks}
        return JSONResponse(status_code=200 if overall_ok else 503, content=body)

    return app


async def _run_readiness_checks() -> dict:
    """Probe each critical dependency with a short timeout. A hung dependency
    must fail fast here, not hang the readiness probe itself indefinitely."""
    import time

    results: dict = {}

    async def _check(name: str, coro) -> None:
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(coro, timeout=_READY_CHECK_TIMEOUT_SECONDS)
            results[name] = {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
        except Exception as exc:
            results[name] = {"ok": False, "error": str(exc)[:200]}

    async def _check_sqlite() -> None:
        from sqlalchemy import text as sa_text
        from app.db.sqlite import get_session
        async with get_session() as db:
            await db.execute(sa_text("SELECT 1"))

    async def _check_qdrant() -> None:
        from app.db.qdrant_client import get_qdrant_client
        await get_qdrant_client().get_collections()

    async def _check_ollama() -> None:
        import httpx
        settings = get_settings()
        base = settings.ollama_base_url.rsplit("/v1", 1)[0]
        async with httpx.AsyncClient(timeout=_READY_CHECK_TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{base}/api/tags")
            resp.raise_for_status()

    await asyncio.gather(
        _check("sqlite", _check_sqlite()),
        _check("qdrant", _check_qdrant()),
        _check("ollama", _check_ollama()),
    )
    return results


# ── Startup helpers ───────────────────────────────────────────────────────────

async def _seed_master_admin(db, settings) -> None:
    """Create the bootstrap master_admin account if none exists yet.

    Multi-tenant AURA has no meaningful "default tenant" to seed a regular
    admin into at boot — tenant admin accounts are created by a master_admin
    via POST /master/tenants instead. This seeds the one platform-level
    account needed to log in and create the first tenant. Reuses the
    DEFAULT_ADMIN_EMAIL/PASSWORD settings (and their production footgun
    guard in _guard_production_footguns) rather than introducing parallel
    env vars for what is, from an ops perspective, the same concept.
    """
    from sqlalchemy import text as sa_text
    from app.core.security import hash_password
    import uuid
    from datetime import datetime, timezone

    count_result = await db.execute(
        sa_text("SELECT COUNT(*) FROM users WHERE role = 'master_admin'")
    )
    if (count_result.scalar() or 0) > 0:
        return

    log = get_logger(__name__)
    email = settings.default_admin_email.lower()

    # DEFAULT_ADMIN_EMAIL collides with a pre-existing tenant account (e.g. a
    # demo/seed user created before this instance had a master_admin concept)
    # often enough that this must never crash the whole app on startup — log
    # and skip; an operator can seed a distinctly-emailed master_admin by hand.
    existing = (await db.execute(
        sa_text("SELECT 1 FROM users WHERE email = :email"), {"email": email},
    )).first()
    if existing is not None:
        log.error("aura.master_admin_seed_skipped_email_collision", email=email)
        return

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        sa_text(
            "INSERT INTO users (user_id, tenant_id, email, display_name, hashed_password, role, created_at) "
            "VALUES (:uid, NULL, :email, :name, :pw, 'master_admin', :now)"
        ),
        {
            "uid": user_id,
            "email": email,
            "name": "AURA Master Admin",
            "pw": hash_password(settings.default_admin_password),
            "now": now,
        },
    )

    log.info("aura.master_admin_seeded", email=email)


app = create_app()
