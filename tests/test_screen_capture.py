import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.screen_capture import router
from services.screen_capture import capture_main_display


class ScreenCaptureTests(unittest.TestCase):
    def test_main_display_capture_is_resized_and_temporary_files_removed(self):
        paths = []
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            image = Path(command[-1])
            paths.append(image)
            image.write_bytes(b"jpeg-content")
            return subprocess.CompletedProcess(command, 0)

        with (
            patch("services.screen_capture.platform.system", return_value="Darwin"),
            patch("services.screen_capture.subprocess.run", side_effect=run),
        ):
            self.assertEqual(capture_main_display(), b"jpeg-content")
        self.assertEqual(calls[0][0][1:-1], ["-x", "-m", "-t", "jpg"])
        self.assertEqual(calls[1][0][1:-1], ["-Z", "2560"])
        self.assertTrue(all(not image.parent.exists() for image in paths))

    def test_permission_failure_does_not_return_a_screenshot(self):
        with (
            patch("services.screen_capture.platform.system", return_value="Darwin"),
            patch(
                "services.screen_capture.subprocess.run",
                return_value=subprocess.CompletedProcess([], 1),
            ),self.assertRaisesRegex(RuntimeError, "Screen Recording")
        ):
            capture_main_display()

    def test_missing_output_does_not_report_success(self):
        with (
            patch("services.screen_capture.platform.system", return_value="Darwin"),
            patch(
                "services.screen_capture.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ),self.assertRaisesRegex(RuntimeError, "Could not capture")
        ):
            capture_main_display()

    def test_timeout_releases_capture_slot(self):
        from services.screen_capture import _capture_lock

        with (
            patch("services.screen_capture.platform.system", return_value="Darwin"),
            patch(
                "services.screen_capture.subprocess.run",
                side_effect=subprocess.TimeoutExpired("screencapture", 12),
            ),self.assertRaisesRegex(RuntimeError, "timed out")
        ):
            capture_main_display()
        self.assertFalse(_capture_lock.locked())

    def test_native_screenshot_requires_mac(self):
        with (
            patch("services.screen_capture.platform.system", return_value="Linux"),
            self.assertRaisesRegex(RuntimeError, "require macOS"),
        ):
            capture_main_display()

    def test_local_endpoint_returns_image_without_caching(self):
        app = FastAPI()
        app.include_router(router)
        with (
            TestClient(app) as client,
            patch(
                "api.screen_capture.capture_main_display", return_value=b"jpeg-content"
            ),
        ):
            response = client.post("/api/screen/capture", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.content, b"jpeg-content")

    def test_foreign_origin_cannot_trigger_capture(self):
        app = FastAPI()
        app.include_router(router)
        with (
            TestClient(app) as client,
            patch("api.screen_capture.capture_main_display") as capture,
        ):
            response = client.post(
                "/api/screen/capture",
                json={},
                headers={"Origin": "https://example.com"},
            )
        self.assertEqual(response.status_code, 403)
        capture.assert_not_called()

    def test_capture_failure_returns_actionable_error(self):
        app = FastAPI()
        app.include_router(router)
        with (
            TestClient(app) as client,
            patch(
                "api.screen_capture.capture_main_display",
                side_effect=RuntimeError("Allow Aura in Screen Recording settings."),
            ),
        ):
            response = client.post("/api/screen/capture", json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Screen Recording", response.json()["detail"])
