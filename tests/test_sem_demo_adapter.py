"""Embedded SEM demo adapter tests; no configured DB, network, or writes."""
import os
from datetime import date

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:1/test")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
os.environ.setdefault("ADMIN_API_KEY", "local-test-only")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import alerts, dashboard, insights, keywords, manage, operations, search_terms, structure, suggestions, writeback
from app.database import get_session
from app.security import auth
from app.security.auth import AuthContext
from app.sem_demo_adapter import DEMO_REVISION, is_demo_read


class NoDataSession:
    def __getattr__(self, name):
        raise AssertionError(f"demo read touched session.{name}")


@pytest.fixture
def demo_client(monkeypatch):
    app = FastAPI()
    for router in (
        dashboard.router, insights.router, keywords.router, search_terms.router,
        structure.router, suggestions.router, writeback.router, manage.router,
        alerts.router, operations.router,
    ):
        app.include_router(router)
    ctx = AuthContext(
        5016,
        "workbench_test_readonly",
        "readonly",
        16,
        {
            "monitor.dashboard": "view",
            "optimize.keywords": "view",
            "optimize.searchterms": "view",
            "manage.campaigns": "view",
            "manage.adgroups": "view",
            "manage.account": "view",
            "monitor.alerts": "view",
            "verify.adjustments": "view",
        },
    )
    session = NoDataSession()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[auth.require_auth] = lambda: ctx
    async def no_module_side_effect(*_args):
        return None
    monkeypatch.setattr(auth, "ensure_module_access", no_module_side_effect)
    monkeypatch.setattr(auth, "ensure_sem_identity_access", no_module_side_effect)
    with TestClient(app) as client:
        yield client


