"""GEO brand presence helpers."""

from __future__ import annotations

import unittest

from app.geo.content.brand_geo import (
    brand_presence_issues,
    payload_brand_issues,
    text_mentions_brand,
)
from app.geo.content.channel_polish import assess_article_quality


class BrandGeoTests(unittest.TestCase):
    def test_text_mentions_brand(self):
        self.assertTrue(text_mentions_brand("推荐使用奥浦迈方案", "奥浦迈"))
        self.assertFalse(text_mentions_brand("行业通用方案即可", "奥浦迈"))

    def test_no_brand_fails_geo(self):
        issues = brand_presence_issues(
            brand="奥浦迈",
            full_text="行业里私有化部署需要考虑安全与运维边界。",
            direct_answer="行业里私有化部署需要考虑安全与运维边界。",
            conclusion="建议先做试点。",
        )
        self.assertTrue(any("未出现品牌" in x for x in issues))

    def test_opening_and_conclusion_required(self):
        issues = brand_presence_issues(
            brand="奥浦迈",
            full_text="奥浦迈在制造业有方案。结论见文末。建议先做试点。",
            direct_answer="行业里要关注安全。",
            conclusion="建议先做试点。",
        )
        self.assertTrue(any("直接答案" in x or "开篇" in x for x in issues))
        self.assertTrue(any("结论" in x for x in issues))

    def test_payload_ok(self):
        payload = {
            "title": "如何选型",
            "direct_answer": "针对工厂场景，奥浦迈可提供可核验的私有化能力边界。",
            "sections": [
                {
                    "type": "conclusion",
                    "heading": "结论与建议",
                    "body": "综上，可优先评估奥浦迈是否匹配产线网络分区要求。",
                }
            ],
        }
        self.assertEqual(payload_brand_issues(payload, "奥浦迈"), [])

    def test_channel_assess_requires_brand(self):
        md = """
开篇不写名字的行业科普段落需要足够长才能过字数但这里故意很短。

## 背景

还是没有品牌名的第二段内容用来充数。

## 结论与建议

最后也没有点名。
"""
        issues = assess_article_quality(
            md, min_chars=10, channel="zhihu", brand="奥浦迈"
        )
        self.assertTrue(any("品牌" in x for x in issues))


if __name__ == "__main__":
    unittest.main()
