from __future__ import annotations

import unittest

from app.geo.content.evidence_cite import attach_sentence_citations, split_sentences
from app.geo.content.generate_article import to_markdown


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
        _, safe_rows = attach_sentence_citations(
            "- 官网\n来源：https://example.com/manual\n"
            "**来源：https://例子.测试/manual%20v2?lang=zh#section**",
            [],
        )
        self.assertTrue(safe_rows and all(not row["needs_fact"] for row in safe_rows))
        _, claim_rows = attach_sentence_citations(
            "官网称终身保修。报告证明无故障。\n"
            "来源：https://example.com/manual，官网称终身保修。",
            [],
        )
        self.assertEqual(len(claim_rows), 3)
        self.assertTrue(all(row["needs_fact"] for row in claim_rows))

    def test_body_author_lines_never_receive_a_metadata_exemption(self):
        for value in (
            "*作者：内容编辑*",
            "*作者：本产品终身保修且采用钛合金齿轮*",
        ):
            _, rows = attach_sentence_citations(value, [])
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["needs_fact"])

    def test_fixed_generation_chrome_does_not_block_grounded_content(self):
        statement = "MAXXDRIVE XT features a ribbed housing."
        payload = {
            "title": statement,
            "direct_answer": statement,
            "sections": [{"type": "conclusion", "body": statement}],
            "updated_at": "2026-09-07",
            "disclaimer": (
                "【草案】基于客户提供资料自动生成，仅供内部改稿；"
                "须人工润色与核验后方可发布。不承诺被 AI 引用或排名。"
            ),
        }
        _, rows = attach_sentence_citations(
            to_markdown(payload),
            [{"id": 1, "statement": statement, "source_name": "Manual"}],
        )
        self.assertTrue(rows)
        self.assertTrue(all(not row["needs_fact"] for row in rows), rows)

    def test_model_written_disclaimer_claim_still_requires_evidence(self):
        _, rows = attach_sentence_citations(
            "【草案】本产品终身保修，须人工核验后发布。", []
        )
        self.assertTrue(any(row["needs_fact"] for row in rows))

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
