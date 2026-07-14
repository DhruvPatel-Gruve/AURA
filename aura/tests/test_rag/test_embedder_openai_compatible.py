"""Unit tests for app.rag.embedder_openai_compatible.OpenAICompatibleEmbedder."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.chunker import DynamicChunker
from app.rag.embedder_openai_compatible import OpenAICompatibleEmbedder


def _mock_embeddings_response(vectors: list[list[float]]):
    return MagicMock(data=[MagicMock(embedding=v) for v in vectors])


@pytest.fixture
def embedder():
    with patch("app.rag.embedder_openai_compatible.AsyncOpenAI"):
        return OpenAICompatibleEmbedder(
            base_url="http://localhost:8080/v1", api_key="k", model="text-embedding-3-small",
        )


# ── fit_bm25 / sparse_vector (delegates to BM25SparseEncoder — same behavior as Gemini path) ──

def test_fit_bm25_builds_vocab(embedder):
    embedder.fit_bm25(["VPN connection failed", "printer offline"])
    assert embedder._bm25.fitted
    assert len(embedder._bm25._corpus.vocab) > 0


def test_sparse_vector_raises_without_fit(embedder):
    with pytest.raises(RuntimeError, match="BM25 corpus not fitted"):
        embedder._bm25.sparse_vector("some text")


# ── embed_texts (mocked OpenAI-compatible client) ──────────────────────────────

@pytest.mark.asyncio
async def test_embed_texts_returns_correct_count(embedder):
    embedder._client.embeddings.create = AsyncMock(
        return_value=_mock_embeddings_response([[0.1] * 1536] * 3)
    )
    vectors = await embedder.embed_texts(["text one", "text two", "text three"])
    assert len(vectors) == 3
    assert len(vectors[0]) == 1536


@pytest.mark.asyncio
async def test_embed_texts_batches_by_batch_size():
    with patch("app.rag.embedder_openai_compatible.AsyncOpenAI"):
        small_batch_embedder = OpenAICompatibleEmbedder(
            base_url="http://localhost:8080/v1", api_key="k", model="m", batch_size=2,
        )
    calls = []

    async def fake_create(model, input):
        calls.append(list(input))
        return _mock_embeddings_response([[0.1] * 8 for _ in input])

    small_batch_embedder._client.embeddings.create = fake_create
    await small_batch_embedder.embed_texts(["a", "b", "c", "d", "e"])

    assert [len(c) for c in calls] == [2, 2, 1]


@pytest.mark.asyncio
async def test_embed_query_text_returns_single_vector(embedder):
    embedder._client.embeddings.create = AsyncMock(
        return_value=_mock_embeddings_response([[0.2] * 1536])
    )
    vector = await embedder.embed_query_text("hello world")
    assert len(vector) == 1536


# ── embed_chunks ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_chunks_raises_without_fit(embedder, sample_ticket):
    chunker = DynamicChunker()
    chunks = chunker.chunk(sample_ticket)
    with pytest.raises(RuntimeError, match="BM25 corpus not fitted"):
        await embedder.embed_chunks(chunks)


@pytest.mark.asyncio
async def test_embed_chunks_returns_one_per_chunk_with_dense_and_sparse_vectors(embedder, sample_ticket):
    chunker = DynamicChunker()
    chunks = chunker.chunk(sample_ticket)
    embedder.fit_bm25([c.content for c in chunks])
    embedder._client.embeddings.create = AsyncMock(
        return_value=_mock_embeddings_response([[0.1] * 1536] * len(chunks))
    )

    embedded = await embedder.embed_chunks(chunks)

    assert len(embedded) == len(chunks)
    for ec in embedded:
        assert len(ec.dense_vector) == 1536
        assert isinstance(ec.sparse_indices, list)
        assert isinstance(ec.sparse_values, list)
