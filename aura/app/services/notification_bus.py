"""In-process WebSocket connection registry and event broadcast bus.

One singleton instance (`notification_bus`) is imported by all agent nodes,
services, and route handlers that need to push real-time events to clients.

Event envelope:
    { "event_type": str, "payload": dict, "timestamp": ISO-8601 }

Broadcast targets — every one of these is scoped to a single tenant, since
team_id is only unique within a tenant and "admin" must mean "this tenant's
admin," never every admin across every client:
    send_to_user(user_id, ...)                    — single user
    broadcast_to_team(tenant_id, team_id, ...)     — one team, one tenant
    broadcast_to_admins(tenant_id, ...)            — that tenant's admins only
    broadcast_to_tenant(tenant_id, ...)            — every connected user in one tenant
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from app.core.logging import get_logger

log = get_logger(__name__)


class NotificationBus:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._user_tenants: dict[str, str | None] = {}
        self._user_teams: dict[str, str | None] = {}
        self._user_roles: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def register(
        self,
        user_id: str,
        websocket: WebSocket,
        *,
        tenant_id: str | None = None,
        team_id: str | None = None,
        role: str = "end_user",
    ) -> None:
        async with self._lock:
            self._connections[user_id] = websocket
            self._user_tenants[user_id] = tenant_id
            self._user_teams[user_id] = team_id
            self._user_roles[user_id] = role
        log.info("ws.connected", user_id=user_id, tenant_id=tenant_id, role=role, team_id=team_id)

    async def unregister(self, user_id: str) -> None:
        async with self._lock:
            self._connections.pop(user_id, None)
            self._user_tenants.pop(user_id, None)
            self._user_teams.pop(user_id, None)
            self._user_roles.pop(user_id, None)
        log.info("ws.disconnected", user_id=user_id)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _envelope(self, event_type: str, payload: dict[str, Any]) -> str:
        return json.dumps(
            {
                "event_type": event_type,
                "payload": payload,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            default=str,
        )

    async def _safe_send(self, user_id: str, ws: WebSocket, data: str) -> bool:
        try:
            await ws.send_text(data)
            return True
        except Exception:
            log.warning("ws.send_failed", user_id=user_id)
            return False

    async def _send_many(
        self,
        targets: list[tuple[str, WebSocket]],
        data: str,
    ) -> None:
        dead: list[str] = []
        for uid, ws in targets:
            ok = await self._safe_send(uid, ws, data)
            if not ok:
                dead.append(uid)
        for uid in dead:
            await self.unregister(uid)

    # ── Public broadcast API ──────────────────────────────────────────────────

    async def send_to_user(
        self, user_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        ws = self._connections.get(user_id)
        if ws:
            await self._safe_send(user_id, ws, self._envelope(event_type, payload))

    async def broadcast_to_team(
        self, tenant_id: str, team_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        data = self._envelope(event_type, payload)
        targets = [
            (uid, ws)
            for uid, ws in list(self._connections.items())
            if self._user_tenants.get(uid) == tenant_id and self._user_teams.get(uid) == team_id
        ]
        await self._send_many(targets, data)

    async def broadcast_to_admins(
        self, tenant_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        data = self._envelope(event_type, payload)
        targets = [
            (uid, ws)
            for uid, ws in list(self._connections.items())
            if self._user_tenants.get(uid) == tenant_id and self._user_roles.get(uid) == "admin"
        ]
        await self._send_many(targets, data)

    async def broadcast_to_tenant(
        self, tenant_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        data = self._envelope(event_type, payload)
        targets = [
            (uid, ws)
            for uid, ws in list(self._connections.items())
            if self._user_tenants.get(uid) == tenant_id
        ]
        await self._send_many(targets, data)


# Module-level singleton — import this everywhere:
#   from app.services.notification_bus import notification_bus
notification_bus = NotificationBus()
