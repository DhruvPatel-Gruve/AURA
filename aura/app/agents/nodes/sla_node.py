"""Node 7 — SLA tracker.

Computes the ticket's SLA deadline from the category's configured sla_minutes,
registers the event in sla_events, and emits WebSocket warnings/breaches.
"""

from datetime import datetime, timezone

from sqlalchemy import text as sa_text

from app.db.sqlite import get_session
from app.models.agent_state import AgentState
from app.services import sla_engine
from app.services.notification_bus import notification_bus

_DEFAULT_SLA_MINUTES = 480  # 8 hours if category has no SLA configured


async def sla_node(state: AgentState) -> dict:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()

    async with get_session() as db:
        result = await db.execute(
            sa_text("SELECT sla_minutes FROM category_config WHERE tenant_id = :tid AND name = :cat"),
            {"tid": state["tenant_id"], "cat": state.get("category") or "Other"},
        )
        row = result.first()
        sla_minutes = int(row[0]) if row and row[0] else _DEFAULT_SLA_MINUTES

        # Parse ticket created_at from raw payload
        raw = state["raw_ticket"]
        created_str = raw.get("created", now)
        try:
            created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            created_at = now_dt

        deadline = sla_engine.compute_deadline(created_at, sla_minutes)
        elapsed_pct = sla_engine.compute_elapsed_pct(created_at, deadline)

        if elapsed_pct >= 100.0:
            status = "breached"
        elif elapsed_pct >= 75.0:
            status = "warning"
        else:
            status = "ok"

        await sla_engine.register(
            db, state["tenant_id"], state["ticket_id"], state.get("category") or "Other", deadline, status,
        )

    ws_payload = {
        "ticket_id": state["ticket_id"],
        "sla_deadline": deadline.isoformat(),
        "elapsed_pct": round(elapsed_pct, 2),
        "category": state.get("category"),
    }
    if status == "warning":
        await notification_bus.broadcast_to_tenant(state["tenant_id"], "SLA_WARNING", ws_payload)
    elif status == "breached":
        await notification_bus.broadcast_to_tenant(state["tenant_id"], "SLA_BREACHED", ws_payload)

    step = {
        "node_name": "sla_node",
        "timestamp": now,
        "decision": f"SLA status={status}, elapsed={elapsed_pct:.1f}%",
        "metadata": {
            "deadline": deadline.isoformat(),
            "elapsed_pct": round(elapsed_pct, 2),
            "sla_minutes": sla_minutes,
        },
    }
    return {
        "sla_deadline": deadline.isoformat(),
        "sla_status": status,
        "audit_steps": [step],
    }
