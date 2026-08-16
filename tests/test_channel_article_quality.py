"""Article-level hard quality gate for channel polish (full_article_v2)."""

from __future__ import annotations

import unittest

from app.geo.content.channel_polish import (
    ArticleQualityError,
    assess_article_quality,
    polish_for_channel,
)


def _long_para(seed: str = "选型") -> str:
    return (
        f"在制造业与数据中台场景中，企业围绕{seed}私有化分析能力时，"
        "需要同时兼顾数据主权、产线网络隔离与分级授权。"
        "若直接套用通用公有云模板，往往在身份集成、运维责任边界与审计留痕上"
        "无法满足现场硬约束，因此应先写清安全分区与可验证事实来源，再进入方案对比与试点。"
    )


class AssessArticleQualityTests(unittest.TestCase):
    def test_outline_style_rejected(self):
        md = """
## 三大关键评估维度

**安全架构**是首要考量。平台应支持认证。

**生产就绪性**同样重要。平台需要故障转移。

**合规**也要注意。
"""
        issues = assess_article_quality(md, min_chars=1000, channel="zhihu")
        self.assertTrue(issues, "outline must fail hard gate")
        self.assertTrue(
            any("字数" in x or "段落" in x or "加粗" in x or "开篇" in x for x in issues)
        )

    def test_thin_opening_rejected(self):
        p = _long_para()
        md = f"""
短答一句不够。

## 背景

{p}

{p}

## 方法

{p}

{p}

## 结论与建议

{p}
"""
        issues = assess_article_quality(md, min_chars=800, channel="zhihu")
        self.assertTrue(any("开篇" in x for x in issues))

    def test_table_without_interpretation_rejected(self):
        p = _long_para("对比")
        md = f"""
{p}

## 背景说明

{p}

{p}

## 选型对比

| 维度 | 自建 | 商业平台 |
| --- | --- | --- |
| 权限 | 细 | 中 |
| 运维 | 高 | 低 |

## 结论与建议

{p}

{p}
"""
        issues = assess_article_quality(md, min_chars=800, channel="zhihu")
        self.assertTrue(any("表格后" in x or "解读" in x for x in issues))

    def test_full_article_passes(self):
        brand = "奥浦迈"
        p = _long_para()
        open_p = (
            f"针对工厂数据中台选型，{brand}可在私有化与身份集成场景给出可核验边界，"
            "需同时兼顾产线隔离、分级授权与运维值班模型，避免直接套用公有云模板。"
            f"下文基于已核验事实说明{brand}的适用条件与对比维度，便于采购与产线团队共同评估，"
            "并在招标与验收阶段保留可追溯的来源依据。"
        )
        close_p = (
            f"综上，建议先固化安全分区与事实来源，再评估{brand}是否匹配产线网络与审计要求，"
            "并安排小范围试点与回滚预案，把可验证来源写入招标与验收条款。"
        )
        md = f"""
{open_p}

## 核心要求

{p}

{p}

## 选型对比

| 维度 | 自建 | 商业平台 |
| --- | --- | --- |
| 权限 | 细 | 中 |
| 运维 | 高 | 低 |

上表说明：权限与审计要求高时，应优先评估可对接企业身份源、并支持产线网络分区的方案，同时预留运维值班与变更窗口，避免试点阶段因权限模型不匹配而返工。

{p}

## 结论与建议

{close_p}

{p}
"""
        issues = assess_article_quality(
            md, min_chars=600, channel="zhihu", brand=brand
        )
        self.assertEqual(issues, [], issues)

    def test_comparison_keyword_requires_table(self):
        p = _long_para("评估维度")
        md = f"""
{p}

## 背景

{p}

{p}

## 方法

{p}

## 结论与建议

{p}
"""
        issues = assess_article_quality(md, min_chars=500, channel="wechat")
        self.assertTrue(any("表格" in x for x in issues))


class PolishHardGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_polish_hard_fails_on_outline(self):
        """LLM returning outline must raise ArticleQualityError (no soft-pass)."""
        import app.geo.content.channel_polish as mod

        async def fake_chat_json(system, user, **kwargs):
            return {
                "title": "测试标题",
                "body_markdown": (
                    "## 维度\n\n"
                    "**A** 很重要。\n\n"
                    "**B** 也很重要。\n\n"
                    "**C** 注意合规。\n"
                ),
            }

        orig_chat, orig_en = mod.chat_json, mod.is_enabled
        mod.chat_json = fake_chat_json  # type: ignore
        mod.is_enabled = lambda: True  # type: ignore
        try:
            with self.assertRaises(ArticleQualityError) as ei:
                await polish_for_channel(
                    "zhihu",
                    "母稿标题",
                    "# 母稿\n\n" + _long_para() * 3,
                    {"direct_answer": _long_para()},
                )
            self.assertTrue(ei.exception.issues)
        finally:
            mod.chat_json = orig_chat
            mod.is_enabled = orig_en


if __name__ == "__main__":
    unittest.main()
