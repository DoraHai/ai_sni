"""GEO channel LLM polish helpers (fallback path, no live LLM)."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.geo.content.channel_polish import (
    ArticleQualityError,
    adapt_or_polish_for_channel,
    strip_draft_markers,
)


class ChannelPolishTests(unittest.TestCase):
    def test_strip_draft_markers(self):
        md = (
            "# 标题\n\n"
            "> **草案提示**：以下为自动生成母稿，请人工润色后再发布；勿直接对外使用。\n\n"
            "直接答案。\n\n"
            "## 定义与背景\n\n正文\n\n"
            "【草案】基于客户提供资料自动生成，仅供内部改稿；须人工润色。\n"
        )
        out = strip_draft_markers(md)
        self.assertNotIn("草案提示", out)
        self.assertNotIn("【草案】", out)
        self.assertIn("直接答案", out)
        self.assertIn("定义与背景", out)

    def test_strip_fact_card_refs(self):
        md = (
            "GEO Demo Brand 可提供 7×24 运维支持（事实卡7）。\n"
            "迭代节奏见事实卡5与（事实卡 #3）。\n"
            "须人工润色与核验后方可发布。\n"
            "待人工终审后再推送。\n"
        )
        out = strip_draft_markers(md)
        self.assertNotIn("事实卡", out)
        self.assertNotIn("须人工润色", out)
        self.assertNotIn("待人工终审", out)
        self.assertIn("7×24 运维支持", out)

    def test_website_fallback_strips_internal_refs(self):
        body = (
            "# 标题\n\n"
            "> **草案提示**：内部草案\n\n"
            "直接答案段落足够长（事实卡7）。\n\n"
            "## 定义与背景\n\n定义段说明产品边界。\n\n"
            "【草案】须人工润色。\n"
        )

        async def _run():
            return await adapt_or_polish_for_channel(
                "website",
                "数据中心服务能力对比",
                body,
                {"direct_answer": "直接答案段落足够长。"},
                llm=None,
                use_llm=False,
            )

        _title, out, meta = asyncio.run(_run())
        self.assertTrue(meta.get("fallback"))
        self.assertEqual(meta.get("quality"), "adapted_draft_not_publishable")
        self.assertFalse(meta.get("publishable", True))
        self.assertNotIn("事实卡", out)
        self.assertNotIn("草案提示", out)
        self.assertNotIn("【草案】", out)

    def test_adapt_or_polish_falls_back_without_llm(self):
        body = (
            "# 标题\n\n"
            "> **草案提示**：内部草案\n\n"
            "直接答案段落足够长。\n\n"
            "## 定义与背景\n\n定义段说明产品边界。\n\n"
            "## 常见问题\n\n- **问：** a\n  **答：** b\n- **问：** c\n  **答：** d\n\n"
            "## 结论与建议\n\n结论段\n\n- 来源：官网文档\n\n*更新时间：2026-08-09*\n"
        )

        async def _run():
            return await adapt_or_polish_for_channel(
                "zhihu",
                "很长的标题需要被缩短一下才符合知乎限制",
                body,
                {"direct_answer": "直接答案段落足够长。"},
                llm=None,
                use_llm=False,
            )

        title, out, meta = asyncio.run(_run())
        self.assertLessEqual(len(title), 40)
        self.assertTrue(meta.get("fallback"))
        self.assertEqual(meta.get("engine"), "deterministic_v1")
        self.assertNotIn("草案提示", out)
        self.assertIn("直接答案", out)

    def test_quality_failure_keeps_non_publishable_channel_draft(self):
        body = (
            "# 标题\n\n"
            "> **草案提示**：内部草案\n\n"
            "直接答案段落足够长。\n\n"
            "## 定义与背景\n\n定义段说明产品边界。\n"
        )

        async def _run():
            with patch(
                "app.geo.content.channel_polish.polish_for_channel",
                new=AsyncMock(side_effect=ArticleQualityError(["正文长度不足"])),
            ):
                return await adapt_or_polish_for_channel(
                    "website",
                    "数据中心服务能力对比",
                    body,
                    {"direct_answer": "直接答案段落足够长。"},
                    llm={"api_key": "test-only"},
                    use_llm=True,
                )

        _title, out, meta = asyncio.run(_run())
        self.assertTrue(meta.get("fallback"))
        self.assertFalse(meta.get("publishable", True))
        self.assertEqual(meta.get("quality"), "adapted_draft_not_publishable")
        self.assertEqual(meta.get("quality_issues"), ["正文长度不足"])
        self.assertNotIn("草案提示", out)


if __name__ == "__main__":
    unittest.main()
