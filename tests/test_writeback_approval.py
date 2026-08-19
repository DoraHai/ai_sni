import unittest
from types import SimpleNamespace

from app.baidu.writeback_approval import (
    ACTION_KEYWORD_BID,
    WritebackApprovalError,
    claim_approval,
    payload_fingerprint,
)


class _Session:
    def __init__(self, row):
        self.row = row
        self.flushed = False
        self.statement = None

    async def scalar(self, statement):
        self.statement = statement
        return self.row

    async def flush(self):
        self.flushed = True


class WritebackApprovalTests(unittest.IsolatedAsyncioTestCase):
    def test_fingerprint_normalizes_money(self):
        left, left_hash = payload_fingerprint(
            ACTION_KEYWORD_BID, {"keyword_id": "7", "new_bid": "1.230"}
        )
        right, right_hash = payload_fingerprint(
            ACTION_KEYWORD_BID, {"keyword_id": 7, "new_bid": 1.23}
        )
        self.assertEqual(left, right)
        self.assertEqual(left_hash, right_hash)

    def test_payload_rejects_non_finite_or_non_positive_values(self):
        bad_payloads = (
            {"keyword_id": 7, "new_bid": float("nan")},
            {"keyword_id": 7, "new_bid": float("inf")},
            {"keyword_id": 7, "new_bid": 0},
            {"keyword_id": 7, "new_bid": 0.001},
            {"keyword_id": 0, "new_bid": 1.2},
            {"keyword_id": 7.9, "new_bid": 1.2},
            {"keyword_id": True, "new_bid": 1.2},
            {"keyword_id": 7, "new_bid": True},
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(WritebackApprovalError):
                    payload_fingerprint(ACTION_KEYWORD_BID, payload)

    async def test_claim_requires_different_approver_and_executor(self):
        payload, fingerprint = payload_fingerprint(
            ACTION_KEYWORD_BID, {"keyword_id": 7, "new_bid": 1.23}
        )
        row = SimpleNamespace(
            tenant_id=3,
            status="approved",
            action_type=ACTION_KEYWORD_BID,
            payload_hash=fingerprint,
            payload=payload,
            approved_by=9,
            consumed_by=None,
            consumed_at=None,
        )
        with self.assertRaisesRegex(WritebackApprovalError, "必须是不同用户"):
            await claim_approval(
                _Session(row),
                approval_id=1,
                tenant_id=3,
                action_type=ACTION_KEYWORD_BID,
                payload=payload,
                operator_user_id=9,
            )

    async def test_claim_consumes_matching_approval_once(self):
        payload, fingerprint = payload_fingerprint(
            ACTION_KEYWORD_BID, {"keyword_id": 7, "new_bid": 1.23}
        )
        row = SimpleNamespace(
            tenant_id=3,
            status="approved",
            action_type=ACTION_KEYWORD_BID,
            payload_hash=fingerprint,
            payload=payload,
            approved_by=8,
            consumed_by=None,
            consumed_at=None,
        )
        session = _Session(row)
        await claim_approval(
            session,
            approval_id=1,
            tenant_id=3,
            action_type=ACTION_KEYWORD_BID,
            payload=payload,
            operator_user_id=9,
        )
        self.assertEqual(row.status, "consumed")
        self.assertEqual(row.consumed_by, 9)
        self.assertTrue(session.flushed)
        self.assertIsNotNone(session.statement._for_update_arg)

    async def test_claim_rejects_parameter_change(self):
        payload, fingerprint = payload_fingerprint(
            ACTION_KEYWORD_BID, {"keyword_id": 7, "new_bid": 1.23}
        )
        row = SimpleNamespace(
            tenant_id=3,
            status="approved",
            action_type=ACTION_KEYWORD_BID,
            payload_hash=fingerprint,
            payload=payload,
            approved_by=8,
            consumed_by=None,
            consumed_at=None,
        )
        with self.assertRaisesRegex(WritebackApprovalError, "参数不一致"):
            await claim_approval(
                _Session(row),
                approval_id=1,
                tenant_id=3,
                action_type=ACTION_KEYWORD_BID,
                payload={"keyword_id": 7, "new_bid": 1.24},
                operator_user_id=9,
            )


if __name__ == "__main__":
    unittest.main()
