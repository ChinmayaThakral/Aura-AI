import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException

from api import config_api
from core.env_utils import EnvManager
from services import stt_service


class DeepgramSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.env = EnvManager(str(Path(directory.name) / ".env"))
        self.settings = SimpleNamespace(DEEPGRAM_API_KEY="old-cached-key")
        self.client_class = httpx.AsyncClient
        for target, value in [
            ("services.stt_service.env_manager", self.env),
            ("services.stt_service.settings", self.settings),
            ("api.config_api.env_manager", self.env),
            ("api.config_api.settings", self.settings),
        ]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def client_factory(self, handler):
        return lambda **kwargs: self.client_class(
            transport=httpx.MockTransport(handler), **kwargs
        )

    async def test_saved_and_external_key_changes_apply_without_restarting(self):
        used_keys = []

        def authenticate(request):
            self.assertEqual(request.url.path, "/v1/auth/token")
            used_keys.append(request.headers["Authorization"])
            return httpx.Response(200, json={})

        with patch.object(
            stt_service.httpx,
            "AsyncClient",
            side_effect=self.client_factory(authenticate),
        ):
            self.env.update_key("DEEPGRAM_API_KEY", "first-example-key")
            self.assertTrue((await stt_service.get_deepgram_key_status())["valid"])
            await config_api.save_deepgram_key(
                config_api.SaveKeyRequest(key="  second-example-key  ")
            )
            self.assertTrue((await stt_service.get_deepgram_key_status())["valid"])
            self.env.update_key("DEEPGRAM_API_KEY", "external-example-key")
            self.assertTrue((await stt_service.get_deepgram_key_status())["valid"])
        self.assertEqual(
            used_keys,
            [
                "Token first-example-key",
                "Token second-example-key",
                "Token external-example-key",
            ],
        )
        with patch.object(stt_service, "DeepgramClient", return_value=Mock()) as sdk:
            stt_service.DeepgramManager(lambda transcript: None)
            self.assertEqual(sdk.call_args.args[0], "external-example-key")

    async def test_cleared_key_does_not_fall_back_to_a_stale_cached_key(self):
        self.env.update_key("DEEPGRAM_API_KEY", "")
        with patch.object(stt_service.httpx, "AsyncClient") as client:
            status = await stt_service.get_deepgram_key_status()
        client.assert_not_called()
        self.assertFalse(status["valid"])
        self.assertIn("missing", status["message"])

    async def test_auth_permission_rate_limit_and_network_errors_are_distinct(self):
        self.env.update_key("DEEPGRAM_API_KEY", "example-secret-never-in-errors")
        for code, expected in [
            (401, "rejected"),
            (403, "permissions"),
            (429, "rate-limiting"),
            (503, "HTTP 503"),
        ]:
            with (
                self.subTest(status=code),
                patch.object(
                    stt_service.httpx,
                    "AsyncClient",
                    side_effect=self.client_factory(
                        lambda request, code=code: httpx.Response(code)
                    ),
                ),
            ):
                status = await stt_service.get_deepgram_key_status()
                self.assertFalse(status["valid"])
                self.assertIn(expected, status["message"])
                self.assertNotIn("example-secret", status["message"])

        def offline(request):
            raise httpx.ConnectError("offline", request=request)

        with patch.object(
            stt_service.httpx, "AsyncClient", side_effect=self.client_factory(offline)
        ):
            status = await stt_service.get_deepgram_key_status()
        self.assertIn("internet", status["message"])

    async def test_save_rejects_values_that_would_add_other_env_settings(self):
        for value in ['key"', "key\nDEV_MODE=true", "key\rother=value"]:
            with self.subTest(value=value), self.assertRaises(HTTPException) as error:
                await config_api.save_deepgram_key(config_api.SaveKeyRequest(key=value))
            self.assertEqual(error.exception.status_code, 400)
