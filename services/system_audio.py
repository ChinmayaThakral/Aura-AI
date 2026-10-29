"""Stream native Mac playback to the desktop audio mixer without disk recording."""

import asyncio
import base64
import contextlib
import json
import platform
from pathlib import Path

import anyio
from starlette.websockets import WebSocketDisconnect

from core.paths import is_frozen, resource_path


def helper_path():
    directory = "native" if is_frozen() else "build"
    return Path(resource_path(directory, "AuraSystemAudio"))


def capture_status():
    version = platform.mac_ver()[0].split(".")[0]
    supported = platform.system() == "Darwin" and bool(version) and int(version) >= 13
    available = supported and helper_path().is_file()
    message = "Mac playback capture is available. Allow Aura's capture permission when starting."
    if not supported:
        message = "Direct Mac playback capture requires macOS 13 or newer."
    elif not available:
        message = "The native audio helper is missing. For source runs, execute .venv/bin/python native/build_audio.py."
    return {
        "available": available,
        "message": message,
        "sample_rate": 48000,
        "channels": 1,
    }


async def stop_helper(process):
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 2)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()


class SystemAudioService:
    def __init__(self):
        self._slot = asyncio.Lock()

    async def serve(self, websocket):
        status = capture_status()
        if not status["available"]:
            await websocket.send_json({"type": "error", "message": status["message"]})
            return
        if self._slot.locked():
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Another Mac audio capture is running. End that session and try again.",
                }
            )
            return
        async with self._slot:
            process = None
            tasks = []
            try:
                process = await asyncio.create_subprocess_exec(
                    str(helper_path()),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=262144,
                )
                tasks = [
                    asyncio.create_task(self._forward(process, websocket)),
                    asyncio.create_task(self._wait_for_disconnect(websocket)),
                ]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            except (OSError, ValueError, RuntimeError) as error:
                with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": f"Mac playback capture failed: {str(error)[:300]}",
                        }
                    )
            except WebSocketDisconnect:
                pass
            finally:
                for task in tasks:
                    task.cancel()
                # ASGI cancels the request when its owner closes. Keep cleanup
                # alive long enough to stop recording and reap the helper.
                with anyio.CancelScope(shield=True):
                    if process is not None:
                        await stop_helper(process)
                    await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    async def _wait_for_disconnect(websocket):
        while True:
            if (await websocket.receive())["type"] == "websocket.disconnect":
                return

    @staticmethod
    async def _forward(process, websocket):
        ready = False
        while line := await process.stdout.readline():
            message = json.loads(line)
            kind = message.get("type")
            if kind == "ready":
                if (message.get("sample_rate"), message.get("channels")) != (48000, 1):
                    raise ValueError("Native audio returned an incompatible format.")
                ready = True
                await websocket.send_json(message)
            elif kind == "audio" and ready:
                data = base64.b64decode(message.get("data", ""), validate=True)
                if not data or len(data) % 2 or len(data) > 96000:
                    raise ValueError("Native audio returned an invalid PCM frame.")
                await websocket.send_bytes(data)
            elif kind == "error":
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": str(message.get("message", "Mac capture stopped."))[
                            :700
                        ],
                    }
                )
                return
        await websocket.send_json(
            {
                "type": "error",
                "message": "Mac playback capture ended. Restart the session to reconnect.",
            }
        )


system_audio_service = SystemAudioService()
