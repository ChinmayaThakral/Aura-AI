"""Local-only connection for the desktop's native playback capture."""

from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from services.system_audio import capture_status, system_audio_service

router = APIRouter()


@router.get("/api/audio/system/status")
async def system_audio_status():
    return capture_status()


@router.websocket("/ws/system-audio")
async def system_audio_socket(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        expected_scheme = "https" if websocket.url.scheme == "wss" else "http"
        if (
            parsed.scheme != expected_scheme
            or parsed.netloc != websocket.url.netloc
            or parsed.hostname not in {"127.0.0.1", "localhost"}
        ):
            await websocket.close(code=1008)
            return
    await websocket.accept()
    try:
        await system_audio_service.serve(websocket)
    finally:
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
