"""Node 8 — Abstention gate.

Probes the top Qdrant retrieval score for the query.  If it's below the
admin-configured abstention_threshold (default 0.60), no relevant resolved
ticket exists in the KB — halt and flag for manual handling.

Never calls the LLM — purely vector-search-based.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import text as sa_text

from app.db.qdrant_client import ensure_tenant_collection
from app.db.sqlite import get_session
from app.models.agent_state import AgentState
from app.rag.retriever import HybridRetriever
from app.services.notification_bus import notification_bus

_FALLBACK_THRESHOLD = 0.60


async def abstention_node(state: AgentState) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    tenant_id = state["tenant_id"]

    async with get_session() as db:
        result = await db.execute(
            sa_text("SELECT abstention_threshold FROM platform_config WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        row = result.first()
    threshold = float(row[0]) if row and row[0] is not None else _FALLBACK_THRESHOLD

    raw = state["raw_ticket"]
    query_text = (raw.get("summary") or "") + "\n" + (raw.get("description") or "")

    collection = await ensure_tenant_collection(tenant_id)
    retriever = HybridRetriever()
    top_score, query_embedding = await retriever.probe_top_score(
        query_text=query_text,
        collection=collection,
        query_vector=state.get("query_embedding"),
    )

    if top_score < threshold:
        async with get_session() as db:
            await db.execute(
                sa_text(
                    "INSERT OR REPLACE INTO low_confidence_queue "
                    "(queue_id, tenant_id, ticket_id, formatted_comment, confidence_score, "
                    " citations, abstained, team_id, reporter_account_id, queued_at) "
                    "VALUES (:qid, :tenant, :tid, :comment, :score, '[]', 1, :team, :rid, :now)"
                ),
                {
                    "qid": str(uuid.uuid4()),
                    "tenant": tenant_id,
                    "tid": state["ticket_id"],
                    "comment": (
                        "AURA: No sufficiently similar resolved ticket found in the "
                        "knowledge base. This ticket requires manual technician handling."
                    ),
                    "score": top_score,
                    "team": state.get("assigned_team") or "",
                    "rid": raw.get("reporter_account_id"),
                    "now": now,
                },
            )

        await notification_bus.broadcast_to_tenant(
            tenant_id,
            "ABSTENTION_FLAGGED",
            {
                "ticket_id": state["ticket_id"],
                "top_score": round(top_score, 4),
                "threshold": threshold,
                "category": state.get("category"),
            },
        )

        step = {
            "node_name": "abstention_node",
            "timestamp": now,
            "decision": f"Abstained: top KB score {top_score:.2f} < threshold {threshold:.2f}",
            "metadata": {"top_score": top_score, "threshold": threshold},
        }
        return {
            "abstained": True,
            "top_retrieval_score": top_score,
            "abstention_reason": (
                f"Top retrieval score {top_score:.2f} is below the abstention "
                f"threshold {threshold:.2f}."
            ),
            "query_embedding": query_embedding,
            "pipeline_halted": True,
            "halt_reason": "abstention",
            "action_taken": "abstained_no_kb_coverage",
            "audit_steps": [step],
        }

    step = {
        "node_name": "abstention_node",
        "timestamp": now,
        "decision": f"KB coverage sufficient (top score={top_score:.2f} >= {threshold:.2f}) — proceeding",
        "metadata": {"top_score": top_score, "threshold": threshold},
    }
    return {
        "abstained": False,
        "top_retrieval_score": top_score,
        "query_embedding": query_embedding,
        "audit_steps": [step],
    }
