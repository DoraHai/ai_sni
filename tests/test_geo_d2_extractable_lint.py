"""D2 extractable blocks + draft fabrication lint (GeoLook port)."""

import unittest

from app.geo.content.draft_lint import lint_draft, lint_summary
from app.geo.content.extractable_blocks import (
    BLOCK_CODES,
    blocks_payload,
    detect_blocks,
)
from app.geo.content.rules import RuleInput, build_fix_patches, is_ready, run_checks


RICH_BODY = (
    "数据分析平台是一种用于汇聚业务数据的系统。\n"
    "覆盖 80% 场景，实施约 14 天，服务 120 家客户。\n"
    "与传统报表工具相比，自助分析更适合跨部门协作。\n"
    "步骤 1：明确场景。\n步骤 2：核验事实。\n步骤 3：试点上线。\n"
    "## FAQ\n\n"
    "- **Q：** 如何验证？\n  **A：** 核对事实卡。\n"
)


class ExtractableBlocksTests(unittest.TestCase):
    def test_definition_heading_is_an_extractable_definition_block(self):
        text = "## 定义\n\n面向采购决策的产品能力说明。"
        self.assertTrue(detect_blocks(text)["definition"])

    def test_detect_all_five(self):
        blocks = detect_blocks(RICH_BODY)
        self.assertTrue(all(blocks.values()))
        self.assertEqual(blocks_payload(RICH_BODY)["missing"], [])

    def test_missing_numbers_and_howto(self):
        text = "这是一种工具。与竞品相比更好。常见问题：无。"
        blocks = detect_blocks(text)
        self.assertTrue(blocks["definition"])
        self.assertTrue(blocks["comparison"])
        self.assertFalse(blocks["numbers"])
        self.assertFalse(blocks["howto"])
        payload = blocks_payload(text)
        self.assertIn("numbers", payload["missing"])
        self.assertIn(BLOCK_CODES["numbers"], payload["issue_codes"])

    def test_howto_soft_with_list(self):
        text = "如何上手：\n- 一\n- 二\n- 三\n"
        self.assertTrue(detect_blocks(text)["howto"])

    def test_faq_via_schema(self):
        blocks = detect_blocks("正文无问答标题", schema_types={"FAQPage"})
        self.assertTrue(blocks["faq"])


class DraftLintTests(unittest.TestCase):
    def test_placeholder_brand_is_high(self):
        issues = lint_draft("对比工具A与工具B的差异")
        summary = lint_summary(issues)
        self.assertGreaterEqual(summary["high"], 1)
        self.assertFalse(summary["blocks_ready"])
        self.assertTrue(any(i["code"] == "fake_placeholder" for i in issues))

    def test_unverified_number_medium(self):
        issues = lint_draft("市场份额达 37%", facts=[])
        self.assertTrue(any(i["code"] == "unverified_number" for i in issues))
        self.assertEqual(lint_summary(issues)["high"], 0)

    def test_known_fact_number_skipped(self):
        facts = [{"statement": "覆盖 80% 场景", "source_name": "白皮书"}]
        issues = lint_draft("覆盖 80% 场景，适合多数团队。", facts=facts)
        self.assertFalse(any(i["code"] == "unverified_number" for i in issues))

    def test_suspicious_year(self):
        issues = lint_draft("报告发布于 2020 年", year=2026)
        self.assertTrue(any(i["code"] == "suspicious_year" for i in issues))


class RulesIntegrationTests(unittest.TestCase):
    def _base(self, **kwargs) -> RuleInput:
        data = dict(
            question="数据分析平台哪个好用",
            title="怎么选",
            body_markdown=RICH_BODY
            + "\n## 结论\n\n优先核验。\n\n## 来源\n\n- 白皮书\n\n"
            "*作者：Demo*\n*更新时间：2026-07-28*\n",
            outline={
                "direct_answer": "应结合场景与可核验事实选择。",
                "author_name": "Demo",
                "updated_at": "2026-07-28",
                "sections": [
                    {
                        "type": "definition",
                        "body": "数据分析平台是一种用于汇聚业务数据的系统。",
                    }
                ],
                "faq": [{"q": "a", "a": "b"}, {"q": "c", "a": "d"}],
                "conclusion": "优先核验。",
            },
            facts=[
                {
                    "id": 1,
                    "statement": "覆盖 80% 场景",
                    "source_name": "白皮书",
                    "trust_level": "verified",
                    "status": "active",
                },
                {
                    "id": 2,
                    "statement": "实施约 14 天",
                    "source_name": "文档",
                    "trust_level": "verified",
                    "status": "active",
                },
                {
                    "id": 3,
                    "statement": "服务 120 家客户",
                    "source_name": "案例",
                    "trust_level": "verified",
                    "status": "active",
                },
            ],
            target_channels=["website"],
            variants=["website"],
        )
        data.update(kwargs)
        return RuleInput(**data)

    def test_rich_body_passes_new_rules(self):
        by_code = {c.code: c for c in run_checks(self._base())}
        self.assertTrue(by_code["numbers_extractable"].passed)
        self.assertTrue(by_code["comparison_extractable"].passed)
        self.assertTrue(by_code["howto_extractable"].passed)
        self.assertTrue(by_code["fabrication_lint"].passed)
        self.assertTrue(is_ready(list(by_code.values()), require_channels=True))

    def test_fabrication_blocks_ready(self):
        body = self._base().body_markdown + "\n对比工具A即可。\n"
        by_code = {c.code: c for c in run_checks(self._base(body_markdown=body))}
        self.assertFalse(by_code["fabrication_lint"].passed)
        self.assertFalse(is_ready(list(by_code.values()), require_channels=False))

    def test_block_patches_emitted(self):
        patches = {
            p["code"]: p
            for p in build_fix_patches(
                self._base(body_markdown="直接回答：只有一句。\n", outline={"direct_answer": "只有一句。"})
            )
        }
        self.assertIn("numbers_extractable", patches)
        self.assertIn("comparison_extractable", patches)
        self.assertIn("howto_extractable", patches)


if __name__ == "__main__":
    unittest.main()
