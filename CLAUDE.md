# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

A Python 3.14.5 virtual environment is pre-configured at `.venv/`. Activate it before running any Python commands:

```powershell
.\.venv\Scripts\Activate.ps1
```

All Python commands below assume the venv is active and `cd aura` has been run first.

## Commands

### Run tests
```powershell
python -m pytest tests/ -v
python -m pytest tests/test_rag/test_chunker.py -v          # single module
python -m pytest tests/test_rag/test_chunker.py::test_name -v  # single test
```

### Lint
```powershell
ruff check . --fix
```

### Start the app
```powershell
# Qdrant must be running first (from repo root):
docker compose up -d

# Then start FastAPI:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

## Architecture

**AURA** (Agentic Unified Resolution Assistant) is an AI-powered ITSM platform. Phase 0 (knowledge ingestion) is complete; Phase 1 (LangGraph agent pipeline, 12 nodes) is complete; Phase 2 frontend Layers 1–6 are complete; Phase 3 (real-time ops layer — assignment, collision detection, SLA tracking, rollback, ongoing conversation loop, WebSocket notifications, kill switch) is complete. Post-launch UX polish (branding, bug fixes, dashboard improvements) is also complete. 191 backend tests passing.

### Phase 0: Ingestion Pipeline

The core flow runs on a configurable schedule (default every 6 hours):

1. Read cursor timestamp from `platform_config` (SQLite)
2. Fetch resolved JSM tickets since cursor via paginated REST API
3. Skip duplicates already in Qdrant (`resolved_tickets` collection)
4. Chunk each ticket into 1–3 chunks: `title_desc`, `comments` (windowed at 512 tokens/50 overlap), `resolution`
5. Fit BM25 over all chunks, embed with Gemini `models/gemini-embedding-2` (768-dim via Matryoshka truncation, batched 100/call — `text-embedding-004` was deprecated/renamed)
6. Upsert dual-vector points to Qdrant (dense + sparse per chunk)
7. Write `IngestionAuditEntry` to SQLite, advance cursor

Entry point: `aura/app/api/v1/routes/ingestion.py` → `POST /api/v1/ingestion/trigger` kicks off `IngestionPipeline.run()` in `aura/app/rag/ingestion_pipeline.py`.

Document upload (`POST /api/v1/ingestion/documents`) converts PDF/DOCX → Markdown via `markitdown`, then follows the same chunk/embed/upsert path.

### Key Modules

| Path | Purpose |
|------|---------|
| `app/core/config.py` | Pydantic `Settings` — all env vars validated at startup |
| `app/db/sqlite.py` | Async SQLAlchemy engine; 12 tables defined in `db/migrations/init_schema.sql` |
| `app/db/qdrant_client.py` | Qdrant singleton; collections `resolved_tickets` (knowledge base) + `open_tickets` (duplicate detection) |
| `app/rag/chunker.py` | `TicketChunker` — produces `TicketChunk` objects |
| `app/rag/embedder.py` | `GeminiEmbedder` — dense vectors + BM25 sparse vectors |
| `app/rag/ingestion_pipeline.py` | `IngestionPipeline` — 10-step orchestration |
| `app/services/jsm_client.py` | Async HTTPX wrapper for Jira Service Management REST API |
| `scheduler/jobs/ingestion_sync.py` | APScheduler job that triggers the ingestion pipeline |

### Phase 3: Real-Time Ops Services

Backs the agent graph nodes below and runs independently via the scheduler.

| Path | Purpose |
|------|---------|
| `app/services/assignment_service.py` | Least-loaded active technician lookup per team; used by `assignment_node` |
| `app/services/collision_service.py` | Tracks active claims on a ticket to warn of concurrent technician work |
| `app/services/sla_engine.py` | Computes SLA deadlines from category config, registers `sla_events`, fires warning/breach events |
| `app/services/rollback_store.py` | Records reversible actions (e.g. JSM comment posts) so they can be undone |
| `app/services/conversation_service.py` | Drives turn-2+ chat replies and status transitions after initial auto-resolution |
| `app/services/transition_service.py` | Jira status transition helper (Open → In Progress → Resolved) |
| `app/services/kill_switch.py` | In-process cached global enable/disable flag for the agent pipeline |
| `app/services/notification_bus.py` | Broadcasts events to connected clients; backs `app/api/v1/routes/websocket.py` |
| `scheduler/jobs/jsm_poller.py` | Polls JSM for new/updated tickets to feed into the graph |
| `scheduler/jobs/sla_checker.py` | Periodic sweep for SLA warning/breach thresholds |
| `scheduler/jobs/assignment_timeout_checker.py` | Reassigns tickets whose technician hasn't acted in time |
| `scheduler/jobs/conversation_watcher.py` | Polls for reporter replies to drive `conversation_service` |

### Data Flow

```
JSM REST API → JSMClient → IngestionPipeline → Chunker → GeminiEmbedder → Qdrant
                                      ↓
                                  SQLite (audit log, cursor)
