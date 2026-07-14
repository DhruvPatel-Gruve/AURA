"""Node 4 — Triage classifier.

Calls Qwen3 8B (via Ollama OpenAI-compatible endpoint) in JSON mode to
classify the ticket into one of the admin-configured categories.
Falls back to "Other" on any LLM error or low-confidence response.
"""

import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import text as sa_text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.sqlite import get_session
from app.models.agent_state import AgentState
from app.services.ai_config_service import get_ai_config, get_llm_client

log = get_logger(__name__)


async def triage_node(state: AgentState) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    tenant_id = state["tenant_id"]
    ai_config = get_ai_config(tenant_id)
    raw = state["raw_ticket"]

    # Load admin-configured categories
    async with get_session() as db:
        result = await db.execute(
            sa_text("SELECT name, team_id FROM category_config WHERE tenant_id = :tid ORDER BY name"),
            {"tid": tenant_id},
        )
        rows = result.mappings().all()

    if not rows:
        step = {
            "node_name": "triage_node",
            "timestamp": now,
            "decision": "No categories configured — defaulting to 'Other'",
            "metadata": {},
        }
        return {"category": "Other", "assigned_team": None, "audit_steps": [step]}

    category_names = [r["name"] for r in rows]
    team_by_category: dict[str, str | None] = {r["name"]: r["team_id"] for r in rows}

    client = get_llm_client(tenant_id)

    system_prompt = (
        "You are an IT support triage assistant. "
        "Classify the incoming support ticket into exactly one predefined category. "
        "Respond with valid JSON only — no explanation, no markdown.\n"
        f"Available categories: {json.dumps(category_names)}\n"
        "If the ticket does not clearly fit any category, use \"Other\".\n"
        'JSON schema: {"category": "<name>", "confidence": <float 0.0-1.0>}'
    )
    user_prompt = (
        f"Ticket Title: {raw.get('summary', '')}\n"
        f"Description: {(raw.get('description') or '(none)')[:800]}"
    )

    category = "Other"
    triage_confidence = 0.5
    llm_error: str | None = None

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=ai_config.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=64,
                temperature=0,
            ),
            timeout=get_settings().ollama_timeout_seconds,
        )
        raw_text = (response.choices[0].message.content or "{}").strip()
        # Strip markdown code fences if model wraps the JSON
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1].lstrip("json").strip()
        parsed = json.loads(raw_text)
        candidate = parsed.get("category", "Other")
        triage_confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        category = candidate if candidate in category_names and triage_confidence >= 0.5 else "Other"
    except Exception as exc:
        llm_error = str(exc)
        log.error("triage_node.llm_call_failed", ticket_id=state["ticket_id"], error=llm_error)

    assigned_team = team_by_category.get(category)

    step = {
        "node_name": "triage_node",
        "timestamp": now,
        "decision": (
            f"LLM call failed, defaulted to '{category}': {llm_error}"
            if llm_error
            else f"Category='{category}' (confidence={triage_confidence:.2f})"
        ),
        "metadata": {"triage_confidence": triage_confidence, "llm_error": llm_error},
    }
    return {
        "category": category,
        "assigned_team": assigned_team,
        "audit_steps": [step],
    }
