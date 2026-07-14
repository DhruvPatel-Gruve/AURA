"""Gemini embedding provider for AURA hybrid search.

Produces two vector types per chunk:
  - Dense  : Gemini gemini-embedding-2 (configurable-dim float via
             output_dimensionality), batched up to 100/call
  - Sparse : BM25 weights via rank-bm25 (variable-width int indices + float values)

The corpus for BM25 must be fitted before encoding individual chunks.
Call GeminiEmbedder.fit_bm25(all_texts) once per ingestion run, then
embed_chunks() for each batch.

Each tenant supplies their own Gemini API key (app.services.ai_config_service),
so `_configure_and_embed` below runs `genai.configure(api_key=...)` with a
*different* key per tenant against the same process. `google.generativeai`'s
`configure()` sets a process-wide module global, not a per-instance
credential — without `_gemini_lock`, two tenants' concurrent embed calls could
interleave and one could silently embed under the other's key. The lock wraps
the entire configure-then-embed round trip (including the executor call, not
just the configure() line) so at most one such round trip is ever in flight.
"""

import asyncio
from typing import Sequence

# google-genai 2.10.0 has a Python 3.14 incompatibility (_UnionGenericAlias).
# Using google.generativeai until google-genai cuts a 3.14-compatible release.
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import google.generativeai as genai

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.rag.embedder_base import AnyChunk, BM25SparseEncoder, EmbeddedChunk

log = get_logger(__name__)

# Serializes every Gemini configure()+embed_content() round trip process-wide
# — see module docstring. Embedding calls are batched/infrequent (ingestion
# runs, one query embed per ticket/chat turn), not a request-per-second hot
# path, so full serialization across tenants is an acceptable trade-off for
# correctness.
_gemini_lock = asyncio.Lock()

# Last observed Gemini query-embedding latency, in milliseconds. Updated by
# every embed_query_text() call (the hot path hit by the agent graph on each
# ticket) so /dashboard/*/health can report a real, current number instead of
# a hardcoded placeholder — without making an extra API call just to measure it.
_last_query_latency_ms: float | None = None


def get_last_query_latency_ms() -> float | None:
    return _last_query_latency_ms


class GeminiEmbedder:
    def __init__(
        self,
        api_key: str,
        model: str,
        vector_size: int = 768,
        batch_size: int | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._vector_size = vector_size
        self._batch_size = batch_size or get_settings().gemini_embedding_batch_size
        self._bm25 = BM25SparseEncoder()

    # ── BM25 corpus fitting ───────────────────────────────────────────────────

    def fit_bm25(self, texts: Sequence[str]) -> None:
        self._bm25.fit(texts)
        log.info("embedder.bm25_fitted", corpus_size=len(texts))

    # ── Dense embedding (Gemini) ──────────────────────────────────────────────

    def _configure_and_embed_documents(self, texts: list[str]) -> dict:
        genai.configure(api_key=self._api_key)
        return genai.embed_content(
            model=self._model,
            content=texts,
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=self._vector_size,
        )

    def _configure_and_embed_query(self, text: str) -> dict:
        genai.configure(api_key=self._api_key)
        return genai.embed_content(
            model=self._model,
            content=text,
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=self._vector_size,
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch of texts via Gemini API (async via thread pool)."""
        loop = asyncio.get_event_loop()
        async with _gemini_lock:
            result = await loop.run_in_executor(None, self._configure_and_embed_documents, texts)
        return result["embedding"]

    async def embed_query_text(self, text: str) -> list[float]:
        """Embed a single query string with task_type=RETRIEVAL_QUERY.

        Use this at retrieval time (agent nodes). Use embed_texts() / embed_chunks()
        only at ingestion time (task_type=RETRIEVAL_DOCUMENT is baked in there).
        """
        global _last_query_latency_ms
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        async with _gemini_lock:
            result = await loop.run_in_executor(None, self._configure_and_embed_query, text)
        _last_query_latency_ms = round((loop.time() - t0) * 1000, 1)
        return result["embedding"]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts in batches. Returns dense vectors in same order."""
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            vectors = await self._embed_batch(batch)
            all_vectors.extend(vectors)
            log.debug(
                "embedder.batch_done",
                batch_start=i,
                batch_size=len(batch),
                total=len(texts),
            )
        return all_vectors

    # ── Combined embed ────────────────────────────────────────────────────────

    async def embed_chunks(self, chunks: list[AnyChunk]) -> list[EmbeddedChunk]:
        """Produce dense + sparse vectors for every chunk.

        fit_bm25() must have been called with the full corpus beforehand.
        """
        if not self._bm25.fitted:
            raise RuntimeError("BM25 corpus not fitted — call fit_bm25() first.")

        texts = [c.content for c in chunks]
        dense_vectors = await self.embed_texts(texts)

        embedded: list[EmbeddedChunk] = []
        for chunk, dense in zip(chunks, dense_vectors):
            indices, values = self._bm25.sparse_vector(chunk.content)
            embedded.append(
                EmbeddedChunk(
                    chunk=chunk,
                    dense_vector=dense,
                    sparse_indices=indices,
                    sparse_values=values,
                )
            )

        log.info("embedder.chunks_embedded", count=len(embedded))
        return embedded
