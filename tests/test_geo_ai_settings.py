"""GEO AI settings helpers (DashScope defaults)."""

import unittest

from app.geo.content.ai_settings import (
    apply_provider_preset,
    mask_api_key,
    preset_payload,
)


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


if __name__ == "__main__":
    unittest.main()
