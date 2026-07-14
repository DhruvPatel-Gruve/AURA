"""LangGraph agent state definitions.

AgentState is a TypedDict — each node returns only the keys it mutates and
LangGraph merges the partial update into the shared state dict.
"""

import operator
from typing import Annotated, TypedDict


class RetrievedChunk(TypedDict):
    chunk_id: str
    ticket_id: str
    chunk_type: str
    content: str
    score: float
    metadata: dict


class AuditStep(TypedDict):
    node_name: str
    timestamp: str   # ISO-8601 UTC
    decision: str    # Human-readable outcome of this node
    metadata: dict   # Node-specific detail (matched_phrase, score, etc.)


class AgentState(TypedDict):
    # ── Input — populated by jsm_poller before graph entry ───────────────────
    tenant_id: str
    ticket_id: str
    raw_ticket: dict            # Serialised JSMTicket

    # ── Pipeline control ──────────────────────────────────────────────────────
    pipeline_halted: bool       # Default: False
    halt_reason: str | None

    # ── Node 2: Priority ──────────────────────────────────────────────────────
    priority: str | None        # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    priority_method: str | None # "keyword_rule" | "historical_match" | "default_fallback"
    query_embedding: list[float] | None  # 768-dim; cached for reuse by node 8 (abstention)

    # ── Node 4: Triage ────────────────────────────────────────────────────────
    category: str | None
    assigned_team: str | None

    # ── Node 4b: Assignment ───────────────────────────────────────────────────
    assigned_technician: str | None    # user_id of the technician assigned in Jira
    assignment_status: str | None      # "assigned" | "no_technician_available" | "skipped_no_team" | "jsm_error"

    # ── Node 5: Collision ─────────────────────────────────────────────────────
    collision_detected: bool    # Default: False — informational only, never halts
    claimed_by: str | None

    # ── Node 6: Autonomy ──────────────────────────────────────────────────────
    auto_comment_enabled: bool  # per-category toggle: auto-post + transitions + conversation loop

    # ── Node 7: SLA ───────────────────────────────────────────────────────────
    sla_deadline: str | None    # ISO-8601 UTC
    sla_status: str | None      # "ok" | "warning" | "breached"

    # ── Node 8: Abstention ────────────────────────────────────────────────────
    abstained: bool             # Default: False
    abstention_reason: str | None
    top_retrieval_score: float | None

    # ── Node 9: Resolution ────────────────────────────────────────────────────
    retrieved_chunks: list[dict] | None
    llm_raw_response: str | None

    # ── Node 10: Confidence gate ──────────────────────────────────────────────
    confidence_score: float | None
    formatted_comment: str | None   # JSM-ready markdown
    citations: list[str] | None

    # ── Terminal state ────────────────────────────────────────────────────────
    # Possible values:
    #   "comment_posted"        — JSM comment created; rollback record logged
    #   "held_low_confidence"   — Written to low_confidence_queue
    #   "abstained_no_kb_coverage" — Abstention; ticket flagged manually
    #   "halted_kill_switch"    — Kill switch was active
    #   "ai_not_configured"     — Tenant hasn't configured an embedding/LLM provider
    action_taken: str | None
    jsm_comment_id: str | None      # Set on comment_posted; used for rollback

    # ── Audit trail — LangGraph concatenates via operator.add ────────────────
    audit_steps: Annotated[list[dict], operator.add]


def make_initial_state(tenant_id: str, ticket_id: str, raw_ticket: dict) -> AgentState:
    """Build a zeroed-out AgentState for a newly polled ticket."""
    return AgentState(
        tenant_id=tenant_id,
        ticket_id=ticket_id,
        raw_ticket=raw_ticket,
        pipeline_halted=False,
        halt_reason=None,
        priority=None,
        priority_method=None,
        query_embedding=None,
        category=None,
        assigned_team=None,
        assigned_technician=None,
        assignment_status=None,
        collision_detected=False,
        claimed_by=None,
        auto_comment_enabled=False,
        sla_deadline=None,
        sla_status=None,
        abstained=False,
        abstention_reason=None,
        top_retrieval_score=None,
        retrieved_chunks=None,
        llm_raw_response=None,
        confidence_score=None,
        formatted_comment=None,
        citations=None,
        action_taken=None,
        jsm_comment_id=None,
        audit_steps=[],
    )
