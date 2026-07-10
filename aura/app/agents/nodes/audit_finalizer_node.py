"""Terminal node — Audit finalizer.

Runs unconditionally at the end of every pipeline execution path.
Assembles the AuditEntry from the final state and persists it to audit_log.
"""

import uuid
from datetime import datetime, timezone

from app.db.sqlite import get_session
from app.models.agent_state import AgentState
from app.models.audit import AuditEntry, AuditStep
from app.services import audit_logger, ticket_status
from app.core.logging import get_logger

log = get_logger(__name__)


async def audit_finalizer_node(state: AgentState) -> dict:
    now = datetime.now(timezone.utc)

    steps: list[AuditStep] = []
    for raw_step in state.get("audit_steps") or []:
        if isinstance(raw_step, dict):
            steps.append(AuditStep(**raw_step))
        else:
            steps.append(raw_step)

    entry = AuditEntry(
        entry_id=str(uuid.uuid4()),
        tenant_id=state["tenant_id"],
        ticket_id=state["ticket_id"],
        action_taken=state.get("action_taken") or "unknown",
        priority=state.get("priority"),
        category=state.get("category"),
        auto_comment_enabled=state.get("auto_comment_enabled"),
        confidence_score=state.get("confidence_score"),
        abstained=state.get("abstained", False),
        jsm_comment_id=state.get("jsm_comment_id"),
        audit_steps=steps,
        created_at=now,
    )

    async with get_session() as db:
        await audit_logger.log_entry(db, entry)
        raw_status = (state.get("raw_ticket") or {}).get("status")
        await ticket_status.set_status(db, state["tenant_id"], state["ticket_id"], raw_status)

    log.info(
        "agent.pipeline.complete",
        ticket_id=state["ticket_id"],
        action_taken=state.get("action_taken"),
        confidence=state.get("confidence_score"),
        halted=state.get("pipeline_halted"),
        halt_reason=state.get("halt_reason"),
    )

    return {}
