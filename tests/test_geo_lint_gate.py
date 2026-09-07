"""Publish gate fabrication lint (productization enhancement)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.geo.content.gate import PublishGateError, assert_can_publish
from app.geo.content.rules import RuleInput


class LintGateTests(unittest.TestCase):
    def _ready_input(self, body: str) -> RuleInput:
        return RuleInput(
            question="如何选择平台？",
            title="选择指南",
            body_markdown=body,
            outline={},
            facts=[
                {
                    "statement": "覆盖 80% 场景",
                    "title": "覆盖率",
                    "source_name": "白皮书",
                    "trust_level": "verified",
                }
            ]
            * 3,
            target_channels=["website", "wechat", "zhihu"],
            variants=["website", "wechat", "zhihu"],
        )

    def test_high_placeholder_blocked_when_gate_on(self):
        settings = SimpleNamespace(
            geo_lint_gate=True,
            geo_score_gate=False,
            geo_ai_review_gate=False,
            geo_score_threshold=60,
        )
        with (
            patch("app.geo.content.gate.get_settings", return_value=settings),
            patch("app.geo.content.gate.is_ready", return_value=True),
            patch("app.geo.content.gate.run_checks", return_value=[]),
        ):
            with self.assertRaises(PublishGateError) as cm:
                assert_can_publish(self._ready_input("对比工具A与竞品的差异"))
            self.assertIn("编造风险", str(cm.exception))

    def test_clean_body_passes_lint_gate(self):
        settings = SimpleNamespace(
            geo_lint_gate=True,
            geo_score_gate=False,
            geo_ai_review_gate=False,
            geo_score_threshold=60,
        )
        body = (
            "数据分析平台覆盖 80% 场景。"
            "实施约 14 天，适合制造业私有化部署。"
        )
        with (
            patch("app.geo.content.gate.get_settings", return_value=settings),
            patch("app.geo.content.gate.is_ready", return_value=True),
            patch("app.geo.content.gate.run_checks", return_value=[]),
        ):
            # numbers may still flag as medium if not in facts exactly — use body without extra numbers
            assert_can_publish(
                self._ready_input("数据分析平台是用于汇聚业务数据的系统，支持私有化部署。")
            )

    def test_gate_off_allows_placeholder(self):
        settings = SimpleNamespace(
            geo_lint_gate=False,
            geo_score_gate=False,
            geo_ai_review_gate=False,
            geo_score_threshold=60,
        )
        with (
            patch("app.geo.content.gate.get_settings", return_value=settings),
            patch("app.geo.content.gate.is_ready", return_value=True),
            patch("app.geo.content.gate.run_checks", return_value=[]),
        ):
            assert_can_publish(self._ready_input("对比工具A与工具B"))

    def test_brand_validation_blocks_publish_even_when_score_gate_is_off(self):
        settings = SimpleNamespace(
            geo_lint_gate=False,
            geo_score_gate=False,
            geo_ai_review_gate=False,
            geo_score_threshold=60,
        )
        task = SimpleNamespace(
            review_status="approved",
            rule_result={
                "brand_validation": {
                    "passed": False,
                    "brand": "工业齿轮箱",
                    "issues": ["全文未出现品牌「工业齿轮箱」"],
                }
            },
        )
        with (
            patch("app.geo.content.gate.get_settings", return_value=settings),
            patch("app.geo.content.gate.is_ready", return_value=True),
            patch("app.geo.content.gate.run_checks", return_value=[]),
            patch("app.geo.content.review.assert_review_approved", return_value=None),
        ):
            with self.assertRaisesRegex(PublishGateError, "品牌标准未通过"):
                assert_can_publish(self._ready_input("合格正文"), task=task)

    def test_current_article_brand_check_rejects_missing_or_stale_saved_result(self):
        settings = SimpleNamespace(
            geo_lint_gate=False,
            geo_score_gate=False,
            geo_ai_review_gate=False,
            geo_score_threshold=60,
        )
        for stored in ({}, {"brand_validation": {"passed": True, "brand": "工业齿轮箱"}}):
            task = SimpleNamespace(review_status="approved", rule_result=stored)
            with (
                patch("app.geo.content.gate.get_settings", return_value=settings),
                patch("app.geo.content.gate.is_ready", return_value=True),
                patch("app.geo.content.gate.run_checks", return_value=[]),
            ):
                with self.assertRaisesRegex(PublishGateError, "品牌标准未通过"):
                    assert_can_publish(
                        self._ready_input("当前正文没有配置品牌。"),
                        task=task,
                        brand="工业齿轮箱",
                    )


if __name__ == "__main__":
    unittest.main()
