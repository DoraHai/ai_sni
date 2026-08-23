"""GEO content review state machine."""

import unittest
from types import SimpleNamespace

from app.geo.content.gate import PublishGateError, assert_can_publish
from app.geo.content.review import (
    REVIEW_APPROVED,
    REVIEW_NONE,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    apply_decision,
    apply_submit,
    assert_review_approved,
    can_submit_review,
    invalidate_review,
    review_payload,
)
from app.geo.content.rules import RuleInput
from app.security.auth import _required


def _ready_input(**kwargs) -> RuleInput:
    data = dict(
        question="数据分析平台哪个好用",
        title="数据分析平台怎么选",
        body_markdown=(
            "直接回答：应结合场景与可核验事实选择数据分析平台。\n\n"
            "## 定义\n\n数据分析平台是一种用于汇聚与分析业务数据的系统。\n\n"
            "## 对比选型\n\n与传统报表工具相比，自助分析更适合跨部门协作。\n\n"
            "## 操作步骤\n\n"
            "步骤 1：明确场景。\n步骤 2：核对事实。\n步骤 3：试点上线。\n\n"
            "## FAQ\n\n"
            "- **Q：** 需要关注什么？\n  **A：** 来源与时效。\n"
            "- **Q：** 如何验证？\n  **A：** 核对应事实卡。\n\n"
            "## 结论\n\n优先核验来源后再决策。\n\n"
            "## 来源\n\n- 白皮书\n\n"
            "覆盖 80% 场景，实施约 14 天，服务 120 家客户。\n\n"
            "*作者：Demo*\n*更新时间：2026-07-28*\n"
        ),
        outline={
            "direct_answer": "应结合场景与可核验事实选择数据分析平台。",
            "author_name": "Demo",
            "updated_at": "2026-07-28",
        },
        facts=[
            {"id": 1, "statement": "覆盖 80% 场景", "source_name": "s", "trust_level": "verified", "status": "active"},
            {"id": 2, "statement": "实施约 14 天", "source_name": "s", "trust_level": "verified", "status": "active"},
            {"id": 3, "statement": "服务 120 家客户", "source_name": "s", "trust_level": "verified", "status": "active"},
        ],
        target_channels=["website"],
        variants=["website"],
    )
    data.update(kwargs)
    return RuleInput(**data)


class ReviewFsmTests(unittest.TestCase):
    def test_submit_and_approve(self):
        task = SimpleNamespace(
            review_status=REVIEW_NONE,
            review_note=None,
            reviewed_by=None,
            reviewed_at=None,
        )
        ok, _ = can_submit_review(has_article=True, review_status=task.review_status)
        self.assertTrue(ok)
        apply_submit(task, note="请审")
        self.assertEqual(task.review_status, REVIEW_PENDING)
        apply_decision(task, decision="approved", note="ok", reviewer_id=9)
        self.assertEqual(task.review_status, REVIEW_APPROVED)
        self.assertEqual(task.reviewed_by, 9)
        payload = review_payload(task)
        self.assertTrue(payload["review_approved"])
        assert_review_approved(task)

    def test_reject_then_resubmit(self):
        task = SimpleNamespace(
            review_status=REVIEW_PENDING,
            review_note=None,
            reviewed_by=None,
            reviewed_at=None,
        )
        apply_decision(task, decision="rejected", note="缺来源", reviewer_id=1)
        self.assertEqual(task.review_status, REVIEW_REJECTED)
        apply_submit(task)
        self.assertEqual(task.review_status, REVIEW_PENDING)

    def test_invalidate_after_edit(self):
        task = SimpleNamespace(
            review_status=REVIEW_APPROVED,
            review_note="ok",
            reviewed_by=1,
            reviewed_at=object(),
        )
        invalidate_review(task)
        self.assertEqual(task.review_status, REVIEW_NONE)
        with self.assertRaises(ValueError):
            assert_review_approved(task)

    def test_publish_gate_does_not_require_review_when_task_passed(self):
        task = SimpleNamespace(review_status=REVIEW_PENDING)
        checks = assert_can_publish(_ready_input(), task=task)
        self.assertTrue(any(c.passed for c in checks))

    def test_auth_paths(self):
        self.assertEqual(
            _required("/api/v1/geo/publishing-channel-options", "GET"),
            ({"geo.content"}, False),
        )
        self.assertEqual(
            _required("/api/v1/geo/content-tasks/1/submit-review", "POST"),
            ({"geo.content"}, True),
        )


if __name__ == "__main__":
    unittest.main()
