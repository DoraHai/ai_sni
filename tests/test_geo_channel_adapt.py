"""GEO channel adapt profiles and rewriting."""

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
        self.assertIn("适用场景", out)
        self.assertIn("参考说明", out)
        self.assertNotIn("## 来源", out)

        t2, out2 = adapt_for_channel("toutiao", "资讯标题要短一些才行对吧", BODY, OUTLINE)
        self.assertLessEqual(len(t2), 30)
        self.assertIn("直接答案", out2)
        self.assertNotIn("## 定义", out2)

    def test_zhihu_keeps_full_article(self):
        title, out = adapt_for_channel("zhihu", "很长的标题需要被缩短一下才符合知乎限制", BODY, OUTLINE)
        self.assertLessEqual(len(title), 40)
        self.assertIn("直接答案", out)
        self.assertIn("适用场景", out)
        self.assertIn("定义段", out)
        self.assertIn("## 来源", out)

    def test_adapt_meta(self):
        meta = build_adapt_meta(
            "zhihu", master_version_id=9, title="t", body_md="body"
        )
        self.assertEqual(meta["profile_key"], "zhihu")
        self.assertEqual(meta["engine"], "deterministic_v1")
        self.assertIn("faq_trimmed_to_3", meta["dropped"])

    def test_auth_channel_profiles(self):
        self.assertEqual(
            _required("/api/v1/geo/channel-profiles", "GET"),
            ({"geo.content"}, False),
        )


if __name__ == "__main__":
    unittest.main()
