from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_sem_shell_keeps_latest_workspace_identity_and_portal_entry():
    app = _source("frontend/src/App.vue")
    router = _source("frontend/src/router/index.js")

    assert "G-Snipers 获客指挥台" in app
    assert "统一产品门户" in app
    assert "SEM 智投平台" not in app
    assert "redirect: '/deal-sniper/portal'" in router


def test_sem_release_keeps_account_schedule_and_city_region_features():
    router = _source("frontend/src/router/index.js")
    campaign_view = _source("frontend/src/views/manage/CampaignManageView.vue")

    assert "path: '/sem/accounts'" in router
    assert "SemAccountsView.vue" in router
    assert "投放时段" in campaign_view
    assert "投放地域" in campaign_view
    assert "按省/市层级选择，可搜索" in campaign_view
