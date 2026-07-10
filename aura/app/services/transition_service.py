"""Shared helper for ITSM status transitions — used by the acknowledge route
(tickets.py, Open -> "in progress" the moment a technician picks a ticket up)
and the idle-conversation auto-resolve flow (conversation_service.py), so the
"transition + register a reverse rollback" logic exists in exactly one place.
"""

from app.core.logging import get_logger
from app.db.sqlite import get_session
from app.services import itsm_provider_state, rollback_store, ticket_status

log = get_logger(__name__)

# The "someone is actively working this" status, named the same on both
# providers in practice: Jira has a native "In Progress" workflow state, and
# ZendeskClient resolves "In Progress" against the account's Custom Ticket
# Statuses (Zendesk's base status enum has no such state on its own — this
# only works if the account has defined a custom "In Progress" status; see
# ZendeskClient.find_transition_id for the fallback when it hasn't).
_IN_PROGRESS_STATUS_BY_PROVIDER = {
    "jira": "In Progress",
    "zendesk": "In Progress",
}

# Same idea for "done" — Jira's workflow calls it "Resolved"; Zendesk's fixed
# enum calls the equivalent state "solved".
_RESOLVED_STATUS_BY_PROVIDER = {
    "jira": "Resolved",
    "zendesk": "solved",
}


def in_progress_status_name(tenant_id: str) -> str:
    """The active provider's status name for "an agent is on this now" —
    used when a technician acknowledges a ticket, so the real ITSM ticket's
    status stays a live, accurate picture of who's actually working it."""
    return _IN_PROGRESS_STATUS_BY_PROVIDER.get(itsm_provider_state.get(tenant_id), "In Progress")


def resolved_status_name(tenant_id: str) -> str:
    """The active provider's status name for "this is done"."""
    return _RESOLVED_STATUS_BY_PROVIDER.get(itsm_provider_state.get(tenant_id), "Resolved")


async def try_transition(
    tenant_id: str,
    ticket_id: str,
    target_status: str,
    original_status: str | None,
    actor: str = "AURA_AGENT",
) -> bool:
    """Best-effort status transition — never raises.

    A transition failure should never block the primary action (posting a
    comment); it's logged and swallowed. Registers a rollback (transition
    back to original_status) when a reverse transition can be found.

    Returns True if the transition was applied, False otherwise (already
    at that status, not reachable, or the call failed).
    """
    try:
        from app.services.itsm_client import get_itsm_client

        async with get_itsm_client(tenant_id) as itsm:
            transition_id = await itsm.find_transition_id(ticket_id, target_status)
            if transition_id is None:
                return False  # already there, or not reachable from current status
            await itsm.transition_issue(ticket_id, transition_id)

            reverse_id = None
            if original_status:
                reverse_id = await itsm.find_transition_id(ticket_id, original_status)

        async with get_session() as db:
            await ticket_status.set_status(db, tenant_id, ticket_id, target_status)
            if reverse_id:
                await rollback_store.register(
                    db,
                    tenant_id=tenant_id,
                    action_type="ticket_transitioned",
                    ticket_id=ticket_id,
                    rollback_call={
                        "method": "POST",
                        "url": f"/rest/api/3/issue/{ticket_id}/transitions",
                        "body": {"transition": {"id": reverse_id}},
                    },
                    actor=actor,
                )
        return True
    except Exception as exc:
        log.error(
            "transition_service.transition_failed",
            ticket_id=ticket_id,
            target_status=target_status,
            error=str(exc),
        )
        return False
