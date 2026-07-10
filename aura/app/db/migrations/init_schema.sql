-- AURA SQLite Schema — multi-tenant
-- Executed once at startup via app/db/sqlite.py:run_migrations()
-- All timestamps stored as ISO-8601 UTC text for SQLite compatibility.
--
-- Multi-tenancy: every table below except `tenants` itself is scoped by a
-- `tenant_id` column. `master_admin` users have `tenant_id = NULL` — they
-- are not scoped to any tenant, unlike every other role which always has one.
--
-- IMPORTANT: every index that references a `tenant_id` column is deliberately
-- NOT defined here — it's created later in sqlite.py's run_migrations(),
-- after the column-backfill migrations run. This file's statements execute
-- first, unconditionally, on every boot (including against an existing
-- pre-multi-tenancy database where these tables exist but don't have a
-- tenant_id column yet — an index on a not-yet-existing column would crash
-- that pass. Same reasoning as the pre-existing idx_chat_session pattern
-- below, just applied consistently everywhere now.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── 0. tenants ────────────────────────────────────────────────────────────────
-- One row per client. Created exclusively by a master_admin via
-- POST /master/tenants, which also seeds that tenant's first admin user.
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id     TEXT PRIMARY KEY,   -- UUID
    name          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    itsm_provider TEXT NOT NULL DEFAULT 'jira' CHECK (itsm_provider IN ('jira', 'zendesk')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- ── 1. users ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,           -- UUID
    tenant_id       TEXT REFERENCES tenants (tenant_id) ON DELETE CASCADE,  -- NULL only for master_admin
    email           TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL               -- "master_admin" | "admin" | "manager" | "technician" | "end_user"
                    CHECK (role IN ('master_admin', 'admin', 'manager', 'technician', 'end_user')),
    team_id         TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1, -- BOOLEAN (0/1)
    last_login      TEXT,                       -- ISO-8601 UTC | NULL
    jira_account_id TEXT,                       -- real Jira/Atlassian accountId, for native assignee writes
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_email  ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_team   ON users (team_id);

-- ── 2. sessions ───────────────────────────────────────────────────────────────
-- Server-side refresh-token store. Access tokens are stateless (JWT).
-- No tenant_id here — scoping flows through user_id -> users.tenant_id.
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,   -- UUID == refresh_token value
    user_id     TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,      -- ISO-8601 UTC
    revoked     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);

-- ── 3. platform_config ────────────────────────────────────────────────────────
-- One row per tenant (was a single CHECK(id=1) row pre-multi-tenancy).
-- ITSM credentials live here now, encrypted at rest (app/core/crypto.py) —
-- moved out of process-wide .env so each tenant can hold its own Jira/
-- Zendesk API token independently.
CREATE TABLE IF NOT EXISTS platform_config (
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
    company_logo                TEXT,           -- base64 data URL
    accent_color                TEXT,           -- hex, e.g. "#3db549"
    itsm_provider                TEXT NOT NULL DEFAULT 'jira' CHECK (itsm_provider IN ('jira', 'zendesk')),
    jsm_base_url                 TEXT,
    jsm_project_key               TEXT,
    jsm_api_email                 TEXT,
    jsm_api_token_encrypted       TEXT,
    zen_subdomain                 TEXT,
    zen_api_email                 TEXT,
    zen_api_token_encrypted       TEXT,
    updated_at                   TEXT NOT NULL
);

-- ── 4. wizard_progress ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wizard_progress (
    tenant_id   TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    step_data   TEXT NOT NULL,  -- JSON blob
    saved_at    TEXT NOT NULL,
    PRIMARY KEY (tenant_id, step_number)
);

-- ── 5. category_config ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS category_config (
    category_id          TEXT PRIMARY KEY,   -- UUID
    tenant_id             TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    auto_comment_enabled  INTEGER NOT NULL DEFAULT 0
                         CHECK (auto_comment_enabled IN (0, 1)),
    sla_minutes           INTEGER NOT NULL DEFAULT 480,
    team_id               TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE (tenant_id, name)
);

-- ── 6. audit_log ──────────────────────────────────────────────────────────────
-- Append-only. No UPDATE or DELETE should ever touch this table.
CREATE TABLE IF NOT EXISTS audit_log (
    entry_id         TEXT PRIMARY KEY,  -- UUID
    tenant_id        TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    ticket_id        TEXT NOT NULL,
    action_taken     TEXT NOT NULL,
    priority         TEXT,
    category         TEXT,
    auto_comment_enabled INTEGER,
    confidence_score REAL,
    abstained        INTEGER NOT NULL DEFAULT 0,
    jsm_comment_id   TEXT,
    rollback_ref     TEXT,
    audit_steps      TEXT NOT NULL DEFAULT '[]',  -- JSON list[AuditStep]
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_ticket    ON audit_log (ticket_id);
CREATE INDEX IF NOT EXISTS idx_audit_created   ON audit_log (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action    ON audit_log (action_taken);

-- ── 7. rollback_store ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rollback_store (
    action_id       TEXT PRIMARY KEY,   -- UUID
    tenant_id       TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    ticket_id       TEXT NOT NULL,
    action_type     TEXT NOT NULL,      -- "comment_posted" | "ticket_transitioned" | etc.
    rollback_call   TEXT NOT NULL,      -- JSON: { method, url, body }
    actor           TEXT NOT NULL,      -- user_id
    created_at      TEXT NOT NULL,
    rolled_back_at  TEXT,
    rolled_back_by  TEXT
);

CREATE INDEX IF NOT EXISTS idx_rollback_ticket ON rollback_store (ticket_id);

-- ── 8. low_confidence_queue ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS low_confidence_queue (
    queue_id          TEXT PRIMARY KEY,   -- UUID
    tenant_id         TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    ticket_id         TEXT NOT NULL,
    formatted_comment TEXT NOT NULL,
    confidence_score  REAL,
    citations         TEXT NOT NULL DEFAULT '[]',   -- JSON
    abstained         INTEGER NOT NULL DEFAULT 0,
    team_id           TEXT NOT NULL,
    reporter_account_id TEXT,   -- Jira accountId, threaded into conversation tracking on approve/edit
    queued_at         TEXT NOT NULL,
    resolved_at       TEXT,
    resolved_by       TEXT,
    resolution_action TEXT,  -- "approved" | "edited" | "rejected"
    -- ticket_id is only unique within one tenant's own ITSM instance — two
    -- different tenants' Jira/Zendesk projects can both produce a "ITSM-1".
    -- Inline (not a separate CREATE UNIQUE INDEX) so it's safe under
    -- CREATE TABLE IF NOT EXISTS: a no-op against an existing pre-tenant
    -- table, but present from the start on a fresh one, and required for
    -- upsert statements' ON CONFLICT(tenant_id, ticket_id) to resolve.
    UNIQUE (tenant_id, ticket_id)
);

CREATE INDEX IF NOT EXISTS idx_lcq_team   ON low_confidence_queue (team_id);
CREATE INDEX IF NOT EXISTS idx_lcq_queued ON low_confidence_queue (queued_at);

-- ── 9. collision_claims ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS collision_claims (
    claim_id     TEXT PRIMARY KEY,  -- UUID
    tenant_id    TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    ticket_id    TEXT NOT NULL,
    claimed_by   TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    claimed_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    released_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_claims_ticket  ON collision_claims (ticket_id);
CREATE INDEX IF NOT EXISTS idx_claims_expires ON collision_claims (expires_at);

-- ── 9b. ticket_assignments ───────────────────────────────────────────────────
-- Full history kept (like audit_log) — each row is one assignment event.
-- is_current=1 marks the live assignment for a ticket. Superseded rows get
-- reassigned_at stamped and is_current set to 0.
CREATE TABLE IF NOT EXISTS ticket_assignments (
    assignment_id   TEXT PRIMARY KEY,  -- UUID
    tenant_id       TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    ticket_id       TEXT NOT NULL,
    assigned_to     TEXT NOT NULL REFERENCES users (user_id),
    team_id         TEXT,
    assigned_at     TEXT NOT NULL,
    acknowledged_at TEXT,              -- NULL = not yet acknowledged
    reassigned_at   TEXT,              -- set when superseded by a new row
    escalated_at    TEXT,              -- guard: fire admin escalation once per overdue assignment
    is_current      INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_assignments_ticket  ON ticket_assignments (ticket_id);
CREATE INDEX IF NOT EXISTS idx_assignments_current ON ticket_assignments (is_current);

-- ── 9c. ticket_conversations ──────────────────────────────────────────────────
-- One row per ticket that AURA has commented on. Tracks the ongoing
-- conversation with the reporter so the conversation_watcher job knows
-- whether a new reply has arrived and when to give up waiting (idle timeout).
CREATE TABLE IF NOT EXISTS ticket_conversations (
    tenant_id            TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    ticket_id            TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','resolved')),
    reporter_account_id  TEXT,
    last_aura_comment_at TEXT NOT NULL,
    turn_count           INTEGER NOT NULL DEFAULT 1,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    PRIMARY KEY (tenant_id, ticket_id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_status ON ticket_conversations (status);

-- ── 10. sla_events ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sla_events (
    sla_id          TEXT PRIMARY KEY,   -- UUID
    tenant_id       TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    ticket_id       TEXT NOT NULL,
    category        TEXT NOT NULL,
    deadline        TEXT NOT NULL,      -- ISO-8601 UTC
    warning_sent_at TEXT,
    breached_at     TEXT,
    created_at      TEXT NOT NULL,
    -- Same reasoning as low_confidence_queue above.
    UNIQUE (tenant_id, ticket_id)
);

CREATE INDEX IF NOT EXISTS idx_sla_deadline ON sla_events (deadline);

-- ── 11. ingestion_runs ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id          TEXT PRIMARY KEY,   -- UUID
    tenant_id       TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    tickets_fetched INTEGER NOT NULL DEFAULT 0,
    tickets_indexed INTEGER NOT NULL DEFAULT 0,
    tickets_skipped INTEGER NOT NULL DEFAULT 0,
    chunks_created  INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','completed','failed')),
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_started ON ingestion_runs (started_at);

-- ── 11b. chat_sessions ────────────────────────────────────────────────────────
-- One row per Live Chat conversation. A user has at most one 'active'
-- session at a time — closing it (POST /chat/close) starts a fresh one on
-- the next message, with no memory of the closed conversation.
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id  TEXT PRIMARY KEY,   -- UUID
    tenant_id   TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    created_at  TEXT NOT NULL,
    closed_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_status ON chat_sessions (user_id, status);

-- ── 12. chat_messages ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id  TEXT PRIMARY KEY,   -- UUID
    tenant_id   TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    ticket_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    session_id  TEXT REFERENCES chat_sessions (session_id),  -- NULL for legacy pre-session rows
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    citations   TEXT NOT NULL DEFAULT '[]',   -- JSON
    timestamp   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_ticket    ON chat_messages (ticket_id);
CREATE INDEX IF NOT EXISTS idx_chat_timestamp ON chat_messages (timestamp);
-- idx_chat_session is created in sqlite.py's run_migrations(), after the
-- ALTER TABLE that backfills session_id on databases from before this
-- column existed — creating it here would run before that ALTER TABLE on
-- an existing DB and fail with "no such column: session_id".

-- ── 13b. ticket_status ────────────────────────────────────────────────────────
-- Live Jira workflow status cache (Open / In Progress / Resolved — whatever
-- the connected JSM project's workflow defines). Kept separate from audit_log
-- (append-only, one row per pipeline run) since this is a single current
-- value per ticket that gets overwritten as the ticket moves through Jira.
CREATE TABLE IF NOT EXISTS ticket_status (
    tenant_id  TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    ticket_id  TEXT NOT NULL,
    status     TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, ticket_id)
);

-- ── 13. user_submitted_tickets ────────────────────────────────────────────────
-- Records which AURA end-user account submitted each JSM ticket via POST
-- /tickets/submit, so the end-user dashboard can show "my tickets" — nothing
-- in audit_log or JSM's own data links a ticket back to the AURA account
-- that raised it.
CREATE TABLE IF NOT EXISTS user_submitted_tickets (
    tenant_id    TEXT NOT NULL REFERENCES tenants (tenant_id) ON DELETE CASCADE,
    ticket_id    TEXT NOT NULL,
    user_id      TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    submitted_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, ticket_id)
);

CREATE INDEX IF NOT EXISTS idx_submitted_user   ON user_submitted_tickets (user_id);
