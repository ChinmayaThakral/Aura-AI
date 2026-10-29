"""Regression checks for a Chrome audio owner and independent desktop viewers."""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api import config_api
from api import session_manager as sessions
from api import websocket as sockets
from services.desktop_sync import DesktopSync


class FakeLLM:
    def __init__(self):
        self.presets = {"primary": object()}

    def get_current_preset_info(self):
        return {"key": "primary"}

    async def perform_health_checks(self):
        return {"primary": True}

    async def get_ai_answer(self, question, callback):
        for chunk in ["The ", "answer ", "is 4."]:
            await callback(chunk, "chunk")
        return "The answer is 4.", {"success": True}


class FakeSTT:
    is_connected = True

    def __init__(self):
        self.audio = []
        self.finished = False

    async def send_audio(self, audio):
        self.audio.append(audio)

    async def finish(self):
        self.finished = True


class DesktopSyncStateTests(unittest.TestCase):
    def test_slow_viewer_receives_complete_answer_and_late_viewer_gets_snapshot(self):
        sync = DesktopSync()
        queue = sync.subscribe()
        sync.start("chrome")
        sync.publish("chrome", "ai_processing_started", {"question": "Question"})
        for chunk in ["one ", "two ", "three"]:
            sync.publish("chrome", "ai_answer_chunk", {"chunk": chunk})
        self.assertEqual(queue.qsize(), 1)
        self.assertEqual(queue.get_nowait()["answer"], "one two three")
        self.assertEqual(sync.subscribe().get_nowait()["answer"], "one two three")

    def test_other_sessions_cannot_replace_the_selected_chrome_answer(self):
        sync = DesktopSync()
        sync.start("chrome")
        sync.publish("chrome", "ai_answer_complete", {"answer": "Chrome answer"})
        sync.publish("desktop", "ai_answer_complete", {"answer": "Other answer"})
        sync.stop("desktop")
        self.assertTrue(sync.snapshot()["active"])
        self.assertEqual(sync.snapshot()["answer"], "Chrome answer")

    def test_full_conversation_is_retained_until_reset_including_after_session_end(
        self,
    ):
        sync = DesktopSync()
        sync.start("chrome")
        for number in range(25):
            sync.publish("chrome", "ai_processing_started", {"question": str(number)})
            sync.publish("chrome", "ai_answer_complete", {"answer": f"Answer {number}"})
        self.assertEqual(len(sync.snapshot()["history"]), 24)
        self.assertEqual(sync.snapshot()["history"][0]["question"], "0")
        self.assertEqual(
            sync.subscribe().get_nowait()["history"], sync.snapshot()["history"]
        )
        sync.stop("chrome")
        self.assertFalse(sync.snapshot()["active"])
        self.assertEqual(sync.snapshot()["answer"], "Answer 24")
        sync.publish("chrome", "session_reset_complete", {})
        self.assertEqual(sync.snapshot()["answer"], "")
        self.assertEqual(sync.snapshot()["history"], [])


