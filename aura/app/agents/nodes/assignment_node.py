"""Node 4b — Technician assignment.

Runs immediately after triage, once category/team are known. Picks the
least-loaded active technician on the assigned team (via assignment_service)
and sets Jira's native Assignee field via jsm_client.assign_ticket() — so a
human is visibly in the loop on the real ticket, regardless of what
autonomy/confidence decide downstream. The resulting assignment is persisted
via assignment_service.record_assignment() so the timeout/reassignment
scheduler job (scheduler/jobs/assignment_timeout_checker.py) can track it.

Informational only — never halts the pipeline. A team with no technician, or
a technician with no linked Jira account, just gets recorded and skipped.
"""

from datetime import datetime, timezone

from app.core.logging import get_logger
from app.db.sqlite import get_session
from app.models.agent_state import AgentState
from app.services import assignment_service
from app.services.notification_bus import notification_bus

log = get_logger(__name__)


async def assignment_node(state: AgentState) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    tenant_id = state["tenant_id"]
    ticket_id = state["ticket_id"]
    assigned_team = state.get("assigned_team")

    if not assigned_team:
        return _result(now, "skipped_no_team", None, "No team assigned for this category — skipping assignment")

    # The whole read-decide-write sequence must be serialized against other
    # concurrent assignments (see assignment_service.ASSIGNMENT_LOCK) — two
    # tickets for the same team triaged milliseconds apart would otherwise
    # both read "technician X has the fewest assignments" before either
    # records theirs, double-booking X.
    async with assignment_service.ASSIGNMENT_LOCK:
        async with get_session() as db:
            technician = await assignment_service.assign(db, tenant_id, team_id=assigned_team)

        if not technician:
            return _result(
                now, "no_technician_available", None,
                f"No active technician found on team '{assigned_team}'",
            )

        async with get_session() as db:
            jira_account_id = await assignment_service.resolve_jira_account(db, technician)

        if not jira_account_id:
            return _result(
                now, "no_jira_account_mapped", technician["user_id"],
                f"Technician '{technician['display_name']}' has no linked Jira account — "
                f"set jira_account_id in User Management",
            )

        try:
            from app.services.itsm_client import get_itsm_client
            async with get_itsm_client(tenant_id) as itsm:
                await itsm.assign_ticket(ticket_id, jira_account_id)
        except Exception as exc:
            log.error("assignment_node.jsm_assign_failed", ticket_id=ticket_id, error=str(exc))
            return _result(
                now, "jsm_error", technician["user_id"],
                f"Failed to assign '{technician['display_name']}' in Jira: {exc}",
            )

        async with get_session() as db:
            await assignment_service.record_assignment(db, tenant_id, ticket_id, technician["user_id"], assigned_team)

    await notification_bus.send_to_user(
        technician["user_id"],
        "TICKET_ASSIGNED",
        {"ticket_id": ticket_id, "technician_id": technician["user_id"], "team": assigned_team},
    )

    return _result(
        now, "assigned", technician["user_id"],
        f"Assigned to '{technician['display_name']}' (team '{assigned_team}') in Jira",
    )


def _result(now: str, status: str, technician_id: str | None, decision: str) -> dict:
    step = {
        "node_name": "assignment_node",
        "timestamp": now,
        "decision": decision,
        "metadata": {"assignment_status": status, "assigned_technician": technician_id},
    }
    return {
        "assigned_technician": technician_id,
        "assignment_status": status,
        "audit_steps": [step],
    }
