"""GEO channel adapt profiles and rewriting."""

import asyncio
import unittest

from app.geo.content.channel_profiles import (
    DEFAULT_TARGET_CHANNELS,
    list_profiles,
    normalize_channels,
)
from app.geo.content.variants import adapt_for_channel, build_adapt_meta
from app.security.auth import _required


BODY = (
    "# 标题\n\n直接答案段落足够长。\n\n## 定义\n\n定义段说明产品边界。\n\n"
    "## 适用场景\n\n场景 A\n\n"
    "## FAQ\n\n- **Q：** a\n  **A：** b\n- **Q：** c\n  **A：** d\n"
    "- **Q：** e\n  **A：** f\n\n"
    "## 结论\n\n结论段\n\n- 来源：官网文档\n\n*更新时间：2026-07-28*\n"
)
OUTLINE = {"direct_answer": "直接答案段落足够长。", "updated_at": "2026-07-28"}


class ChannelProfileTests(unittest.TestCase):
    def test_list_includes_china_core(self):
        keys = {p["key"] for p in list_profiles()}
        self.assertTrue({"website", "wechat", "zhihu", "baijiahao", "toutiao"} <= keys)

    def test_default_targets(self):
        self.assertEqual(
            list(DEFAULT_TARGET_CHANNELS), ["website", "wechat", "zhihu"]
        )
        self.assertEqual(normalize_channels(None), ["website", "wechat", "zhihu"])
        self.assertEqual(
            normalize_channels(["zhihu", "zhihu", "unknown", "toutiao"]),
            ["zhihu", "toutiao"],
        )

    def test_wechat_and_toutiao_adapt(self):
        title, out = adapt_for_channel("wechat", "标题" * 20, BODY, OUTLINE)
        self.assertLessEqual(len(title), 64)
        self.assertIn("直接答案", out)
        self.assertIn("参考说明", out)

        t2, out2 = adapt_for_channel("toutiao", "资讯标题要短一些才行对吧", BODY, OUTLINE)
        self.assertLessEqual(len(t2), 30)
        self.assertIn("直接答案", out2)
        self.assertNotIn("## 定义", out2)

    def test_adapt_meta(self):
        meta = build_adapt_meta(
            "zhihu", master_version_id=9, title="t", body_md="body"
        )
        self.assertEqual(meta["profile_key"], "zhihu")
        self.assertEqual(meta["engine"], "deterministic_v1")
        self.assertIn("faq_trimmed_to_3", meta["dropped"])
        self.assertNotIn("long_body_sections", meta["dropped"])

    def test_preserves_descriptive_sections_and_entire_selection_table(self):
        rows = "\n".join(f"| 工况{i} | 条件{i} |" for i in range(15))
        body = (
            "# 标题\n\n直接答案。\n\n## 选型前需要确认哪些项目？\n\n"
            "| 项目 | 信息 |\n|---|---|\n" + rows +
            "\n\n## 连续运行时怎样核对散热方案？\n\n保留限制条件和来源。\n\n"
            "## 结论\n\n按工况核算。\n\n*更新时间：2026-09-05*\n"
        )
        for channel in ("wechat", "zhihu"):
            with self.subTest(channel=channel):
                _, out = adapt_for_channel(channel, "标题", body)
                self.assertIn(rows, out)
                self.assertIn("保留限制条件和来源。", out)
                self.assertEqual(out.count("更新时间："), 1)
                self.assertEqual(out.count("## 结论"), 1)

    def test_faq_limit_preserves_multi_paragraph_answers(self):
        questions = "\n\n".join(
            f"- **Q：** 问题{i}\n\n答案{i}第一段\n\n答案{i}第二段"
            for i in range(1, 5)
        )
        body = "开头\n\n## FAQ\n\n" + questions + "\n\n## 结论\n\n结论。"
        for channel in ("wechat", "zhihu"):
            _, out = adapt_for_channel(channel, "标题", body)
            self.assertIn("答案3第二段", out)
            self.assertNotIn("问题4", out)
            self.assertNotIn("答案4", out)

    def test_repeated_update_footer_is_normalized(self):
        body = BODY + "\n*更新时间：2026-07-28*\n"
        for channel in ("wechat", "zhihu"):
            _, out = adapt_for_channel(channel, "标题", body, OUTLINE)
            self.assertEqual(out.count("更新时间："), 1)

    def test_full_fallback_pipeline_keeps_table_without_approving_draft(self):
        from app.geo.content.channel_polish import adapt_or_polish_for_channel

        body = (
            "直接答案。\n\n## 选型前需要确认哪些项目？\n\n"
            "| 项目 | 信息 |\n|---|---|\n| 安装 | 空间 |\n\n"
            "[参数出处](https://example.com/spec)\n\n"
            "## 结论\n\n核对工况。\n\n*更新时间：2026-09-05*\n"
        )
        for channel in ("wechat", "zhihu"):
            _, out, meta = asyncio.run(adapt_or_polish_for_channel(
                channel, "标题", body, use_llm=False
            ))
            self.assertIn("<table", meta["body_html"])
            self.assertIn("https://example.com/spec", meta["body_html"])
            self.assertEqual(out.count("更新时间："), 1)
            self.assertFalse(meta["publishable"])
            self.assertEqual(meta["quality"], "adapted_draft_not_publishable")

    def test_auth_channel_profiles(self):
        self.assertEqual(
            _required("/api/v1/geo/channel-profiles", "GET"),
            ({"geo.content"}, False),
        )


if __name__ == "__main__":
    unittest.main()
