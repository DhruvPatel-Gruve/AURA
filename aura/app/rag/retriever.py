"""Hybrid retriever — dense vector search + BM25 re-ranking fused via RRF.

Strategy
--------
At query time the BM25 corpus fitted during ingestion is not available in memory,
so a two-stage approach is used:

  Stage 1 — Dense retrieval (Qdrant HNSW cosine search)
      Embed the query with task_type=RETRIEVAL_QUERY (Gemini) and fetch
      top_k * CANDIDATE_MULTIPLIER candidates from Qdrant.  This gives high
      semantic recall at the cost of some precision.

  Stage 2 — BM25 re-ranking (local, over the retrieved candidates)
      Build a temporary BM25Okapi model over the candidate chunk contents.
      Score each candidate against the query and produce a second ranking.

  Stage 3 — Reciprocal Rank Fusion (RRF)
      Merge the two ranked lists using the standard RRF formula:
          score(d) = Σ_r  1 / (k + rank_r(d))
      where k = 60 (empirically robust, from the original RRF paper).
      Return the top_k results sorted by fused score descending.

This approach requires no persistent vocabulary, works with any Qdrant
collection that stores content in the payload, and produces results that
consistently outperform dense-only search on keyword-heavy IT support queries.
"""

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.qdrant_client import get_qdrant_client
from app.models.agent_state import RetrievedChunk
from app.rag.embedder import GeminiEmbedder

log = get_logger(__name__)

# How many Qdrant results to pull before BM25 re-ranking.
# Higher = better BM25 coverage, slower retrieval.
_CANDIDATE_MULTIPLIER = 4

# RRF constant — standard value from the original paper (Cormack et al., 2009).
_RRF_K = 60


def _tokenize(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


@dataclass
class _Candidate:
    chunk_id: str
    ticket_id: str
    chunk_type: str
    content: str
    score: float        # dense cosine similarity from Qdrant
    metadata: dict


class HybridRetriever:
    """Stateless retriever — create one instance and reuse across requests."""

    def __init__(self) -> None:
        self._embedder = GeminiEmbedder()
        self._settings = get_settings()

    async def retrieve(
        self,
        query_text: str,
        top_k: int = 5,
        collection: str | None = None,
        query_vector: list[float] | None = None,
    ) -> list[RetrievedChunk]:
        """Run hybrid retrieval and return up to top_k chunks.

        Args:
            query_text:   Raw query string (ticket summary + description).
            top_k:        Number of results to return after RRF fusion.
            collection:   Qdrant collection name; defaults to resolved_tickets.
            query_vector: Pre-computed 768-dim query embedding.  If provided,
                          the Gemini API call is skipped (reuses node 2's vector).

        Returns:
            list[RetrievedChunk] sorted by fused RRF score descending.
        """
        col = collection or self._settings.qdrant_resolved_collection
        n_candidates = top_k * _CANDIDATE_MULTIPLIER

        # ── Stage 1: dense retrieval ──────────────────────────────────────────
        if query_vector is None:
            query_vector = await self._embedder.embed_query_text(query_text)

        candidates = await self._dense_search(query_vector, n_candidates, col)

        if not candidates:
            log.info("retriever.no_results", collection=col, query_preview=query_text[:80])
            return []

        # ── Stage 2: BM25 re-ranking ──────────────────────────────────────────
        bm25_ranked = self._bm25_rank(query_text, candidates)

        # ── Stage 3: RRF fusion ───────────────────────────────────────────────
        fused = self._rrf_merge(
            dense_ranked=candidates,    # already in cosine-desc order from Qdrant
            bm25_ranked=bm25_ranked,
        )

        result = fused[:top_k]
        log.info(
            "retriever.done",
            collection=col,
            candidates=len(candidates),
            returned=len(result),
            top_score=round(result[0]["score"], 4) if result else 0,
        )
        return result

    async def probe_top_score(
        self,
        query_text: str,
        collection: str | None = None,
        query_vector: list[float] | None = None,
    ) -> tuple[float, list[float]]:
        """Return (top_score, query_vector) for the abstention / priority checks.

        Fetches only 1 result — much cheaper than a full retrieve() call.
        Also returns the query_vector so callers can cache it for later reuse.
        """
        col = collection or self._settings.qdrant_resolved_collection

        if query_vector is None:
            query_vector = await self._embedder.embed_query_text(query_text)

        candidates = await self._dense_search(query_vector, 1, col)
        top_score = candidates[0].score if candidates else 0.0

        return top_score, query_vector

    # ── Internal: dense Qdrant search ────────────────────────────────────────

    async def _dense_search(
        self,
        query_vector: list[float],
        limit: int,
        collection: str,
    ) -> list[_Candidate]:
        client = get_qdrant_client()
        try:
            response = await client.query_points(
                collection_name=collection,
                query=query_vector,
                using="",   # "" = default (dense) vector name
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            hits = response.points
        except Exception as exc:
            log.error("retriever.dense_search_failed", collection=collection, error=str(exc))
            return []
        return [
            _Candidate(
                chunk_id=h.payload.get("chunk_id", ""),
                ticket_id=h.payload.get("ticket_id", ""),
                chunk_type=h.payload.get("chunk_type", ""),
                content=h.payload.get("content", ""),
                score=h.score,
                metadata={
                    k: v
                    for k, v in h.payload.items()
                    if k not in ("content",)
                },
            )
            for h in hits
            if h.payload
        ]

    # ── Internal: BM25 re-ranking ─────────────────────────────────────────────

    def _bm25_rank(
        self,
        query_text: str,
        candidates: list[_Candidate],
    ) -> list[_Candidate]:
        """Return candidates re-ordered by BM25 score (descending)."""
        if not candidates:
            return []

        tokenized_corpus = [_tokenize(c.content) for c in candidates]
        bm25 = BM25Okapi(tokenized_corpus)
        query_tokens = _tokenize(query_text)
        scores = bm25.get_scores(query_tokens)

        ranked = sorted(
            zip(candidates, scores),
            key=lambda x: x[1],
            reverse=True,
        )
        return [c for c, _ in ranked]

    # ── Internal: Reciprocal Rank Fusion ──────────────────────────────────────

    def _rrf_merge(
        self,
        dense_ranked: list[_Candidate],
        bm25_ranked: list[_Candidate],
    ) -> list[RetrievedChunk]:
        """Merge two ranked lists using RRF and return RetrievedChunk objects."""
        scores: dict[str, float] = {}

        for rank, cand in enumerate(dense_ranked, start=1):
            scores[cand.chunk_id] = scores.get(cand.chunk_id, 0.0) + 1.0 / (_RRF_K + rank)

        for rank, cand in enumerate(bm25_ranked, start=1):
            scores[cand.chunk_id] = scores.get(cand.chunk_id, 0.0) + 1.0 / (_RRF_K + rank)

        # Build lookup and sort by fused score
        lookup: dict[str, _Candidate] = {c.chunk_id: c for c in dense_ranked}

        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)

        return [
            RetrievedChunk(
                chunk_id=cid,
                ticket_id=lookup[cid].ticket_id,
                chunk_type=lookup[cid].chunk_type,
                content=lookup[cid].content,
                score=round(scores[cid], 6),
                metadata=lookup[cid].metadata,
            )
            for cid in sorted_ids
            if cid in lookup
        ]
