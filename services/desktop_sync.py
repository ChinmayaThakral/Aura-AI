"""In-memory display state for the desktop viewer of a Chrome audio session."""

import asyncio
from copy import deepcopy


class DesktopSync:
    def __init__(self):
        self._viewers = set()
        self._state = self._empty_state()

    @staticmethod
    def _empty_state():
        return {
            "session_id": None,
            "active": False,
            "connected": False,
            "paused": False,
            "transcript": "",
            "question": "",
            "answer": "",
            "answering": False,
            "error": "",
            "history": [],
            "transcription_ready": False,
            "controls": {
                "mic_muted": True,
                "paused": False,
                "vision_active": False,
                "queue_count": 0,
                "queue_limit": 4,
                "vision_model": "",
                "tab_audio_live": False,
            },
            "model": "",
            "shortcut_status": "",
            "shortcut_ok": True,
        }

    def snapshot(self):
        return deepcopy(self._state)

    def subscribe(self):
        # A complete snapshot replaces older pending updates for a slow viewer.
        queue = asyncio.Queue(maxsize=1)
        self._viewers.add(queue)
        queue.put_nowait(self.snapshot())
        return queue

    def unsubscribe(self, queue):
        self._viewers.discard(queue)

    def _broadcast(self):
        for queue in tuple(self._viewers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(self.snapshot())

    def start(self, session_id, transcription_ready=False):
        self._state = self._empty_state()
        self._state.update(
            session_id=session_id,
            active=True,
            connected=True,
            transcription_ready=transcription_ready,
        )
        self._broadcast()

    def readiness(self):
        if not self._state["active"]:
            message = "Start the interview session in Aura’s Chrome tab first."
        elif not self._state["connected"]:
            message = "Aura’s Chrome tab is disconnected. Reconnect it first."
        elif not self._state["controls"]["tab_audio_live"]:
            message = "In Chrome, share the interview tab and enable Share tab audio."
        elif not self._state["transcription_ready"]:
            message = "Chrome’s speech transcription is not connected yet."
        else:
            return {
                "ready": True,
                "message": "Chrome is ready — tab audio and transcription connected.",
            }
        return {"ready": False, "message": message}

    def notify_shortcut(self, message, success=True):
        self._state.update(shortcut_status=message[:300], shortcut_ok=success)
        self._broadcast()

    def connection_changed(self, session_id, connected):
        if self._state["session_id"] == session_id:
            self._state["connected"] = connected
            self._broadcast()

    def stop(self, session_id):
        if self._state["session_id"] == session_id:
            self._state.update(
                active=False,
                answering=False,
                connected=False,
                shortcut_status="Session ended",
                shortcut_ok=True,
            )
            self._broadcast()

    def _begin_answer(self, question):
        if self._state["question"] or self._state["answer"]:
            self._state["history"].append(
                {"question": self._state["question"], "answer": self._state["answer"]}
            )
        self._state.update(
            question=question[:20000], answer="", answering=True, error=""
        )

    def publish(self, session_id, event, payload):
        if session_id != self._state["session_id"]:
            return
        if event == "transcript_update":
            self._state["transcript"] = str(payload.get("transcript", ""))[:20000]
        elif event == "ai_processing_started":
            self._begin_answer(str(payload.get("question", "")))
        elif event == "ai_answer_chunk":
            self._state["answer"] = (
                self._state["answer"] + str(payload.get("chunk", ""))
            )[:100000]
        elif event == "ai_answer_complete":
            self._state.update(
                answer=str(payload.get("answer", ""))[:100000], answering=False
            )
        elif event == "vision_analysis_result":
            if payload.get("success"):
                self._begin_answer("Screen analysis")
                self._state.update(
                    answer=str(payload.get("analysis", ""))[:100000], answering=False
                )
            else:
                self._state["error"] = str(
                    payload.get("error", "Screen analysis failed")
                )[:500]
        elif event == "config_updated":
            self._state["paused"] = bool(payload.get("is_universally_muted"))
        elif event == "controls_updated":
            controls = self._state["controls"]
            for key in ["mic_muted", "paused", "vision_active", "tab_audio_live"]:
                if isinstance(payload.get(key), bool):
                    controls[key] = payload[key]
            if isinstance(payload.get("queue_limit"), int):
                controls["queue_limit"] = max(1, min(4, payload["queue_limit"]))
            if isinstance(payload.get("queue_count"), int):
                controls["queue_count"] = max(
                    0, min(controls["queue_limit"], payload["queue_count"])
                )
            if isinstance(payload.get("vision_model"), str):
                controls["vision_model"] = payload["vision_model"][:200]
            self._state["paused"] = controls["paused"]
            self._state["transcription_ready"] = bool(
                payload.get("transcription_ready", self._state["transcription_ready"])
            )
        elif event in {"preset_initialized", "preset_switched"}:
            self._state["model"] = str(
                payload.get("current_preset", {}).get("model", "")
            )[:200]
            if event == "preset_switched":
                self.notify_shortcut("AI model switched to " + self._state["model"])
                return
        elif event == "preset_switch_failed":
            self.notify_shortcut(
                str(payload.get("error", "AI model switch failed")), False
            )
            return
        elif event == "session_reset_complete":
            self._state.update(
                transcript="",
                question="",
                answer="",
                answering=False,
                error="",
                history=[],
            )
        elif event == "error":
            self._state.update(
                error=str(payload.get("message", "Session error"))[:500],
                answering=False,
            )
        else:
            return
        self._broadcast()


desktop_sync = DesktopSync()
