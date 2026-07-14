from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance,
    HnswConfigDiff,
    OptimizersConfigDiff,
    SparseIndexParams,
    SparseVectorParams,
    VectorParams,
)

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Sparse vector field name — must match what the embedder writes into payloads
SPARSE_VECTOR_NAME = "bm25"

_client: AsyncQdrantClient | None = None

# Collections are per-tenant (agreed isolation strategy: separate collection
# per tenant rather than one shared collection filtered by a tenant_id
# payload field — matches the existing .env.zendesk pattern of
# resolved_tickets_zendesk, just generalised to any tenant_id) and created
# lazily on first use rather than all up front at boot, since the set of
# tenants is now dynamic.
_ensured_collections: set[str] = set()


def resolved_collection_name(tenant_id: str) -> str:
    return f"resolved_tickets_{tenant_id}"


def get_qdrant_client() -> AsyncQdrantClient:
    if _client is None:
        raise RuntimeError("Qdrant client not initialised — call init_qdrant() first.")
    return _client


async def init_qdrant() -> None:
    """Create the AsyncQdrantClient. Called once from FastAPI lifespan on
    startup. Per-tenant collections are ensured lazily via
    ensure_tenant_collection(), not here — the set of tenants isn't known
    until the DB is queried, and doing that here would duplicate the tenant
    lookup logic that main.py's startup sequence already does elsewhere.
    """
    global _client

    settings = get_settings()

    api_key = settings.qdrant_api_key.strip() or None  # blank/empty → None
    _client = AsyncQdrantClient(url=settings.qdrant_url, api_key=api_key)

    log.info("qdrant.ready", url=settings.qdrant_url)


async def close_qdrant() -> None:
    """Close the Qdrant connection — called from FastAPI lifespan on shutdown."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
        _ensured_collections.clear()
        log.info("qdrant.closed")


async def ensure_tenant_collection(tenant_id: str) -> str:
    """Ensure this tenant's resolved-tickets collection exists; return its
    name. Cheap to call on every ingestion/retrieval — the in-process
    `_ensured_collections` set makes every call after the first a no-op
    with zero Qdrant round-trip.

    Vector size comes from this tenant's own embedding configuration (Gemini
    is always 768; an OpenAI-compatible provider's dimension is whatever the
    tenant supplied and verified via the embedding test-connection route) —
    falls back to the global Settings default only if this tenant genuinely
    has no AI config row yet, which shouldn't happen once the AI-config gate
    runs ahead of every real ingestion/retrieval call site.
    """
    from app.services.ai_config_service import get_ai_config

    name = resolved_collection_name(tenant_id)
    if name not in _ensured_collections:
        config = get_ai_config(tenant_id)
        vector_size = (
            config.resolved_embedding_vector_size
            if config.embeddings_configured
            else get_settings().qdrant_vector_size
        )
        await _ensure_collection(name, vector_size)
        _ensured_collections.add(name)
    return name


async def _ensure_collection(name: str, vector_size: int) -> None:
    """Create a hybrid (dense + sparse) collection if it does not already exist."""
    client = get_qdrant_client()
    existing = {c.name for c in (await client.get_collections()).collections}

    if name in existing:
        log.info("qdrant.collection_exists", collection=name)
        return

    await client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(
            size=vector_size,
            distance=Distance.COSINE,
            hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
        ),
        sparse_vectors_config={
            # BM25 sparse vector — variable-width, no distance metric (dot product implied)
            SPARSE_VECTOR_NAME: SparseVectorParams(
                index=SparseIndexParams(on_disk=False)
            )
        },
        optimizers_config=OptimizersConfigDiff(
            indexing_threshold=20_000,   # defer HNSW build until 20k vectors
        ),
    )

    log.info("qdrant.collection_created", collection=name, vector_size=vector_size)
