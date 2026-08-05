"""Multi-engine probe helpers and auth mapping."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from app.geo.content.probe import (
    ENGINE_PERSONAS,
    build_probe_system_prompt,
    resolve_batch_engines,
    run_probe_draft,
)
from app.security.auth import _required


class ProbeBatchHelpersTests(unittest.IsolatedAsyncioTestCase):
    def test_resolve_batch_engines_defaults_skip_other(self):
        self.assertEqual(
            resolve_batch_engines(None, ["chatgpt", "deepseek", "other"]),
            ["chatgpt", "deepseek"],
        )

    def test_resolve_batch_engines_requested(self):
        self.assertEqual(
            resolve_batch_engines(["doubao", "chatgpt", "doubao"], ["chatgpt"]),
            ["doubao", "chatgpt"],
        )

    def test_persona_covers_defaults(self):
        for key in ("chatgpt", "deepseek", "doubao", "perplexity", "other"):
            self.assertIn(key, ENGINE_PERSONAS)
            prompt = build_probe_system_prompt(brand="Acme", engine=key)
            self.assertIn("Acme", prompt)
            self.assertTrue(len(ENGINE_PERSONAS[key]) > 10)
            self.assertIn(ENGINE_PERSONAS[key][:8], prompt)

    async def test_run_probe_draft_normalizes(self):
        chat_json = AsyncMock(
            return_value={
                "raw_text": "推荐使用 Acme 与竞品甲。",
                "suggested_mentions_brand": True,
                "competitors": ["竞品甲", "Acme"],
                "brand_position": "first",
                "sentiment": "positive",
            }
        )
        draft = await run_probe_draft(
            question="哪个品牌好？",
            brand="Acme",
            brand_names=["Acme"],
            engine="chatgpt",
            llm={
                "api_key": "k",
                "base_url": "https://example.com",
                "model": "m",
                "provider": "dashscope",
            },
            chat_json=chat_json,
        )
        self.assertEqual(draft["engine"], "chatgpt")
        self.assertTrue(draft["simulated"])
        self.assertFalse(draft["persisted"])
        self.assertIn("Acme", draft["raw_text"])
        self.assertTrue(draft["suggested_mentions_brand"])
        self.assertEqual(draft["suggested_competitors"], ["竞品甲"])

    def test_probe_batch_requires_geo_content_edit(self):
        self.assertEqual(
            _required("/api/v1/geo/answer-snapshots/probe-batch", "POST"),
            ({"geo.content"}, True),
        )
        self.assertEqual(
            _required("/api/v1/geo/citation-insights", "GET"),
            ({"geo.content"}, False),
        )


if __name__ == "__main__":
    unittest.main()
