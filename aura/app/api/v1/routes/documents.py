"""Document ingestion endpoint.

POST /api/v1/ingestion/documents
  — Upload a file, convert to Markdown, chunk, embed, upsert to Qdrant.
  — Re-uploading the same file is idempotent (UUID5 point IDs overwrite).
"""

import asyncio
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.security import require_admin
from app.db.qdrant_client import ensure_tenant_collection
from app.rag.chunker import DynamicChunker
from app.rag.document_converter import convert_to_markdown
from app.rag.embedder import GeminiEmbedder
from app.rag.ingestion_pipeline import upsert_embedded_chunks
from app.services import kill_switch

log = get_logger(__name__)
router = APIRouter(prefix="/ingestion", tags=["ingestion"])
_settings = get_settings()

_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB read chunks — bounds peak memory while streaming


class DocumentIngestResponse(BaseModel):
    doc_id: str
    filename: str
    chunks_created: int
    message: str


@router.post("/documents", response_model=DocumentIngestResponse, status_code=201)
@limiter.limit(_settings.rate_limit_upload)
async def ingest_document(
    request: Request,
    file: UploadFile,
    current_user: Annotated[dict, Depends(require_admin)],
) -> DocumentIngestResponse:
    """Upload a document and index it into the caller's tenant's Qdrant
    knowledge base.

    The doc_id is a SHA-256 content hash (first 16 hex chars) so re-uploading
    the same file silently overwrites its existing points.
    """
    settings = get_settings()
    tenant_id = current_user["tenant_id"]

    if not kill_switch.is_enabled(tenant_id):
        raise HTTPException(503, "AURA is currently disabled (kill switch active).")

    file_bytes = await _read_upload_capped(file, settings.max_upload_size_bytes)
    filename = file.filename or "document"

    # Stable doc_id from content hash — re-upload overwrites, never duplicates
    doc_id = hashlib.sha256(file_bytes).hexdigest()[:16]
    log.info("documents.ingest_start", doc_id=doc_id, filename=filename, bytes=len(file_bytes))

    # 1. Convert to Markdown — offloaded to a worker thread: markitdown does
    # blocking file I/O/CPU work, and running it inline would stall the event
    # loop for every other concurrent request (including unrelated uploads).
    try:
        markdown = await asyncio.to_thread(convert_to_markdown, file_bytes, filename)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        # Covers markitdown's MissingDependencyException and any other
        # converter-internal failure — never let a single bad/unsupported
        # file crash the request with an opaque 500.
        log.error("documents.conversion_failed", filename=filename, error=str(exc))
        raise HTTPException(422, f"Could not convert '{filename}': {exc}")

    # 2. Chunk (header-aware + sliding window fallback)
    chunker = DynamicChunker()
    chunks = chunker.chunk_document(doc_id=doc_id, filename=filename, markdown=markdown)
    if not chunks:
        raise HTTPException(422, "No content could be extracted from the document.")

    # 3. Embed (dense + sparse BM25)
    embedder = GeminiEmbedder()
    embedder.fit_bm25([c.content for c in chunks])
    embedded = await embedder.embed_chunks(chunks)

    # 4. Upsert to Qdrant
    collection = await ensure_tenant_collection(tenant_id)
    await upsert_embedded_chunks(embedded, collection)

    log.info("documents.ingest_complete", doc_id=doc_id, filename=filename, chunks=len(embedded))
    return DocumentIngestResponse(
        doc_id=doc_id,
        filename=filename,
        chunks_created=len(embedded),
        message=f"Indexed {len(embedded)} chunks from '{filename}'.",
    )


async def _read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an UploadFile in bounded chunks, aborting as soon as the size cap
    is exceeded rather than after buffering the whole (potentially huge) body
    into memory — a single `await file.read()` has no size limit and is a
    trivial memory-exhaustion vector for an admin-authenticated but otherwise
    unbounded upload endpoint."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                413,
                f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)
