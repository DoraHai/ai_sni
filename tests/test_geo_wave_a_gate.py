"""GEO Wave A 发布门禁单测。"""

import unittest

from app.geo.content.gate import PublishGateError, assert_can_publish
from app.geo.content.rules import RuleInput


def _ready_input(**kwargs) -> RuleInput:
    data = dict(
        question="数据分析平台哪个好用",
        title="数据分析平台怎么选",
        body_markdown=(
            "直接回答：应结合场景与可核验事实选择数据分析平台。\n\n"
            "## 定义\n\n数据分析平台用于汇聚与分析业务数据。\n\n"
            "## FAQ\n\n"
            "- **Q：** 需要关注什么？\n  **A：** 来源与时效。\n"
            "- **Q：** 如何验证？\n  **A：** 核对应事实卡。\n\n"
            "## 结论\n\n优先核验来源后再决策。\n\n"
            "## 来源\n\n- 白皮书\n\n"
            "*作者：Demo*\n*更新时间：2026-07-28*\n"
        ),
        outline={"direct_answer": "应结合场景与可核验事实选择数据分析平台。", "author_name": "Demo", "updated_at": "2026-07-28"},
        facts=[
            {"id": 1, "statement": "a", "source_name": "s", "trust_level": "verified", "status": "active"},
            {"id": 2, "statement": "b", "source_name": "s", "trust_level": "verified", "status": "active"},
            {"id": 3, "statement": "c", "source_name": "s", "trust_level": "verified", "status": "active"},
        ],
        target_channels=["website"],
        variants=["website"],
    )
    data.update(kwargs)
    return RuleInput(**data)


class GeoPublishGateTests(unittest.TestCase):
    def test_pass_when_ready(self):
        checks = assert_can_publish(_ready_input())
        self.assertTrue(all(c.passed for c in checks if c.code != "channel_variant_ready" or c.passed))

    def test_blocks_without_channels(self):
        with self.assertRaises(PublishGateError):
            assert_can_publish(_ready_input(variants=[]))

    def test_blocks_without_facts(self):
        with self.assertRaises(PublishGateError):
            assert_can_publish(_ready_input(facts=[]))

    def test_blocks_unverified_or_expired_evidence(self):
        from datetime import date, timedelta

        facts = [
            {"id": 1, "statement": "a", "source_name": "s", "trust_level": "needs_review", "status": "active"},
            {"id": 2, "statement": "b", "source_name": "s", "trust_level": "verified", "status": "active"},
            {
                "id": 3,
                "statement": "c",
                "source_name": "s",
                "trust_level": "verified",
                "status": "active",
                "expires_at": date.today() - timedelta(days=1),
            },
        ]
        with self.assertRaises(PublishGateError):
            assert_can_publish(_ready_input(facts=facts))


if __name__ == "__main__":
    unittest.main()
