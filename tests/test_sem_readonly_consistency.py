from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_account_surfaces_share_all_tenant_baidu_accounts():
    oauth_status = _read("app/api/oauth_baidu.py")
    account_assets = _read("app/api/customer_modules.py")

    assert 'BaiduAccount.auth_mode == "oauth"' not in oauth_status
    assert '"data_state": data_state' in account_assets
    assert '"campaigns": campaign_stats' in account_assets
    assert '"keywords": keyword_stats' in account_assets
    assert '"search_terms": search_term_stats' in account_assets
    assert '"mode": "read_only_repair"' in account_assets
    assert "sync_search_terms_for_account" in _read("app/scheduler.py")


def test_sem_business_surfaces_hide_archived_account_history():
    auth_api = _read("app/api/auth.py")
    oauth_status = _read("app/api/oauth_baidu.py")
    account_assets = _read("app/api/customer_modules.py")
    account_view = _read("frontend/src/views/manage/SemAccountsView.vue")
    onboarding = _read("frontend/src/views/onboarding/AuthorizationSyncView.vue")

    for source in (auth_api, oauth_status, account_assets):
        assert 'BaiduAccount.status != "archived"' in source
    assert "filter((item) => item.status !== 'archived')" in account_view
    assert "filter((item) => item.status !== 'archived')" in onboarding


def test_sem_shell_switcher_keeps_settings_routes_in_sem_scope():
    app_shell = _read("frontend/src/App.vue")
    session_store = _read("frontend/src/store/session.js")
    customer_modules = _read("frontend/src/views/settings/CustomerModulesView.vue")
    account_roles = _read("frontend/src/views/settings/AccountsRolesView.vue")

    scope_block = app_shell.split("const tenantModuleScope", 1)[1].split(")\nconst showSemAccountContext", 1)[0]
    assert "route.path.startsWith('/settings')" not in scope_block
    assert "route.path.startsWith('/admin')" not in scope_block
    assert "fetchTenants(moduleScope)" in app_shell
    assert "tenantListRevision" in session_store
    assert "watch(() => session.tenantListRevision, loadTenants)" in app_shell
    assert "session.requestTenantReload()" in customer_modules
    assert "fetchTenants()" in account_roles
    assert 'v-for="t in tenantOptions"' in account_roles
    assert 'v-for="t in session.tenants"' not in account_roles


def test_sem_frontend_labels_effective_customer_writeback_mode():
    capabilities = _read("frontend/src/constants/semCapabilities.js")
    app_shell = _read("frontend/src/App.vue")
    workbench = _read("frontend/src/views/optimize/KeywordWorkbenchView.vue")

    assert "SEM_LIMITED_LIVE_MESSAGE" in capabilities
    assert "fetchWritebackMode" in app_shell
    assert "writebackMode.mode === 'limited_live'" in app_shell
    assert "只读演练" in app_shell
    assert "加入待回写" in workbench
    assert "优化建议" in app_shell
    assert "待审拓词建议数量" in app_shell


def test_empty_states_distinguish_read_sync_from_writeback():
    workbench = _read("frontend/src/views/optimize/KeywordWorkbenchView.vue")
    search_terms = _read("frontend/src/views/optimize/SearchTermsView.vue")
    adgroups = _read("frontend/src/views/manage/AdgroupManageView.vue")

    assert "这是读取同步问题，与百度回写是否开启无关" in workbench
    assert "该数据来自百度读取，与回写开关无关" in search_terms
    assert "账户已授权但尚未完成首次同步" in adgroups


def test_sem_p1_experience_guards_are_present():
    client = _read("frontend/src/api/client.js")
    router = _read("frontend/src/router/index.js")
    builder = _read("frontend/src/views/onboarding/SmartBuilderView.vue")
    profile = _read("frontend/src/views/monitor/CustomerProfileView.vue")
    adjustment_log = _read("frontend/src/views/verify/AdjustmentLogView.vue")

    assert "return new Promise(() => {})" not in client
    assert "Promise.reject(expired)" in client
    assert "当前账号没有" in router
    assert "startHour: 0, endHour: 24" in builder
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in profile
    assert "AI 建议值" not in adjustment_log
    assert "调后效果" not in adjustment_log


def test_readonly_actions_have_a_unified_auditable_queue():
    api = _read("app/api/writeback.py")
    pending = _read("frontend/src/views/verify/PendingAdjustmentsView.vue")
    labels = _read("app/models/writeback_action.py")

    assert '@router.get("/queue")' in api
    assert '"pending_writeback"' in api
    assert '"writeback_enabled": False' in api
    assert "待回写队列" in pending
    assert "待回写（演练记录）" in labels


