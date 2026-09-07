from __future__ import annotations

import unittest

from app.geo.content.evidence_cite import attach_sentence_citations, split_sentences


class EvidenceCiteTests(unittest.TestCase):
    def test_splits_chinese_sentences(self):
        parts = split_sentences("第一句足够长的说明。第二句也足够长的说明！短")
        self.assertGreaterEqual(len(parts), 2)
        self.assertTrue(all(any(ch.isalnum() for ch in p) for p in parts))

    def test_short_claims_are_not_dropped(self):
        for statement in ("耐用。", "防爆。", "无毒。", "50kW。"):
            _, rows = attach_sentence_citations(statement, [])
            self.assertEqual(len(rows), 1, statement)
            self.assertTrue(rows[0]["needs_fact"], statement)

    def test_only_punctuation_and_decoration_are_dropped(self):
        self.assertEqual(split_sentences("。！？\n---\n***"), [])

    def test_source_exemption_requires_a_reference_shape(self):
        _, safe_rows = attach_sentence_citations("- 官网\n来源：https://example.com/manual", [])
        self.assertTrue(safe_rows and all(not row["needs_fact"] for row in safe_rows))
        _, claim_rows = attach_sentence_citations("官网称终身保修。报告证明无故障。", [])
        self.assertEqual(len(claim_rows), 2)
        self.assertTrue(all(row["needs_fact"] for row in claim_rows))

    def test_cites_overlapping_fact(self):
        md = "Udesk 支持全渠道客服接入。这句话完全无关的内容随便写写。"
        facts = [
            {
                "id": 11,
                "title": "全渠道接入",
                "statement": "Udesk 支持全渠道客服接入",
                "source_name": "官网",
            }
        ]
        out, rows = attach_sentence_citations(md, facts)
        self.assertTrue(any(r["cited"] and r["fact_id"] == 11 for r in rows))
        self.assertEqual(out, md)
        self.assertEqual(rows[0]["fact_id"], 11)

    def test_unmatched_sentence_needs_review(self):
        md = "今天天气很好适合出门散步看花。另一句也跟客服系统毫无关系。"
        facts = [
            {
                "id": 2,
                "title": "SLA",
                "statement": "官方承诺 90% 识别率",
                "source_name": "白皮书",
            }
        ]
        out, rows = attach_sentence_citations(md, facts)
        self.assertTrue(rows)
        self.assertTrue(any(not r["cited"] for r in rows))
        self.assertEqual(out, md)

    def test_no_facts_leaves_body_untouched(self):
        md = "一段足够长的正文句子不会被改写。"
        out, rows = attach_sentence_citations(md, [])
        self.assertEqual(out, md)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["cited"])
        self.assertTrue(rows[0]["needs_fact"])


if __name__ == "__main__":
    unittest.main()
