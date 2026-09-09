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

from app.api import dashboard, keywords, search_terms
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
    for router in (dashboard.router, keywords.router, search_terms.router):
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
    assert detail["keyword_assets"][0]["keyword"] == "工业泵选型"
    assert detail["phone_button_clicks"]["status"] == "unavailable"
    assert len(detail["dimensions"]["region"]["rows"]) == 4
    assert len(detail["dimensions"]["schedule"]["cells"]) == 168
    assert any(cell["status"] == "observed" for cell in detail["dimensions"]["schedule"]["cells"])


def test_demo_search_terms_filter_pagination_and_account_scope(demo_client):
    response = demo_client.get(
        "/api/v1/search-terms/cockpit",
        params={"tenant_id": 16, "baidu_account_id": 160001, "q": "泵", "page": 1, "page_size": 2},
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
