"""Unit tests for app.rag.embedder.GeminiEmbedder."""

from unittest.mock import patch

import pytest

from app.rag.chunker import DynamicChunker
from app.rag.embedder_base import _tokenize


# ── _tokenize ─────────────────────────────────────────────────────────────────

def test_tokenize_lowercases():
    assert _tokenize("Hello WORLD") == ["hello", "world"]


def test_tokenize_strips_punctuation():
    tokens = _tokenize("error: disk full!")
    assert "error" in tokens
    assert "disk" in tokens
    assert "full" in tokens
    assert ":" not in tokens


def test_tokenize_empty_string():
    assert _tokenize("") == []


# ── fit_bm25 ──────────────────────────────────────────────────────────────────

def test_fit_bm25_builds_vocab(mock_embedder):
    texts = ["VPN connection failed", "printer offline on floor three"]
    mock_embedder.fit_bm25(texts)

    assert mock_embedder._bm25.fitted
    assert len(mock_embedder._bm25._corpus.vocab) > 0


def test_fit_bm25_vocab_contains_expected_tokens(mock_embedder):
    texts = ["VPN timeout error"]
    mock_embedder.fit_bm25(texts)
    vocab = mock_embedder._bm25._corpus.vocab
    assert "vpn" in vocab
    assert "timeout" in vocab
    assert "error" in vocab


def test_fit_bm25_is_idempotent(mock_embedder):
    texts = ["first corpus"]
    mock_embedder.fit_bm25(texts)
    vocab_size_1 = len(mock_embedder._bm25._corpus.vocab)

    mock_embedder.fit_bm25(texts)
    vocab_size_2 = len(mock_embedder._bm25._corpus.vocab)
    assert vocab_size_1 == vocab_size_2


def test_fit_bm25_corpus_size_matches(mock_embedder):
    texts = ["doc one", "doc two", "doc three"]
    mock_embedder.fit_bm25(texts)
    assert len(mock_embedder._bm25._corpus.tokenized_docs) == 3


# ── sparse vector ─────────────────────────────────────────────────────────────

def test_sparse_vector_raises_without_fit(mock_embedder):
    with pytest.raises(RuntimeError, match="BM25 corpus not fitted"):
        mock_embedder._bm25.sparse_vector("some text")


def test_sparse_vector_returns_indices_and_values(mock_embedder):
    mock_embedder.fit_bm25(["VPN error timeout", "printer offline"])
    indices, values = mock_embedder._bm25.sparse_vector("VPN error")
    assert isinstance(indices, list)
    assert isinstance(values, list)
    assert len(indices) == len(values)


def test_sparse_vector_only_nonzero_terms(mock_embedder):
    mock_embedder.fit_bm25(["VPN error timeout", "printer offline"])
    indices, values = mock_embedder._bm25.sparse_vector("VPN error")
    # All returned values must be positive
    assert all(v > 0 for v in values)


def test_sparse_vector_empty_text_gives_empty(mock_embedder):
    mock_embedder.fit_bm25(["VPN error", "printer issue"])
    indices, values = mock_embedder._bm25.sparse_vector("")
    assert indices == []
    assert values == []


def test_sparse_vector_out_of_vocab_term_ignored(mock_embedder):
    mock_embedder.fit_bm25(["VPN error"])
    # "zzznonsensexxx" is not in vocab — should not appear in sparse vector
    indices, values = mock_embedder._bm25.sparse_vector("zzznonsensexxx")
    assert indices == []
    assert values == []


# ── embed_texts (mocked Gemini) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_texts_returns_correct_count(mock_embedder):
    texts = ["text one", "text two", "text three"]
    vectors = await mock_embedder.embed_texts(texts)
    assert len(vectors) == 3


@pytest.mark.asyncio
async def test_embed_texts_vector_dimension(mock_embedder):
    vectors = await mock_embedder.embed_texts(["hello world"])
    assert len(vectors[0]) == 768


@pytest.mark.asyncio
async def test_embed_texts_empty_list(mock_embedder):
    vectors = await mock_embedder.embed_texts([])
    assert vectors == []


# ── embed_chunks ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_chunks_raises_without_fit(mock_embedder, sample_ticket):
    chunker = DynamicChunker()
    chunks = chunker.chunk(sample_ticket)
    with pytest.raises(RuntimeError, match="BM25 corpus not fitted"):
        await mock_embedder.embed_chunks(chunks)


