"""
Chat endpoint — talk to Sol.
Supports both REST (POST) and WebSocket streaming.
"""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


async def _ws_auth_check(websocket: WebSocket) -> bool:
    """Accept the WS connection then verify there is an active Kite session.

    Returns True if authenticated. If not, sends an auth_error frame and
    closes the connection, then returns False.
    WebSocket upgrades cannot carry HTTP-level auth so we check post-accept.
    """
    from sol.api.auth import verify_session
    from fastapi import HTTPException

    try:
        await verify_session()
        return True
    except HTTPException:
        await websocket.send_text(json.dumps({"type": "auth_error", "detail": "Not authenticated"}))
        await websocket.close(code=4401)
        return False


@router.get("/chat/history")
async def get_chat_history(limit: int = 20):
    """Return the last N chat messages for display on frontend load."""
    from sol.database import get_session
    from sol.models.session import ChatMessage
    from sqlalchemy import select

    async with get_session() as db:
        result = await db.execute(
            select(ChatMessage)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        messages = list(reversed(result.scalars().all()))

    return [
        {"role": m.role, "content": m.content, "timestamp": m.created_at.isoformat()}
        for m in messages
    ]


@router.post("/chat")
async def chat_with_sol(request: ChatRequest):
    """REST chat endpoint."""
    from sol.core.orchestrator import get_orchestrator
    from sol.database import get_session
    from sol.models.session import ChatMessage

    orchestrator = get_orchestrator()

    # Save user message immediately so it persists even if tab is switched mid-request
    async with get_session() as db:
        db.add(ChatMessage(role="user", content=request.message))
        await db.flush()

    async with get_session() as db:
        response = await orchestrator.chat(request.message, db_session=db)
    return {"response": response}


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """WebSocket chat — streaming responses from Sol."""
    from sol.core.orchestrator import get_orchestrator

    await websocket.accept()
    if not await _ws_auth_check(websocket):
        return
    orchestrator = get_orchestrator()

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            user_message = msg.get("message", "")

            # Stream response (non-streaming for now, send full response)
            response = await orchestrator.chat(user_message)
            await websocket.send_text(json.dumps({
                "type": "message",
                "role": "assistant",
                "content": response,
            }))
    except WebSocketDisconnect:
        pass


@router.websocket("/ws/feed")
async def ws_feed(websocket: WebSocket):
    """WebSocket feed — real-time events (prices, proposals, alerts)."""
    from sol.core.event_bus import subscribe, unsubscribe

    await websocket.accept()
    if not await _ws_auth_check(websocket):
        return
    queue = subscribe()

    try:
        while True:
            # Wait for event or check for client disconnect
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_text(event)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        unsubscribe(queue)
