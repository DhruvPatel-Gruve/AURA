"""Node 1 — Kill switch gate.

Synchronous check — no DB hit in the hot path (in-process boolean cache).
If the kill switch is OFF: set pipeline_halted=True and return immediately.
"""

from datetime import datetime, timezone

from app.models.agent_state import AgentState
from app.services import kill_switch


def kill_switch_node(state: AgentState) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    enabled = kill_switch.is_enabled(state["tenant_id"])

    step = {
        "node_name": "kill_switch_node",
        "timestamp": now,
        "decision": "Kill switch ON — continuing" if enabled else "Pipeline halted: kill switch is OFF",
        "metadata": {"kill_switch_enabled": enabled},
    }

    if not enabled:
        return {
            "pipeline_halted": True,
            "halt_reason": "kill_switch_active",
            "action_taken": "halted_kill_switch",
            "audit_steps": [step],
        }

    return {"audit_steps": [step]}
