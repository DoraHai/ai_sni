"""GEO AI settings helpers (DashScope defaults)."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.geo.content.ai_settings import (
    apply_provider_preset,
    mask_api_key,
    preset_payload,
    resolve_llm_credentials,
)
from app.geo.content.routes import (
    put_ai_settings,
    test_ai_settings as run_ai_settings_test_endpoint,
)
from app.geo.content.schemas import AiSettingsUpdate


class GeoAiSettingsTests(unittest.TestCase):
    def test_dashscope_is_default_preset(self):
        presets = {p["provider"]: p for p in preset_payload()}
        self.assertIn("dashscope", presets)
        self.assertIn("compatible-mode/v1", presets["dashscope"]["base_url"])
        self.assertEqual(presets["dashscope"]["model"], "deepseek-v3")

    def test_apply_provider_preset(self):
        dash = apply_provider_preset("dashscope")
        self.assertEqual(dash["provider"], "dashscope")
        self.assertTrue(dash["base_url"].endswith("/v1"))
        deep = apply_provider_preset("deepseek")
        self.assertEqual(deep["model"], "deepseek-chat")
        fallback = apply_provider_preset("unknown")
        self.assertEqual(fallback["provider"], "dashscope")

    def test_mask_api_key(self):
        self.assertIsNone(mask_api_key(None))
        self.assertEqual(mask_api_key("short"), "****")
        self.assertEqual(mask_api_key("sk-abcdefghijklmnop"), "sk-a****mnop")


class GeoPlatformAiSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_dashscope_server_secret_is_shared_without_tenant_lookup(self):
        settings = SimpleNamespace(
            dashscope_api_key="platform-dash-key",
            dashscope_base_url="https://dash.example/v1/",
            dashscope_model="platform-model",
            deepseek_api_key="tenant-must-not-win",
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-chat",
        )
        session = object()
        with (
            patch("app.geo.content.ai_settings.get_settings", return_value=settings),
            patch("app.geo.content.ai_settings.get_ai_setting_row") as tenant_lookup,
        ):
            first = await resolve_llm_credentials(session, 1)
            second = await resolve_llm_credentials(session, 999)

        tenant_lookup.assert_not_called()
        self.assertEqual(first, second)
        self.assertEqual(first["source"], "env_dashscope")
        self.assertEqual(first["base_url"], "https://dash.example/v1")
        self.assertEqual(first["model"], "platform-model")

    async def test_deepseek_server_secret_is_used_when_dashscope_is_empty(self):
        settings = SimpleNamespace(
            dashscope_api_key="",
            dashscope_base_url="https://dashscope.example/v1",
            dashscope_model="unused",
            deepseek_api_key="platform-deepseek-key",
            deepseek_base_url="https://api.deepseek.example/",
            deepseek_model="deepseek-platform",
        )
        with patch("app.geo.content.ai_settings.get_settings", return_value=settings):
            resolved = await resolve_llm_credentials(object(), 7)

        self.assertEqual(resolved["source"], "env_deepseek")
        self.assertEqual(resolved["base_url"], "https://api.deepseek.example")
        self.assertEqual(resolved["model"], "deepseek-platform")

    async def test_customer_cannot_write_or_test_platform_credentials(self):
        checked_tenants = []
        ctx = SimpleNamespace(ensure_tenant=checked_tenants.append)
        request = AiSettingsUpdate(tenant_id=23, provider="deepseek")

        with self.assertRaises(HTTPException) as write_error:
            await put_ai_settings(request, ctx=ctx, session=object())
        with self.assertRaises(HTTPException) as test_error:
            await run_ai_settings_test_endpoint(
                tenant_id=23, ctx=ctx, session=object()
            )

        self.assertEqual(write_error.exception.status_code, 403)
        self.assertEqual(test_error.exception.status_code, 403)
        self.assertEqual(checked_tenants, [23, 23])


if __name__ == "__main__":
    unittest.main()