```

### Design Patterns

- **Async throughout**: `AsyncSession`, `httpx.AsyncClient`, `AsyncIOScheduler`; all tests use `asyncio_mode = "auto"`
- **Dependency injection**: FastAPI `Depends()` for DB session and settings in every route
- **Retry with backoff**: `tenacity` wraps Gemini API calls to handle 429s
- **Deterministic IDs**: Qdrant point IDs are UUID5 derived from `chunk_id`, preventing duplicates on re-run
- **Structured logging**: `structlog` with JSON in production, colored in dev

### SQLite Tables (12)

`users`, `sessions`, `platform_config` (single-row config + cursor), `wizard_progress`, `category_config`, `audit_log`, `rollback_store`, `low_confidence_queue`, `collision_claims`, `sla_events`, `ingestion_runs`, `chat_messages`

### Configuration

Key `.env` variables (see `aura/.env.example`):

```
APP_SECRET_KEY          # 32+ char random string (required)
GEMINI_API_KEY          # Google AI Studio key
JSM_BASE_URL            # https://your-domain.atlassian.net
JSM_PROJECT_KEY         # e.g. ITSM
JSM_API_EMAIL / JSM_API_TOKEN
QDRANT_URL              # http://localhost:6333
INGESTION_SYNC_INTERVAL_HOURS  # default 6
OLLAMA_BASE_URL / OLLAMA_MODEL # points at a remote vLLM server (Qwen2.5-32B-Instruct-GPTQ-Int8); name kept as OLLAMA_* for historical consistency, not actually local Ollama
```

Current `.env` (not `.env.example`) is wired to a real, live Jira Service Management domain and a real remote LLM endpoint — this is not a mocked/placeholder setup.

Missing required vars raise `ValidationError` on startup.

## Test Structure

```
aura/tests/
├── conftest.py           # db_session, mock_qdrant, mock_jsm_search, mock_embedder fixtures
├── test_rag/             # chunker, embedder, ingestion_pipeline, document_ingestion, retriever
├── test_agents/          # one file per graph node (12 files)
├── test_api/             # admin audit export, documents, qdrant stats, user email update,
│                          # ticket approve/transition, websocket team registration
├── test_scheduler/       # jsm_poller, assignment_timeout_checker, conversation_watcher
└── test_services/        # kill_switch, collision, sla_engine, transition, assignment,
                           # rollback_store, conversation_service
```

191 tests passing (`python -m pytest tests/ --collect-only -q` to recount). Fixtures stub out Gemini API, Qdrant, and JSM HTTP calls. BM25 runs for real in tests.

## Phase 1 (Complete)

LangGraph `StateGraph` in `app/agents/graph.py` with 12 nodes, one file per node under `app/agents/nodes/`:

```
kill_switch → priority_scorer → duplicate_detector → triage → assignment → collision
  → autonomy → sla → abstention → resolution → confidence_gate → audit_finalizer
```

Conditional routing after `kill_switch`, `duplicate_detector`, `autonomy`, and `abstention` jumps straight to `audit_finalizer` (terminal node, always runs, persists the full `AuditEntry` with all `audit_steps`).

Key node behaviors:
- **assignment_node** — looks up the least-loaded active technician for the ticket's team via `assignment_service`, resolves their `jira_account_id`, and calls `JSMClient.assign_ticket()` to set Jira's native Assignee. Never halts the graph; records a status (`assigned`, `skipped_no_team`, `no_technician_available`, `no_jira_account_mapped`, `jsm_error`) instead.
- **duplicate_detector_node** — on high similarity against `open_tickets`, queues a proposed dedup comment for technician review and halts; never auto-posts.
- **autonomy_node** — a single per-category `auto_comment_enabled` toggle (replaces an earlier tiered design). OFF always queues for review; ON unlocks confidence-based auto-post and Jira status transitions.
- **abstention_node** — halts before calling the resolution LLM if top retrieval similarity is below `abstention_threshold` (default 0.60).
- **confidence_gate_node** — logic factored into `apply_confidence_gate()` so `conversation_service` can reuse it for turn-2+ chat replies. High confidence + autonomy ON: posts a JSM comment, registers a rollback record, starts conversation tracking. Otherwise: queues to `low_confidence_queue`.

`audit_steps` uses LangGraph's `Annotated[list, operator.add]` reducer — nodes only ever return `{"audit_steps": [step]}`, never mutate the accumulated list directly.

## API Surface (`app/api/v1/routes/`)

| File | Area |
|------|------|
| `auth.py` | login/refresh/logout/me (JWT + httpOnly refresh cookie) |
| `setup.py` | setup wizard status/save/progress/complete |
| `admin.py` | platform config, branding, kill switch, user/category CRUD, rollback, Qdrant stats/rebuild, documents, audit log export (largest file, ~25 routes; `/admin/audit` and `/admin/audit/export` are intentional back-compat aliases, kept alive by regression tests — do not remove) |
| `dashboard.py` | system health, technician stats, manager analytics (SLA compliance, resolution/confidence analytics, team performance, abstention report, duplicate/collision log, cost savings, approval queue) |
| `tickets.py` | ticket list/detail, low-confidence queue, acknowledge/approve/reject/edit, submission |
| `chat.py` | end-user live chat, RAG-grounded, persisted to `chat_messages` |
| `ingestion.py` / `documents.py` | JSM sync trigger/status/runs; PDF/DOCX upload pipeline |
| `websocket.py` | `/ws/{user_id}` real-time notification channel |

---

## Phase 2: Frontend (Vite + React)

**Directory:** `C:\Users\DhruvPatel\ITSM\frontend\`

### Layer status
| Layer | Status |
|-------|--------|
| L1 — Scaffold + Theme + Auth + App Shell | ✅ COMPLETE |
| L2 — Setup Wizard (8 steps, incl. Branding) | ✅ COMPLETE |
| L3 — Admin Pages | ✅ COMPLETE |
| L4 — Manager Pages | ✅ COMPLETE |
| L5 — Technician Pages | ✅ COMPLETE |
| L6 — End User Pages | ✅ COMPLETE |
| Post-launch UX Polish | ✅ COMPLETE |

### Frontend Commands

```powershell
# From repo root:
cd frontend

