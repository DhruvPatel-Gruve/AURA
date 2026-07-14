"""Node 1b — AI configuration gate.

Runs immediately after kill_switch_node, before priority_scorer_node (which
already embeds the query on node entry). No fallback by design: a tenant that
hasn't configured both an embedding provider and an LLM endpoint gets a clean
halt here rather than crashing deep inside GeminiEmbedder/AsyncOpenAI, or
silently borrowing another tenant's or the operator's key.
"""

from datetime import datetime, timezone

from app.models.agent_state import AgentState
from app.services.ai_config_service import get_ai_config


def ai_config_gate_node(state: AgentState) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    config = get_ai_config(state["tenant_id"])

    if not (config.embeddings_configured and config.llm_configured):
        missing = [
            name for name, ok in (
                ("embeddings", config.embeddings_configured),
                ("LLM", config.llm_configured),
            )
            if not ok
        ]
        step = {
            "node_name": "ai_config_gate_node",
            "timestamp": now,
            "decision": f"Pipeline halted: AI not configured for this tenant (missing: {', '.join(missing)})",
            "metadata": {"missing": missing},
        }
        return {
            "pipeline_halted": True,
            "halt_reason": "ai_not_configured",
            "action_taken": "ai_not_configured",
            "audit_steps": [step],
        }

    step = {
        "node_name": "ai_config_gate_node",
        "timestamp": now,
        "decision": "AI configuration present — continuing",
        "metadata": {},
    }
    return {"audit_steps": [step]}
