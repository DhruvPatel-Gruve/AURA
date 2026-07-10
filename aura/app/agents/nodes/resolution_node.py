"""Node 9 — Resolution generator.

Three-stage flow:
  1. Hybrid retrieval (dense + BM25 RRF) from resolved_tickets KB
  2. Qwen3 8B RAG-grounded JSON generation (solution + confidence + citations)
  3. Sanitise citations (filter hallucinated ticket IDs), format JSM comment
"""

import asyncio
import json
from datetime import datetime, timezone

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.qdrant_client import ensure_tenant_collection
from app.models.agent_state import AgentState
from app.rag.retriever import HybridRetriever

log = get_logger(__name__)

_TOP_K = 5
_MAX_DESC_CHARS = 1500
_MAX_CONTEXT_CHARS = 4000


async def resolution_node(state: AgentState) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    settings = get_settings()
    raw = state["raw_ticket"]
    query_text = (raw.get("summary") or "") + "\n" + (raw.get("description") or "")

    # ── Stage 1: Hybrid retrieval ─────────────────────────────────────────────
    collection = await ensure_tenant_collection(state["tenant_id"])
    retriever = HybridRetriever()
    chunks = await retriever.retrieve(
        query_text=query_text,
        top_k=_TOP_K,
        collection=collection,
        query_vector=state.get("query_embedding"),
    )

    if not chunks:
        step = {
            "node_name": "resolution_node",
            "timestamp": now,
            "decision": "No chunks retrieved — cannot generate resolution",
            "metadata": {},
        }
        return {
            "retrieved_chunks": [],
            "confidence_score": 0.0,
            "formatted_comment": None,
            "citations": [],
            "audit_steps": [step],
        }

    # ── Stage 2: Format context block ─────────────────────────────────────────
    context_parts: list[str] = []
    total_chars = 0
    for i, chunk in enumerate(chunks, 1):
        block = f"[{i}] {chunk['ticket_id']} ({chunk['chunk_type']}):\n{chunk['content']}"
        if total_chars + len(block) > _MAX_CONTEXT_CHARS:
            break
        context_parts.append(block)
        total_chars += len(block)

    formatted_context = "\n\n".join(context_parts)
    valid_ticket_ids = {c["ticket_id"] for c in chunks}

    # ── Stage 3: LLM call ─────────────────────────────────────────────────────
    client = AsyncOpenAI(
        base_url=settings.ollama_base_url,
        api_key="ollama",
        timeout=settings.ollama_timeout_seconds,
    )

    system_prompt = (
        "You are an IT support assistant. "
        "Resolve the employee's support ticket using ONLY the provided context from "
        "previously resolved tickets. Do not use general knowledge or make up steps.\n"
        "If the context is insufficient, set confidence below 0.5.\n\n"
        "Respond with valid JSON only (no markdown, no explanation):\n"
        '{"solution": "<step-by-step resolution in Markdown>", '
        '"confidence": <float 0.0-1.0>, '
        '"citations": ["<ticket_id>", ...]}\n\n'
        "Confidence guide:\n"
        "  0.9-1.0: Context directly and completely answers the question.\n"
        "  0.7-0.9: Context mostly applies; minor verification recommended.\n"
        "  0.5-0.7: Context partially applies; technician should validate.\n"
        "  0.0-0.5: Context is weak or tangential."
    )
    user_prompt = (
        f"Support Ticket:\n"
        f"Title: {raw.get('summary', '')}\n"
        f"Description: {(raw.get('description') or '(none)')[:_MAX_DESC_CHARS]}\n\n"
        f"Context from Resolved Tickets:\n{formatted_context}"
    )

    confidence_score = 0.5
    solution = "Unable to generate a reliable resolution from the available knowledge base."
    citations: list[str] = []
    llm_raw = ""
    llm_error: str | None = None

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.ollama_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=1024,
                temperature=0.2,
            ),
            timeout=settings.ollama_timeout_seconds,
        )
        llm_raw = (response.choices[0].message.content or "{}").strip()
        # Strip markdown code fences
        if llm_raw.startswith("```"):
            llm_raw = llm_raw.split("```")[1].lstrip("json").strip()
        parsed = json.loads(llm_raw)
        solution = parsed.get("solution") or solution
        confidence_score = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        raw_cits = parsed.get("citations") or []
        # Filter hallucinated IDs — only accept IDs from the retrieved set
        citations = [c for c in raw_cits if c in valid_ticket_ids]
    except Exception as exc:
        llm_error = str(exc)
        log.error("resolution_node.llm_call_failed", ticket_id=state["ticket_id"], error=llm_error)

    formatted_comment = (
        f"**AURA Suggested Resolution** _(Confidence: {confidence_score * 100:.0f}%)_\n\n"
        + solution
        + "\n\n---\n**Sources:** "
        + (", ".join(f"[{tid}]" for tid in citations) if citations else "_none_")
    )

    step = {
        "node_name": "resolution_node",
        "timestamp": now,
        "decision": (
            f"LLM call failed, held at default confidence: {llm_error}"
            if llm_error
            else f"Resolution generated (confidence={confidence_score:.2f}, citations={len(citations)})"
        ),
        "metadata": {"citations": citations, "chunk_count": len(chunks), "llm_error": llm_error},
    }
    return {
        "retrieved_chunks": [dict(c) for c in chunks],
        "llm_raw_response": llm_raw,
        "confidence_score": confidence_score,
        "formatted_comment": formatted_comment,
        "citations": citations,
        "audit_steps": [step],
    }
