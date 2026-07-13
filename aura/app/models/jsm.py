from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.models.itsm import ITSMComment, ITSMTicket

# Backwards-compatible aliases — these shapes are provider-agnostic now
# (used by ZendeskClient too, not just JSMClient), see app/models/itsm.py.
JSMComment = ITSMComment
JSMTicket = ITSMTicket


class ChunkMetadata(BaseModel):
    ticket_id: str
    category: str | None = None
    priority: str
    resolved_date: datetime | None = None
    chunk_type: Literal["title_desc", "comments", "resolution"]


ChunkType = Literal["title_desc", "comments", "resolution"]


class TicketChunk(BaseModel):
    # chunk_id format: "{ticket_id}__{chunk_type}" or "{ticket_id}__comments__{n}"
    chunk_id: str
    ticket_id: str
    chunk_type: ChunkType
    content: str
    metadata: ChunkMetadata


class DocumentChunkMetadata(BaseModel):
    doc_id: str
    filename: str
    source_type: Literal["document"] = "document"
    chunk_type: str
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentChunk(BaseModel):
    chunk_id: str
    doc_id: str
    chunk_type: str
    content: str
    metadata: DocumentChunkMetadata


class IngestionRunSummary(BaseModel):
    run_id: str
    started_at: datetime
    completed_at: datetime | None = None
    tickets_fetched: int = 0
    tickets_indexed: int = 0
    tickets_skipped: int = 0
    chunks_created: int = 0
    status: Literal["running", "completed", "failed"] = "running"
    error_message: str | None = None
