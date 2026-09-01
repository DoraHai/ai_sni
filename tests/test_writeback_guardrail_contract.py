import ast
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.baidu.writeback import (
    _active_account,
    _claim_funds_approval,
    _preflight_active_account,
)


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
    module_source = (ROOT / "app/baidu/writeback.py").read_text(encoding="utf-8")
    tree = ast.parse(module_source)
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
        function_source = ast.get_source_segment(
            module_source, _async_function(tree, function_name)
        )
        assert (
            "session.refresh(rec, with_for_update=True)" in function_source
        ), function_name
        assert calls.count("with_for_update") >= minimum_local_locks, function_name

    active_account_source = ast.get_source_segment(
        module_source, _async_function(tree, "_active_account")
    )
    assert "_load_active_account" in active_account_source
    assert "lock=True" in active_account_source
    for function_name in (
        "apply_campaign_schedule_writeback",
        "apply_campaign_region_writeback",
        "apply_adgroup_pause_writeback",
    ):
        assert "with_for_update" in _call_names(_async_function(tree, function_name))


def test_budget_preflight_reads_finish_before_funds_rows_are_locked():
    source = (ROOT / "app/baidu/writeback.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    account_loader_source = ast.get_source_segment(
        source, _async_function(tree, "_load_active_account")
    )
    assert "if lock:" in account_loader_source
    assert "query = query.with_for_update()" in account_loader_source

    preflight_source = ast.get_source_segment(
        source, _async_function(tree, "_preflight_active_account")
    )
    assert "_load_active_account" in preflight_source
    assert "lock=False" in preflight_source
    assert source.count("_preflight_active_account(") == 3

    campaign_source = ast.get_source_segment(
        source, _async_function(tree, "apply_campaign_budget_writeback")
    )
    campaign_preflight = campaign_source.index(".get_account_info(")
    campaign_lock = campaign_source.index("execution_options(populate_existing=True)")
    campaign_guard = campaign_source.index("_ensure_no_unresolved_funds_writeback")
    assert "_preflight_active_account" in campaign_source[:campaign_preflight]
    assert campaign_preflight < campaign_lock < campaign_guard
    assert "_active_account" in campaign_source[campaign_lock:]
    assert "execution_options(populate_existing=True)" in campaign_source
    assert "locked_account_id != preflight_account_id" in campaign_source

    account_source = ast.get_source_segment(
        source, _async_function(tree, "apply_account_budget_writeback")
    )
    account_preflight = account_source.index(".get_account_info(")
    account_lock = account_source.index("_active_account(", account_preflight)
    account_guard = account_source.index("_ensure_no_unresolved_funds_writeback")
    assert "_preflight_active_account" in account_source[:account_preflight]
    assert account_preflight < account_lock < account_guard
    assert "acc.id != preflight_account_id" in account_source


def test_active_account_preflight_query_omits_row_lock_until_requested():
    account = SimpleNamespace(id=17)
    unlocked_session = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [account]))
    )
    locked_session = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [account]))
    )

    unlocked = asyncio.run(_preflight_active_account(unlocked_session, 7, 17))
    locked = asyncio.run(_active_account(locked_session, 7, 17))

    assert unlocked is account
    assert locked is account
    unlocked_query = str(unlocked_session.scalars.await_args.args[0]).upper()
    locked_query = str(locked_session.scalars.await_args.args[0]).upper()
    assert "FOR UPDATE" not in unlocked_query
    assert "FOR UPDATE" in locked_query


def test_live_write_scope_is_checked_in_orchestration_and_http_client():
    orchestration = (ROOT / "app/baidu/writeback.py").read_text(encoding="utf-8")
    client = (ROOT / "app/baidu/client.py").read_text(encoding="utf-8")
    account_client = (ROOT / "app/baidu/sync.py").read_text(encoding="utf-8")

    loader = ast.get_source_segment(
        orchestration,
        _async_function(ast.parse(orchestration), "_load_active_account"),
    )
    assert "baidu_live_write_allowed(tenant_id, acc.id)" in loader
    assert "if not settings.baidu_write_dry_run" in loader
    assert "is_write_request" in client
    assert "settings.baidu_live_write_allowed(" in client
    assert "tenant_id=baidu_account.tenant_id" in account_client
    assert "baidu_account_id=baidu_account.id" in account_client


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
    assert "CONFIRM_BAIDU_WRITEBACK" in approval_view
    assert "confirmation: approvalForm.confirmation" in approval_view

    approval_api = (ROOT / "app/api/writeback.py").read_text(encoding="utf-8")
    assert "req.confirmation != WRITEBACK_CONFIRMATION" in approval_api
    assert 'status="approved"' in approval_api
    assert "approved_by=ctx.user_id" in approval_api

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
