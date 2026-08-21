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


def test_sem_frontend_labels_write_actions_as_pending_in_readonly_mode():
    capabilities = _read("frontend/src/constants/semCapabilities.js")
    app_shell = _read("frontend/src/App.vue")
    workbench = _read("frontend/src/views/optimize/KeywordWorkbenchView.vue")

    assert "SEM_WRITEBACK_ENABLED = false" in capabilities
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
