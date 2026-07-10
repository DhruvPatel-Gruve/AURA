"""Node 6 — Autonomy enforcer.

Reads the per-category `auto_comment_enabled` toggle and passes it through
to the rest of the pipeline:

  Toggle OFF — AURA still triages and drafts a reply, but it's always queued
               for technician review (never auto-posted).
  Toggle ON  — today's confidence-threshold auto-post/queue split.

Jira status transitions (Open -> In Progress, In Progress -> Resolved) and
the conversation loop are independent of this toggle — see jsm_poller.py and
conversation_service.py.
"""

from datetime import datetime, timezone

from sqlalchemy import text as sa_text

from app.db.sqlite import get_session
from app.models.agent_state import AgentState


async def get_auto_comment_enabled(db, tenant_id: str, category: str | None) -> bool:
    """DB-backed lookup — shared by autonomy_node and any route/service that
    needs the effective toggle for a category outside the graph."""
    result = await db.execute(
        sa_text("SELECT auto_comment_enabled FROM category_config WHERE tenant_id = :tid AND name = :cat"),
        {"tid": tenant_id, "cat": category or "Other"},
    )
    row = result.first()
    return bool(row[0]) if row else False


async def autonomy_node(state: AgentState) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    async with get_session() as db:
        auto_comment_enabled = await get_auto_comment_enabled(db, state["tenant_id"], state.get("category"))

    step = {
        "node_name": "autonomy_node",
        "timestamp": now,
        "decision": f"Auto-comment {'enabled' if auto_comment_enabled else 'disabled'} for category '{state.get('category')}'",
        "metadata": {"auto_comment_enabled": auto_comment_enabled},
    }
    return {
        "auto_comment_enabled": auto_comment_enabled,
        "audit_steps": [step],
    }
