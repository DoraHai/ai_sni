from __future__ import annotations

import unittest

from app.geo.content.claim_guard import invented_stat_claims


class ClaimGuardTests(unittest.TestCase):
    def test_blocks_percent_not_in_facts(self):
        facts = [{"title": "能力", "statement": "支持多渠道接入"}]
        bad = invented_stat_claims("识别率达到 90%，30 秒响应", facts)
        self.assertTrue(any("90" in x or "30" in x for x in bad))

    def test_allows_numbers_present_in_facts(self):
        facts = [{"title": "SLA", "statement": "90% 识别率，30 秒内响应"}]
        bad = invented_stat_claims("官方承诺 90% 识别率，30 秒响应", facts)
        self.assertEqual(bad, [])

    def test_allows_same_number_with_or_without_space(self):
        facts = [{"title": "服务半径", "statement": "华东 48 小时到场，备件标准库存 90 天。"}]
        bad = invented_stat_claims(
            "华东地区提供48小时到场服务，备件库存可覆盖90天需求。",
            facts,
        )
        self.assertEqual(bad, [])

    def test_does_not_treat_bare_48_as_48_percent(self):
        facts = [{"title": "服务半径", "statement": "华东 48 小时到场"}]
        bad = invented_stat_claims("市占率达到 48%。", facts)
        self.assertTrue(any("48" in x for x in bad))

    def test_allows_calendar_year(self):
        facts = [{"title": "简介", "statement": "工业泵制造商"}]
        bad = invented_stat_claims("公司成立于 2016 年，服务华东市场。", facts)
        self.assertEqual(bad, [])

    def test_blocks_case_and_performance_without_facts(self):
        from app.geo.content.claim_guard import ungrounded_claims

        facts = [{"title": "能力", "statement": "支持多渠道接入"}]
        hits = ungrounded_claims(
            "识别率达到行业领先，并有头部客户成功案例。",
            facts,
        )
        kinds = {h["kind"] for h in hits}
        self.assertIn("performance", kinds)
        self.assertIn("case", kinds)


if __name__ == "__main__":
    unittest.main()
