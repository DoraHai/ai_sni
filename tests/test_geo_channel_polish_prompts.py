"""GEO channel polish prompt defaults + resolve bundle."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.geo.content.channel_polish import _resolve_prompt_bundle
from app.geo.content.channel_polish_defaults import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_VOICE_BY_CHANNEL,
    default_min_body_chars,
    default_voice_for_channel,
    list_default_prompts,
)
from app.geo.content.channel_polish_prompts import (
    get_effective_prompts,
    resolve_for_channel,
    upsert_prompts,
)


class ChannelPolishDefaultsTests(unittest.TestCase):
    def test_list_default_prompts_covers_channels(self):
        data = list_default_prompts()
        self.assertTrue(data["system_prompt"])
        self.assertFalse(data["is_custom_system"])
        keys = {c["channel_key"] for c in data["channels"]}
        self.assertTrue({"website", "wechat", "zhihu", "baijiahao", "toutiao"} <= keys)
        zhihu = next(c for c in data["channels"] if c["channel_key"] == "zhihu")
        self.assertIn("知乎", zhihu["voice_prompt"])
        self.assertEqual(zhihu["min_body_chars"], default_min_body_chars("zhihu"))

    def test_resolve_prompt_bundle_defaults(self):
        system, voice, mn = _resolve_prompt_bundle("zhihu", None)
        self.assertEqual(system, DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(voice, DEFAULT_VOICE_BY_CHANNEL["zhihu"])
        self.assertEqual(mn, default_min_body_chars("zhihu"))

    def test_resolve_prompt_bundle_override(self):
        system, voice, mn = _resolve_prompt_bundle(
            "website",
            {
                "system_prompt": "CUSTOM SYSTEM",
                "voice_prompt": "CUSTOM VOICE",
                "min_body_chars": 1200,
            },
        )
        self.assertEqual(system, "CUSTOM SYSTEM")
        self.assertEqual(voice, "CUSTOM VOICE")
        self.assertEqual(mn, 1200)

    def test_default_voice_fallback_unknown(self):
        self.assertEqual(default_voice_for_channel("unknown_x"), "")


class ChannelPolishPromptsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_for_channel_uses_defaults_without_rows(self):
        session = MagicMock()
        with patch(
            "app.geo.content.channel_polish_prompts._rows_by_key",
            new=AsyncMock(return_value={}),
        ):
            got = await resolve_for_channel(session, 1, "wechat")
        self.assertEqual(got["system_prompt"], DEFAULT_SYSTEM_PROMPT)
        self.assertEqual(got["voice_prompt"], default_voice_for_channel("wechat"))
        self.assertEqual(got["min_body_chars"], default_min_body_chars("wechat"))

    async def test_resolve_for_channel_uses_overrides(self):
        sys_row = MagicMock(
            system_prompt="SYS OVERRIDE",
            voice_prompt=None,
            min_body_chars=None,
        )
        ch_row = MagicMock(
            system_prompt=None,
            voice_prompt="VOICE OVERRIDE",
            min_body_chars=800,
        )
        session = MagicMock()
        with patch(
            "app.geo.content.channel_polish_prompts._rows_by_key",
            new=AsyncMock(return_value={"__system__": sys_row, "zhihu": ch_row}),
        ):
            got = await resolve_for_channel(session, 1, "zhihu")
        self.assertEqual(got["system_prompt"], "SYS OVERRIDE")
        self.assertEqual(got["voice_prompt"], "VOICE OVERRIDE")
        self.assertEqual(got["min_body_chars"], 800)

    async def test_get_effective_marks_custom(self):
        sys_row = MagicMock(system_prompt="S", voice_prompt=None, min_body_chars=None)
        session = MagicMock()
        with patch(
            "app.geo.content.channel_polish_prompts._rows_by_key",
            new=AsyncMock(return_value={"__system__": sys_row}),
        ):
            payload = await get_effective_prompts(session, 9)
        self.assertTrue(payload["is_custom_system"])
        self.assertEqual(payload["system_prompt"], "S")
        self.assertFalse(payload["channels"][0]["is_custom_voice"])

    async def test_upsert_reset_clears_override(self):
        row = MagicMock()
        row.voice_prompt = "old"
        row.min_body_chars = 999
        session = MagicMock()
        session.commit = AsyncMock()
        with patch(
            "app.geo.content.channel_polish_prompts.get_or_create_row",
            new=AsyncMock(return_value=row),
        ), patch(
            "app.geo.content.channel_polish_prompts.get_effective_prompts",
            new=AsyncMock(return_value={"ok": True}),
        ):
            out = await upsert_prompts(
                session,
                1,
                channels=[{"channel_key": "website", "reset": True}],
                updated_by=2,
            )
        self.assertIsNone(row.voice_prompt)
        self.assertIsNone(row.min_body_chars)
        self.assertEqual(row.updated_by, 2)
        self.assertEqual(out, {"ok": True})


if __name__ == "__main__":
    unittest.main()
