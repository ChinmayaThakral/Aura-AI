import asyncio
import orjson
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional

from .session_manager import session_manager
from .utils import send_json
from services.desktop_sync import desktop_sync

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: Optional[str] = Query(None), source: str = Query("desktop")):
    """
    Main WebSocket endpoint. Handles new connections and resumes existing sessions.
    """
    session = None
    if session_id:
        session = session_manager.get_session(session_id)
        if session:
            print(f"🔗 Resuming session: {session_id}")
            session.websocket = websocket
            desktop_sync.connection_changed(session.session_id, True)
            await websocket.accept()
            await send_json(websocket, "session_resumed", {"session_id": session.session_id})
        else:
            print(f"⚠️ Session not found: {session_id}. Creating new session.")
    
    if not session:
        await websocket.accept()
        session = session_manager.create_session()
        session.source = "browser" if source == "browser" else "desktop"
        session.websocket = websocket
        await send_json(websocket, "session_created", {"session_id": session.session_id})

    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            payload = message.get("payload", {})

            # Route message to the appropriate handler within the session
            handler = getattr(session, f"handle_{message_type}", None)
            if handler:
                try:
                    await handler(payload)
                except Exception as handler_err:
                    print(f"❌ Handler error in session {session.session_id} for '{message_type}': {handler_err}")
                    try:
                        await session._send_json("error", {
                            "message": f"Error processing '{message_type}': {str(handler_err)[:200]}",
                            "type": message_type
                        })
                    except Exception:
                        pass  # Don't crash if we can't send the error
            else:
                print(f"⚠️ Unknown message type: {message_type}")

    except WebSocketDisconnect:
        print(f"🔌 WebSocket disconnected from session: {session.session_id}")
        if session.websocket is websocket:
            session.websocket = None
            desktop_sync.connection_changed(session.session_id, False)
    except Exception as e:
        print(f"❌ Unhandled WebSocket error in session {session.session_id}: {e}")
        if session.websocket is websocket:
            session.websocket = None
            desktop_sync.connection_changed(session.session_id, False)


@router.websocket("/ws/desktop")
async def desktop_viewer(websocket: WebSocket):
    """Observe the Chrome session without replacing its audio WebSocket."""
    from urllib.parse import urlsplit

    origin = websocket.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.port != websocket.url.port):
            await websocket.close(code=1008)
            return
    await websocket.accept()
    queue = desktop_sync.subscribe()

    async def send_updates():
        while True:
            state = await queue.get()
            await websocket.send_json({"type": "desktop_state", "payload": state})

    sender = asyncio.create_task(send_updates())
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            # This connection is display-only; received commands are ignored.
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        desktop_sync.unsubscribe(queue)
