"""Shared "post a comment to JSM and track the conversation" helper.

Used by both the automated confidence gate (confidence_gate_node.py, Path A)
and the technician review-queue routes (tickets.py approve/edit), so a
comment posted either way is tracked identically — the 24h-inactivity
auto-resolve and "reconsider if the reporter replies again" loop
(conversation_service.py) apply the same regardless of who posted it.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services import conversation_service, rollback_store

log = get_logger(__name__)


async def post_and_track(
    db: AsyncSession,
    tenant_id: str,
    ticket_id: str,
    comment: str,
    actor: str,
    reporter_account_id: str | None,
) -> dict:
    """Post `comment` to JSM, register a rollback record, and start/refresh
    conversation tracking for `ticket_id`.

    Raises whatever JSMClient.post_comment_markdown() raises — callers
    decide the fallback (e.g. downgrade to hold-for-review) themselves.

    Returns {"jsm_comment_id": str, "rollback_action_id": str}.
    """
    from app.services.itsm_client import get_itsm_client

    async with get_itsm_client(tenant_id) as itsm:
        jsm_comment_id = await itsm.post_comment_markdown(ticket_id, comment)

    rollback_action_id = await rollback_store.register(
        db,
        tenant_id=tenant_id,
        action_type="comment_posted",
        ticket_id=ticket_id,
        rollback_call={
            "method": "DELETE",
            "url": f"/tickets/{ticket_id}/comments/{jsm_comment_id}",
            "body": None,
        },
        actor=actor,
    )

    # INSERT OR IGNORE — safe if a conversation is already being tracked. If
    # one already existed, bump its watermark instead — this is what makes a
    # technician's approve/edit reset the idle clock exactly like an AURA
    # auto-post does. (A freshly-inserted row already has turn_count=1 and
    # last_aura_comment_at=now, so it doesn't need a separate bump.)
    inserted = await conversation_service.start_tracking(db, tenant_id, ticket_id, reporter_account_id)
    if not inserted:
        await conversation_service.touch(db, tenant_id, ticket_id)

    return {"jsm_comment_id": jsm_comment_id, "rollback_action_id": rollback_action_id}
