import os
from datetime import date
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.ai.assistant import _requested_report_period
from app.classification import classify_one, resolve_brand_terms


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_current_month_uses_real_calendar_instead_of_stale_data_month():
    period = _requested_report_period(
        "这个月花了多少",
        available_start=date(2026, 4, 1),
        available_end=date(2026, 6, 22),
        today=date(2026, 8, 22),
    )

    assert period.label == "本月"
    assert period.start == date(2026, 8, 1)
    assert period.end == date(2026, 8, 22)


def test_previous_month_uses_real_calendar_instead_of_stale_data_month():
    period = _requested_report_period(
        "上月的消费",
        available_start=date(2026, 4, 1),
        available_end=date(2026, 6, 22),
        today=date(2026, 8, 22),
    )

    assert period.start == date(2026, 7, 1)
    assert period.end == date(2026, 7, 31)


def test_sem_customer_facing_views_do_not_hardcode_legacy_customer():
    assert "苏尔寿" not in _read("frontend/src/views/assistant/AssistantView.vue")
    assert "苏尔寿" not in _read("frontend/src/views/manage/OcpcView.vue")


def test_customer_switch_discards_stale_page_responses():
    for path, marker in (
        ("frontend/src/views/monitor/DashboardView.vue", "version !== loadVersion"),
        ("frontend/src/views/delivery/MonthlyReportView.vue", "requestVersion !== loadVersion"),
        ("frontend/src/views/assistant/AssistantView.vue", "version !== contextVersion"),
        ("frontend/src/views/manage/OcpcView.vue", "version !== loadVersion"),
    ):
        source = _read(path)
        assert marker in source
        assert "tenantId !== TENANT_ID.value" in source


def test_assistant_hides_provider_error_details_from_customer():
    view = _read("frontend/src/views/assistant/AssistantView.vue")
    assert "AI 分析暂时不可用" in view
    assert "e.response?.data?.detail" not in view
    assert "'出错了：'" not in view


def test_report_view_survives_older_backend_payload():
    view = _read("frontend/src/views/delivery/MonthlyReportView.vue")
    assert "const clientDelivery = computed" in view
    assert "data.value?.client_delivery ||" in view
    assert "const operationalFocus = computed" in view
    assert "data.value?.operational_focus ||" in view
    assert "data.client_delivery.completed_count" not in view


def test_dashboard_marks_incomplete_data_without_false_decline():
    backend = _read("app/api/dashboard.py")
    frontend = _read("frontend/src/views/monitor/DashboardView.vue")
    assert '"requested_data_complete": requested_data_complete' in backend
    assert 'item["change_pct"] = None' in backend
    assert "缺失的报表日不是 0 消费" in backend
    assert "数据未同步" in frontend
    assert "connectionAlert" in frontend


def test_brand_terms_have_one_canonical_fallback_for_alerts_and_filters():
    tenant = type("TenantStub", (), {"brand_terms": [" Nord ", "nord"], "name": "诺德"})()
    assert resolve_brand_terms(tenant) == ["nord"]
    assert classify_one("NORD 工业齿轮箱", None, 100, resolve_brand_terms(tenant)) == "brand"

    rule = _read("app/rules/brand_rank.py")
    keywords = _read("app/api/keywords.py")
    assert "resolve_brand_terms(tenant)" in rule
    assert "resolve_brand_terms(tenant)" in keywords


