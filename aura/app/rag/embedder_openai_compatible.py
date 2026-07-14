"""OpenAI-compatible embeddings provider — the alternative a tenant can pick
instead of Gemini in their AI Configuration (app.services.ai_config_service).

Each instance owns its own `AsyncOpenAI` client (base_url + api_key baked in
at construction), so unlike GeminiEmbedder there is no process-wide SDK global
to serialize around — concurrent calls for different tenants are naturally
safe without a lock.
"""

from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.logging import get_logger
from app.rag.embedder_base import AnyChunk, BM25SparseEncoder, EmbeddedChunk

log = get_logger(__name__)


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        batch_size: int = 100,
    ) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "unused")
        self._model = model
        self._batch_size = batch_size
        self._bm25 = BM25SparseEncoder()

    # ── BM25 corpus fitting ───────────────────────────────────────────────────

    def fit_bm25(self, texts) -> None:
        self._bm25.fit(texts)
        log.info("embedder.bm25_fitted", corpus_size=len(texts))

    # ── Dense embedding ───────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in response.data]

    async def embed_query_text(self, text: str) -> list[float]:
        vectors = await self._embed_batch([text])
        return vectors[0]

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
