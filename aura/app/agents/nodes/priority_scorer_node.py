"""Node 2 — Priority scorer.

Two-stage pipeline:
  A. Keyword rules   — fast, deterministic
  B. Semantic match  — query Qdrant resolved_tickets top-3, take statistical mode

Always embeds the query and stores it in state.query_embedding so the
abstention node can reuse the vector without a second Gemini API call.
"""

from datetime import datetime, timezone
from statistics import StatisticsError, mode

from app.core.logging import get_logger
from app.db.qdrant_client import ensure_tenant_collection, get_qdrant_client
from app.models.agent_state import AgentState
from app.services.ai_config_service import get_embedder

log = get_logger(__name__)

_KEYWORD_RULES: dict[str, list[str]] = {
    "CRITICAL": [
        "server down", "production outage", "all users affected",
        "system down", "outage", "data loss", "security breach",
        "cannot login", "complete outage",
    ],
    "HIGH": [
        "vp ", "ceo ", "cto ", "executive", "director", "urgent", "asap",
        "multiple users", "several users", "cannot access", "blocked",
    ],
    "LOW": [
        "how to", "wondering", "question about", "help understanding",
        "documentation", "curious", "feature request",
    ],
}

_JIRA_PRIORITY_MAP = {
    "HIGHEST": "CRITICAL",
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "LOWEST": "LOW",
}


async def priority_scorer_node(state: AgentState) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    raw = state["raw_ticket"]
    text = ((raw.get("summary") or "") + " " + (raw.get("description") or "")).lower()

    # ── Stage A: keyword rules ────────────────────────────────────────────────
    priority: str | None = None
    matched_phrase: str | None = None

    for level in ("CRITICAL", "HIGH", "LOW"):
        for phrase in _KEYWORD_RULES[level]:
            if phrase in text:
                priority = level
                matched_phrase = phrase
                break
        if priority:
            break

    # Always embed query — other nodes depend on state.query_embedding
    embedder = get_embedder(state["tenant_id"])
    query_embedding = state.get("query_embedding") or await embedder.embed_query_text(text[:2000])

    if priority:
        method = "keyword_rule"
    else:
        # ── Stage B: semantic fallback via Qdrant ─────────────────────────────
        client = get_qdrant_client()
        try:
            collection = await ensure_tenant_collection(state["tenant_id"])
            response = await client.query_points(
                collection_name=collection,
                query=query_embedding,
                using="",
                limit=3,
                with_payload=True,
                with_vectors=False,
            )
            hits = response.points
            raw_priorities = [
                (h.payload.get("priority") or "Medium").upper()
                for h in hits
                if h.payload
            ]
            normalized = [_JIRA_PRIORITY_MAP.get(p, "MEDIUM") for p in raw_priorities]
            priority = mode(normalized) if normalized else "MEDIUM"
            method = "historical_match" if normalized else "default_fallback"
        except (Exception, StatisticsError) as exc:
            log.error("priority_scorer_node.qdrant_query_failed", ticket_id=state["ticket_id"], error=str(exc))
            priority = "MEDIUM"
            method = "default_fallback"

    step = {
        "node_name": "priority_scorer_node",
        "timestamp": now,
        "decision": (
            f"Priority={priority} via {method}"
            + (f" (matched: '{matched_phrase}')" if matched_phrase else "")
        ),
        "metadata": {"method": method, "matched_phrase": matched_phrase},
    }

    return {
        "priority": priority,
        "priority_method": method,
        "query_embedding": query_embedding,
        "audit_steps": [step],
    }
