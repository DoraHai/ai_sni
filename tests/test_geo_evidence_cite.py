from __future__ import annotations

import unittest

from app.geo.content.evidence_cite import attach_sentence_citations, split_sentences


class EvidenceCiteTests(unittest.TestCase):
    def test_splits_chinese_sentences(self):
        parts = split_sentences("第一句足够长的说明。第二句也足够长的说明！短")
        self.assertGreaterEqual(len(parts), 2)
        self.assertTrue(all(len(p) >= 8 for p in parts))

    def test_cites_overlapping_fact(self):
        md = "Udesk 支持全渠道客服接入，可覆盖网页与社交渠道。这句话完全无关的内容随便写写。"
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
        self.assertFalse(rows[0]["needs_fact"])


if __name__ == "__main__":
    unittest.main()
