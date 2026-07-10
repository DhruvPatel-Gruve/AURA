"""WebSocket endpoint — real-time notification bus.

WS /ws/{user_id}?token=<jwt>

Clients connect with a valid JWT passed as a query param (WebSocket headers
are not browser-accessible). The connection is registered in NotificationBus
so the backend can push typed events (SLA_WARNING, AURA_COMMENT_POSTED, etc.)
directly to individual users or broadcast to teams/admins.
"""

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import text as sa_text

from app.core.security import decode_access_token
from app.db.sqlite import get_session
from app.services.notification_bus import notification_bus

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    token: str = Query(..., description="JWT access token"),
) -> None:
    # Validate JWT before accepting the connection
    try:
        payload = decode_access_token(token)
        token_user_id: str = payload.get("sub", "")
        role: str = payload.get("role", "end_user")
        if token_user_id != user_id:
            await websocket.close(code=4001)
            return
    except Exception:
        await websocket.close(code=4001)
        return

    # tenant_id/team_id aren't in the JWT — read them fresh from the DB so
    # broadcast_to_team()/broadcast_to_admins()/broadcast_to_tenant() can
    # actually find this connection instead of matching against None.
    async with get_session() as db:
        row = (await db.execute(
            sa_text("SELECT tenant_id, team_id FROM users WHERE user_id = :uid"), {"uid": user_id}
        )).first()
    tenant_id = row[0] if row else None
    team_id = row[1] if row else None

    await websocket.accept()
    await notification_bus.register(user_id, websocket, tenant_id=tenant_id, team_id=team_id, role=role)

    try:
        # Keep connection alive; client messages are not expected but won't error
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await notification_bus.unregister(user_id)
