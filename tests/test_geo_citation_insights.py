"""Citation domain aggregation helpers (post Wave C visibility)."""

import unittest

from app.geo.content.cn_blueprint import match_blueprint_for_domain
from app.geo.content.snapshots import extract_cited_domain, extract_cited_domains


class CitationInsightsTests(unittest.TestCase):
    def test_match_known_cn_hosts(self):
        zhihu = match_blueprint_for_domain("zhuanlan.zhihu.com")
        self.assertIsNotNone(zhihu)
        self.assertEqual(zhihu["channel_key"], "zhihu")
        self.assertEqual(zhihu["channel_name"], "知乎")

        toutiao = match_blueprint_for_domain("www.toutiao.com")
        self.assertEqual(toutiao["channel_key"], "toutiao")
        self.assertEqual(toutiao["priority_band"], "P1")

        wechat = match_blueprint_for_domain("mp.weixin.qq.com")
        self.assertEqual(wechat["channel_key"], "wechat")

    def test_unknown_host_returns_none(self):
        self.assertIsNone(match_blueprint_for_domain("example.org"))
        self.assertIsNone(match_blueprint_for_domain(""))

    def test_aggregate_inputs_dedupe_domains(self):
        domains = extract_cited_domains(
            [
                "https://www.zhihu.com/question/1",
                "https://zhihu.com/question/2",
                "https://baike.baidu.com/item/x",
            ]
        )
        self.assertEqual(domains, ["zhihu.com", "baike.baidu.com"])
        self.assertEqual(extract_cited_domain("https://baike.baidu.com/item/x"), "baike.baidu.com")
        baike = match_blueprint_for_domain("baike.baidu.com")
        self.assertEqual(baike["channel_key"], "baike")


if __name__ == "__main__":
    unittest.main()