@pytest.mark.asyncio
async def test_embed_chunks_returns_one_per_chunk(mock_embedder, sample_ticket):
    chunker = DynamicChunker()
    chunks = chunker.chunk(sample_ticket)
    mock_embedder.fit_bm25([c.content for c in chunks])
    embedded = await mock_embedder.embed_chunks(chunks)
    assert len(embedded) == len(chunks)


@pytest.mark.asyncio
async def test_embed_chunks_dense_vector_shape(mock_embedder, sample_ticket):
    chunker = DynamicChunker()
    chunks = chunker.chunk(sample_ticket)
    mock_embedder.fit_bm25([c.content for c in chunks])
    embedded = await mock_embedder.embed_chunks(chunks)
    for ec in embedded:
        assert len(ec.dense_vector) == 768


@pytest.mark.asyncio
async def test_embed_chunks_sparse_vector_present(mock_embedder, sample_ticket):
    chunker = DynamicChunker()
    chunks = chunker.chunk(sample_ticket)
    mock_embedder.fit_bm25([c.content for c in chunks])
    embedded = await mock_embedder.embed_chunks(chunks)
    for ec in embedded:
        assert isinstance(ec.sparse_indices, list)
        assert isinstance(ec.sparse_values, list)
        assert len(ec.sparse_indices) == len(ec.sparse_values)


@pytest.mark.asyncio
async def test_embed_chunks_chunk_reference_preserved(mock_embedder, sample_ticket):
    chunker = DynamicChunker()
    chunks = chunker.chunk(sample_ticket)
    mock_embedder.fit_bm25([c.content for c in chunks])
    embedded = await mock_embedder.embed_chunks(chunks)
    embedded_ids = {ec.chunk.chunk_id for ec in embedded}
    original_ids = {c.chunk_id for c in chunks}
    assert embedded_ids == original_ids


# ── Per-tenant API key + concurrency safety ───────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_embed_calls_do_not_interleave_configure():
    """Regression test for the genai.configure() global-state race: two
    tenants' embedders must never see each other's api_key, even when their
    embed calls run concurrently. Without the module-level lock wrapping the
    *entire* configure-then-embed round trip (not just configure() itself),
    this test fails intermittently as the two tasks' executor threads
    interleave against the shared google.generativeai module state."""
    import asyncio
    import time

    from app.rag.embedder import GeminiEmbedder

    current_key = {"value": None}
    call_log: list[tuple[str, str]] = []

    def fake_configure(api_key):
        current_key["value"] = api_key
        call_log.append(("configure", api_key))
        time.sleep(0.05)  # widen the race window

    def fake_embed_content(model, content, task_type, output_dimensionality):
        time.sleep(0.05)
        call_log.append(("embed", current_key["value"]))
        return {"embedding": [0.1] * output_dimensionality}

    embedder_a = GeminiEmbedder(api_key="key-A", model="m", vector_size=768)
    embedder_b = GeminiEmbedder(api_key="key-B", model="m", vector_size=768)

    with patch("app.rag.embedder.genai.configure", side_effect=fake_configure), \
         patch("app.rag.embedder.genai.embed_content", side_effect=fake_embed_content):
        await asyncio.gather(
            embedder_a.embed_query_text("hello"),
            embedder_b.embed_query_text("world"),
        )

    # Calls must alternate strictly configure→embed, each embed seeing the
    # key its own immediately-preceding configure set — never interleaved.
    assert len(call_log) == 4
    for i in range(0, len(call_log), 2):
        (kind1, key1), (kind2, key2) = call_log[i], call_log[i + 1]
        assert kind1 == "configure" and kind2 == "embed"
        assert key1 == key2


@pytest.mark.asyncio
async def test_output_dimensionality_uses_configured_vector_size():
    from app.rag.embedder import GeminiEmbedder

    captured = {}

    def fake_embed_content(model, content, task_type, output_dimensionality):
        captured["output_dimensionality"] = output_dimensionality
        return {"embedding": [0.1] * output_dimensionality}

    embedder = GeminiEmbedder(api_key="key", model="m", vector_size=1536)

    with patch("app.rag.embedder.genai.configure"), \
         patch("app.rag.embedder.genai.embed_content", side_effect=fake_embed_content):
        vector = await embedder.embed_query_text("hello")

    assert captured["output_dimensionality"] == 1536
    assert len(vector) == 1536