class DesktopSyncConnectionTests(unittest.TestCase):
    def setUp(self):
        self.sync = DesktopSync()
        self.manager = sessions.SessionManager()

        async def initialize(session, *args):
            session.llm_manager = FakeLLM()
            session.stt_manager = FakeSTT()
            session.is_active = True

        for target, value in [
            ("api.session_manager.desktop_sync", self.sync),
            ("api.websocket.desktop_sync", self.sync),
            ("api.session_manager.session_manager", self.manager),
            ("api.websocket.session_manager", self.manager),
            ("api.session_manager.InterviewSession.initialize_managers", initialize),
        ]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(sockets.router)
        app.include_router(config_api.router)
        self.client = TestClient(app)

    @staticmethod
    def receive_until(ws, condition):
        for _ in range(30):
            message = ws.receive_json()
            if condition(message):
                return message
        raise AssertionError("Expected state was not received")

    def start_browser(self, browser):
        session_id = browser.receive_json()["payload"]["session_id"]
        browser.send_json({"type": "start_interview", "payload": {}})
        self.assertEqual(browser.receive_json()["type"], "preset_initialized")
        return session_id

    def ask(self, browser):
        browser.send_json(
            {"type": "manual_question", "payload": {"text": "What is 2 + 2?"}}
        )
        return self.receive_until(
            browser, lambda message: message["type"] == "ai_answer_complete"
        )

    def test_viewer_receives_stream_without_stealing_audio_or_controlling_session(self):
        with (
            self.client as client,
            client.websocket_connect("/ws?source=browser") as browser,
        ):
            session_id = self.start_browser(browser)
            owner = self.manager.active_sessions[session_id].websocket
            with client.websocket_connect("/ws/desktop") as desktop:
                self.assertTrue(desktop.receive_json()["payload"]["active"])
                # Display connections cannot start/end sessions or inject audio.
                desktop.send_json({"type": "end_interview", "payload": {}})
                desktop.send_json({"type": "audio_chunk", "payload": {"audio": [9]}})
                browser.send_json(
                    {"type": "audio_chunk", "payload": {"audio": [1, 2, 3]}}
                )
                self.assertEqual(
                    self.ask(browser)["payload"]["answer"], "The answer is 4."
                )
                state = self.receive_until(
                    desktop,
                    lambda message: message["payload"]["answer"] == "The answer is 4.",
                )
                self.assertEqual(state["payload"]["question"], "What is 2 + 2?")
                self.assertIs(self.manager.active_sessions[session_id].websocket, owner)
                self.assertEqual(
                    self.manager.active_sessions[session_id].stt_manager.audio,
                    [b"\x01\x02\x03"],
                )
            self.assertEqual(self.ask(browser)["payload"]["answer"], "The answer is 4.")
            # Reopening a viewer shows the latest answer immediately.
            with client.websocket_connect("/ws/desktop") as desktop:
                self.assertEqual(
                    desktop.receive_json()["payload"]["answer"], "The answer is 4."
                )

    def test_reconnecting_browser_survives_the_old_socket_closing(self):
        with (
            self.client as client,
            client.websocket_connect("/ws?source=browser") as old,
        ):
            session_id = self.start_browser(old)
            with client.websocket_connect(
                f"/ws?session_id={session_id}&source=browser"
            ) as new:
                self.assertEqual(new.receive_json()["type"], "session_resumed")
                old.close()
                self.assertEqual(self.ask(new)["payload"]["answer"], "The answer is 4.")
                self.assertIsNotNone(self.manager.active_sessions[session_id].websocket)
                self.assertTrue(self.sync.snapshot()["connected"])

    def test_desktop_audio_session_does_not_start_browser_sync(self):
        with self.client as client, client.websocket_connect("/ws") as desktop:
            self.start_browser(desktop)
            self.assertFalse(self.sync.snapshot()["active"])

    def test_upstream_base64_audio_transport_preserves_pcm_bytes(self):
        import base64

        with (
            self.client as client,
            client.websocket_connect("/ws?source=browser") as browser,
        ):
            session_id = self.start_browser(browser)
            pcm = b"\x00\x80\x00\x00\xff\x7f"
            browser.send_json(
                {
                    "type": "audio_chunk",
                    "payload": {"audio_b64": base64.b64encode(pcm).decode()},
                }
            )
            self.ask(browser)
            self.assertEqual(
                self.manager.active_sessions[session_id].stt_manager.audio, [pcm]
            )

    def test_unrelated_websites_cannot_subscribe_to_the_display(self):
        with self.client as client:
            with (
                self.assertRaises(WebSocketDisconnect) as error,
                client.websocket_connect(
                    "/ws/desktop", headers={"origin": "https://example.com"}
                ),
            ):
                pass
            self.assertEqual(error.exception.code, 1008)
            with client.websocket_connect(
                "ws://127.0.0.1:8002/ws/desktop",
                headers={"origin": "http://127.0.0.1:8002"},
            ) as viewer:
                self.assertEqual(viewer.receive_json()["type"], "desktop_state")

    def test_all_session_shortcuts_route_to_the_chrome_owner_and_confirm_state(self):
        from core.shortcuts import SESSION_SHORTCUTS

        with (
            self.client as client,
            client.websocket_connect("/ws?source=browser") as browser,
        ):
            session_id = self.start_browser(browser)
            owner = self.manager.active_sessions[session_id].websocket
            for command in SESSION_SHORTCUTS:
                choices = (
                    ["primary", "secondary", "auto"]
                    if command == "switch_preset"
                    else ["primary"]
                )
                for preset in choices:
                    delivered = client.portal.call(
                        self.manager.route_shortcut,
                        {
                            "command": command,
                            "preset_key": preset,
                            "text": "Typed question",
                        },
                    )
                    self.assertTrue(delivered)
                    message = browser.receive_json()
                    self.assertEqual(message["type"], "session_shortcut")
                    self.assertEqual(message["payload"]["command"], command)
                    self.assertEqual(message["payload"]["preset_key"], preset)
                    browser.send_json(
                        {
                            "type": "shortcut_applied",
                            "payload": {
                                "id": message["payload"]["id"],
                                "success": True,
                            },
                        }
                    )
            browser.send_json(
                {
                    "type": "client_controls",
                    "payload": {
                        "tab_audio_live": True,
                        "mic_muted": False,
                        "paused": True,
                        "vision_active": True,
                        "queue_count": 2,
                        "vision_model": "Example vision model",
                    },
                }
            )
            self.assertEqual(browser.receive_json()["type"], "controls_updated")
            state = self.sync.snapshot()
            self.assertFalse(state["controls"]["mic_muted"])
            self.assertTrue(state["controls"]["vision_active"])
            self.assertTrue(state["paused"])
            self.assertEqual(state["controls"]["queue_count"], 2)
            self.assertIn("applied in Chrome", state["shortcut_status"])
            self.assertIs(self.manager.active_sessions[session_id].websocket, owner)

    def test_window_buttons_control_the_browser_and_ending_stops_its_session(self):
        with (
            self.client as client,
            client.websocket_connect("/ws?source=browser") as browser,
        ):
            session_id = self.start_browser(browser)
            stt = self.manager.active_sessions[session_id].stt_manager
            self.ask(browser)
            with client.websocket_connect("/ws/desktop") as desktop:
                desktop.receive_json()
                result = client.post(
                    "/api/desktop/command",
                    json={"session_id": session_id, "command": "toggle_mic_mute"},
                    headers={"origin": "http://testserver"},
                )
                self.assertEqual(result.status_code, 200)
                command = browser.receive_json()["payload"]
                self.assertEqual(command["command"], "toggle_mic_mute")
                browser.send_json(
                    {
                        "type": "shortcut_applied",
                        "payload": {"id": command["id"], "success": True},
                    }
                )
                browser.send_json(
                    {"type": "client_controls", "payload": {"mic_muted": False}}
                )
                self.assertEqual(browser.receive_json()["type"], "controls_updated")
                state = self.receive_until(
                    desktop,
                    lambda message: not message["payload"]["controls"]["mic_muted"],
                )
                self.assertIn("applied in Chrome", state["payload"]["shortcut_status"])

                self.assertEqual(
                    client.post(
                        "/api/desktop/command",
                        json={"session_id": session_id, "command": "end_interview"},
                    ).status_code,
                    200,
                )
                self.assertEqual(
                    browser.receive_json()["payload"]["command"], "end_interview"
                )
                # Chrome executes the forwarded command and stops its capture.
                browser.send_json({"type": "end_interview", "payload": {}})
                ended = self.receive_until(
                    desktop, lambda message: not message["payload"]["active"]
                )["payload"]
                self.assertTrue(stt.finished)
                self.assertNotIn(session_id, self.manager.active_sessions)
                self.assertEqual(ended["answer"], "The answer is 4.")
                self.assertEqual(
                    client.post(
                        "/api/desktop/command",
                        json={"session_id": session_id, "command": "toggle_mic_mute"},
                    ).status_code,
                    409,
                )

    def test_window_commands_reject_stale_sessions_unknown_actions_and_foreign_pages(
        self,
    ):
        with (
            self.client as client,
            client.websocket_connect("/ws?source=browser") as browser,
        ):
            session_id = self.start_browser(browser)
            body = {"session_id": session_id, "command": "toggle_mic_mute"}
            self.assertEqual(
                client.post(
                    "/api/desktop/command", json={**body, "session_id": "old-session"}
                ).status_code,
                409,
            )
            self.assertEqual(
                client.post(
                    "/api/desktop/command", json={**body, "session_id": ""}
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    "/api/desktop/command", json={**body, "command": "unknown"}
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    "/api/desktop/command",
                    json=body,
                    headers={"origin": "https://example.com"},
                ).status_code,
                403,
            )
            self.assertEqual(
                self.manager.active_sessions[session_id].pending_shortcuts, {}
            )

    def test_typed_question_is_forwarded_to_the_same_browser_session(self):
        with (
            self.client as client,
            client.websocket_connect("/ws?source=browser") as browser,
        ):
            session_id = self.start_browser(browser)
            body = {
                "session_id": session_id,
                "command": "manual_question",
                "text": "  Question from desktop  ",
            }
            self.assertEqual(
                client.post("/api/desktop/command", json=body).status_code, 200
            )
            command = browser.receive_json()["payload"]
            self.assertEqual(command["text"], "Question from desktop")
            browser.send_json(
                {"type": "manual_question", "payload": {"text": command["text"]}}
            )
            self.receive_until(
                browser, lambda message: message["type"] == "ai_answer_complete"
            )
            self.assertEqual(self.sync.snapshot()["question"], "Question from desktop")

    def test_window_appearance_controls_delegate_without_changing_browser_audio(self):
        from unittest.mock import Mock

        manager = Mock()
        manager.set_transparency.return_value = True
        manager.move_window.return_value = True
        manager.is_ghost_mode = False
        manager.can_restore_click_through.return_value = True
        manager.toggle_ghost_mode.return_value = True
        with (
            self.client as client,
            patch.object(config_api.window_manager, "window_manager", manager),
        ):
            for body in [
                {"action": "opacity", "opacity": 0.7},
                {"action": "click_through"},
                {"action": "hide"},
                {"action": "move", "direction": "left"},
            ]:
                self.assertEqual(
                    client.post("/api/desktop/appearance", json=body).json(),
                    {"success": True},
                )
            manager.set_transparency.assert_called_once_with(0.7)
            manager.toggle_ghost_mode.assert_called_once_with()
            manager.toggle_visibility.assert_called_once_with()
            manager.move_window.assert_called_once_with(-20, 0)
            self.assertEqual(
                client.post(
                    "/api/desktop/appearance",
                    json={"action": "hide"},
                    headers={"origin": "https://example.com"},
                ).status_code,
                403,
            )
            self.assertEqual(
                client.post(
                    "/api/desktop/appearance", json={"action": "opacity", "opacity": -1}
                ).status_code,
                422,
            )

    def test_click_through_api_reports_native_failure_and_requires_shortcut_recovery(
        self,
    ):
        from unittest.mock import Mock

        manager = Mock()
        manager.is_ghost_mode = False
        manager.can_restore_click_through.return_value = True
        manager.toggle_ghost_mode.return_value = False
        manager.get_click_through_state.return_value = {
            "available": True,
            "click_through": False,
            "shortcuts_ready": True,
        }
        with (
            self.client as client,
            patch.object(config_api.window_manager, "window_manager", manager),
        ):
            self.assertEqual(
                client.post(
                    "/api/desktop/appearance", json={"action": "click_through"}
                ).json(),
                {"success": False},
            )
            self.assertEqual(
                client.get("/api/desktop/appearance").json(),
                manager.get_click_through_state.return_value,
            )
            manager.can_restore_click_through.return_value = False
            response = client.post(
                "/api/desktop/appearance", json={"action": "click_through"}
            )
            self.assertEqual(response.status_code, 409)
            self.assertIn("Option+X", response.json()["detail"])
            manager.toggle_ghost_mode.assert_called_once()

    def test_native_monitor_uses_browser_route_instead_of_the_desktop_javascript(self):
        from unittest.mock import Mock

        import main

        with (
            patch.object(main, "desktop_sync", self.sync),
            patch.object(main, "session_manager", self.manager),
        ):
            monitor = main.GlobalCommandMonitor()
            monitor.startup_time = 0
            monitor._js = Mock()
            with (
                self.client as client,
                client.websocket_connect("/ws?source=browser") as browser,
            ):
                self.start_browser(browser)
                self.assertTrue(
                    client.portal.call(
                        monitor._process_command,
                        {
                            "source": "global_hotkey",
                            "command": "toggle_mic_mute",
                            "event_id": 1,
                        },
                    )
                )
                self.assertEqual(
                    browser.receive_json()["payload"]["command"], "toggle_mic_mute"
                )
                monitor._js.assert_not_called()

    def test_desktop_display_requires_live_chrome_audio_and_transcription(self):
        from unittest.mock import Mock

        from api import config_api

        app = FastAPI()
        app.include_router(sockets.router)
        app.include_router(config_api.router)
        window = Mock(return_value=True)
        with (
            patch.object(config_api, "desktop_sync", self.sync),
            patch.object(
                config_api.window_manager.window_manager, "set_desktop_display", window
            ),
            TestClient(app) as client,
        ):
            self.assertFalse(client.get("/api/desktop/status").json()["ready"])
            self.assertEqual(
                client.post(
                    "/api/window/desktop-display", json={"enabled": True}
                ).status_code,
                409,
            )
            window.assert_not_called()
            with client.websocket_connect("/ws?source=browser") as browser:
                self.start_browser(browser)
                self.assertFalse(client.get("/api/desktop/status").json()["ready"])
                browser.send_json(
                    {"type": "client_controls", "payload": {"tab_audio_live": True}}
                )
                browser.receive_json()
                self.assertTrue(client.get("/api/desktop/status").json()["ready"])
                self.assertEqual(
                    client.post(
                        "/api/window/desktop-display", json={"enabled": True}
                    ).json(),
                    {"success": True},
                )
                browser.send_json(
                    {"type": "client_controls", "payload": {"tab_audio_live": False}}
                )
                browser.receive_json()
                self.assertEqual(
                    client.post(
                        "/api/window/desktop-display", json={"enabled": True}
                    ).status_code,
                    409,
                )

    def test_ended_chrome_session_does_not_capture_normal_desktop_shortcuts(self):
        from unittest.mock import Mock

        import main

        self.sync.start("ended-browser")
        self.sync.stop("ended-browser")
        with (
            patch.object(main, "desktop_sync", self.sync),
            patch.object(
                main.window_manager.window_manager, "is_desktop_display", False
            ),
            self.client as client,
        ):
            monitor = main.GlobalCommandMonitor()
            monitor.startup_time = 0
            monitor._js = Mock()
            client.portal.call(
                monitor._process_command,
                {
                    "source": "global_hotkey",
                    "command": "toggle_mic_mute",
                    "event_id": "desktop",
                },
            )
            monitor._js.assert_called_once()

    def test_stale_or_unknown_shortcuts_are_not_sent_to_an_unrelated_session(self):
        with self.client as client:
            self.assertFalse(
                client.portal.call(
                    self.manager.route_shortcut, {"command": "toggle_mic_mute"}
                )
            )
            self.assertFalse(
                client.portal.call(
                    self.manager.route_shortcut, {"command": "arbitrary_javascript"}
                )
            )
            with client.websocket_connect("/ws?source=browser") as browser:
                self.start_browser(browser)
                self.assertFalse(
                    client.portal.call(
                        self.manager.route_shortcut,
                        {"command": "switch_preset", "preset_key": "untrusted"},
                    )
                )


if __name__ == "__main__":
    unittest.main()
