import asyncio
import base64
import json
import struct
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api import system_audio as api
from services import system_audio as audio


class FakeProcess:
    def __init__(self, events):
        self.stdout = asyncio.StreamReader()
        for event in events:
            self.stdout.feed_data(json.dumps(event).encode() + b"\n")
        self.returncode = None
        self.terminated = False

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    async def wait(self):
        return self.returncode


class SystemAudioTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(api.router)
        self.client = TestClient(app)
        self.events = [{"type": "ready", "sample_rate": 48000, "channels": 1}]
        self.processes = []

        async def spawn(*args, **kwargs):
            process = FakeProcess(self.events)
            self.processes.append(process)
            return process

        for target, kwargs in [
            (
                "services.system_audio.capture_status",
                {"return_value": {"available": True}},
            ),
            (
                "services.system_audio.asyncio.create_subprocess_exec",
                {"new": AsyncMock(side_effect=spawn)},
            ),
            (
                "api.system_audio.system_audio_service",
                {"new": audio.SystemAudioService()},
            ),
        ]:
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_native_pcm_is_forwarded_unchanged_and_disconnect_stops_capture(self):
        pcm = struct.pack("<3h", -32768, 0, 32767)
        self.events.append({"type": "audio", "data": base64.b64encode(pcm).decode()})
        with self.client as client, client.websocket_connect("/ws/system-audio") as ws:
            self.assertEqual(ws.receive_json()["sample_rate"], 48000)
            self.assertEqual(ws.receive_bytes(), pcm)
        self.assertTrue(self.processes[0].terminated)

    def test_second_connection_does_not_start_a_second_system_capture(self):
        with (
            self.client as client,
            client.websocket_connect("/ws/system-audio") as first,
        ):
            first.receive_json()
            with client.websocket_connect("/ws/system-audio") as second:
                self.assertIn("Another", second.receive_json()["message"])
            self.assertEqual(len(self.processes), 1)

    def test_permission_errors_and_invalid_pcm_are_not_reported_as_connected_audio(
        self,
    ):
        for event, expected in [
            (
                {"type": "error", "message": "Allow Aura capture permission"},
                "permission",
            ),
            ({"type": "audio", "data": base64.b64encode(b"x").decode()}, "invalid PCM"),
        ]:
            with self.subTest(event=event["type"]):
                self.events = [
                    {"type": "ready", "sample_rate": 48000, "channels": 1},
                    event,
                ]
                with (
                    self.client as client,
                    client.websocket_connect("/ws/system-audio") as ws,
                ):
                    ws.receive_json()
                    self.assertIn(expected, ws.receive_json()["message"])
                self.assertTrue(self.processes[-1].terminated)

    def test_foreign_websites_cannot_start_capture(self):
        with self.client as client:
            with (
                self.assertRaises(WebSocketDisconnect) as error,
                client.websocket_connect(
                    "ws://127.0.0.1:8002/ws/system-audio",
                    headers={"origin": "https://example.com"},
                ),
            ):
                pass
            self.assertEqual(error.exception.code, 1008)
        self.assertEqual(self.processes, [])

    def test_missing_helper_does_not_spawn_or_silently_fall_back_to_microphone(self):
        with (
            patch.object(
                audio,
                "capture_status",
                return_value={"available": False, "message": "Build the native helper"},
            ),
            self.client as client,
            client.websocket_connect("/ws/system-audio") as ws,
        ):
            self.assertIn("Build", ws.receive_json()["message"])
        self.assertEqual(self.processes, [])

    @unittest.skipUnless(
        Path("build/AuraSystemAudio").is_file(),
        "Build the native helper to test its compiled PCM contract",
    )
    def test_compiled_swift_helper_clips_and_encodes_pcm_without_recording(self):
        result = json.loads(
            subprocess.check_output(["build/AuraSystemAudio", "--self-test"])
        )
        self.assertEqual((result["sample_rate"], result["channels"]), (48000, 1))
        self.assertEqual(
            struct.unpack("<8h", base64.b64decode(result["pcm"])),
            (0, 16383, -16384, 32767, -32768, 0, 32767, -32768),
        )