def test_p1_p2_frontend_contracts_are_present():
    alerts = _read("frontend/src/views/monitor/AlertsView.vue")
    app = _read("frontend/src/App.vue")
    router = _read("frontend/src/router/index.js")
    builder = _read("frontend/src/views/onboarding/SmartBuilderView.vue")
    accounts = _read("frontend/src/views/onboarding/AuthorizationSyncView.vue")
    auth_api = _read("frontend/src/api/auth.js")
    diagnosis = _read("frontend/src/views/diagnosis/DiagnosisCenterView.vue")
    seo_shell = _read("frontend/src/views/seo/SeoWorkspaceShell.vue")
    session_store = _read("frontend/src/store/session.js")
    adgroups = _read("frontend/src/views/manage/AdgroupManageView.vue")

    assert "今日新增 {{ todayNew }} 条" in alerts
    assert "按计划批量筛选" in alerts and "按告警类型批量筛选" in alerts
    assert '<div class="ac-foot">' in alerts
    assert "batch-resolve" in _read("app/api/alerts.py")
    assert "closeTenantPopoverOnEscape" in app
    assert "path: '/settings/users', redirect: '/settings/accounts'" in router
    assert "DiagnosisCenterView.vue" in router
    assert "没有链接，粘贴文字" in builder
    assert 'goal: \'获取高意向线索\'' in builder
    assert "fetchSemAccounts" in accounts and "item.counts.campaigns" in accounts
    assert "fetchTenants('sem')" in accounts
    assert "params: module ? { module } : undefined" in auth_api
    assert "tenantModuleScope" in app and "fetchTenants(moduleScope)" in app
    assert "watch(tenantModuleScope" in app
    assert "loadTenants(); loadWritebackMode()" in app
    assert "tenantModuleScope.value !== 'sem'" in app
    assert "fetchTenants('seo')" in seo_shell
    assert "fetchTenants('geo')" in diagnosis
    assert "sessionStorage.removeItem('sem_tenant_id')" in session_store
    assert 'fixed="right"' in adgroups and "状态未同步" in adgroups


def test_tenant_account_identity_guards_are_visible_and_race_safe():
    app_shell = _read("frontend/src/App.vue")
    customers = _read("frontend/src/views/settings/CustomerModulesView.vue")
    accounts = _read("frontend/src/views/manage/SemAccountsView.vue")
    router = _read("frontend/src/router/index.js")
    backend = _read("app/api/customer_modules.py")
    self_auth = _read("app/main.py")
    identity_guard = _read("app/security/sem_identity.py")
    auth_api = _read("app/api/auth.py")
    auth_guard = _read("app/security/auth.py")
    client = _read("frontend/src/api/client.js")

    assert "SEM 推广账户归属" in customers
    assert "重新检查归属" in customers and "identity_issues" in customers
    assert "推广账户：" in app_shell and "UCID" in app_shell
    assert "sem_accounts" in app_shell and "fmtAccountSync" in app_shell
    assert "推广账户归属冲突，已暂停展示该客户的 SEM 数据" in app_shell
    assert "showSemIdentityBlock" in app_shell and "v-if=\"!showSemIdentityBlock\"" in app_shell
    assert "SEM_ACCOUNT_IDENTITY_CONFLICT" in identity_guard
    assert "identity_conflict" in identity_guard
    assert "public_sem_identity_state(identity_states.get(tenant.id))" in auth_api
    assert "ensure_sem_identity_access" in auth_guard
    assert "filter_identity_safe_active_accounts" in _read("app/scheduler.py")
    assert "filter_identity_safe_active_accounts" in _read("app/baidu/sync.py")
    assert "error.response?.data?.detail?.code" in client
    assert "badgeLoadGeneration" in app_shell
    assert "generation !== badgeLoadGeneration" in app_shell
    assert "tenant?.sem_identity?.status === 'blocked'" in app_shell
    assert "badgeLoadGeneration += 1" in app_shell
    assert "resetBadges()" in app_shell
    assert "identity_locked" in customers and "受控客户更名" in customers
    assert "最终确认" in customers and "name_change_reason" in customers
    assert "confirm_bound_name_change" in backend
    assert "AUDIT customer_bound_name_changed" in backend
    assert "不能再绑定到另一个客户名称" in self_auth
    assert "generation !== loadGeneration" in accounts
    assert "tenantId !== currentTenantId.value" in accounts
    assert "正在读取推广账户" in accounts
    assert "path: '/:pathMatch(.*)*'" in router
    assert "NotFoundView.vue" in router
    assert "{ path: '/sem/plans', redirect: '/manage/campaigns' }" in router
    assert "{ path: '/admin/internal', redirect: '/settings/accounts' }" in router


def test_negative_rows_are_deduplicated_before_display():
    backend = _read("app/api/negatives.py")
    frontend = _read("frontend/src/views/optimize/NegativeWordsView.vue")
    assert "seen_items" in backend
    assert "dedupeCandidatePayload" in frontend