def test_permission_failures_are_actionable():
    client = _read("frontend/src/api/client.js")
    router = _read("frontend/src/router/index.js")
    accounts = _read("frontend/src/views/settings/AccountsRolesView.vue")

    assert "PERMISSION_DENIED" in client
    assert "账号与权限" in router
    assert "settings.accounts" in accounts
    assert "这不是数据为空" in accounts


def test_refresh_and_timeout_failures_reach_a_visible_terminal_state():
    client = _read("frontend/src/api/client.js")
    app = _read("frontend/src/App.vue")
    router = _read("frontend/src/router/index.js")

    assert "REQUEST_TIMEOUT" in client
    assert "超过 30 秒" in client
    assert "bootstrapError" in app and "客户列表加载失败" in app
    assert "router.onError" in router and "页面加载失败" in router


def test_stale_dynamic_chunks_recover_once_after_a_release():
    router = _read("frontend/src/router/index.js")
    recovery = _read("frontend/src/router/chunkRecovery.js")

    assert "vite:preloadError" in router
    assert "recoverFromChunkLoadError" in router
    assert "sessionStorage" in recovery
    assert "window.location.reload()" in recovery


def test_effect_verification_exposes_sample_maturity():
    keyword = _read("app/ai/adjustment_verify.py")
    budget = _read("app/ai/budget_adjustment_verify.py")
    view = _read("frontend/src/views/verify/PendingAdjustmentsView.vue")

    assert "MIN_AFTER_DAYS = 3" in keyword
    assert '"sample": sample_status' in keyword
    assert '"sample": sample' in budget
    assert "样本已达到基础验证门槛" in keyword
    assert "sample-state" in view


def test_report_connects_review_to_today_work():
    report = _read("app/ai/monthly_report.py")
    view = _read("frontend/src/views/delivery/MonthlyReportView.vue")

    assert '"operational_focus": operational_focus' in report
    assert '"pending_writebacks"' in report
    assert '"sync_risks"' in report
    assert "今日执行焦点" in view
    assert "待审建议" in view and "待回写" in view
    assert '"priority_suggestions"' in report
    assert "_suggestion_business_score" in report
    assert '"impact": _suggestion_impact(row)' in report
    assert '"suggestions_path": "/optimize/keywords?has_suggestion=true&from=report"' in report
    assert '"queue_path": "/verify/pending?mode=queue"' in report
    assert "openWorkItem" in view and "focus-list" in view and "查看全部" in view
    assert "route.query.has_suggestion === 'true'" in _read("frontend/src/views/optimize/KeywordWorkbenchView.vue")
    assert "focused-account-row" in _read("frontend/src/views/manage/SemAccountsView.vue")
    assert "route.query.mode === 'queue'" in _read("frontend/src/views/verify/PendingAdjustmentsView.vue")


def test_suggestion_internal_workflow_has_owner_status_and_deadline():
    model = _read("app/models/suggestion.py")
    api = _read("app/api/suggestions.py")
    client = _read("frontend/src/api/suggestions.js")
    workbench = _read("frontend/src/views/optimize/KeywordWorkbenchView.vue")
    report = _read("frontend/src/views/delivery/MonthlyReportView.vue")
    migration = _read("migrations/versions/20260822_0074_suggestion_workflow.py")

    for field in ("handling_status", "assignee_id", "due_at", "workflow_updated_at"):
        assert field in model and field in migration
    assert '@router.patch("/{suggestion_id}/workflow")' in api
    assert 'ensure_module_access(session, ctx, suggestion.tenant_id, "sem")' in api
    assert "ensure_sem_identity_access(session, suggestion.tenant_id)" in api
    assert '@router.get("/assignees")' in api
    assert "updateSuggestionWorkflow" in client
    assert "内部状态不代表百度已实际回写" in workbench
    assert "负责人：" in report and "fmtDeadline" in report


def test_client_report_only_admits_evidenced_completed_actions():
    report_api = _read("app/api/reports.py")
    report_data = _read("app/ai/monthly_report.py")
    report_client = _read("frontend/src/api/reports.js")
    view = _read("frontend/src/views/delivery/MonthlyReportView.vue")
    verify = _read("app/ai/adjustment_verify.py")

    assert "def _client_report_view" in report_api
    assert 'data.pop("operational_focus", None)' in report_api
    assert 'data.pop("alerts_review", None)' in report_api
    assert 'data.pop("pending_modules", None)' in report_api
    assert 'ctx.tenant_id is not None or version == "client"' in report_api
    assert '"evidence": "百度操作记录"' in report_data
    assert '"client_delivery": client_delivery' in report_data
    assert '"sample": sample_status(kid, before, after)' in verify
    assert "version = 'internal'" in report_client
    assert "效果观察中" in view and "已完成优化与效果" in view
    assert '<section v-if="showInternal" id="mod-pending"' in view
