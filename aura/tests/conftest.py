"""Shared pytest fixtures for AURA test suite.

Fixtures provided:
  - settings         : Settings instance backed by env vars / defaults
  - db_session       : In-memory SQLite AsyncSession with all 12 tables created
  - mock_qdrant      : MagicMock replacing AsyncQdrantClient
  - mock_jsm         : respx router that intercepts all JSM HTTPX calls
  - mock_embedder    : GeminiEmbedder with Gemini API replaced by a stub
  - sample_ticket    : A fully-populated JSMTicket for reuse
  - sample_tickets   : List of 3 JSMTicket instances
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Force test env vars before any app module is imported ─────────────────────
# ITSM credentials are no longer process-level Settings — they're per-tenant,
# encrypted in platform_config, and set explicitly by whichever test needs
# them (see mock_jsm_search / individual test fixtures).
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-32-chars-minimum!!")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("SQLITE_DB_PATH", ":memory:")

from app.core.config import Settings, get_settings
from app.models.jsm import JSMComment, JSMTicket

# Constant tenant_id auto-seeded into every db_session (see below) and used
# by base_state — most tests don't need to think about tenants at all.
SAMPLE_TENANT_ID = "test-tenant-1"


# ── Settings ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


# ── In-memory SQLite database ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Yield a transactional AsyncSession backed by an in-memory SQLite DB.

    All 12 tables are created fresh for each test; the DB is discarded after.
    """
    from pathlib import Path
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    migration_sql = (
        Path(__file__).parent.parent
        / "app" / "db" / "migrations" / "init_schema.sql"
    ).read_text(encoding="utf-8")

    from sqlalchemy import text as sa_text

    statements = [
        stmt.strip()
        for stmt in migration_sql.split(";")
        if any(
            line.strip() and not line.strip().startswith("--")
            for line in stmt.splitlines()
        )
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(sa_text(stmt))

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # Every tenant-scoped table FKs to `tenants` and FK enforcement is on
        # by default for this driver/SQLite build — seed the one tenant most
        # tests implicitly assume (SAMPLE_TENANT_ID, matching base_state's
        # tenant_id) so `INSERT INTO category_config (tenant_id, ...)` etc.
        # doesn't need every test file to seed a tenants row itself.
        now = datetime.now(timezone.utc).isoformat()
        await session.execute(
            sa_text(
                "INSERT INTO tenants (tenant_id, name, status, itsm_provider, created_at, updated_at) "
                "VALUES (:tid, 'Test Tenant', 'active', 'jira', :now, :now)"
            ),
            {"tid": SAMPLE_TENANT_ID, "now": now},
        )
        await session.execute(
            sa_text("INSERT INTO platform_config (tenant_id, updated_at) VALUES (:tid, :now)"),
            {"tid": SAMPLE_TENANT_ID, "now": now},
        )
        await session.commit()
        yield session

    await engine.dispose()


# ── Mock Qdrant client ────────────────────────────────────────────────────────

@pytest.fixture
def mock_qdrant():
    """Replace the module-level Qdrant client with a MagicMock."""
    client = MagicMock()
    client.scroll = AsyncMock(return_value=([], None))   # no duplicates by default
    client.upsert = AsyncMock(return_value=None)
    client.get_collections = AsyncMock(
        return_value=MagicMock(collections=[])
    )
    # ensure_tenant_collection() -> _ensure_collection() calls create_collection()
    # whenever get_collections() doesn't already list the tenant's collection
    # (as above, it never does) — must be an AsyncMock or `await` raises TypeError.
    client.create_collection = AsyncMock(return_value=None)

    # _ensured_collections is a module-level cache that persists across tests
    # in the same process — clear it so a collection "created" against this
    # test's mock client isn't skipped as already-ensured in a later test.
    from app.db import qdrant_client as _qdrant_client_module
    _qdrant_client_module._ensured_collections.clear()

    with patch("app.db.qdrant_client._client", client), \
         patch("app.rag.ingestion_pipeline.get_qdrant_client", return_value=client):
        yield client


# ── Mock JSM HTTPX client ─────────────────────────────────────────────────────

@pytest.fixture
def mock_jsm_search(sample_tickets):
    """Patch get_itsm_client().search_tickets to return sample_tickets without HTTP."""
    with patch(
        "app.rag.ingestion_pipeline.get_itsm_client"
    ) as mock_cls:
        instance = AsyncMock()
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        instance.search_tickets = AsyncMock(return_value=sample_tickets)
        mock_cls.return_value = instance
        yield instance


# ── Mock Gemini embedder ──────────────────────────────────────────────────────

@pytest.fixture
def mock_embedder():
    """GeminiEmbedder with _embed_batch replaced by a deterministic stub.

    Returns 768-dim vectors of value 0.1 * (1 + batch_index).
    BM25 fitting and sparse vectors are still real (pure Python).
    """
    from app.rag.embedder import GeminiEmbedder

    embedder = GeminiEmbedder.__new__(GeminiEmbedder)
    embedder._model = "models/gemini-embedding-2"
    embedder._batch_size = 100
    embedder._corpus = None

    async def _stub_embed_batch(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 768 for _ in texts]

    embedder._embed_batch = _stub_embed_batch
    return embedder


# ── Phase 1: shared node-test fixtures ───────────────────────────────────────

@pytest.fixture
def mock_get_session(db_session):
    """Patch every node's `get_session` import to return the test db_session.

    Nodes call `async with get_session() as db: ...` internally.  This fixture
    replaces that context-manager factory with one that yields the in-memory
    test session so node tests run against a real (in-memory) DB.
    """
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    @asynccontextmanager
    async def _get_session():
        yield db_session

    targets = [
        "app.agents.nodes.triage_node.get_session",
        "app.agents.nodes.assignment_node.get_session",
        "app.agents.nodes.collision_node.get_session",
        "app.agents.nodes.autonomy_node.get_session",
        "app.agents.nodes.sla_node.get_session",
        "app.agents.nodes.abstention_node.get_session",
        "app.agents.nodes.confidence_gate_node.get_session",
        "app.agents.nodes.audit_finalizer_node.get_session",
        "app.services.transition_service.get_session",
        "app.db.sqlite.get_session",
    ]
    patches = [patch(t, _get_session) for t in targets]
    for p in patches:
        p.start()
    yield db_session
    for p in patches:
        p.stop()


@pytest.fixture
def sample_tenant_id() -> str:
    """Constant tenant_id already seeded (with its tenants + platform_config
    rows) by the db_session fixture itself — use this wherever a test needs
    the id as a value, not a DB row."""
    return SAMPLE_TENANT_ID


@pytest_asyncio.fixture
async def seeded_tenant(db_session) -> str:
    """Alias for sample_tenant_id — kept as its own fixture name for tests
    that want to make the dependency on a real `tenants` row explicit. The
    row itself is already inserted by db_session; this does not insert again."""
    return SAMPLE_TENANT_ID


@pytest.fixture
def base_state() -> dict:
    """Minimal valid AgentState dict for node tests."""
    return {
        "tenant_id": SAMPLE_TENANT_ID,
        "ticket_id": "TEST-100",
        "raw_ticket": {
            "summary": "VPN fails after password reset",
            "description": "Error 691 after AD password change.",
            "priority": "Medium",
            "created": "2024-01-10T08:00:00+00:00",
        },
        "pipeline_halted": False,
        "halt_reason": None,
        "priority": None,
        "priority_method": None,
        "query_embedding": [0.1] * 768,
        "category": "Network",
        "assigned_team": "net-team",
        "assigned_technician": None,
        "assignment_status": None,
        "collision_detected": False,
        "claimed_by": None,
        "auto_comment_enabled": False,
        "sla_deadline": None,
        "sla_status": None,
        "abstained": False,
        "abstention_reason": None,
        "top_retrieval_score": None,
        "retrieved_chunks": None,
        "llm_raw_response": None,
        "confidence_score": None,
        "formatted_comment": None,
        "citations": None,
        "action_taken": None,
        "jsm_comment_id": None,
        "audit_steps": [],
    }


# ── Sample data ───────────────────────────────────────────────────────────────

@pytest.fixture
def sample_ticket() -> JSMTicket:
    return JSMTicket(
        ticket_id="TEST-001",
        summary="VPN not connecting after password reset",
        description="User reports VPN client fails with error 691 after resetting AD password.",
        comments=[
            JSMComment(
                author="Alice",
                body="Checked AD sync — password propagation delayed by ~15 min. Asked user to retry.",
                created=datetime(2024, 1, 10, 9, 0, tzinfo=timezone.utc),
            ),
            JSMComment(
                author="Bob",
                body="User confirmed VPN connects successfully after waiting 20 minutes.",
                created=datetime(2024, 1, 10, 9, 30, tzinfo=timezone.utc),
            ),
        ],
        resolution_note="AD password sync delay resolved issue. No config changes needed.",
        category="Network",
        priority="High",
        status="Done",
        created=datetime(2024, 1, 10, 8, 0, tzinfo=timezone.utc),
        resolved=datetime(2024, 1, 10, 10, 0, tzinfo=timezone.utc),
        assignee="Alice",
    )


@pytest.fixture
def sample_tickets(sample_ticket) -> list[JSMTicket]:
    t2 = JSMTicket(
        ticket_id="TEST-002",
        summary="Printer offline on 3rd floor",
        description="HP LaserJet shows offline in print queue despite being powered on.",
        comments=[
            JSMComment(
                author="Carol",
                body="Restarted print spooler service on the server. Printer back online.",
                created=datetime(2024, 1, 11, 10, 0, tzinfo=timezone.utc),
            ),
        ],
        resolution_note="Print spooler restart resolved the issue.",
        category="Hardware",
        priority="Medium",
        status="Done",
        created=datetime(2024, 1, 11, 9, 0, tzinfo=timezone.utc),
        resolved=datetime(2024, 1, 11, 11, 0, tzinfo=timezone.utc),
        assignee="Carol",
    )
    t3 = JSMTicket(
        ticket_id="TEST-003",
        summary="Empty ticket with no resolution",
        description=None,
        comments=[],
        resolution_note=None,
        category="Software",
        priority="Low",
        status="Done",
        created=datetime(2024, 1, 12, 9, 0, tzinfo=timezone.utc),
        resolved=None,
        assignee=None,
    )
    return [sample_ticket, t2, t3]
