"""Tests for document ingestion: converter, chunker, and the upload endpoint."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import require_admin
from app.rag.chunker import DynamicChunker
from app.rag.document_converter import convert_to_markdown
from app.services.ai_config_service import ResolvedAIConfig
from tests.conftest import SAMPLE_TENANT_ID as TENANT

_FAKE_ADMIN = {"user_id": "test-admin", "email": "admin@aura.local", "role": "admin", "tenant_id": TENANT}

_CONFIGURED_AI = ResolvedAIConfig(
    tenant_id=TENANT,
    embedding_provider="gemini", embedding_api_key="k", embedding_base_url=None,
    embedding_model="models/gemini-embedding-2", embedding_vector_size=768,
    llm_base_url="http://localhost:11434/v1", llm_model="qwen3:8b", llm_api_key=None,
)


# ── document_converter ────────────────────────────────────────────────────────

def test_convert_txt_to_markdown():
    content = b"# Hello\n\nThis is a test document."
    md = convert_to_markdown(content, "test.txt")
    assert "Hello" in md
    assert "test document" in md


def test_convert_raises_on_empty_output():
    with patch("app.rag.document_converter._converter") as mock_conv:
        mock_conv.convert.return_value = MagicMock(text_content="")
        with pytest.raises(ValueError, match="no content"):
            convert_to_markdown(b"irrelevant", "empty.txt")


def test_convert_rejects_zip_archives():
    with pytest.raises(ValueError, match="Unsupported file type"):
        convert_to_markdown(b"PK\x03\x04irrelevant", "bundle.zip")


def test_convert_accepts_json():
    md = convert_to_markdown(b'{"ticket": "VPN-1", "resolution": "restart client"}', "kb_articles.json")
    assert "VPN-1" in md


def test_convert_rejects_files_with_no_extension():
    with pytest.raises(ValueError, match="Unsupported file type"):
        convert_to_markdown(b"irrelevant", "some_folder")


def test_convert_rejects_disallowed_extension_without_invoking_markitdown():
    with patch("app.rag.document_converter._converter") as mock_conv:
        with pytest.raises(ValueError, match="Unsupported file type"):
            convert_to_markdown(b"irrelevant", "archive.zip")
        mock_conv.convert.assert_not_called()


def test_convert_handles_non_ascii_byte_past_markitdown_4kb_sample_window():
    """Regression test: markitdown's magika-based charset guess only samples the
    first 4KB of a file. A pure-ASCII prefix followed by a UTF-8 multi-byte
    character past that window used to guess charset="ascii" and then crash
    with UnicodeDecodeError decoding the full file. We now re-detect the
    charset ourselves from the *whole* file before handing off to markitdown.
    """
    padding = b"a" * 4200  # push the non-ASCII byte well past the 4096-byte sample
    content = padding + "— resolved via VPN client restart".encode("utf-8")
    md = convert_to_markdown(content, "kb_articles.txt")
    assert "resolved via VPN client restart" in md


# ── DynamicChunker.chunk_document ─────────────────────────────────────────────

@pytest.fixture
def chunker():
    return DynamicChunker()


def test_chunk_document_returns_chunks(chunker):
    md = "# Section One\n\nSome content here.\n\n## Section Two\n\nMore content."
    chunks = chunker.chunk_document("doc123", "guide.md", md)
    assert len(chunks) >= 1


def test_chunk_document_ids_are_sequential(chunker):
    md = "# A\n\nContent A.\n\n# B\n\nContent B.\n\n# C\n\nContent C."
    chunks = chunker.chunk_document("docX", "file.md", md)
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_id == f"docX__section__{i}"


def test_chunk_document_metadata_filename(chunker):
    md = "# Title\n\nSome text."
    chunks = chunker.chunk_document("d1", "manual.pdf", md)
    for chunk in chunks:
        assert chunk.metadata.filename == "manual.pdf"
        assert chunk.metadata.doc_id == "d1"
        assert chunk.metadata.source_type == "document"


def test_chunk_document_skips_blank_sections(chunker):
    md = "# Header\n\n\n\n# Another\n\nReal content."
    chunks = chunker.chunk_document("d2", "file.txt", md)
    for chunk in chunks:
        assert chunk.content.strip()


def test_chunk_document_long_section_splits(chunker):
    # ~6 tokens per phrase × 120 reps ≈ 720 tokens — well above the 512 split threshold
    long_text = "# Big Section\n\n" + ("network packet timeout error repeated " * 120)
    chunks = chunker.chunk_document("d3", "big.txt", long_text)
    assert len(chunks) > 1


def test_chunk_document_no_headers_treated_as_one_section(chunker):
    md = "Just plain text without any headers. " * 5
    chunks = chunker.chunk_document("d4", "plain.txt", md)
    assert len(chunks) >= 1


# ── POST /api/v1/ingestion/documents endpoint ─────────────────────────────────

@pytest.fixture
def mock_embedder_for_api():
    from app.rag.embedder import GeminiEmbedder
    embedder = GeminiEmbedder.__new__(GeminiEmbedder)
    embedder._api_key = "test-key"
    embedder._model = "models/text-embedding-004"
    embedder._vector_size = 768
    embedder._batch_size = 100
    from app.rag.embedder_base import BM25SparseEncoder
    embedder._bm25 = BM25SparseEncoder()

    async def _stub(texts):
        return [[0.1] * 768 for _ in texts]

    embedder._embed_batch = _stub
    return embedder


def _lifespan_patches(mock_qdrant):
    """Patch all lifespan hooks so create_app() starts without real infra.

    The lifespan imports these locally at call time, so we patch at their
    source modules rather than on app.main. Also patches documents.py's
    get_ai_config so the route's "embeddings configured?" gate passes —
    every test in this file exercises document-conversion/chunking behavior,
    not AI-config gating itself (that has its own dedicated test).
    """
    return [
        patch("app.db.sqlite.init_db", new=AsyncMock()),
        patch("app.db.sqlite.close_db", new=AsyncMock()),
        patch("app.db.qdrant_client.init_qdrant", new=AsyncMock()),
        patch("app.db.qdrant_client.close_qdrant", new=AsyncMock()),
        patch("scheduler.scheduler.start", new=AsyncMock()),
        patch("scheduler.scheduler.stop", new=AsyncMock()),
        patch("app.rag.ingestion_pipeline.get_qdrant_client", return_value=mock_qdrant),
        patch("app.api.v1.routes.documents.get_ai_config", return_value=_CONFIGURED_AI),
    ]


@pytest.mark.asyncio
async def test_ingest_document_returns_201(mock_qdrant, mock_embedder_for_api):
    from app.main import create_app
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _lifespan_patches(mock_qdrant):
            stack.enter_context(p)
        stack.enter_context(
            patch("app.api.v1.routes.documents.get_embedder", return_value=mock_embedder_for_api)
        )
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ingestion/documents",
                files={"file": ("guide.txt", b"# VPN Guide\n\nConnect via Cisco AnyConnect.", "text/plain")},
            )

    assert response.status_code == 201
    body = response.json()
    assert body["chunks_created"] >= 1
    assert body["filename"] == "guide.txt"
    assert len(body["doc_id"]) == 16


@pytest.mark.asyncio
async def test_ingest_document_doc_id_is_content_hash(mock_qdrant, mock_embedder_for_api):
    from app.main import create_app
    from contextlib import ExitStack

    content = b"# Access Policy\n\nUse SSO for all internal tools."
    expected_doc_id = hashlib.sha256(content).hexdigest()[:16]

    with ExitStack() as stack:
        for p in _lifespan_patches(mock_qdrant):
            stack.enter_context(p)
        stack.enter_context(
            patch("app.api.v1.routes.documents.get_embedder", return_value=mock_embedder_for_api)
        )
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ingestion/documents",
                files={"file": ("policy.txt", content, "text/plain")},
            )

    assert response.json()["doc_id"] == expected_doc_id


@pytest.mark.asyncio
async def test_ingest_document_upserts_to_qdrant(mock_qdrant, mock_embedder_for_api):
    from app.main import create_app
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _lifespan_patches(mock_qdrant):
            stack.enter_context(p)
        stack.enter_context(
            patch("app.api.v1.routes.documents.get_embedder", return_value=mock_embedder_for_api)
        )
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/v1/ingestion/documents",
                files={"file": ("runbook.txt", b"# Runbook\n\nRestart the service.", "text/plain")},
            )

    mock_qdrant.upsert.assert_called_once()
    points = mock_qdrant.upsert.call_args.kwargs["points"]
    assert len(points) >= 1
    assert points[0].payload["source_type"] == "document"


@pytest.mark.asyncio
async def test_ingest_document_422_on_zip_upload(mock_qdrant):
    from app.main import create_app
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _lifespan_patches(mock_qdrant):
            stack.enter_context(p)
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ingestion/documents",
                files={"file": ("bundle.zip", b"PK\x03\x04fake-zip-bytes", "application/zip")},
            )

    assert response.status_code == 422
    mock_qdrant.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_document_422_on_empty_file(mock_qdrant):
    from app.main import create_app
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _lifespan_patches(mock_qdrant):
            stack.enter_context(p)
        mock_conv = stack.enter_context(patch("app.rag.document_converter._converter"))
        mock_conv.convert.return_value = MagicMock(text_content="")
        app = create_app()
        app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ingestion/documents",
                files={"file": ("empty.txt", b"", "text/plain")},
            )

    assert response.status_code == 422