def test_demo_report_is_versioned_full_and_truthful(demo_client):
    response = demo_client.get(
        "/api/v1/dashboard/cockpit",
        params={"tenant_id": 16, "start_date": "2026-09-04", "end_date": "2026-09-10"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["is_demo"] is True and data["demo_revision"] == DEMO_REVISION
    assert data["read_only"] is True and data["demo_policy"] == {
        "data_origin": "embedded_synthetic_fixture",
        "external_calls": False,
        "persistent_writes": False,
        "actions": "simulation_only",
    }
    assert data["account_scope"]["configured_account_ids"] == [160001, 160002]
    assert len(data["accounts"]) == 2 and len(data["devices"]) == 2
    by_date = {row["date"]: row for row in data["trend"]}
    assert by_date["2026-09-06"]["status"] == "no_data"
    assert by_date["2026-09-06"]["cost"] is None
    assert by_date["2026-09-07"]["status"] == "observed"
    assert by_date["2026-09-07"]["cost"] == 0
    assert data["coverage"]["missing_dates"] == ["2026-09-06"]
    assert "有效咨询" in data["unavailable"]["phone_button_clicks"]


def test_demo_keywords_detail_dimensions_and_phone_boundary(demo_client):
    params = {"tenant_id": 16, "start_date": "2026-09-04", "end_date": "2026-09-10"}
    listing = demo_client.get(
        "/api/v1/keywords/cockpit", params={**params, "page": 1, "page_size": 20}
    ).json()
    assert listing["total"] == 6
    assert listing["association_summary"]["counts"] == {
        "matched": 5, "account_mismatch": 0, "no_report": 1
    }
    assert all(item["phone_button_clicks"]["status"] in {"unavailable", "no_data"}
               for item in listing["items"])

    detail = demo_client.get(
        "/api/v1/keywords/cockpit/160100001", params=params
    ).json()
    assert detail["keyword_assets"][0]["keyword"] == "TIGER粉末涂料"
    assert detail["phone_button_clicks"]["status"] == "unavailable"
    assert len(detail["dimensions"]["region"]["rows"]) == 4
    assert len(detail["dimensions"]["schedule"]["cells"]) == 168
    assert any(cell["status"] == "observed" for cell in detail["dimensions"]["schedule"]["cells"])


def test_demo_search_terms_filter_pagination_and_account_scope(demo_client):
    response = demo_client.get(
        "/api/v1/search-terms/cockpit",
        params={"tenant_id": 16, "baidu_account_id": 160001, "q": "粉末", "page": 1, "page_size": 2},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 3 and len(data["items"]) == 2
    assert data["account_scope"]["mode"] == "single"
    assert data["account_scope"]["observed_account_ids"] == [160001]
    assert sum(item["stored_rows"] for item in data["windows"]) == data["total"]
    assert all(item["baidu_account_id"] == 160001 for item in data["items"])


def test_demo_scope_requires_exact_non_admin_identity_and_tenant(demo_client):
    assert is_demo_read(AuthContext(1, "workbench_test_readonly", "r", 16, {}), 16)
    assert not is_demo_read(AuthContext(1, "another_user", "r", 16, {}), 16)
    assert not is_demo_read(AuthContext(1, "workbench_test_readonly", "r", None, {}, True), 16)
    assert demo_client.get(
        "/api/v1/dashboard/cockpit",
        params={"tenant_id": 15, "start_date": date(2026, 9, 4), "end_date": date(2026, 9, 10)},
    ).status_code == 403
    assert demo_client.get(
        "/api/v1/dashboard/cockpit",
        params={"tenant_id": 16, "start_date": "2026-09-04", "end_date": "2026-09-10",
                "baidu_account_id": 999999},
    ).status_code == 404


def test_classic_dashboard_and_insight_use_demo_without_session_or_ai(demo_client):
    dashboard_response = demo_client.get(
        "/api/v1/dashboard/today",
        params={"tenant_id": 16, "start_date": "2026-09-04", "end_date": "2026-09-10"},
    )
    assert dashboard_response.status_code == 200, dashboard_response.text
    data = dashboard_response.json()
    assert data["is_demo"] is True and data["read_only"] is True
    assert data["tenant"]["id"] == 16
    assert data["connection"]["asset_counts"]["keywords"] == 6
    assert data["account"]["status"] == "error"
    assert data["freshness"]["missing_dates"] == ["2026-09-06"]

    insight_response = demo_client.get(
        "/api/v1/dashboard/insight",
        params={"tenant_id": 16, "target_date": "2026-09-10", "force": True},
    )
    assert insight_response.status_code == 200, insight_response.text
    insight = insight_response.json()
    assert insight["is_demo"] is True and insight["enabled"] is False
    assert insight["force_ignored"] is True
    assert "不会生成 AI" in insight["reason"]


def test_classic_keyword_page_reads_are_complete_and_writeback_disabled(demo_client):
    listing = demo_client.get(
        "/api/v1/keywords",
        params={"tenant_id": 16, "page": 1, "page_size": 20},
    )
    assert listing.status_code == 200, listing.text
    data = listing.json()
    assert data["is_demo"] is True and data["total"] == 6
    assert data["totals"] == {
        "campaigns": 4, "adgroups": 4, "keywords": 6, "serving_now": 5,
        "current_slot": "演示时段", "last_synced_at": "2026-09-10T00:35:00+00:00",
    }
    assert data["keywords"][0]["metrics_7d"]["ctr"] >= 0

    detail = demo_client.get(
        "/api/v1/keywords/160100001", params={"tenant_id": 16}
    )
    assert detail.status_code == 200, detail.text
    detail_data = detail.json()
    assert detail_data["is_demo"] is True
    assert detail_data["keyword"]["keyword"] == "TIGER粉末涂料"
    assert len(detail_data["schedule_analysis"]["cells"]) == 168

    campaigns = demo_client.get("/api/v1/structure/campaigns", params={"tenant_id": 16}).json()
    adgroups = demo_client.get("/api/v1/structure/adgroups", params={"tenant_id": 16}).json()
    assert campaigns["total"] == 4 and campaigns["is_demo"] is True
    assert adgroups["total"] == 4 and adgroups["is_demo"] is True
    assert demo_client.get("/api/v1/suggestions", params={"tenant_id": 16}).json()["suggestions"] == []
    assert demo_client.get("/api/v1/suggestions/assignees", params={"tenant_id": 16}).json()["assignees"] == []
    mode = demo_client.get("/api/v1/writeback/mode", params={"tenant_id": 16}).json()
    assert mode["mode"] == "disabled" and mode["writeback_enabled"] is False


def test_classic_search_term_page_reads_embedded_rows(demo_client):
    response = demo_client.get(
        "/api/v1/search-terms",
        params={"tenant_id": 16, "status": "not_added", "page": 1, "page_size": 50},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["is_demo"] is True
    assert data["total"] == 4
    assert len(data["search_terms"]) == 4
    assert data["window"]["start"] == "2026-09-04"
    assert all(row["status_label"] == "未加成关键词" for row in data["search_terms"])


def test_demo_manage_reads_never_touch_database_or_realtime_account(demo_client):
    account = demo_client.get("/api/v1/manage/account-budget", params={
        "tenant_id": 16, "baidu_account_id": 160001,
    })
    assert account.status_code == 200, account.text
    assert account.json()["demo_policy"]["external_calls"] is False
    assert account.json()["baidu_account_name"] == "TIGER品牌推广（演示）"

    campaigns = demo_client.get("/api/v1/manage/campaigns", params={
        "tenant_id": 16, "baidu_account_id": 160002,
    }).json()
    assert campaigns["is_demo"] is True and campaigns["total"] == 2
    assert {row["baidu_account_id"] for row in campaigns["campaigns"]} == {160002}
    assert {row["baidu_account_name"] for row in campaigns["campaigns"]} == {"TIGER行业推广（演示）"}

    adgroups = demo_client.get("/api/v1/manage/adgroups", params={
        "tenant_id": 16, "campaign_id": 160201,
    }).json()
    assert adgroups["is_demo"] is True and adgroups["total"] == 1


def test_demo_alerts_and_all_adjustment_tabs_are_embedded_reads(demo_client):
    alerts_data = demo_client.get("/api/v1/alerts", params={"tenant_id": 16, "status": "all"}).json()
    assert alerts_data["is_demo"] is True and len(alerts_data["alerts"]) == 2
    assert alerts_data["total_open"] == 1

    operations_data = demo_client.get("/api/v1/operation-records", params={
        "tenant_id": 16, "over_limit": True,
    }).json()
    assert operations_data["is_demo"] is True and operations_data["total"] == 1
    assert operations_data["records"][0]["change"]["over_limit"] is True

    writebacks = demo_client.get("/api/v1/writeback", params={"tenant_id": 16}).json()
    approvals = demo_client.get("/api/v1/writeback/approvals", params={"tenant_id": 16}).json()
    actions = demo_client.get("/api/v1/search-terms/actions", params={"tenant_id": 16}).json()
    assert writebacks["is_demo"] is True and writebacks["writebacks"][0]["dry_run"] is True
    assert approvals["is_demo"] is True and approvals["approvals"][0]["status"] == "consumed"
    assert actions["is_demo"] is True and actions["actions"][0]["status"] == "dry_run"


def test_demo_visible_copy_uses_tiger_powder_coating_branding(demo_client):
    responses = [
        demo_client.get("/api/v1/keywords", params={"tenant_id": 16, "page": 1, "page_size": 20}).json(),
        demo_client.get("/api/v1/search-terms", params={"tenant_id": 16, "page": 1, "page_size": 50}).json(),
        demo_client.get("/api/v1/manage/campaigns", params={"tenant_id": 16}).json(),
        demo_client.get("/api/v1/manage/adgroups", params={"tenant_id": 16}).json(),
        demo_client.get("/api/v1/alerts", params={"tenant_id": 16, "status": "all"}).json(),
        demo_client.get("/api/v1/operation-records", params={"tenant_id": 16, "page": 1, "page_size": 20}).json(),
        demo_client.get("/api/v1/writeback", params={"tenant_id": 16}).json(),
        demo_client.get("/api/v1/search-terms/actions", params={"tenant_id": 16}).json(),
    ]
    visible_copy = str(responses)
    assert "TIGER粉末涂料" in visible_copy
    assert "表面技术解决方案" in visible_copy
    assert "TIGER品牌推广（演示）" in visible_copy
    assert "TIGER行业推广（演示）" in visible_copy
    assert not any(legacy in visible_copy for legacy in ("工业泵", "水泵", "泵站", "化工泵", "污水提升泵"))