# Install dependencies (already done)
npm install

# Start Vite dev server (requires backend running on :8000)
npm run dev
# → http://localhost:5173

# TypeScript type check (0 errors expected)
npx tsc --noEmit

# Build for production
npm run build
```

### Key frontend files

| Path | Purpose |
|------|---------|
| `frontend/src/App.tsx` | Root — checks setup status, routes by role; fetches branding on login |
| `frontend/src/store/configStore.ts` | Zustand: theme, accent, kill switch, companyName, companyLogo; `DEFAULT_ACCENT` exported |
| `frontend/src/store/` | authStore, ticketStore, notificationStore |
| `frontend/src/api/` | client.ts, auth.api.ts, setup.api.ts, admin.api.ts, dashboard.api.ts, tickets.api.ts, ingestion.api.ts, chat.api.ts |
| `frontend/src/hooks/` | useAuth, useWebSocket, useKillSwitchStatus, useNotifications |
| `frontend/src/components/layout/AppShell.tsx` | Sidebar + TopBar + SuspendedBanner (flow, not fixed) + Outlet |
| `frontend/src/components/layout/Sidebar.tsx` | Collapsible; Zap icon + "AURA" text when expanded; no client branding |
| `frontend/src/components/layout/TopBar.tsx` | AURA (Zap + "AURA") on left; client logo + name + controls on right |
| `frontend/src/components/layout/SuspendedBanner.tsx` | Full-width red bar in normal flow (not fixed/overlay) |
| `frontend/src/utils/colorExtractor.ts` | Canvas-based dominant color extraction; returns `null` accent for greyscale logos |
| `frontend/src/utils/formatters.ts` | formatRelativeTime, formatDateTime, hexToRgbString, lightenHex |
| `frontend/src/utils/constants.ts` | ROLES, ROLE_NAV, WS_EVENTS, ACCENT_PRESETS |

### Design constraints
- Minimalistic and clean; no extraneous decoration
- Light + dark mode via Tailwind `class` strategy; `configStore.setTheme()` toggles
- Accent colour: CSS variables `--accent` / `--accent-hover`; default AURA green `#3db549` / hover `#5dd669`
- Client company logo and accent derived from logo upload in Setup Wizard Step 2; stored in `platform_config` and `localStorage`
- `GET /admin/branding` fetched on login for all roles — applies client accent and shows company logo in TopBar
- Shadcn-style components copied inline — not installed as a package

### Branding layout
- **TopBar left:** Zap icon in accent box + "AURA" text (product identity, always present)
- **TopBar right:** client company logo + company name (when set) → divider → kill switch pill → theme toggle → notifications → logout
- **Sidebar:** Zap icon + "AURA" text when expanded; Zap icon only when collapsed; no client branding

### Backend changes from UX polish session
| File | Change |
|------|--------|
| `aura/app/db/migrations/init_schema.sql` | Added `company_name`, `company_logo`, `accent_color` columns to `platform_config` |
| `aura/app/db/sqlite.py` | `run_migrations()` uses `PRAGMA table_info` to safely add new columns on existing DBs |
| `aura/app/models/api_schemas.py` | `PlatformConfigResponse` + `BrandingResponse` include branding fields; `SystemHealthResponse` includes `polling_interval_minutes` |
| `aura/app/api/v1/routes/admin.py` | `GET /admin/branding` (any auth); `PUT /admin/config` now reschedules APScheduler jobs live when `polling_interval_minutes` or `ingestion_interval_hours` change |
| `aura/app/api/v1/routes/setup.py` | `complete()` reads step 2 branding; step indices shifted +1 for all steps after new Branding step |
| `aura/app/api/v1/routes/dashboard.py` | Health endpoint reads `polling_interval_minutes` from `platform_config` (not env var) |
