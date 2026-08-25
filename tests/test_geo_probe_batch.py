"""Multi-engine probe helpers and auth mapping."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from app.geo.content.probe import (
    ENGINE_PERSONAS,
    SAMPLE_MODE_PERSONA,
    SAMPLE_MODE_REAL,
    SKIP_DASHSCOPE_OTHER_ENGINE,
    build_probe_system_prompt,
    dashscope_usable_for_engine,
    resolve_batch_engines,
    resolve_engine_llm,
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
        self.assertEqual(draft["sample_mode"], SAMPLE_MODE_PERSONA)
        self.assertFalse(draft["persisted"])
        self.assertIn("Acme", draft["raw_text"])
        self.assertTrue(draft["suggested_mentions_brand"])
        self.assertEqual(draft["suggested_competitors"], ["竞品甲"])

    async def test_run_probe_draft_deepseek_persona_is_simulated(self):
        """deepseek 人设路径也应标 simulated，避免巡检把模拟算成真采样。"""
        chat_json = AsyncMock(
            return_value={
                "raw_text": "推荐使用 Acme。",
                "suggested_mentions_brand": True,
                "competitors": [],
                "brand_position": "first",
                "sentiment": "positive",
            }
        )
        draft = await run_probe_draft(
            question="哪个品牌好？",
            brand="Acme",
            brand_names=["Acme"],
            engine="deepseek",
            llm={
                "api_key": "k",
                "base_url": "https://example.com",
                "model": "m",
                "provider": "deepseek",
            },
            chat_json=chat_json,
            sample_mode=SAMPLE_MODE_PERSONA,
        )
        self.assertTrue(draft["simulated"])
        self.assertEqual(draft["sample_mode"], SAMPLE_MODE_PERSONA)

    async def test_run_probe_draft_real_mode_not_simulated(self):
        chat_json = AsyncMock(
            return_value={
                "raw_text": "真实路径回答 Acme。",
                "suggested_mentions_brand": True,
                "competitors": [],
                "brand_position": "first",
                "sentiment": "neutral",
            }
        )
        draft = await run_probe_draft(
            question="哪个品牌好？",
            brand="Acme",
            brand_names=["Acme"],
            engine="chatgpt",
            llm={
                "api_key": "k",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
                "provider": "engine:chatgpt",
            },
            chat_json=chat_json,
            sample_mode=SAMPLE_MODE_REAL,
        )
        self.assertFalse(draft["simulated"])
        self.assertEqual(draft["sample_mode"], SAMPLE_MODE_REAL)

    def test_dashscope_only_usable_for_deepseek(self):
        self.assertTrue(
            dashscope_usable_for_engine(
                "deepseek",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                provider="dashscope",
            )
        )
        self.assertFalse(
            dashscope_usable_for_engine(
                "chatgpt",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                provider="dashscope",
            )
        )
        self.assertTrue(
            dashscope_usable_for_engine(
                "chatgpt",
                base_url="https://api.openai.com/v1",
                provider="openai",
            )
        )

    def test_resolve_engine_llm_dashscope_tenant_only_deepseek(self):
        class Row:
            sample_mode = SAMPLE_MODE_REAL
            api_key_encrypted = None
            api_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            model = "deepseek-v3"

        tenant = {
            "api_key": "tk",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "deepseek-v3",
            "provider": "dashscope",
        }
        blocked, mode, reason = resolve_engine_llm(
            engine="chatgpt", tenant_llm=tenant, engine_row=Row()
        )
        self.assertEqual(blocked, {})
        self.assertEqual(mode, SAMPLE_MODE_REAL)
        self.assertEqual(reason, SKIP_DASHSCOPE_OTHER_ENGINE)

        llm, mode, reason = resolve_engine_llm(
            engine="deepseek", tenant_llm=tenant, engine_row=Row()
        )
        self.assertEqual(mode, SAMPLE_MODE_REAL)
        self.assertEqual(llm["api_key"], "tk")
        self.assertIn("tenant_fallback", str(llm.get("source") or ""))
        self.assertIsNone(reason)

    def test_resolve_engine_llm_falls_back_without_key(self):
        class Row:
            sample_mode = SAMPLE_MODE_REAL
            api_key_encrypted = None
            api_base_url = "https://example.com/v1"
            model = "m"

        tenant = {
            "api_key": "tk",
            "base_url": "https://tenant.example/v1",
            "model": "tenant-m",
            "provider": "openai",
        }
        llm, mode, reason = resolve_engine_llm(
            engine="chatgpt", tenant_llm=tenant, engine_row=Row()
        )
        # 非百炼租户凭证仍可回退为真采样。
        self.assertEqual(mode, SAMPLE_MODE_REAL)
        self.assertEqual(llm["api_key"], "tk")
        self.assertIn("tenant_fallback", str(llm.get("source") or ""))
        self.assertIsNone(reason)

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
