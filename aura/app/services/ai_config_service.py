"""Per-tenant AI (embedding + LLM) provider config — factory + in-process cache.

Mirrors app.services.itsm_client's shape: credentials live encrypted in
platform_config, decrypted once into an in-process cache at startup
(init_ai_config), refreshed after any test-and-persist write
(refresh_tenant_ai_config), and read synchronously off the hot path
(get_ai_config).

Deliberate divergence from get_itsm_client: get_ai_config() never raises for
an unconfigured tenant — it returns a ResolvedAIConfig with every field None,
which is the ordinary "not configured" state app.agents.nodes.ai_config_gate_node
branches on. get_embedder()/get_llm_client() below DO raise — they're a
defensive backstop for code paths that should be unreachable once the gate
has already run, not something callers are expected to catch routinely.
"""

import asyncio
from dataclasses import dataclass

from openai import AsyncOpenAI
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt
from app.core.logging import get_logger
from app.rag.embedder_base import Embedder

log = get_logger(__name__)

_DEFAULT_GEMINI_MODEL = "models/gemini-embedding-2"
_DEFAULT_GEMINI_VECTOR_SIZE = 768


@dataclass
class ResolvedAIConfig:
    tenant_id: str
    embedding_provider: str | None          # "gemini" | "openai_compatible" | None
    embedding_api_key: str | None            # decrypted
    embedding_base_url: str | None           # only meaningful for openai_compatible
    embedding_model: str | None
    embedding_vector_size: int | None
    llm_base_url: str | None
    llm_model: str | None
    llm_api_key: str | None                  # decrypted

    @property
    def embeddings_configured(self) -> bool:
        if self.embedding_provider == "gemini":
            return bool(self.embedding_api_key)
        if self.embedding_provider == "openai_compatible":
            return bool(
                self.embedding_api_key
                and self.embedding_base_url
                and self.embedding_model
                and self.embedding_vector_size
            )
        return False

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)   # llm_api_key optional — many self-hosted endpoints need none

    @property
    def resolved_embedding_model(self) -> str:
        return self.embedding_model or _DEFAULT_GEMINI_MODEL

    @property
    def resolved_embedding_vector_size(self) -> int:
        return self.embedding_vector_size or _DEFAULT_GEMINI_VECTOR_SIZE


# In-process cache of each tenant's DECRYPTED AI config, keyed by tenant_id.
# Populated at startup (init_ai_config) and refreshed whenever a tenant's
# embedding/LLM connection is tested-and-saved (setup wizard / admin
# Integrations page) — see refresh_tenant_ai_config(). Never persisted
# outside this process; the encrypted form is what lives in the DB.
_configs: dict[str, ResolvedAIConfig] = {}
_lock = asyncio.Lock()

_AI_CONFIG_COLUMNS = (
    "embedding_provider", "embedding_api_key_encrypted", "embedding_base_url",
    "embedding_model", "embedding_vector_size",
    "llm_base_url", "llm_model", "llm_api_key_encrypted",
)


def _decrypt_row(tenant_id: str, row) -> ResolvedAIConfig:
    return ResolvedAIConfig(
        tenant_id=tenant_id,
        embedding_provider=row["embedding_provider"],
        embedding_api_key=decrypt(row["embedding_api_key_encrypted"]),
        embedding_base_url=row["embedding_base_url"],
        embedding_model=row["embedding_model"],
        embedding_vector_size=row["embedding_vector_size"],
        llm_base_url=row["llm_base_url"],
        llm_model=row["llm_model"],
        llm_api_key=decrypt(row["llm_api_key_encrypted"]),
    )


async def init_ai_config(db: AsyncSession) -> None:
    """Load every tenant's decrypted AI config into the in-process cache.
    Call once from the FastAPI lifespan, right after init_itsm_credentials().
    """
    global _configs
    result = await db.execute(
        sa_text(f"SELECT tenant_id, {', '.join(_AI_CONFIG_COLUMNS)} FROM platform_config")
    )
    async with _lock:
        _configs = {row.tenant_id: _decrypt_row(row.tenant_id, row._mapping) for row in result}
    log.info("ai_config.loaded", tenant_count=len(_configs))


async def refresh_tenant_ai_config(db: AsyncSession, tenant_id: str) -> None:
    """Re-read one tenant's row and update the cache — call after any write to
    that tenant's embedding_*/llm_* columns (wizard AI-config step, admin
    Integrations page) so get_ai_config()/get_embedder()/get_llm_client()
    pick up the change immediately."""
    result = await db.execute(
        sa_text(
            f"SELECT {', '.join(_AI_CONFIG_COLUMNS)} FROM platform_config WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return
    async with _lock:
        _configs[tenant_id] = _decrypt_row(tenant_id, row)
    log.info("ai_config.refreshed", tenant_id=tenant_id)


def get_ai_config(tenant_id: str) -> ResolvedAIConfig:
    """Sync cache lookup — never raises. A tenant with no row/cache entry
    (not yet configured) gets a ResolvedAIConfig with every field None, an
    ordinary state callers branch on, not an exceptional one."""
    return _configs.get(tenant_id) or ResolvedAIConfig(
        tenant_id=tenant_id,
        embedding_provider=None, embedding_api_key=None, embedding_base_url=None,
        embedding_model=None, embedding_vector_size=None,
        llm_base_url=None, llm_model=None, llm_api_key=None,
    )


def get_embedder(tenant_id: str) -> Embedder:
    """Raises RuntimeError if embeddings aren't configured for this tenant —
    defensive backstop only; real call sites check ai_config.embeddings_configured
    via the pipeline gate / route-level check *before* reaching here."""
    config = get_ai_config(tenant_id)
    if not config.embeddings_configured:
        raise RuntimeError(
            f"Embeddings not configured for tenant {tenant_id!r} — complete or "
            f"edit the Model & AI Configuration step."
        )
    if config.embedding_provider == "gemini":
        from app.rag.embedder import GeminiEmbedder
        return GeminiEmbedder(
            api_key=config.embedding_api_key,
            model=config.resolved_embedding_model,
            vector_size=config.resolved_embedding_vector_size,
        )
    from app.rag.embedder_openai_compatible import OpenAICompatibleEmbedder
    return OpenAICompatibleEmbedder(
        base_url=config.embedding_base_url,
        api_key=config.embedding_api_key,
        model=config.embedding_model,
    )


def get_llm_client(tenant_id: str) -> AsyncOpenAI:
    """Raises RuntimeError if the LLM endpoint isn't configured. Returns only
    the client — callers still read ai_config.llm_model themselves for the
    `model=` kwarg, matching every existing call site's existing shape."""
    config = get_ai_config(tenant_id)
    if not config.llm_configured:
        raise RuntimeError(
            f"LLM endpoint not configured for tenant {tenant_id!r} — complete or "
            f"edit the Model & AI Configuration step."
        )
    settings = get_settings()
    return AsyncOpenAI(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key or "unused",
        timeout=settings.ollama_timeout_seconds,
    )
