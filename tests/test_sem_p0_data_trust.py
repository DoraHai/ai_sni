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
    assert 'fixed="right"' in adgroups and "状态未同步" in adgroups


def test_negative_rows_are_deduplicated_before_display():
    backend = _read("app/api/negatives.py")
    frontend = _read("frontend/src/views/optimize/NegativeWordsView.vue")
    assert "seen_items" in backend
    assert "dedupeCandidatePayload" in frontend
