"""Unit tests for app.rag.chunker.DynamicChunker."""

import pytest

from app.rag.chunker import (
    COMMENT_SPLIT_TOKENS,
    OVERLAP_TOKENS,
    DynamicChunker,
    _build_comment_block,
    _build_title_desc,
)
from app.models.jsm import JSMComment, JSMTicket
from datetime import datetime, timezone


@pytest.fixture
def chunker() -> DynamicChunker:
    return DynamicChunker()


# ── title_desc chunk ──────────────────────────────────────────────────────────

def test_title_desc_always_created(chunker, sample_ticket):
    chunks = chunker.chunk(sample_ticket)
    types = [c.chunk_type for c in chunks]
    assert "title_desc" in types


def test_title_desc_content_includes_summary(chunker, sample_ticket):
    chunks = chunker.chunk(sample_ticket)
    td = next(c for c in chunks if c.chunk_type == "title_desc")
    assert sample_ticket.summary in td.content


def test_title_desc_content_includes_description(chunker, sample_ticket):
    chunks = chunker.chunk(sample_ticket)
    td = next(c for c in chunks if c.chunk_type == "title_desc")
    assert "error 691" in td.content


def test_title_desc_chunk_id_format(chunker, sample_ticket):
    chunks = chunker.chunk(sample_ticket)
    td = next(c for c in chunks if c.chunk_type == "title_desc")
    assert td.chunk_id == f"{sample_ticket.ticket_id}__title_desc"


# ── resolution chunk ──────────────────────────────────────────────────────────

def test_resolution_chunk_created_when_present(chunker, sample_ticket):
    chunks = chunker.chunk(sample_ticket)
    assert any(c.chunk_type == "resolution" for c in chunks)


def test_resolution_chunk_not_created_when_absent(chunker, sample_ticket):
    ticket = sample_ticket.model_copy(update={"resolution_note": None})
    chunks = chunker.chunk(ticket)
    assert not any(c.chunk_type == "resolution" for c in chunks)


def test_resolution_content_matches(chunker, sample_ticket):
    chunks = chunker.chunk(sample_ticket)
    res = next(c for c in chunks if c.chunk_type == "resolution")
    assert sample_ticket.resolution_note in res.content


# ── comments chunk ────────────────────────────────────────────────────────────

def test_comments_chunk_created_when_present(chunker, sample_ticket):
    chunks = chunker.chunk(sample_ticket)
    assert any(c.chunk_type == "comments" for c in chunks)


def test_no_comments_chunk_when_empty(chunker, sample_ticket):
    ticket = sample_ticket.model_copy(update={"comments": []})
    chunks = chunker.chunk(ticket)
    assert not any(c.chunk_type == "comments" for c in chunks)


def test_short_comments_single_chunk(chunker, sample_ticket):
    comment_chunks = [c for c in chunker.chunk(sample_ticket) if c.chunk_type == "comments"]
    assert len(comment_chunks) == 1
    assert comment_chunks[0].chunk_id == f"{sample_ticket.ticket_id}__comments"


def test_long_comments_split_into_windows(chunker, sample_ticket):
    """Comments exceeding COMMENT_SPLIT_TOKENS tokens must be split."""
    # Build a comment body that is definitely > COMMENT_SPLIT_TOKENS tokens
    long_body = "network packet timeout error repeated " * 40  # ~320 tokens each
    long_comments = [
        JSMComment(
            author="Tech",
            body=long_body,
            created=datetime(2024, 1, 10, 9, 0, tzinfo=timezone.utc),
        )
        for _ in range(3)  # 3 × ~320 ≈ 960 tokens — well above 512
    ]
    ticket = sample_ticket.model_copy(update={"comments": long_comments})
    comment_chunks = [c for c in chunker.chunk(ticket) if c.chunk_type == "comments"]

    assert len(comment_chunks) > 1
    # Sub-chunks must follow indexed ID format
    for i, chunk in enumerate(comment_chunks):
        assert chunk.chunk_id == f"{ticket.ticket_id}__comments__{i}"


def test_split_chunks_have_overlap(chunker, sample_ticket):
    """Verify consecutive windows share overlapping tokens."""
    long_body = "the quick brown fox jumps over the lazy dog " * 30
    long_comments = [
        JSMComment(
            author="Tech",
            body=long_body,
            created=datetime(2024, 1, 10, 9, 0, tzinfo=timezone.utc),
        )
        for _ in range(4)
    ]
    ticket = sample_ticket.model_copy(update={"comments": long_comments})
    comment_chunks = [c for c in chunker.chunk(ticket) if c.chunk_type == "comments"]

    assert len(comment_chunks) >= 2
    # The end of window N and start of window N+1 must share some text
    end_of_first = comment_chunks[0].content[-50:]
    start_of_second = comment_chunks[1].content[:50]
    # At least some characters overlap (not an exact equality — token boundaries differ)
    assert len(set(end_of_first.split()) & set(start_of_second.split())) > 0


# ── metadata ──────────────────────────────────────────────────────────────────

def test_chunk_metadata_fields(chunker, sample_ticket):
    chunks = chunker.chunk(sample_ticket)
    for chunk in chunks:
        assert chunk.metadata.ticket_id == sample_ticket.ticket_id
        assert chunk.metadata.category == sample_ticket.category
        assert chunk.metadata.priority == sample_ticket.priority
        assert chunk.metadata.chunk_type == chunk.chunk_type


def test_chunk_ticket_id_matches(chunker, sample_ticket):
    for chunk in chunker.chunk(sample_ticket):
        assert chunk.ticket_id == sample_ticket.ticket_id


# ── chunk_many ────────────────────────────────────────────────────────────────

def test_chunk_many_aggregates_all_tickets(chunker, sample_tickets):
    # TEST-003 has no resolution or comments — only title_desc
    chunks = chunker.chunk_many(sample_tickets)
    ticket_ids_in_chunks = {c.ticket_id for c in chunks}
    assert "TEST-001" in ticket_ids_in_chunks
    assert "TEST-002" in ticket_ids_in_chunks
    assert "TEST-003" in ticket_ids_in_chunks


def test_chunk_many_minimum_one_per_ticket(chunker, sample_tickets):
    chunks = chunker.chunk_many(sample_tickets)
    for ticket in sample_tickets:
        assert any(c.ticket_id == ticket.ticket_id for c in chunks)
