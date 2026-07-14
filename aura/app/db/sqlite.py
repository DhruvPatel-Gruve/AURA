from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.core.config import get_settings
from app.core.crypto import encrypt
from app.core.logging import get_logger

log = get_logger(__name__)

_MIGRATIONS_FILE = Path(__file__).parent / "migrations" / "init_schema.sql"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialised — call init_db() first.")
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Session factory not initialised — call init_db() first.")
    return _session_factory


async def init_db() -> None:
    """Create the async engine, run SQL migrations, and warm the session factory.
    Called once from FastAPI lifespan on startup.
    """
    global _engine, _session_factory

    settings = get_settings()
    db_path = Path(settings.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _engine = create_async_engine(
        settings.sqlite_url,
        echo=False,
        connect_args={
            "check_same_thread": False,
            "timeout": 30,
        },
    )

    # PRAGMA journal_mode=WAL is persisted in the database file header, so
    # setting it once in init_schema.sql is enough. PRAGMA foreign_keys and
    # busy_timeout are NOT persistent — they reset to SQLite's defaults
    # (foreign_keys=OFF) on every new DBAPI connection, and the connection
    # pool opens several over the app's lifetime. Without this listener, FK
    # constraints were only ever enforced on the one connection used during
    # the startup migration — silently off everywhere else.
    @event.listens_for(_engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    await run_migrations()
    log.info("database.ready", path=str(db_path.resolve()))


async def _table_has_column(conn, table: str, column: str) -> bool:
    from sqlalchemy import text as sa_text

    info = await conn.execute(sa_text(f"PRAGMA table_info({table})"))
    return column in {row[1] for row in info.all()}


async def _backfill_ai_config_from_global_settings() -> None:
    """One-time backfill, run only the first time the AI-config columns are
    added to an existing database. Populates every current tenant row with
    the operator's pre-existing global Settings (the single Gemini key /
    LLM endpoint every tenant already shares today) so upgrading doesn't
    break any tenant's live pipeline. Tenants created after this point start
    with these columns NULL and must configure their own via the wizard —
    this function must never run again after the initial upgrade.
    """
    from sqlalchemy import text as sa_text

    settings = get_settings()
    encrypted_embedding_key = encrypt(settings.gemini_api_key)
    async with _get_engine().begin() as conn:
        await conn.execute(
            sa_text(
                """
                UPDATE platform_config
                SET embedding_provider = 'gemini',
                    embedding_api_key_encrypted = :embedding_key,
                    embedding_model = :embedding_model,
                    embedding_vector_size = :vector_size,
                    llm_base_url = :llm_base_url,
                    llm_model = :llm_model
                WHERE embedding_provider IS NULL
                """
            ),
            {
                "embedding_key": encrypted_embedding_key,
                "embedding_model": settings.gemini_embedding_model,
                "vector_size": settings.qdrant_vector_size,
                "llm_base_url": settings.ollama_base_url,
                "llm_model": settings.ollama_model,
            },
        )
    log.info("database.ai_config_backfilled_from_global_settings")


async def _recreate_for_tenancy(
    conn, table: str, create_sql: str, copy_sql: str | None = None,
) -> None:
    """Idempotently reshape a pre-multi-tenancy table into its tenant-aware
    shape: rename it aside, create the new shape under the real table name,
    optionally copy rows forward, then drop the old one.

    No-ops if `tenant_id` is already present — a fresh database already has
    every table in its final shape straight from init_schema.sql, so this
    only ever does real work against a database created before multi-tenancy.

    Safe without touching `PRAGMA foreign_keys`: SQLite resolves a REFERENCES
    clause by table name at DML time, not at CREATE TABLE time, and nothing
    queries these tables mid-migration (the app isn't serving requests yet) —
    so the brief window where a table's old and new versions swap names
    never has anything else observing it.
    """
    from sqlalchemy import text as sa_text

    if await _table_has_column(conn, table, "tenant_id"):
        return

    backup = f"{table}_pretenant_backup"
    await conn.execute(sa_text(f"ALTER TABLE {table} RENAME TO {backup}"))
    await conn.execute(sa_text(create_sql))
    if copy_sql:
        await conn.execute(sa_text(copy_sql.format(backup=backup)))
    await conn.execute(sa_text(f"DROP TABLE {backup}"))
    log.info("database.recreated_for_tenancy", table=table, copied_data=copy_sql is not None)


async def _fix_stale_fk_reference(conn, table: str, correct_create_sql: str) -> None:
    """Repair a table whose stored schema still references `{other}_pretenant_backup`.

    SQLite auto-rewrites every OTHER table's foreign-key text when the table
    they reference is renamed (documented behaviour since 3.25) — so the
    `users` recreate-for-tenancy rename (`users` -> `users_pretenant_backup`)
    silently rewrote every table with `REFERENCES users` to instead say
    `REFERENCES users_pretenant_backup`, and dropping that backup table
    afterward never fixed the dangling reference back. Detected via a schema
    substring check so this is a no-op (and safe to call unconditionally)
    once repaired.
    """
    from sqlalchemy import text as sa_text

    row = (await conn.execute(
        sa_text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"), {"t": table},
    )).first()
    if row is None or "_pretenant_backup" not in row[0]:
        return

    backup = f"{table}_fk_repair_backup"
    await conn.execute(sa_text(f"ALTER TABLE {table} RENAME TO {backup}"))
    await conn.execute(sa_text(correct_create_sql))
    cols = [r[1] for r in (await conn.execute(sa_text(f"PRAGMA table_info({backup})"))).all()]
    col_list = ", ".join(cols)
    await conn.execute(sa_text(f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM {backup}"))
    await conn.execute(sa_text(f"DROP TABLE {backup}"))
    log.info("database.fk_reference_repaired", table=table)


async def run_migrations() -> None:
    """Execute init_schema.sql idempotently (CREATE TABLE IF NOT EXISTS),
    then backfill multi-tenancy support into any pre-existing database.
    """
    from sqlalchemy import text as sa_text

    sql = _MIGRATIONS_FILE.read_text(encoding="utf-8")
    # Split into individual statements — SQLAlchemy's async adapter does not
    # expose executescript(), so we execute each statement separately.
    # Filter keeps only chunks that contain at least one non-comment SQL line.
    statements = [
        stmt.strip()
        for stmt in sql.split(";")
        if any(
            line.strip() and not line.strip().startswith("--")
            for line in stmt.splitlines()
        )
    ]
    async with _get_engine().begin() as conn:
        for stmt in statements:
            await conn.execute(sa_text(stmt))

    # ── Multi-tenancy backfill for pre-existing databases ───────────────────
    # Every table here either had its PRIMARY KEY / UNIQUE constraint move
    # from a bare column to a (tenant_id, column) pair (SQLite can't ALTER a
    # constraint in place — full recreate is the only option), or just needs
    # a plain tenant_id column added. All of this is a no-op on a fresh
    # database, which already got every table in its final shape above.
    #
    # No data is carried forward except for `users` — real login accounts
    # are worth keeping (as tenant_id=NULL orphans, invisible to every
    # tenant-scoped query going forward); the operational/ticket tables are
    # deliberately started clean, matching the decision to re-onboard both
    # existing demo instances as fresh tenants rather than migrate their data.
    async with _get_engine().begin() as conn:
        await _recreate_for_tenancy(
            conn, "users",
            """
            CREATE TABLE users (
                user_id         TEXT PRIMARY KEY,
                tenant_id       TEXT REFERENCES tenants (tenant_id) ON DELETE CASCADE,
                email           TEXT NOT NULL UNIQUE,
                hashed_password TEXT NOT NULL,
                display_name    TEXT NOT NULL,
                role            TEXT NOT NULL
                                CHECK (role IN ('master_admin', 'admin', 'manager', 'technician', 'end_user')),
                team_id         TEXT,
                is_active       INTEGER NOT NULL DEFAULT 1,
                last_login      TEXT,
                jira_account_id TEXT,
                created_at      TEXT NOT NULL
            )
            """,
            copy_sql="""
            INSERT INTO users
                (user_id, tenant_id, email, hashed_password, display_name, role, team_id, is_active, last_login, jira_account_id, created_at)
            SELECT user_id, NULL, email, hashed_password, display_name, role, team_id, is_active, last_login, jira_account_id, created_at
            FROM {backup}
            """,
        )

        await _recreate_for_tenancy(
            conn, "platform_config",
            """
            CREATE TABLE platform_config (
                tenant_id                   TEXT PRIMARY KEY REFERENCES tenants (tenant_id) ON DELETE CASCADE,
                aura_enabled                INTEGER NOT NULL DEFAULT 1,
                confidence_threshold        REAL    NOT NULL DEFAULT 0.90,
                abstention_threshold        REAL    NOT NULL DEFAULT 0.60,
                polling_interval_minutes    INTEGER NOT NULL DEFAULT 5,
                ingestion_interval_hours    INTEGER NOT NULL DEFAULT 4,
                collision_timeout_minutes   INTEGER NOT NULL DEFAULT 30,
                assignment_timeout_minutes  INTEGER NOT NULL DEFAULT 60,
                conversation_idle_timeout_hours INTEGER NOT NULL DEFAULT 24,
                last_poll_timestamp         TEXT,
                last_sync_timestamp         TEXT,
                setup_complete              INTEGER NOT NULL DEFAULT 0,
                current_wizard_step         INTEGER NOT NULL DEFAULT 1,
                kill_switch_changed_by      TEXT,
                kill_switch_changed_at      TEXT,
                company_name                TEXT,
                company_logo                TEXT,
                accent_color                TEXT,
                itsm_provider                TEXT NOT NULL DEFAULT 'jira' CHECK (itsm_provider IN ('jira', 'zendesk')),
                jsm_base_url                 TEXT,
                jsm_project_key               TEXT,
                jsm_api_email                 TEXT,
                jsm_api_token_encrypted       TEXT,
                zen_subdomain                 TEXT,
                zen_api_email                 TEXT,
                zen_api_token_encrypted       TEXT,
                updated_at                   TEXT NOT NULL
            )
            """,
        )

        await _recreate_for_tenancy(
            conn, "wizard_progress",
            """
            CREATE TABLE wizard_progress (
                tenant_id   TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
                step_number INTEGER NOT NULL,
                step_data   TEXT NOT NULL,
                saved_at    TEXT NOT NULL,
                PRIMARY KEY (tenant_id, step_number)
            )
            """,
        )

        # Also retires the old L0-L4 autonomy_level enum column for good —
        # it was already unused dead weight (see prior migration comment),
        # and a full recreate finally drops it instead of leaving it inert.
        await _recreate_for_tenancy(
            conn, "category_config",
            """
            CREATE TABLE category_config (
                category_id          TEXT PRIMARY KEY,
                tenant_id             TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
                name                  TEXT NOT NULL,
                auto_comment_enabled  INTEGER NOT NULL DEFAULT 0
                                     CHECK (auto_comment_enabled IN (0, 1)),
                sla_minutes           INTEGER NOT NULL DEFAULT 480,
                team_id               TEXT NOT NULL,
                created_at            TEXT NOT NULL,
                updated_at            TEXT NOT NULL,
                UNIQUE (tenant_id, name)
            )
            """,
        )

        # ticket_id is only unique within one tenant's own ITSM instance —
        # the old bare `ticket_id UNIQUE` constraint has to go, not just gain
        # a tenant_id column alongside it.
        await _recreate_for_tenancy(
            conn, "low_confidence_queue",
            """
            CREATE TABLE low_confidence_queue (
                queue_id          TEXT PRIMARY KEY,
                tenant_id         TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
                ticket_id         TEXT NOT NULL,
                formatted_comment TEXT NOT NULL,
                confidence_score  REAL,
                citations         TEXT NOT NULL DEFAULT '[]',
                abstained         INTEGER NOT NULL DEFAULT 0,
                team_id           TEXT NOT NULL,
                reporter_account_id TEXT,
                queued_at         TEXT NOT NULL,
                resolved_at       TEXT,
                resolved_by       TEXT,
                resolution_action TEXT,
                UNIQUE (tenant_id, ticket_id)
            )
            """,
        )

        await _recreate_for_tenancy(
            conn, "sla_events",
            """
            CREATE TABLE sla_events (
                sla_id          TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
                ticket_id       TEXT NOT NULL,
                category        TEXT NOT NULL,
                deadline        TEXT NOT NULL,
                warning_sent_at TEXT,
                breached_at     TEXT,
                created_at      TEXT NOT NULL,
                UNIQUE (tenant_id, ticket_id)
            )
            """,
        )

        await _recreate_for_tenancy(
            conn, "ticket_conversations",
            """
            CREATE TABLE ticket_conversations (
                tenant_id            TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
                ticket_id            TEXT NOT NULL,
                status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','resolved')),
                reporter_account_id  TEXT,
                last_aura_comment_at TEXT NOT NULL,
                turn_count           INTEGER NOT NULL DEFAULT 1,
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL,
                PRIMARY KEY (tenant_id, ticket_id)
            )
            """,
        )

        await _recreate_for_tenancy(
            conn, "ticket_status",
            """
            CREATE TABLE ticket_status (
                tenant_id  TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
                ticket_id  TEXT NOT NULL,
                status     TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, ticket_id)
            )
            """,
        )

        await _recreate_for_tenancy(
            conn, "user_submitted_tickets",
            """
            CREATE TABLE user_submitted_tickets (
                tenant_id    TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
                ticket_id    TEXT NOT NULL,
                user_id      TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
                submitted_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, ticket_id)
            )
            """,
        )

    # Repair any table whose FK text got silently rewritten to reference
    # `users_pretenant_backup` by SQLite's automatic FK-rewrite-on-RENAME
    # behaviour during the `users` recreate above (see _fix_stale_fk_reference).
    # No-ops once repaired. sessions has no tenant_id column (ties to a user,
    # not a tenant) so its correct shape is listed separately from the rest.
    async with _get_engine().begin() as conn:
        await _fix_stale_fk_reference(
            conn, "sessions",
            """
            CREATE TABLE sessions (
                session_id  TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
                expires_at  TEXT NOT NULL,
                revoked     INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL
            )
            """,
        )
        await _fix_stale_fk_reference(
            conn, "collision_claims",
            """
            CREATE TABLE collision_claims (
                claim_id     TEXT PRIMARY KEY,
                tenant_id    TEXT REFERENCES tenants (tenant_id),
                ticket_id    TEXT NOT NULL,
                claimed_by   TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
                claimed_at   TEXT NOT NULL,
                expires_at   TEXT NOT NULL,
                released_at  TEXT
            )
            """,
        )
        await _fix_stale_fk_reference(
            conn, "ticket_assignments",
            """
            CREATE TABLE ticket_assignments (
                assignment_id   TEXT PRIMARY KEY,
                tenant_id       TEXT REFERENCES tenants (tenant_id),
                ticket_id       TEXT NOT NULL,
                assigned_to     TEXT NOT NULL REFERENCES users (user_id),
                team_id         TEXT,
                assigned_at     TEXT NOT NULL,
                acknowledged_at TEXT,
                reassigned_at   TEXT,
                escalated_at    TEXT,
                is_current      INTEGER NOT NULL DEFAULT 1
            )
            """,
        )
        await _fix_stale_fk_reference(
            conn, "chat_sessions",
            """
            CREATE TABLE chat_sessions (
                session_id  TEXT PRIMARY KEY,
                tenant_id   TEXT REFERENCES tenants (tenant_id),
                user_id     TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
                status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
                created_at  TEXT NOT NULL,
                closed_at   TEXT
            )
            """,
        )
        await _fix_stale_fk_reference(
            conn, "chat_messages",
            """
            CREATE TABLE chat_messages (
                message_id  TEXT PRIMARY KEY,
                tenant_id   TEXT REFERENCES tenants (tenant_id),
                ticket_id   TEXT NOT NULL,
                user_id     TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
                session_id  TEXT REFERENCES chat_sessions (session_id),
                role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content     TEXT NOT NULL,
                citations   TEXT NOT NULL DEFAULT '[]',
                timestamp   TEXT NOT NULL
            )
            """,
        )

    # These tables' existing PK/UNIQUE shape needs no change — tenant_id is
    # just a new nullable column (orphaned/NULL on pre-existing rows, same
    # "start clean" treatment as above).
    async with _get_engine().begin() as conn:
        for table in (
            "audit_log", "rollback_store", "collision_claims",
            "ticket_assignments", "ingestion_runs", "chat_sessions", "chat_messages",
        ):
            if not await _table_has_column(conn, table, "tenant_id"):
                await conn.execute(
                    sa_text(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT REFERENCES tenants (tenant_id)")
                )

    # ── Column-level migrations unrelated to tenancy, for existing DBs ─────
    async with _get_engine().begin() as conn:
        if not await _table_has_column(conn, "audit_log", "auto_comment_enabled"):
            await conn.execute(
                sa_text("ALTER TABLE audit_log ADD COLUMN auto_comment_enabled INTEGER")
            )

    async with _get_engine().begin() as conn:
        if not await _table_has_column(conn, "chat_messages", "session_id"):
            await conn.execute(
                sa_text("ALTER TABLE chat_messages ADD COLUMN session_id TEXT REFERENCES chat_sessions (session_id)")
            )
        # Column is now guaranteed present (either just added above, or
        # already existed on a fresh DB created from the current schema) —
        # safe to index unconditionally here.
        await conn.execute(
            sa_text("CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages (session_id)")
        )

    # ── Per-tenant AI (embedding/LLM) provider config ───────────────────────
    # No fallback by design: a tenant with these columns NULL gets a clean
    # pipeline abstention rather than silently borrowing another tenant's or
    # the operator's key. `_ai_columns_newly_added` distinguishes "upgrading
    # an existing DB that predates this feature" (needs a one-time backfill
    # from the old global Settings, below, so already-running tenants don't
    # suddenly break) from "fresh DB created from the current init_schema.sql"
    # (no pre-existing tenants to backfill) and from "columns already added on
    # a prior startup" (must NOT re-backfill — that would erase a tenant's own
    # configured values, or wrongly un-blank a NULL a newer tenant left
    # unconfigured on purpose).
    async with _get_engine().begin() as conn:
        _ai_columns_newly_added = not await _table_has_column(conn, "platform_config", "embedding_provider")
        for col, ddl_type in (
            ("embedding_provider", "TEXT"),
            ("embedding_api_key_encrypted", "TEXT"),
            ("embedding_base_url", "TEXT"),
            ("embedding_model", "TEXT"),
            ("embedding_vector_size", "INTEGER"),
            ("llm_base_url", "TEXT"),
            ("llm_model", "TEXT"),
            ("llm_api_key_encrypted", "TEXT"),
        ):
            if not await _table_has_column(conn, "platform_config", col):
                await conn.execute(sa_text(f"ALTER TABLE platform_config ADD COLUMN {col} {ddl_type}"))

    if _ai_columns_newly_added:
        await _backfill_ai_config_from_global_settings()

    # ── tenant_id indexes ────────────────────────────────────────────────────
    # Deliberately created here, not in init_schema.sql — every table above
    # is guaranteed to have its tenant_id column by now, whether it came from
    # a fresh CREATE or one of the recreate/ALTER steps above. Creating these
    # any earlier (e.g. inline in init_schema.sql) would crash the very first
    # migration pass against a pre-existing database, since that pass runs
    # before the tenant_id column exists on any of these tables.
    async with _get_engine().begin() as conn:
        for stmt in (
            "CREATE INDEX IF NOT EXISTS idx_users_tenant ON users (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_category_config_tenant ON category_config (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_rollback_tenant ON rollback_store (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_lcq_tenant ON low_confidence_queue (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_claims_tenant ON collision_claims (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_assignments_tenant ON ticket_assignments (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_conversations_tenant ON ticket_conversations (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_sla_tenant ON sla_events (tenant_id)",
            # Defensive duplicates of the inline UNIQUE(tenant_id, ticket_id) on
            # these two tables (see init_schema.sql) — harmless if that inline
            # constraint's automatic index already covers it, but required for
            # any database that got its tenant_id column added on a code
            # revision that predated the inline constraint (the per-table
            # _recreate_for_tenancy guard only checks column presence, so it
            # would otherwise never revisit an already-migrated table).
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_lcq_tenant_ticket ON low_confidence_queue (tenant_id, ticket_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sla_tenant_ticket ON sla_events (tenant_id, ticket_id)",
            "CREATE INDEX IF NOT EXISTS idx_runs_tenant ON ingestion_runs (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_chat_sessions_tenant ON chat_sessions (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_chat_tenant ON chat_messages (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_ticket_status_tenant ON ticket_status (tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_submitted_tenant ON user_submitted_tickets (tenant_id)",
        ):
            await conn.execute(sa_text(stmt))

    log.info("database.migrations_applied")


async def close_db() -> None:
    """Dispose the engine — called from FastAPI lifespan on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        log.info("database.closed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a transactional AsyncSession per request."""
    session = _get_session_factory()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for use outside FastAPI request scope.

    Use this in agent nodes, scheduler jobs, and background tasks that need
    a DB session without going through FastAPI's Depends() mechanism.

    Usage:
        async with get_session() as db:
            result = await db.execute(...)
    """
    session = _get_session_factory()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
