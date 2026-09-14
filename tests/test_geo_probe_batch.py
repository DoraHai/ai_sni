"""Multi-engine probe helpers and auth mapping."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.ai.deepseek import DeepSeekError, safe_ai_error_detail
from app.geo.content.probe import (
    ENGINE_PERSONAS,
    PROBE_ANSWER_TIMEOUT_SECONDS,
    SAMPLE_MODE_PERSONA,
    SAMPLE_MODE_REAL,
    SKIP_DASHSCOPE_OTHER_ENGINE,
    build_probe_system_prompt,
    dashscope_usable_for_engine,
    probe_temperature_for_model,
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
        for key in (
            "chatgpt",
            "deepseek",
            "doubao",
            "qwen",
            "hunyuan",
            "wenxin",
            "perplexity",
            "other",
        ):
            self.assertIn(key, ENGINE_PERSONAS)
            prompt = build_probe_system_prompt(brand="Acme", engine=key)
            self.assertNotIn("Acme", prompt)
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

    async def test_run_probe_draft_pins_kimi_k2_temperature(self):
        chat_json = AsyncMock(
            return_value={
                "raw_text": "Kimi 真实回答 Acme。",
                "suggested_mentions_brand": True,
                "competitors": [],
                "brand_position": "first",
                "sentiment": "neutral",
            }
        )
        await run_probe_draft(
            question="哪个品牌好？",
            brand="Acme",
            brand_names=["Acme"],
            engine="kimi",
            llm={
                "api_key": "k",
                "base_url": "https://api.moonshot.cn/v1",
                "model": "kimi-k2.6",
                "provider": "kimi",
            },
            chat_json=chat_json,
            sample_mode=SAMPLE_MODE_REAL,
        )
        self.assertEqual(chat_json.await_args_list[0].kwargs["temperature"], 1.0)
        self.assertEqual(chat_json.await_args_list[1].kwargs["temperature"], 1.0)
        self.assertEqual(
            chat_json.await_args_list[0].kwargs["timeout"],
            PROBE_ANSWER_TIMEOUT_SECONDS,
        )
        self.assertEqual(chat_json.await_args_list[1].kwargs["timeout"], 60.0)

    async def test_run_probe_draft_keeps_other_model_default_temperature(self):
        chat_json = AsyncMock(
            return_value={
                "raw_text": "千问真实回答 Acme。",
                "suggested_mentions_brand": True,
                "competitors": [],
                "brand_position": "first",
                "sentiment": "neutral",
            }
        )
        await run_probe_draft(
            question="哪个品牌好？",
            brand="Acme",
            brand_names=["Acme"],
            engine="qwen",
            llm={
                "api_key": "k",
                "base_url": "https://example.com/v1",
                "model": "qwen3.8-max",
                "provider": "qwen",
            },
            chat_json=chat_json,
            sample_mode=SAMPLE_MODE_REAL,
        )
        self.assertNotIn("temperature", chat_json.await_args.kwargs)

    def test_probe_temperature_override_is_model_scoped(self):
        self.assertEqual(probe_temperature_for_model("kimi-k2.6"), 1.0)
        self.assertEqual(probe_temperature_for_model("KIMI-K2-latest"), 1.0)
        self.assertIsNone(probe_temperature_for_model("qwen3.8-max"))
        self.assertIsNone(probe_temperature_for_model(None))

    async def test_answer_sampling_retries_read_timeout_once(self):
        timeout = httpx.ReadTimeout("")
        first_error = DeepSeekError("timeout")
        first_error.__cause__ = timeout
        chat_json = AsyncMock(
            side_effect=[
                first_error,
                {"raw_text": "Kimi 真实回答。"},
                {"suggested_mentions_brand": False},
            ]
        )

        draft = await run_probe_draft(
            question="如何选择？",
            brand="Acme",
            brand_names=["Acme"],
            engine="kimi",
            llm={
                "api_key": "k",
                "base_url": "https://api.moonshot.cn/v1",
                "model": "kimi-k2.6",
                "provider": "kimi",
            },
            chat_json=chat_json,
            sample_mode=SAMPLE_MODE_REAL,
        )

        self.assertEqual(chat_json.await_count, 3)
        self.assertEqual(draft["raw_text"], "Kimi 真实回答。")
        self.assertEqual(chat_json.await_args_list[0].kwargs["timeout"], 120.0)
        self.assertEqual(chat_json.await_args_list[1].kwargs["timeout"], 120.0)
        self.assertEqual(chat_json.await_args_list[2].kwargs["timeout"], 60.0)

    async def test_answer_sampling_final_timeout_records_attempt_budget(self):
        errors = []
        for _ in range(2):
            error = DeepSeekError("timeout")
            error.__cause__ = httpx.ConnectTimeout("")
            errors.append(error)
        chat_json = AsyncMock(side_effect=errors)

        with self.assertRaises(DeepSeekError) as caught:
            await run_probe_draft(
                question="如何选择？",
                brand="Acme",
                brand_names=["Acme"],
                engine="doubao",
                llm={
                    "api_key": "k",
                    "base_url": "https://example.com/v1",
                    "model": "m",
                    "provider": "doubao",
                },
                chat_json=chat_json,
                sample_mode=SAMPLE_MODE_REAL,
            )

        detail = safe_ai_error_detail(caught.exception, provider="doubao")
        self.assertEqual(chat_json.await_count, 2)
        self.assertEqual(detail["exception_class"], "ConnectTimeout")
        self.assertEqual(detail["attempts"], 2)
        self.assertEqual(detail["timeout_seconds"], 120.0)

    async def test_answer_sampling_does_not_retry_http_or_parse_errors(self):
        cases = [
            httpx.HTTPStatusError(
                "bad request",
                request=httpx.Request("POST", "https://example.com"),
                response=httpx.Response(
                    400, request=httpx.Request("POST", "https://example.com")
                ),
            ),
            ValueError("bad response shape"),
        ]
        for cause in cases:
            error = DeepSeekError("failed")
            error.__cause__ = cause
            chat_json = AsyncMock(side_effect=error)
            with self.assertRaises(DeepSeekError):
                await run_probe_draft(
                    question="如何选择？",
                    brand="Acme",
                    brand_names=["Acme"],
                    engine="doubao",
                    llm={
                        "api_key": "k",
                        "base_url": "https://example.com/v1",
                        "model": "m",
                        "provider": "doubao",
                    },
                    chat_json=chat_json,
                    sample_mode=SAMPLE_MODE_REAL,
                )
            self.assertEqual(chat_json.await_count, 1)

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
        with patch(
            "app.geo.content.engine_providers.resolve_platform_engine_credentials",
            return_value=None,
        ):
            blocked, mode, reason = resolve_engine_llm(
                engine="chatgpt", tenant_llm=tenant, engine_row=Row()
            )
        self.assertEqual(blocked, {})
        self.assertEqual(mode, SAMPLE_MODE_PERSONA)
        self.assertEqual(reason, SKIP_DASHSCOPE_OTHER_ENGINE)

        with patch(
            "app.geo.content.engine_providers.resolve_platform_engine_credentials",
            return_value=None,
        ):
            llm, mode, reason = resolve_engine_llm(
                engine="deepseek", tenant_llm=tenant, engine_row=Row()
            )
        self.assertEqual(mode, SAMPLE_MODE_PERSONA)
        self.assertEqual(llm["api_key"], "tk")
        self.assertIsNone(reason)

    def test_resolve_engine_llm_ignores_tenant_engine_key(self):
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
        with patch(
            "app.geo.content.engine_providers.resolve_platform_engine_credentials",
            return_value=None,
        ):
            llm, mode, reason = resolve_engine_llm(
                engine="chatgpt", tenant_llm=tenant, engine_row=Row()
            )
        self.assertEqual(mode, SAMPLE_MODE_PERSONA)
        self.assertEqual(llm["api_key"], "tk")
        self.assertIsNone(reason)

    def test_resolve_engine_llm_prefers_platform_engine(self):
        platform = {
            "api_key": "platform-key",
            "base_url": "https://api.example/v1",
            "model": "provider-model",
            "provider": "qwen",
            "source": "env:GEO_QWEN",
        }
        with patch(
            "app.geo.content.engine_providers.resolve_platform_engine_credentials",
            return_value=platform,
        ):
            llm, mode, reason = resolve_engine_llm(
                engine="qwen", tenant_llm=None, engine_row=None
            )
        self.assertEqual(llm, platform)
        self.assertEqual(mode, SAMPLE_MODE_REAL)
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
