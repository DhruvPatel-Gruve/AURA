"""Node 5 — Collision detector.

Checks whether another technician has already claimed this ticket.
Informational only — never halts the pipeline.
"""

from datetime import datetime, timezone

from app.db.sqlite import get_session
from app.models.agent_state import AgentState
from app.services import collision_service


async def collision_node(state: AgentState) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    async with get_session() as db:
        claim = await collision_service.check_claim(db, state["tenant_id"], state["ticket_id"])

    if claim:
        step = {
            "node_name": "collision_node",
            "timestamp": now,
            "decision": f"Ticket claimed by {claim['claimed_by']} until {claim['expires_at']} — noted, continuing",
            "metadata": claim,
        }
        return {
            "collision_detected": True,
            "claimed_by": claim["claimed_by"],
            "audit_steps": [step],
        }

    step = {
        "node_name": "collision_node",
        "timestamp": now,
        "decision": "No active claim — continuing",
        "metadata": {},
    }
    return {
        "collision_detected": False,
        "audit_steps": [step],
    }
