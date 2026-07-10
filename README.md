# AURA — Agentic Unified Resolution Assistant

AURA is an AI-powered ITSM (IT Service Management) automation platform. It watches your Jira Service Management or Zendesk queue, retrieves similar past resolutions from a knowledge base, drafts an answer with an LLM, and — when it's confident enough — posts that answer back to the ticket and moves it forward, all without a human touching it. When it isn't confident, it hands the draft to a technician instead of guessing.

This is a working proof-of-concept: the pipeline, the real-time ops layer, and the five role-based dashboards are all functional end-to-end against a live Jira/Zendesk instance, not a mocked demo.

**Multi-tenant.** One backend, one database, one frontend deployment serves every client. Each client is a *tenant* with its own users, categories, tickets, audit trail, and Qdrant knowledge-base collection — fully isolated from every other tenant. A **master_admin** role sits above all tenants with exactly one job: provisioning tenants and their first admin account. It has zero visibility into any tenant's ticket data.

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture at a glance](#architecture-at-a-glance)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [The agent pipeline (11 nodes)](#the-agent-pipeline-11-nodes)
- [Knowledge base / RAG pipeline](#knowledge-base--rag-pipeline)
- [Real-time ops layer](#real-time-ops-layer)
- [Multi-ITSM support (Jira + Zendesk)](#multi-itsm-support-jira--zendesk)
- [Database](#database)
- [API surface](#api-surface)
- [Frontend](#frontend)
- [Getting started](#getting-started)
- [Configuration reference](#configuration-reference)
- [Running the app](#running-the-app)
- [Testing](#testing)
- [Key design decisions & known limitations](#key-design-decisions--known-limitations)

---

## What it does

1. A ticket lands in Jira/Zendesk (submitted by an end-user through AURA itself, or directly in the ITSM tool).
2. A scheduler polls for new/updated tickets and feeds each one into an 11-node LangGraph pipeline.
3. The pipeline scores priority, categorizes the ticket, auto-assigns it to the least-loaded technician on the right team, checks for a concurrent-work collision, computes an SLA deadline, and retrieves similar resolved tickets from a vector knowledge base.
4. If there's no relevant knowledge, AURA **abstains** rather than guessing, and flags the ticket for a human.
5. Otherwise, an LLM drafts a resolution grounded in the retrieved context and self-reports a confidence score.
6. If the category has auto-posting enabled **and** confidence clears the configured threshold, AURA posts the comment itself, registers a rollback record, and starts tracking the conversation for follow-up replies. Otherwise, the draft is queued for a technician to approve, edit, or reject.
7. Every decision — automated or human — is written to an append-only, per-tenant audit log that feeds five role-based dashboards (Master Admin, Admin, Manager, Technician, End User).
8. If a technician disagrees with something AURA auto-posted, they can roll the comment back and post a corrected one, but only after acknowledging the ticket first.

## Architecture at a glance

```
                     ┌─────────────────────┐
   Jira/Zendesk  ───▶│   jsm_poller (5m)    │──▶ AgentState ──▶ LangGraph (11 nodes) ──▶ audit_log
                     └─────────────────────┘                         │
                                                                      ▼
                                                        comment posted / queued for review
                                                                      │
        ┌─────────────────────────────────────────────────────────────┘
        ▼
  WebSocket notification_bus ──▶ React Query cache invalidation ──▶ live dashboards

  Ingestion (every 6h) ── resolved tickets ──▶ Chunker ──▶ Gemini embeddings ──▶ Qdrant (RAG corpus)
```

Everything runs as one FastAPI process: the API, the APScheduler background jobs, and the WebSocket server share the same app instance and the same SQLite database.

## Tech stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI (async, Python 3.14) |
| Agent orchestration | LangGraph (`StateGraph`) |
| LLM (triage + resolution) | Qwen3-8B via an OpenAI-compatible endpoint (Ollama or a remote vLLM server — env vars are still named `OLLAMA_*` for historical reasons) |
| Embeddings | Google Gemini `gemini-embedding-2` (768-dim via Matryoshka truncation) |
| Vector store | Qdrant (hybrid dense + BM25 sparse vectors) |
| Relational store | SQLite (async via SQLAlchemy + `aiosqlite`), raw SQL — no ORM models, no Alembic |
| Scheduler | APScheduler (in-process background jobs) |
| Auth | JWT access tokens + httpOnly refresh cookie, bcrypt password hashing |
| Frontend | React 18 + TypeScript + Vite |
| Frontend state | TanStack React Query (server state) + Zustand (auth/theme/notifications) |
| Frontend styling | Tailwind CSS, shadcn-style components copied inline (not installed as a package) |
| Realtime | Native WebSocket, one connection per logged-in user |
| ITSM integration | Jira Service Management REST API and/or Zendesk REST API, switchable at runtime |

## Repository layout

```
ITSM/
├── aura/                        # Backend (FastAPI)
│   ├── app/
│   │   ├── agents/              # LangGraph nodes + graph wiring
│   │   ├── api/v1/routes/       # All HTTP routes
│   │   ├── core/                # Settings, security, logging, rate limiting
│   │   ├── db/                  # SQLite engine + migrations, Qdrant client
│   │   ├── models/              # Pydantic schemas (no ORM)
│   │   ├── rag/                 # Chunker, embedder, retriever, ingestion pipeline
│   │   └── services/            # Assignment, collision, SLA, rollback, conversation, ITSM clients...
│   ├── scheduler/jobs/          # APScheduler jobs (polling, SLA checks, ingestion, etc.)
│   ├── tests/                   # pytest suite (240 tests)
│   ├── aura.db                  # SQLite DB — every tenant lives in this one file
│   └── .env / .env.example
├── frontend/                    # React + Vite SPA
│   └── src/
│       ├── pages/{admin,manager,technician,enduser}/
│       ├── components/          # Shared UI primitives + layout shell
│       ├── store/                # Zustand stores (auth, config, notifications, toast)
│       ├── api/                  # Typed API client modules
│       └── hooks/                # useAuth, useWebSocket, useKillSwitchStatus, ...
├── files (1)/                   # Sample knowledge-base articles (multiple formats) for ingestion testing
├── docker-compose.yml           # Qdrant container
└── CLAUDE.md                    # Instructions for AI coding agents working in this repo
```

## The agent pipeline (11 nodes)

Defined in `aura/app/agents/graph.py`, one file per node under `aura/app/agents/nodes/`. LangGraph's `StateGraph` carries a shared `AgentState` (a `TypedDict`) through the following path:

```
kill_switch → priority_scorer → triage → assignment → collision → autonomy
  → sla → abstention → resolution → confidence_gate → audit_finalizer
```

`audit_finalizer` is terminal and always runs — every ticket, halted early or not, gets one row in the audit log.

| Node | What it does |
|---|---|
| **kill_switch** | Checks an in-process cached flag (`platform_config.aura_enabled`). If AURA is globally disabled, halts immediately. |
| **priority_scorer** | Two-stage: hardcoded keyword rules first (CRITICAL/HIGH/LOW), then a semantic fallback that queries Qdrant for the 3 most similar resolved tickets and takes the majority priority. Always embeds the ticket text and caches the vector in state so later nodes don't re-embed. |
| **triage** | Calls the LLM to classify the ticket into one of the admin-configured categories, with a confidence floor (0.5) below which it falls back to `"Other"`. Looks up the category's owning team. |
| **assignment** | Assigns the least-loaded active technician on that team via `assignment_service`, and sets Jira's/Zendesk's native assignee field. Never halts the pipeline — records a status (`assigned`, `no_technician_available`, `skipped_no_team`, etc.) either way. |
| **collision** | Checks whether another technician already has an active claim on this ticket. Informational only. |
| **autonomy** | Reads the category's `auto_comment_enabled` toggle from the DB. OFF means "always queue for human review, no matter how confident AURA is." |
| **sla** | Computes a deadline from the category's configured SLA minutes (default 8h), and flags warning (≥75% elapsed) / breach (≥100%) states. |
| **abstention** | A pure vector-search gate — no LLM call. If the top Qdrant match score is below the abstention threshold (default 0.60), AURA halts and flags the ticket as "no relevant knowledge" rather than letting the LLM invent an answer. |
| **resolution** | Retrieves the top-5 relevant chunks (dense + BM25-reranked) from Qdrant, builds a grounded prompt, and asks the LLM for a resolution and a self-reported confidence score (0–1). Filters out any hallucinated ticket-ID citations. |
| **confidence_gate** | The auto-post-or-queue decision: if `auto_comment_enabled` AND `confidence ≥ threshold` (default 0.90), posts the comment, registers a rollback record, and starts conversation tracking. Otherwise writes to the `low_confidence_queue` for a technician. This logic is factored into a standalone function (`apply_confidence_gate`) so multi-turn conversation replies reuse the exact same rule. |
| **audit_finalizer** | Assembles everything the run produced into one `AuditEntry` and writes it, plus updates the cached ticket status. Runs unconditionally, from every halt path. |

## Knowledge base / RAG pipeline

1. **Ingestion** (`app/rag/ingestion_pipeline.py`, triggered manually or every N hours by the scheduler): fetches resolved tickets since the last cursor, skips ones already indexed, chunks each into up to 3 pieces (`title_desc`, windowed `comments`, `resolution`), fits a BM25 model over the batch, embeds everything with Gemini, and upserts dual (dense + sparse) vectors into Qdrant with deterministic UUID5 point IDs (so re-running is idempotent).
2. Document upload (PDF/DOCX/etc.) follows the same chunk → embed → upsert path via `markitdown` conversion to Markdown first.
3. **Retrieval** (`app/rag/retriever.py`): dense search against Qdrant's `resolved_tickets` collection, then a BM25 rerank over the candidate set, fused via Reciprocal Rank Fusion.
4. Every ticket's query embedding is computed once (in `priority_scorer`) and reused by `abstention` and `resolution` to avoid redundant embedding API calls.

## Real-time ops layer

Backend services (`app/services/`) that run independently of a single ticket's pipeline pass, mostly driven by scheduler jobs:

| Service | Job that drives it | Purpose |
|---|---|---|
| `assignment_service` | `assignment_timeout_checker` (1m) | Least-loaded technician lookup; auto-reassigns/escalates if nobody acknowledges in time |
| `collision_service` | `sla_checker` (shares its 5m cadence) | Soft claim locks so two technicians don't duplicate work; auto-expires stale claims |
| `sla_engine` | `sla_checker` (1m) | Registers deadlines, fires one-time warning/breach events |
| `rollback_store` | — | Registers/executes reversible actions (comment posted, status transitioned) with an atomic claim to prevent double-execution |
| `conversation_service` | `conversation_watcher` (5m) | Drives turn-2+ replies from the ticket reporter and auto-closes idle conversations after a configurable timeout |
| `transition_service` | — | Shared Jira/Zendesk status-transition helper (Open → In Progress → Resolved), provider-aware |
| `kill_switch` | — | In-process cached global enable/disable flag, checked on every ticket's hot path with no DB round-trip |
| `notification_bus` | — | In-process WebSocket registry; every other service pushes typed events through it to connected browsers |

All of this is surfaced live in the frontend: a WebSocket event triggers a React Query cache invalidation, so dashboards update without polling.

## Multi-ITSM support (Jira + Zendesk)

AURA isn't hard-wired to Jira. `app/services/itsm_client.py` defines a provider-agnostic `ITSMClient` protocol; `JSMClient` and `ZendeskClient` both implement it. Each *tenant* picks its own provider, stored (and its credentials encrypted at rest) in that tenant's `platform_config` row and cached in-process keyed by `tenant_id` (`itsm_provider_state.py`, `itsm_client.py`), switchable without a restart. Every agent node and service calls `get_itsm_client(tenant_id)` and never imports a concrete client directly, so the whole pipeline is provider-agnostic above the client layer.

A tenant's own admin enters their Jira/Zendesk credentials via the Setup Wizard's connection step — this actually persists them (Fernet-encrypted, keyed from `APP_SECRET_KEY`) into that tenant's `platform_config` row, not just a connectivity test.

## Database

SQLite, 18 tables, no ORM (all access is raw parameterized SQL via SQLAlchemy's `text()`). Migrations are hand-rolled idempotent `ALTER TABLE`/table-recreate statements guarded by `PRAGMA table_info` checks (`app/db/sqlite.py`). Every table except `tenants` and `sessions` carries a `tenant_id` column (or composite key) that every query filters on — `tenants` is the row above them all, and `sessions` ties to a user directly.

| Table | Purpose |
|---|---|
| `tenants` | One row per client organization — name, status (active/suspended), ITSM provider |
| `users` / `sessions` | Accounts (including the platform-wide `master_admin`, `tenant_id = NULL`) and refresh-token sessions |
| `platform_config` | One row per tenant: thresholds, kill switch, ITSM provider + encrypted credentials, branding, polling intervals, setup-wizard state |
| `wizard_progress` | Setup wizard step state |
| `category_config` | Category → team mapping, per-category auto-post toggle and SLA minutes |
| `audit_log` | Append-only decision log — one row per pipeline run; backs every analytics dashboard |
| `rollback_store` | Reversible-action records (comment posts, transitions) |
| `low_confidence_queue` | Draft resolutions awaiting technician review |
| `collision_claims` | Active/expired technician claim locks |
| `ticket_assignments` | Who's assigned, when, and whether they've acknowledged |
| `ticket_conversations` | Turn-tracking state for post-resolution follow-up replies |
| `sla_events` | Per-ticket deadline + warning/breach timestamps |
| `ingestion_runs` | KB ingestion run history |
| `chat_sessions` / `chat_messages` | End-user Live Chat history |
| `ticket_status` | Cached last-known Jira/Zendesk status per ticket |
| `user_submitted_tickets` | Links a ticket back to the AURA end-user who submitted it |

Vector data (the RAG knowledge base) lives separately in **Qdrant** — one collection per tenant, named `resolved_tickets_<tenant_id>`, each with named dense + sparse (`bm25`) vectors per point. Fully isolated: nothing in one tenant's collection is ever visible to a retrieval running for another.

## API surface

All routes under `/api/v1`, grouped by `app/api/v1/routes/`:

| File | Covers |
|---|---|
| `auth.py` | Login / refresh / logout / me (JWT + httpOnly refresh cookie, rotation with reuse detection) |
| `master.py` | master_admin only: list/create/suspend/reactivate tenants, reset a tenant's admin password — zero ticket/audit visibility |
| `setup.py` | First-run setup wizard: status, connection tests, save/progress/complete (per tenant) |
| `admin.py` | Platform config, branding, kill switch, user/category CRUD, rollback history, Qdrant stats/rebuild, document management, audit log export |
| `dashboard.py` | System health, technician stats, and the full Manager analytics suite (SLA, resolution, confidence, team performance, abstention, collisions, cost savings, approvals) |
| `tickets.py` | Ticket list/detail, low-confidence queue, acknowledge, approve/reject/edit a queued draft, roll back and re-post a comment, end-user submission |
| `chat.py` | End-user live chat, RAG-grounded, persisted per session |
| `ingestion.py` / `documents.py` | Trigger/monitor KB ingestion; upload documents into the knowledge base |
| `websocket.py` | `/ws/{user_id}` — the one real-time notification channel every client connects to |

Every route is protected by one of five auth dependencies (`require_any_auth`, `require_technician`, `require_manager`, `require_admin`, `require_master_admin`), enforced server-side — the frontend's role-based routing is a UX convenience, not the security boundary. Every tenant-scoped route additionally filters every query by `current_user["tenant_id"]`; `master_admin` routes take a tenant_id as an explicit path/body parameter instead, since that role has none of its own.

## Frontend

Role-based single-page app, five distinct experiences behind one login:

- **Master Admin** — Tenants: create a client organization + its first admin account, rename, suspend/reactivate, reset a locked-out admin's password. Nothing else — no ticket/audit data of any tenant is ever visible here.
- **Admin** — Dashboard, Users, Categories, Agent Config (thresholds), Kill Switch, Rollback History, Audit Log, Knowledge Index (Qdrant stats/rebuild), System Health, and the 9-step Setup Wizard.
- **Manager** — Dashboard, SLA Compliance, Resolution Analytics, Confidence Analytics, Team Performance, Abstention Report, Collision Log, Cost Savings Report, Approval Queue.
- **Technician** — Dashboard, unified Ticket Queue (acknowledge, view live comment thread, approve/edit/reject AURA's draft, roll back and correct a posted comment).
- **End User** — Dashboard, My Tickets, Submit Ticket, Live Chat.

State management is deliberately split: **React Query** owns all server data (tickets, dashboards, config) with WebSocket-driven cache invalidation for live updates; **Zustand** only holds client-only state (auth session, theme, accent color, notifications, toasts) — there's no separate "ticket store" duplicating what React Query already caches.

## Getting started

### Prerequisites

- Python 3.14 (a `.venv` is expected at repo root)
- Node.js 18+ and npm
- Docker (for Qdrant) — or a Qdrant instance reachable at the URL you configure
- A Jira Service Management **or** Zendesk account with API credentials
- A Google AI Studio (Gemini) API key
- An OpenAI-compatible LLM endpoint (local Ollama running `qwen3:8b`, or a remote vLLM server)

### Backend setup

```powershell
# From the repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1

cd aura
pip install -r requirements.txt
cp .env.example .env      # then fill in your credentials

# Qdrant must be running first (from repo root):
cd ..
docker compose up -d

cd aura
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The first startup runs schema migrations automatically and seeds one bootstrap `master_admin` account (`DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD`, defaulting to `admin@aura.local` / `changeme123`) — log in as that account to create your first tenant. API docs: `http://localhost:8000/docs`.

### Frontend setup

```powershell
cd frontend
npm install
npm run dev
```

App runs at `http://localhost:5173` and expects the backend on `:8000`. On first load it detects an incomplete setup and walks you through the wizard: branding → ITSM connection → categories → teams → agent thresholds → knowledge ingestion → review.

## Configuration reference

Key variables from `aura/.env.example` — see that file for the full annotated list:

```
APP_SECRET_KEY                # 32+ char random string (required)
ITSM_PROVIDER                 # "jira" or "zendesk" — boot-time seed, admin can switch later
JSM_BASE_URL / JSM_PROJECT_KEY / JSM_API_EMAIL / JSM_API_TOKEN
ZEN_SUBDOMAIN / ZEN_API_EMAIL / ZEN_API_TOKEN
GEMINI_API_KEY                # embeddings only, not resolution generation
QDRANT_URL                    # http://localhost:6333
OLLAMA_BASE_URL / OLLAMA_MODEL # OpenAI-compatible LLM endpoint (name kept for historical reasons)
INGESTION_SYNC_INTERVAL_HOURS # default 6
```

Runtime thresholds (confidence, abstention, polling interval, SLA per category) are **not** env-only — they're stored in `platform_config`/`category_config` and adjustable live from the Admin UI without a restart.

## Running the app

1. `docker compose up -d` — starts Qdrant.
2. `uvicorn app.main:app --reload` (from `aura/`) — starts the API, scheduler, and WebSocket server together.
3. `npm run dev` (from `frontend/`) — starts the SPA.
4. Log in with the seeded `master_admin` account: `admin@aura.local` / `changeme123` (overridable via `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD`). Change it immediately — a startup guard actively blocks this insecure default when `APP_ENV=production`.
5. As `master_admin`, create your first tenant (name, ITSM provider, admin email) — this hands back a one-time temporary password for that tenant's admin.
6. Log in as the tenant admin, complete the Setup Wizard (including entering that tenant's real Jira/Zendesk credentials), trigger an initial knowledge ingestion, then either let the scheduler poll your live ITSM queue or submit test tickets through the End User "Submit Ticket" page.

## Testing

```powershell
cd aura
.\..\.venv\Scripts\Activate.ps1
python -m pytest tests/ -v
```

240 tests across `test_rag/`, `test_agents/` (one file per node), `test_api/`, `test_scheduler/`, and `test_services/`. Every test seeds a `tenants` row and threads `tenant_id` through fixtures — nothing exercises a "no tenant" code path except the master_admin-specific tests. Fixtures stub out the Gemini API, Qdrant, and JSM/Zendesk HTTP calls — BM25 runs for real. The frontend currently has no automated test suite; verify UI changes manually against a running backend.

Lint:
```powershell
ruff check . --fix
```

## Key design decisions & known limitations

Documented here deliberately, since this is a POC under active iteration:

- **No ORM, no Alembic.** All persistence is raw parameterized SQL; schema changes are hand-written idempotent `ALTER TABLE` migrations. Simple, but every new column needs manual migration code.
- **Duplicate-ticket detection was removed.** An earlier design included a `duplicate_detector` node; it's been fully removed from the codebase (not just disabled) because it wasn't part of the intended product surface. Collision detection (concurrent technician claims on the *same* ticket) is unrelated and still fully functional.
- **Acknowledge-before-post is enforced.** A technician cannot approve, edit-and-post, or roll back/re-post a comment until they've acknowledged the ticket — this is checked server-side, not just hidden in the UI, and applies uniformly whether the comment came from the queue or from AURA's auto-post path.
- **Auto-posted comments aren't duplicated in AURA's own database.** The comment thread shown in the UI is a best-effort live fetch from Jira/Zendesk on every ticket-detail view, not a local cache — so it's always accurate but adds one external API call per view.
- **Single-process assumptions.** The kill switch cache, the WebSocket connection registry, and the assignment race-lock are all in-process (`asyncio.Lock` / plain dict). Fine for a single backend instance; would need rework to run multiple API workers behind a load balancer.
- **Two separate LLM backends.** Gemini is used only for embeddings; all text generation (triage classification, resolution drafting) goes through a separate Qwen3-8B endpoint. Don't assume one provider covers both.
- **Setup Wizard credentials are cosmetic today.** ITSM connection testing in the wizard doesn't actually wire up the credentials used at runtime — those still come from environment variables.

---

For AI coding agents working in this repo, see `CLAUDE.md` for environment activation steps and command shortcuts.
