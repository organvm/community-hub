"""WebSocket live salon rooms — real-time discussion during active salons."""

from __future__ import annotations

import html
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

router = APIRouter()

# Limits
MAX_MESSAGE_SIZE = 4096  # 4 KB
MAX_MESSAGES_PER_SECOND = 10
MAX_CONNECTIONS_PER_ROOM = 100


class RoomManager:
    """In-process room manager — maps room IDs to sets of active WebSocket connections."""

    def __init__(self):
        self._rooms: dict[str, set[WebSocket]] = {}
        self._rate_state: dict[int, list[float]] = {}  # ws id -> list of timestamps

    def _room(self, room_id: str) -> set[WebSocket]:
        if room_id not in self._rooms:
            self._rooms[room_id] = set()
        return self._rooms[room_id]

    def _check_rate_limit(self, ws: WebSocket) -> bool:
        """Return True if the message is allowed, False if rate-limited."""
        ws_id = id(ws)
        now = time.monotonic()
        timestamps = self._rate_state.get(ws_id, [])
        # Keep only timestamps within the last second
        timestamps = [t for t in timestamps if now - t < 1.0]
        if len(timestamps) >= MAX_MESSAGES_PER_SECOND:
            self._rate_state[ws_id] = timestamps
            return False
        timestamps.append(now)
        self._rate_state[ws_id] = timestamps
        return True

    async def connect(self, room_id: str, ws: WebSocket):
        room = self._room(room_id)
        if len(room) >= MAX_CONNECTIONS_PER_ROOM:
            await ws.close(code=1013, reason="Room is full")
            return False

        await ws.accept()
        room.add(ws)
        count = len(room)
        logger.info("WebSocket joined room %s (%d connected)", room_id, count)
        await self.broadcast(room_id, {
            "type": "system",
            "text": f"A participant joined. {count} connected.",
            "count": count,
        })
        return True

    async def disconnect(self, room_id: str, ws: WebSocket):
        room = self._rooms.get(room_id)
        if room:
            room.discard(ws)
            # Clean up rate state
            self._rate_state.pop(id(ws), None)
            count = len(room)
            if count == 0:
                del self._rooms[room_id]
                logger.info("Room %s empty, removed", room_id)
            else:
                logger.info("WebSocket left room %s (%d remaining)", room_id, count)
                await self.broadcast(room_id, {
                    "type": "system",
                    "text": f"A participant left. {count} connected.",
                    "count": count,
                })

    async def broadcast(self, room_id: str, data: dict):
        room = self._rooms.get(room_id, set())
        dead = []
        message = json.dumps(data)
        for ws in room:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            room.discard(ws)

    def participant_count(self, room_id: str) -> int:
        return len(self._rooms.get(room_id, set()))


manager = RoomManager()


def _validate_token(token: str | None) -> bool:  # allow-secret
    """Validate a session token.

    SECURITY NOTE: This is a placeholder that accepts any string >= 8 chars.
    Live rooms are effectively unauthenticated. This is acceptable while the
    portal is public read-only with no private salons, but must be replaced
    with real session/JWT validation before:
      - private/invite-only salons are introduced
      - user identity matters for message attribution
      - any moderation features are added

    See: https://github.com/organvm-vi-koinonia/community-hub/issues (track as E10)
    """
    return bool(token and len(token) >= 8)


@router.get("/salons/{session_id}/live")
async def salon_live(request: Request, session_id: int):
    """Render the live salon room page."""
    templates = request.app.state.templates
    count = manager.participant_count(str(session_id))
    return templates.TemplateResponse(request=request, name="salons/live.html", context={
        "request": request,
        "session_id": session_id,
        "participant_count": count,
    })


@router.websocket("/ws/salons/{session_id}")
async def salon_ws(websocket: WebSocket, session_id: int, token: str = Query(default="")):  # allow-secret
    """WebSocket endpoint for live salon participation.

    Requires a `token` query parameter for authentication.
    Enforces per-connection rate limits and message size limits.
    """
    # Authenticate
    if not _validate_token(token):
        await websocket.close(code=4001, reason="Authentication required")
        return

    room_id = str(session_id)
    connected = await manager.connect(room_id, websocket)
    if not connected:
        return

    try:
        while True:
            text = await websocket.receive_text()

            # Enforce message size limit
            if len(text) > MAX_MESSAGE_SIZE:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "text": f"Message too large (max {MAX_MESSAGE_SIZE} bytes).",
                }))
                continue

            if text == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            # Rate limit
            if not manager._check_rate_limit(websocket):
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "text": "Rate limit exceeded. Slow down.",
                }))
                continue

            # Sanitize: strip HTML tags via escaping
            sanitized = html.escape(text.strip())
            if not sanitized:
                continue

            await manager.broadcast(room_id, {
                "type": "message",
                "text": sanitized,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except WebSocketDisconnect:
        await manager.disconnect(room_id, websocket)
    except Exception:
        logger.exception("WebSocket error in room %s", room_id)
        await manager.disconnect(room_id, websocket)
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=1011)
