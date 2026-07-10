"""Embedding layer for AURA hybrid search.

Produces two vector types per chunk:
  - Dense  : Gemini gemini-embedding-2 (768-dim float via output_dimensionality), batched up to 100/call
  - Sparse : BM25 weights via rank-bm25 (variable-width int indices + float values)

The corpus for BM25 must be fitted before encoding individual chunks.
Call GeminiEmbedder.fit_bm25(all_texts) once per ingestion run, then
embed_chunks() for each batch.
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Sequence

# google-genai 2.10.0 has a Python 3.14 incompatibility (_UnionGenericAlias).
# Using google.generativeai until google-genai cuts a 3.14-compatible release.
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import google.generativeai as genai

from rank_bm25 import BM25Okapi
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.jsm import DocumentChunk, TicketChunk

log = get_logger(__name__)

AnyChunk = TicketChunk | DocumentChunk

# Last observed Gemini query-embedding latency, in milliseconds. Updated by
# every embed_query_text() call (the hot path hit by the agent graph on each
# ticket) so /dashboard/*/health can report a real, current number instead of
# a hardcoded placeholder — without making an extra API call just to measure it.
_last_query_latency_ms: float | None = None


def get_last_query_latency_ms() -> float | None:
    return _last_query_latency_ms


@dataclass
class EmbeddedChunk:
    chunk: AnyChunk
    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]


@dataclass
class BM25Corpus:
    """Fitted BM25 model + token→index vocabulary built from the ingestion corpus."""
    model: BM25Okapi
    vocab: dict[str, int]           # token → column index
    tokenized_docs: list[list[str]] = field(repr=False)


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


class GeminiEmbedder:
    def __init__(self) -> None:
        settings = get_settings()
        genai.configure(api_key=settings.gemini_api_key)
        self._model = settings.gemini_embedding_model
        self._batch_size = settings.gemini_embedding_batch_size
        self._corpus: BM25Corpus | None = None

    # ── BM25 corpus fitting ───────────────────────────────────────────────────

    def fit_bm25(self, texts: Sequence[str]) -> None:
        """Fit the BM25 model on the full corpus of chunk texts.

        Must be called before embed_chunks(). Rebuilds the vocab and the
        BM25Okapi model from scratch — safe to call multiple times.
        """
        tokenized = [_tokenize(t) for t in texts]
        model = BM25Okapi(tokenized)

        # Build a stable token→index vocabulary from all unique tokens
        vocab: dict[str, int] = {}
        for tokens in tokenized:
            for tok in tokens:
                if tok not in vocab:
                    vocab[tok] = len(vocab)

        self._corpus = BM25Corpus(
            model=model,
            vocab=vocab,
            tokenized_docs=tokenized,
        )
        log.info(
            "embedder.bm25_fitted",
            corpus_size=len(texts),
            vocab_size=len(vocab),
        )

    def _sparse_vector(self, text: str) -> tuple[list[int], list[float]]:
        """Compute BM25 sparse vector for a single text.

        Returns (indices, values) — only non-zero terms are included,
        matching Qdrant's SparseVector format.
        """
        if self._corpus is None:
            raise RuntimeError("BM25 corpus not fitted — call fit_bm25() first.")

        tokens = _tokenize(text)
        return _bm25_term_weights(self._corpus, tokens)

    # ── Dense embedding (Gemini) ──────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch of texts via Gemini API (async via thread pool)."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: genai.embed_content(
                model=self._model,
                content=texts,
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=768,
            ),
        )
        return result["embedding"]

    async def embed_query_text(self, text: str) -> list[float]:
        """Embed a single query string with task_type=RETRIEVAL_QUERY.

        Use this at retrieval time (agent nodes). Use embed_texts() / embed_chunks()
        only at ingestion time (task_type=RETRIEVAL_DOCUMENT is baked in there).
        """
        global _last_query_latency_ms
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        result = await loop.run_in_executor(
            None,
            lambda: genai.embed_content(
                model=self._model,
                content=text,
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768,
            ),
        )
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
        if self._corpus is None:
            raise RuntimeError("BM25 corpus not fitted — call fit_bm25() first.")

        texts = [c.content for c in chunks]
        dense_vectors = await self.embed_texts(texts)

        embedded: list[EmbeddedChunk] = []
        for chunk, dense in zip(chunks, dense_vectors):
            indices, values = self._sparse_vector(chunk.content)
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


# ── BM25 term-weight helper ───────────────────────────────────────────────────

def _bm25_term_weights(
    corpus: BM25Corpus,
    query_tokens: list[str],
) -> tuple[list[int], list[float]]:
    """Compute per-term BM25 IDF × average-TF weight for a query document.

    This produces the sparse representation used as the Qdrant SparseVector:
    only tokens present in the corpus vocabulary get a non-zero weight.
    """
    from collections import Counter

    k1 = 1.5
    b = 0.75
    bm25 = corpus.model

    tf_counter = Counter(query_tokens)
    avg_dl = sum(len(d) for d in corpus.tokenized_docs) / max(len(corpus.tokenized_docs), 1)
    doc_len = len(query_tokens)

    indices: list[int] = []
    values: list[float] = []

    for tok, col_idx in corpus.vocab.items():
        tf = tf_counter.get(tok, 0)
        if tf == 0:
            continue

        # IDF from the fitted BM25 model's idf array (BM25Okapi stores it)
        try:
            idf = bm25.idf.get(tok, 0.0)
        except AttributeError:
            # fallback — BM25Okapi stores idf as a dict-like via internal word_map
            idf = 0.0

        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / max(avg_dl, 1)))
        weight = idf * tf_norm
        if weight > 0:
            indices.append(col_idx)
            values.append(weight)

    return indices, values
