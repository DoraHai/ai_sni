import unittest
import inspect
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.baidu.writeback_approval import (
    ACTION_ACCOUNT_BUDGET,
    ACTION_KEYWORD_BID,
    WritebackApprovalError,
    claim_approval,
    payload_fingerprint,
)
from app.baidu.writeback import (
    _ensure_no_unresolved_funds_writeback,
    _record_writeback_exception,
    apply_account_budget_writeback,
    apply_adgroup_bid_writeback,
    apply_campaign_budget_writeback,
    apply_keyword_writeback,
    apply_negative_writeback_campaign,
    apply_remove_negative_writeback,
    WritebackError,
)
from app.models import BidWriteback
from app.api.writeback import (
    ApprovalRequest,
    ReconciliationDecision,
    _queue_stage,
    reconcile_writeback,
    request_writeback_approval,
)
from app.security.auth import AuthContext


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
    async def test_single_operator_confirmation_is_created_ready_to_execute(self):
        class Session:
            def __init__(self):
                self.row = None
                self.commit = AsyncMock()

            def add(self, row):
                self.row = row

            async def refresh(self, row):
                row.id = 41

        session = Session()
        ctx = AuthContext(9, "operator", "运营", 3, {"verify.adjustments": "edit"})
        result = await request_writeback_approval(
            ApprovalRequest(
                tenant_id=3,
                action_type=ACTION_KEYWORD_BID,
                payload={"keyword_id": 7, "new_bid": 1.23},
                confirmation="CONFIRM_BAIDU_WRITEBACK",
            ),
            ctx=ctx,
            session=session,
        )
        self.assertEqual(result["approval"]["status"], "approved")
        self.assertEqual(result["approval"]["requested_by"], 9)
        self.assertEqual(result["approval"]["approved_by"], 9)
        session.commit.assert_awaited_once()

    async def test_single_operator_confirmation_rejects_wrong_phrase(self):
        ctx = AuthContext(9, "operator", "运营", 3, {"verify.adjustments": "edit"})
        with self.assertRaisesRegex(Exception, "CONFIRM_BAIDU_WRITEBACK"):
            await request_writeback_approval(
                ApprovalRequest(
                    tenant_id=3,
                    action_type=ACTION_KEYWORD_BID,
                    payload={"keyword_id": 7, "new_bid": 1.23},
                    confirmation="confirm",
                ),
                ctx=ctx,
                session=SimpleNamespace(),
            )

    def test_account_budget_approval_is_bound_to_account(self):
        normalized, _ = payload_fingerprint(
            ACTION_ACCOUNT_BUDGET,
            {"baidu_account_id": 12, "new_budget": 500},
        )
        self.assertEqual(normalized, {"baidu_account_id": 12, "new_budget": 500.0})
        with self.assertRaisesRegex(WritebackApprovalError, "baidu_account_id"):
            payload_fingerprint(ACTION_ACCOUNT_BUDGET, {"new_budget": 500})

    def test_unresolved_real_funds_intent_requires_reconciliation(self):
        self.assertEqual(_queue_stage("pending", False), "reconciliation_required")
        self.assertEqual(_queue_stage("reconcile", False), "reconciliation_required")
        self.assertEqual(_queue_stage("unexpected", False), "reconciliation_required")

    def test_unknown_real_funds_result_is_not_marked_failed(self):
        row = SimpleNamespace(status="pending", error_msg=None, executed_at=None)
        _record_writeback_exception(row, TimeoutError("timeout"), dry_run=False)
        self.assertEqual(row.status, "reconcile")
        self.assertIn("需人工对账", row.error_msg)

    def test_unknown_dry_run_result_can_be_marked_failed(self):
        row = SimpleNamespace(status="pending", error_msg=None, executed_at=None)
        _record_writeback_exception(row, TimeoutError("timeout"), dry_run=True)
        self.assertEqual(row.status, "failed")

    async def test_unresolved_real_funds_record_blocks_duplicate_write(self):
        session = SimpleNamespace(scalar=AsyncMock(return_value=41))
        with self.assertRaisesRegex(WritebackError, "先完成对账"):
            await _ensure_no_unresolved_funds_writeback(
                session,
                BidWriteback,
            )
        statement = session.scalar.await_args.args[0]
        self.assertIsNotNone(statement._for_update_arg)

    async def test_different_user_can_close_reconciliation_with_audit(self):
        row = SimpleNamespace(
            id=41, tenant_id=3, dry_run=False, status="reconcile",
            operator_user_id=8, error_msg="执行结果未知：timeout",
            reconciliation_result=None, reconciliation_note=None,
            reconciled_by=None, reconciled_at=None,
        )
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=row),
            commit=AsyncMock(), refresh=AsyncMock(),
        )
        ctx = AuthContext(9, "reviewer", "运营", None, {"verify.adjustments": "edit"})
        result = await reconcile_writeback(
            "bid", 41,
            ReconciliationDecision(
                tenant_id=3,
                decision="confirmed_not_executed",
                note="百度后台确认未生效",
            ),
            ctx=ctx, session=session,
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(row.reconciled_by, 9)
        self.assertIn("原异常", row.reconciliation_note)
        session.commit.assert_awaited_once()
        self.assertIsNotNone(session.scalar.await_args.args[0]._for_update_arg)

    async def test_executor_cannot_close_own_reconciliation(self):
        row = SimpleNamespace(
            id=41, tenant_id=3, dry_run=False, status="reconcile",
            operator_user_id=9, error_msg="timeout",
        )
        session = SimpleNamespace(scalar=AsyncMock(return_value=row))
        ctx = AuthContext(9, "executor", "运营", None, {"verify.adjustments": "edit"})
        with self.assertRaisesRegex(Exception, "不能确认自己的"):
            await reconcile_writeback(
                "action", 41,
                ReconciliationDecision(
                    tenant_id=3,
                    decision="confirmed_executed",
                    note="百度后台确认已生效",
                ),
                ctx=ctx, session=session,
            )

    def test_full_list_negative_writebacks_lock_the_mutated_row(self):
        campaign_source = inspect.getsource(apply_negative_writeback_campaign)
        adgroup_source = inspect.getsource(apply_remove_negative_writeback)

        self.assertIn("with_for_update()", campaign_source)
        self.assertIn("with_for_update()", adgroup_source)

    def test_real_funds_intent_is_committed_before_external_write(self):
        for function in (
            apply_keyword_writeback,
            apply_campaign_budget_writeback,
            apply_adgroup_bid_writeback,
            apply_account_budget_writeback,
        ):
            with self.subTest(function=function.__name__):
                source = inspect.getsource(function)
                persist_at = source.find("_persist_funds_intent")
                external_at = min(
                    position
                    for marker in (
                        ".update_word_bid(",
                        ".update_campaign_budget(",
                        ".update_adgroup_fields(",
                        ".update_account_budget(",
                    )
                    if (position := source.find(marker)) >= 0
                )
                self.assertGreaterEqual(persist_at, 0)
                self.assertLess(persist_at, external_at)

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

    async def test_claim_rejects_confirmation_owned_by_another_operator(self):
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
            requested_by=9,
            created_at=datetime.utcnow(),
            consumed_by=None,
            consumed_at=None,
        )
        with self.assertRaisesRegex(WritebackApprovalError, "当前实名操作员本人"):
            await claim_approval(
                _Session(row),
                approval_id=1,
                tenant_id=3,
                action_type=ACTION_KEYWORD_BID,
                payload=payload,
                operator_user_id=8,
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
            approved_by=9,
            requested_by=9,
            created_at=datetime.utcnow(),
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
            requested_by=8,
            created_at=datetime.utcnow(),
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

    async def test_claim_rejects_expired_confirmation(self):
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
            requested_by=9,
            created_at=datetime.utcnow() - timedelta(minutes=16),
            consumed_by=None,
            consumed_at=None,
        )
        with self.assertRaisesRegex(WritebackApprovalError, "已过期"):
            await claim_approval(
                _Session(row),
                approval_id=1,
                tenant_id=3,
                action_type=ACTION_KEYWORD_BID,
                payload=payload,
                operator_user_id=9,
            )


if __name__ == "__main__":
    unittest.main()
