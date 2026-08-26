import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.baidu.writeback import _claim_funds_approval


ROOT = Path(__file__).resolve().parents[1]


def _async_function(tree: ast.AST, name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing async function: {name}")


def _call_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name):
            names.append(item.func.id)
        elif isinstance(item.func, ast.Attribute):
            names.append(item.func.attr)
    return names


def test_high_risk_writebacks_keep_approval_and_row_lock_contracts():
    tree = ast.parse((ROOT / "app/baidu/writeback.py").read_text(encoding="utf-8"))
    required = {
        "apply_keyword_writeback": 2,
        "apply_campaign_budget_writeback": 1,
        "apply_adgroup_bid_writeback": 2,
        "apply_account_budget_writeback": 0,
    }
    for function_name, minimum_local_locks in required.items():
        calls = _call_names(_async_function(tree, function_name))
        assert "_claim_funds_approval" in calls, function_name
        assert "_ensure_no_unresolved_funds_writeback" in calls, function_name
        assert "_record_writeback_exception" in calls, function_name
        source = ast.get_source_segment(
            (ROOT / "app/baidu/writeback.py").read_text(encoding="utf-8"),
            _async_function(tree, function_name),
        )
        assert "session.refresh(rec, with_for_update=True)" in source, function_name
        assert calls.count("with_for_update") >= minimum_local_locks, function_name

    active_account_calls = _call_names(_async_function(tree, "_active_account"))
    assert "with_for_update" in active_account_calls
    for function_name in (
        "apply_campaign_schedule_writeback",
        "apply_campaign_region_writeback",
        "apply_adgroup_pause_writeback",
    ):
        assert "with_for_update" in _call_names(_async_function(tree, function_name))


def test_backend_and_frontend_keep_approval_id_wiring():
    manage_api = (ROOT / "app/api/manage.py").read_text(encoding="utf-8")
    keyword_api = (ROOT / "app/api/keywords.py").read_text(encoding="utf-8")
    manage_client = (ROOT / "frontend/src/api/manage.js").read_text(encoding="utf-8")
    keyword_client = (ROOT / "frontend/src/api/keywords.js").read_text(encoding="utf-8")
    approval_view = (
        ROOT / "frontend/src/views/verify/AdjustmentLogView.vue"
    ).read_text(encoding="utf-8")

    assert manage_api.count("approval_id: int | None = None") >= 3
    assert manage_api.count("approval_id=req.approval_id") >= 3
    assert keyword_api.count("approval_id: int | None = None") >= 2
    assert keyword_api.count("approval_id=") >= 2
    assert manage_client.count("approval_id: approvalId") == 3
    assert "approval_id: approvalId" in keyword_client
    assert approval_view.count("approvalId: row.id") == 4

    orchestration = (ROOT / "app/baidu/writeback.py").read_text(encoding="utf-8")
    assert orchestration.count("approval_id=approval_id if not dry_run else None") == 4
    migration = (
        ROOT / "migrations/versions/20260825_0076_oauth_rebind_intent.py"
    ).read_text(encoding="utf-8")
    assert '"bid_writebacks", sa.Column("approval_id"' in migration
    assert '"writeback_actions", sa.Column("approval_id"' in migration
    assert '"bid_writebacks", sa.Column("reconciliation_result"' in migration
    assert '"writeback_actions", sa.Column("reconciliation_result"' in migration


def test_frontend_never_treats_reconciliation_as_success():
    keyword = (ROOT / "frontend/src/composables/useKeywordWriteback.js").read_text(encoding="utf-8")
    adgroup = (ROOT / "frontend/src/views/manage/AdgroupManageView.vue").read_text(encoding="utf-8")
    queue = (ROOT / "frontend/src/views/verify/PendingAdjustmentsView.vue").read_text(encoding="utf-8")
    router = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")
    ledger = (ROOT / "frontend/src/views/verify/AdjustmentLogView.vue").read_text(encoding="utf-8")
    assert "['pending', 'reconcile'].includes(response.writeback?.status)" in keyword
    assert "response.writeback?.status !== 'success'" in keyword
    assert "['pending', 'reconcile'].includes(res.status)" in adgroup
    assert "确认百度已执行" in queue and "确认百度未执行" in queue
    assert "['verify.pending', 'verify.adjustments']" in router
    assert "人工对账队列" in ledger


def test_real_writeback_claims_approval_but_dry_run_does_not():
    session = SimpleNamespace()
    with (
        patch(
            "app.baidu.writeback.get_settings",
            return_value=SimpleNamespace(baidu_write_dry_run=False),
        ),
        patch("app.baidu.writeback.claim_approval", new_callable=AsyncMock) as claim,
    ):
        asyncio.run(
            _claim_funds_approval(
                session,
                approval_id=17,
                tenant_id=3,
                action_type="keyword_bid",
                payload={"keyword_id": 7, "new_bid": 1.23},
                operator_user_id=9,
            )
        )
        claim.assert_awaited_once()

    with (
        patch(
            "app.baidu.writeback.get_settings",
            return_value=SimpleNamespace(baidu_write_dry_run=True),
        ),
        patch("app.baidu.writeback.claim_approval", new_callable=AsyncMock) as claim,
    ):
        asyncio.run(
            _claim_funds_approval(
                session,
                approval_id=None,
                tenant_id=3,
                action_type="keyword_bid",
                payload={"keyword_id": 7, "new_bid": 1.23},
                operator_user_id=9,
            )
        )
        claim.assert_not_awaited()
