"""Shared contract + BM25 sparse-vector logic for every embedder implementation.

`Embedder` documents the exact surface every provider-specific embedder
(GeminiEmbedder, OpenAICompatibleEmbedder) must provide — callers (retriever,
ingestion pipeline, agent nodes) depend only on this, never on a concrete
class, so a tenant's chosen provider is an implementation detail behind
`app.services.ai_config_service.get_embedder()`.
"""

import re
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from rank_bm25 import BM25Okapi

from app.models.jsm import DocumentChunk, TicketChunk

AnyChunk = TicketChunk | DocumentChunk


@dataclass
class EmbeddedChunk:
    chunk: AnyChunk
    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]


class Embedder(Protocol):
    def fit_bm25(self, texts: Sequence[str]) -> None: ...
    async def embed_query_text(self, text: str) -> list[float]: ...
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_chunks(self, chunks: list[AnyChunk]) -> list[EmbeddedChunk]: ...


@dataclass
class BM25Corpus:
    """Fitted BM25 model + token→index vocabulary built from the ingestion corpus."""
    model: BM25Okapi
    vocab: dict[str, int]           # token → column index
    tokenized_docs: list[list[str]] = field(repr=False)


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


class BM25SparseEncoder:
    """Provider-agnostic BM25 sparse-vector encoder — every embedder composes
    one of these rather than reimplementing BM25 fitting/scoring itself."""

    def __init__(self) -> None:
        self._corpus: BM25Corpus | None = None

    def fit(self, texts: Sequence[str]) -> None:
        """Fit the BM25 model on the full corpus of chunk texts.

        Must be called before sparse_vector(). Rebuilds the vocab and the
        BM25Okapi model from scratch — safe to call multiple times.
        """
        tokenized = [_tokenize(t) for t in texts]
        model = BM25Okapi(tokenized)

        vocab: dict[str, int] = {}
        for tokens in tokenized:
            for tok in tokens:
                if tok not in vocab:
                    vocab[tok] = len(vocab)

        self._corpus = BM25Corpus(model=model, vocab=vocab, tokenized_docs=tokenized)

    @property
    def fitted(self) -> bool:
        return self._corpus is not None

    def sparse_vector(self, text: str) -> tuple[list[int], list[float]]:
        """Compute BM25 sparse vector for a single text.

        Returns (indices, values) — only non-zero terms are included,
        matching Qdrant's SparseVector format.
        """
        if self._corpus is None:
            raise RuntimeError("BM25 corpus not fitted — call fit() first.")
        tokens = _tokenize(text)
        return _bm25_term_weights(self._corpus, tokens)


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

        try:
            idf = bm25.idf.get(tok, 0.0)
        except AttributeError:
            idf = 0.0

        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / max(avg_dl, 1)))
        weight = idf * tf_norm
        if weight > 0:
            indices.append(col_idx)
            values.append(weight)

    return indices, values
