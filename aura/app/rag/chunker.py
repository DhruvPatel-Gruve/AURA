"""Dynamic chunker for JSM resolved tickets.

Produces up to 3 named chunks per ticket:
  - title_desc  : summary + description  (always created)
  - comments    : comment thread(s)      (created when comments exist)
  - resolution  : resolution note        (created when resolution note exists)

Comment threads longer than COMMENT_SPLIT_TOKENS are split into overlapping
sub-chunks of COMMENT_SPLIT_TOKENS tokens with OVERLAP_TOKENS overlap.
Sub-chunk IDs follow the pattern: "{ticket_id}__comments__{n}".
"""

import re
from datetime import datetime, timezone
from typing import Sequence

import tiktoken

from app.core.logging import get_logger
from app.models.jsm import (
    ChunkMetadata,
    DocumentChunk,
    DocumentChunkMetadata,
    JSMTicket,
    TicketChunk,
)

log = get_logger(__name__)

# Token budget above which a comment block is split into overlapping windows
COMMENT_SPLIT_TOKENS = 512
OVERLAP_TOKENS = 50

# tiktoken encoding — cl100k_base matches Gemini's approximate tokenisation
_ENCODING_NAME = "cl100k_base"


class DynamicChunker:
    def __init__(self) -> None:
        self._enc = tiktoken.get_encoding(_ENCODING_NAME)

    def chunk(self, ticket: JSMTicket) -> list[TicketChunk]:
        """Return all chunks for a single ticket. Minimum 1, maximum varies."""
        chunks: list[TicketChunk] = []

        # ── Chunk 1: title + description ──────────────────────────────────────
        title_desc_text = _build_title_desc(ticket)
        chunks.append(
            self._make_chunk(
                ticket=ticket,
                chunk_type="title_desc",
                content=title_desc_text,
                index=None,
            )
        )

        # ── Chunk 2: comments (split if long) ─────────────────────────────────
        if ticket.comments:
            comment_text = _build_comment_block(ticket)
            token_count = self._count_tokens(comment_text)

            if token_count <= COMMENT_SPLIT_TOKENS:
                chunks.append(
                    self._make_chunk(
                        ticket=ticket,
                        chunk_type="comments",
                        content=comment_text,
                        index=None,
                    )
                )
            else:
                windows = self._sliding_window(comment_text)
                for n, window_text in enumerate(windows):
                    chunks.append(
                        self._make_chunk(
                            ticket=ticket,
                            chunk_type="comments",
                            content=window_text,
                            index=n,
                        )
                    )

        # ── Chunk 3: resolution note ───────────────────────────────────────────
        if ticket.resolution_note and ticket.resolution_note.strip():
            chunks.append(
                self._make_chunk(
                    ticket=ticket,
                    chunk_type="resolution",
                    content=ticket.resolution_note.strip(),
                    index=None,
                )
            )

        log.debug(
            "chunker.ticket_chunked",
            ticket_id=ticket.ticket_id,
            chunk_count=len(chunks),
        )
        return chunks

    def chunk_many(self, tickets: Sequence[JSMTicket]) -> list[TicketChunk]:
        all_chunks: list[TicketChunk] = []
        for ticket in tickets:
            all_chunks.extend(self.chunk(ticket))
        return all_chunks

    # ── Document chunking ─────────────────────────────────────────────────────

    def chunk_document(self, doc_id: str, filename: str, markdown: str) -> list[DocumentChunk]:
        """Chunk a Markdown document by headers with sliding-window fallback.

        Splits on H1/H2/H3 boundaries first. Sections that exceed
        COMMENT_SPLIT_TOKENS are further split with the same 50-token overlap
        used for long comment threads.
        """
        sections = _split_by_headers(markdown)
        chunks: list[DocumentChunk] = []
        idx = 0
        uploaded_at = datetime.now(timezone.utc)

        for section in sections:
            content = section.strip()
            if not content:
                continue
            if self._count_tokens(content) <= COMMENT_SPLIT_TOKENS:
                chunks.append(self._make_doc_chunk(doc_id, filename, content, idx, uploaded_at))
                idx += 1
            else:
                for window in self._sliding_window(content):
                    chunks.append(self._make_doc_chunk(doc_id, filename, window, idx, uploaded_at))
                    idx += 1

        log.debug("chunker.document_chunked", doc_id=doc_id, chunk_count=len(chunks))
        return chunks

    def _make_doc_chunk(
        self, doc_id: str, filename: str, content: str, index: int, uploaded_at: datetime
    ) -> DocumentChunk:
        chunk_type = f"section_{index}"
        return DocumentChunk(
            chunk_id=f"{doc_id}__section__{index}",
            doc_id=doc_id,
            chunk_type=chunk_type,
            content=content,
            metadata=DocumentChunkMetadata(
                doc_id=doc_id,
                filename=filename,
                chunk_type=chunk_type,
                uploaded_at=uploaded_at,
            ),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_chunk(
        self,
        ticket: JSMTicket,
        chunk_type: str,
        content: str,
        index: int | None,
    ) -> TicketChunk:
        if index is None:
            chunk_id = f"{ticket.ticket_id}__{chunk_type}"
        else:
            chunk_id = f"{ticket.ticket_id}__{chunk_type}__{index}"

        return TicketChunk(
            chunk_id=chunk_id,
            ticket_id=ticket.ticket_id,
            chunk_type=chunk_type,  # type: ignore[arg-type]
            content=content,
            metadata=ChunkMetadata(
                ticket_id=ticket.ticket_id,
                category=ticket.category,
                priority=ticket.priority,
                resolved_date=ticket.resolved,
                chunk_type=chunk_type,  # type: ignore[arg-type]
            ),
        )

    def _count_tokens(self, text: str) -> int:
        return len(self._enc.encode(text))

    def _sliding_window(self, text: str) -> list[str]:
        """Split *text* into overlapping token windows.

        Each window is COMMENT_SPLIT_TOKENS tokens wide with OVERLAP_TOKENS
        overlap between consecutive windows.
        """
        tokens = self._enc.encode(text)
        step = COMMENT_SPLIT_TOKENS - OVERLAP_TOKENS
        windows: list[str] = []
        start = 0
        while start < len(tokens):
            window_tokens = tokens[start : start + COMMENT_SPLIT_TOKENS]
            windows.append(self._enc.decode(window_tokens))
            if start + COMMENT_SPLIT_TOKENS >= len(tokens):
                break
            start += step
        return windows


# ── Text builders & splitters ────────────────────────────────────────────────

def _build_title_desc(ticket: JSMTicket) -> str:
    parts = [f"Title: {ticket.summary}"]
    if ticket.description and ticket.description.strip():
        parts.append(f"Description: {ticket.description.strip()}")
    if ticket.category:
        parts.append(f"Category: {ticket.category}")
    parts.append(f"Priority: {ticket.priority}")
    return "\n\n".join(parts)


def _split_by_headers(text: str) -> list[str]:
    """Split Markdown on H1/H2/H3 boundaries, keeping the header with its section."""
    parts = re.split(r"(?=^#{1,3} )", text, flags=re.MULTILINE)
    return [p for p in parts if p.strip()]


def _build_comment_block(ticket: JSMTicket) -> str:
    lines: list[str] = []
    for comment in ticket.comments:
        ts = comment.created.strftime("%Y-%m-%d %H:%M")
        lines.append(f"[{ts}] {comment.author}: {comment.body.strip()}")
    return "\n\n".join(lines)
