import unittest
import inspect
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

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
    WRITEBACK_CONFIRMATION,
    WritebackApprovalError,
    claim_approval,
    create_self_approved_approval,
    payload_fingerprint,
)
from app.baidu.writeback import (
    _ensure_no_unresolved_funds_writeback,
    _record_writeback_exception,
    _validate,
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
    _signed_writeback_change_pct,
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


def _live_confirmation_settings(*, legacy: bool = False):
    return SimpleNamespace(
        baidu_write_confirmation_ttl_minutes=15,
        baidu_legacy_split_confirmation_enabled=legacy,
    )


def _shanghai_now_naive():
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


class WritebackApprovalTests(unittest.IsolatedAsyncioTestCase):
    def test_writeback_change_percentage_preserves_direction(self):
        self.assertEqual(_validate(13.28, 13.27), -0.08)
        self.assertEqual(_validate(10.0, 11.0), 10.0)

        self.assertEqual(_validate(10.0, 8.0), -20.0)
        self.assertEqual(_validate(10.0, 12.0), 20.0)
        with self.assertRaisesRegex(WritebackError, "20%"):
            _validate(10.0, 7.99)
        with self.assertRaisesRegex(WritebackError, "20%"):
            _validate(10.0, 12.01)

        historical_decrease = SimpleNamespace(
            old_bid=13.28,
            new_bid=13.27,
            change_pct=0.08,
        )
        self.assertEqual(
            _signed_writeback_change_pct(historical_decrease),
            -0.08,
        )

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
        self.assertIsNotNone(session.row.decided_at)
        self.assertLess(
            abs((_shanghai_now_naive() - session.row.decided_at).total_seconds()),
            5,
        )
        session.commit.assert_awaited_once()

    async def test_one_click_confirmation_creates_parameter_bound_audit_row(self):
        class Session:
            def __init__(self):
                self.row = None
                self.flush = AsyncMock()
                self.execute = AsyncMock()
                self.scalar = AsyncMock(return_value=None)

            def add(self, row):
                self.row = row

        session = Session()
        row = await create_self_approved_approval(
            session,
            tenant_id=3,
            action_type=ACTION_KEYWORD_BID,
            payload={"keyword_id": 7, "new_bid": 1.234},
            operator_user_id=9,
            confirmation=WRITEBACK_CONFIRMATION,
            idempotency_key="sem-one-click-audit-0001",
        )

        self.assertIs(row, session.row)
        self.assertEqual(row.status, "approved")
        self.assertEqual(row.payload, {"keyword_id": 7, "new_bid": 1.23})
        self.assertEqual(row.requested_by, 9)
        self.assertEqual(row.approved_by, 9)
        self.assertEqual(row.decision_note, "本人一次确认")
        self.assertIsNotNone(row.created_at)
        self.assertIsNone(row.created_at.tzinfo)
        self.assertLess(
            abs(
                (
                    _shanghai_now_naive() - row.created_at
                ).total_seconds()
            ),
            5,
        )
        session.flush.assert_awaited_once()

    async def test_idempotent_confirmation_stores_only_digest_marker(self):
        class Session:
            def __init__(self):
                self.row = None
                self.execute = AsyncMock()
                self.scalar = AsyncMock(return_value=None)
                self.flush = AsyncMock()

            def add(self, row):
                self.row = row

        session = Session()
        raw_key = "sem-writeback-request-0001"
        row = await create_self_approved_approval(
            session,
            tenant_id=3,
            action_type=ACTION_KEYWORD_BID,
            payload={"keyword_id": 7, "new_bid": 1.23},
            operator_user_id=9,
            confirmation=WRITEBACK_CONFIRMATION,
            idempotency_key=raw_key,
        )

        self.assertTrue(row.request_note.startswith("idempotency-sha256:"))
        self.assertNotIn(raw_key, row.request_note)
        self.assertEqual(len(row.request_note), len("idempotency-sha256:") + 64)
        self.assertIn("pg_advisory_xact_lock", str(session.execute.await_args.args[0]))
        session.scalar.assert_awaited_once()
        session.flush.assert_awaited_once()

    async def test_idempotent_confirmation_reuses_matching_audit_row(self):
        normalized, fingerprint = payload_fingerprint(
            ACTION_KEYWORD_BID, {"keyword_id": 7, "new_bid": 1.23}
        )
        existing = SimpleNamespace(
            id=41,
            action_type=ACTION_KEYWORD_BID,
            payload=normalized,
            payload_hash=fingerprint,
        )
        session = SimpleNamespace(
            execute=AsyncMock(),
            scalar=AsyncMock(return_value=existing),
            add=unittest.mock.Mock(),
            flush=AsyncMock(),
        )

        row = await create_self_approved_approval(
            session,
            tenant_id=3,
            action_type=ACTION_KEYWORD_BID,
            payload={"keyword_id": 7, "new_bid": 1.23},
            operator_user_id=9,
            confirmation=WRITEBACK_CONFIRMATION,
            idempotency_key="sem-writeback-request-0001",
        )

        self.assertIs(row, existing)
        session.add.assert_not_called()
        session.flush.assert_not_awaited()

    async def test_idempotency_key_cannot_be_reused_for_different_parameters(self):
        normalized, fingerprint = payload_fingerprint(
            ACTION_KEYWORD_BID, {"keyword_id": 7, "new_bid": 1.24}
        )
        existing = SimpleNamespace(
            id=41,
            action_type=ACTION_KEYWORD_BID,
            payload=normalized,
            payload_hash=fingerprint,
        )
        session = SimpleNamespace(
            execute=AsyncMock(), scalar=AsyncMock(return_value=existing)
        )
        with self.assertRaisesRegex(WritebackApprovalError, "其他执行参数"):
            await create_self_approved_approval(
                session,
                tenant_id=3,
                action_type=ACTION_KEYWORD_BID,
                payload={"keyword_id": 7, "new_bid": 1.23},
                operator_user_id=9,
                confirmation=WRITEBACK_CONFIRMATION,
                idempotency_key="sem-writeback-request-0001",
            )

    async def test_one_click_confirmation_rejects_missing_confirmation(self):
        with self.assertRaisesRegex(WritebackApprovalError, WRITEBACK_CONFIRMATION):
            await create_self_approved_approval(
                SimpleNamespace(),
                tenant_id=3,
                action_type=ACTION_KEYWORD_BID,
                payload={"keyword_id": 7, "new_bid": 1.23},
                operator_user_id=9,
                confirmation=None,
            )

    async def test_legacy_frontend_can_create_pending_during_dry_run_rollout(self):
        class Session:
            def __init__(self):
                self.row = None
                self.commit = AsyncMock()

            def add(self, row):
                self.row = row

            async def refresh(self, row):
                row.id = 42

        session = Session()
        ctx = AuthContext(9, "operator", "运营", 3, {"verify.adjustments": "edit"})
        with patch(
            "app.api.writeback.get_settings",
            return_value=SimpleNamespace(baidu_legacy_split_confirmation_enabled=True),
        ):
            result = await request_writeback_approval(
                ApprovalRequest(
                    tenant_id=3,
                    action_type=ACTION_KEYWORD_BID,
                    payload={"keyword_id": 7, "new_bid": 1.23},
                ),
                ctx=ctx,
                session=session,
            )
        self.assertEqual(result["approval"]["status"], "pending")
        self.assertIsNone(result["approval"]["approved_by"])

    async def test_missing_confirmation_is_rejected_after_compatibility_window(self):
        ctx = AuthContext(9, "operator", "运营", 3, {"verify.adjustments": "edit"})
        with (
            patch(
                "app.api.writeback.get_settings",
                return_value=SimpleNamespace(
                    baidu_legacy_split_confirmation_enabled=False
                ),
            ),
            self.assertRaisesRegex(Exception, "CONFIRM_BAIDU_WRITEBACK"),
        ):
            await request_writeback_approval(
                ApprovalRequest(
                    tenant_id=3,
                    action_type=ACTION_KEYWORD_BID,
                    payload={"keyword_id": 7, "new_bid": 1.23},
                ),
                ctx=ctx,
                session=SimpleNamespace(),
            )

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

    def test_fingerprint_preserves_bigint_identity(self):
        for value in (2**53, 2**53 + 1, 2**63 - 1):
            with self.subTest(value=value):
                normalized, digest = payload_fingerprint(
                    ACTION_KEYWORD_BID, {"keyword_id": value, "new_bid": 1.23}
                )
                self.assertEqual(normalized["keyword_id"], value)
                self.assertEqual(payload_fingerprint(
                    ACTION_KEYWORD_BID, {"keyword_id": str(value), "new_bid": 1.23}
                )[1], digest)
        self.assertNotEqual(
            payload_fingerprint(ACTION_KEYWORD_BID, {"keyword_id": 2**53, "new_bid": 1.23})[1],
            payload_fingerprint(ACTION_KEYWORD_BID, {"keyword_id": 2**53 + 1, "new_bid": 1.23})[1],
        )

    def test_id_rejects_out_of_range_and_fractional_strings(self):
        for value in (str(2**63), float(2**53), "7.0000000000000000001", "NaN", "Infinity", "1e999999", [], None):
            with self.subTest(value=value), self.assertRaises(WritebackApprovalError):
                payload_fingerprint(ACTION_KEYWORD_BID, {"keyword_id": value, "new_bid": 1.23})

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
            created_at=_shanghai_now_naive(),
            consumed_by=None,
            consumed_at=None,
        )
        with (
            patch(
                "app.baidu.writeback_approval.get_settings",
                return_value=_live_confirmation_settings(),
            ),
            self.assertRaisesRegex(WritebackApprovalError, "当前实名操作员本人"),
        ):
            await claim_approval(
                _Session(row), approval_id=1, tenant_id=3,
                action_type=ACTION_KEYWORD_BID, payload=payload, operator_user_id=8,
            )

    async def test_legacy_split_confirmation_cannot_be_consumed_during_rollout(self):
        payload, fingerprint = payload_fingerprint(
            ACTION_KEYWORD_BID, {"keyword_id": 7, "new_bid": 1.23}
        )
        row = SimpleNamespace(
            tenant_id=3, status="approved", action_type=ACTION_KEYWORD_BID,
            payload_hash=fingerprint, payload=payload, approved_by=8, requested_by=9,
            created_at=_shanghai_now_naive(), consumed_by=None, consumed_at=None,
        )
        with (
            patch(
                "app.baidu.writeback_approval.get_settings",
                return_value=_live_confirmation_settings(legacy=True),
            ),
            self.assertRaisesRegex(WritebackApprovalError, "兼容期间"),
        ):
            await claim_approval(
                _Session(row), approval_id=1, tenant_id=3,
                action_type=ACTION_KEYWORD_BID, payload=payload, operator_user_id=9,
            )
        self.assertEqual(row.status, "approved")

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
            created_at=_shanghai_now_naive(),
            consumed_by=None,
            consumed_at=None,
        )
        session = _Session(row)
        with patch(
            "app.baidu.writeback_approval.get_settings",
            return_value=_live_confirmation_settings(),
        ):
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
            created_at=_shanghai_now_naive(),
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
            created_at=_shanghai_now_naive() - timedelta(minutes=16),
            consumed_by=None,
            consumed_at=None,
        )
        with (
            patch(
                "app.baidu.writeback_approval.get_settings",
                return_value=_live_confirmation_settings(),
            ),
            self.assertRaisesRegex(WritebackApprovalError, "已过期"),
        ):
            await claim_approval(
                _Session(row), approval_id=1, tenant_id=3,
                action_type=ACTION_KEYWORD_BID, payload=payload, operator_user_id=9,
            )


if __name__ == "__main__":
    unittest.main()
