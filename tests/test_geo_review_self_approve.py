"""客户单次审核，允许同一客户账号创作并确认。"""

import unittest
from types import SimpleNamespace

from app.geo.content.review import apply_decision, apply_submit


class SelfApproveTests(unittest.TestCase):
    def test_customer_can_approve_own_submission(self):
        task = SimpleNamespace(
            review_status="none",
            review_note=None,
            review_submitted_by=None,
            owner_user_id=7,
            reviewed_by=None,
            reviewed_at=None,
        )
        apply_submit(task, note="please review", submitter_id=7)
        self.assertEqual(task.review_status, "pending")
        self.assertEqual(task.review_submitted_by, 7)
        apply_decision(task, decision="approved", note="客户确认", reviewer_id=7)
        self.assertEqual(task.review_status, "approved")
        self.assertEqual(task.reviewed_by, 7)
        self.assertIsNotNone(task.reviewed_at)

    def test_other_user_can_approve(self):
        task = SimpleNamespace(
            review_status="pending",
            review_note=None,
            review_submitted_by=7,
            owner_user_id=7,
            reviewed_by=None,
            reviewed_at=None,
        )
        apply_decision(task, decision="approved", note="lgtm", reviewer_id=8)
        self.assertEqual(task.review_status, "approved")
        self.assertEqual(task.reviewed_by, 8)

    def test_self_reject_allowed(self):
        task = SimpleNamespace(
            review_status="pending",
            review_note=None,
            review_submitted_by=7,
            owner_user_id=7,
            reviewed_by=None,
            reviewed_at=None,
        )
        apply_decision(task, decision="rejected", note="fix", reviewer_id=7)
        self.assertEqual(task.review_status, "rejected")


if __name__ == "__main__":
    unittest.main()
