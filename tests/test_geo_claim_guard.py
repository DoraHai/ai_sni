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
