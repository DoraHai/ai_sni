import json
import os
import asyncio
from datetime import datetime

import pytest
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@primary-db/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00+00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.security.auth import AuthContext
from app.seo_static_demo import (
    DEMO_DATASET_VERSION,
    DEMO_SITE_ID,
    DEMO_TENANT_ID,
    DEMO_USERNAME,
    load_fixture,
    resolve_demo_response,
    serve_static_demo,
)


def query(**values):
    return {key: str(value) for key, value in values.items() if value is not None}


def request(path: str, *, method: str = "GET", token: str = "demo", body=None):
    raw = json.dumps(body or {}).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    path_only, _, query_string = path.partition("?")
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path_only,
        "raw_path": path_only.encode(),
        "query_string": query_string.encode(),
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 443),
    }
    return Request(scope, receive)


def demo_context(**changes):
    values = {
        "user_id": 16001,
        "username": DEMO_USERNAME,
        "role_name": "只读演示",
        "tenant_id": DEMO_TENANT_ID,
        "permissions": {
            "seo.assets": "view",
            "seo.dashboard": "view",
            "seo.alerts": "view",
            "seo.content": "view",
            "seo.site": "view",
            "seo.keywords": "view",
            "seo.links": "view",
            "seo.competitors": "view",
        },
    }
    values.update(changes)
    return AuthContext(**values)


def test_fixture_is_versioned_scoped_and_has_valid_dates():
    fixture = load_fixture()
    assert fixture["dataset"]["version"] == DEMO_DATASET_VERSION
    assert fixture["dataset"]["tenant_id"] == DEMO_TENANT_ID
    assert fixture["dataset"]["site_id"] == DEMO_SITE_ID
    assert len(fixture["pages"]) == 26
    assert all(row["tenant_id"] == DEMO_TENANT_ID for row in fixture["pages"])
    for section in ("pages", "contents", "publications", "rankings"):
        for row in fixture[section]:
            for key in ("updated_at", "published_at", "checked_at", "last_checked_at"):
                if row.get(key):
                    datetime.fromisoformat(row[key])


@pytest.mark.parametrize(
    ("path", "key", "expected"),
    [
        ("/api/v1/seo/content-assets", "total", 4),
        ("/api/v1/seo/content-distribution/publications", "total", 4),
        ("/api/v1/seo/site-pages", "total", 26),
        ("/api/v1/seo/keywords", "total", 4),
        ("/api/v1/seo/rank-serp/results", "total", 12),
        ("/api/v1/seo/content-distribution/connections", "total", 0),
        ("/api/v1/seo/content-distribution/variants", "total", 0),
    ],
)
def test_list_routes_keep_current_shapes(path, key, expected):
    result = resolve_demo_response("GET", path, query(tenant_id=16, site_id=1601))
    assert result.status_code == 200
    assert result.payload[key] == expected
    assert result.payload["demo_meta"]["dataset_version"] == DEMO_DATASET_VERSION


def test_filters_and_pagination_are_deterministic():
    contents = resolve_demo_response(
        "GET",
        "/api/v1/seo/content-assets",
        query(tenant_id=16, site_id=1601, status="published", page=1, page_size=1),
    ).payload
    assert contents["total"] == 1
    assert len(contents["items"]) == 1
    assert contents["items"][0]["status"] == "published"

    drafts = resolve_demo_response(
        "GET",
        "/api/v1/seo/content-assets",
        query(tenant_id=16, site_id=1601, status="planned,drafting"),
    ).payload
    assert [row["id"] for row in drafts["items"]] == [1602004]

    pages = resolve_demo_response(
        "GET", "/api/v1/seo/site-pages", query(tenant_id=16, site_id=1601, q="应用行业")
    ).payload
    assert pages["total"] == 1
    assert pages["items"][0]["id"] == 1601002


def test_site_selectors_keep_existing_response_keys():
    sites = resolve_demo_response("GET", "/api/v1/seo/sites", query(tenant_id=16)).payload
    assert sites["sites"][0]["id"] == 1601
    workbench = resolve_demo_response(
        "GET", "/api/v1/seo/workbench/sites", query(tenant_id=16)
    ).payload
    assert workbench["tenant_id"] == 16
    assert workbench["sites"] == [
        {
            "id": 1601,
            "name": "TIGER 老虎中国官网（演示）",
            "domain": "https://www.tiger-coatings.cn/",
            "status": "active",
        }
    ]


def test_overview_keeps_dashboard_shape_and_separates_external_metrics():
    overview = resolve_demo_response(
        "GET", "/api/v1/seo/overview", query(tenant_id=16, site_id=1601)
    ).payload
    assert overview["stats"]["pages"] == 26
    assert overview["stats"]["keywords"] == 4
    assert overview["crawl"]["source"] == "public_preflight"
    assert overview["metrics"]["verified_traffic"]["status"] == "not_configured"
    assert overview["search_clicks"]["available"] is False
    assert len(overview["collection_status"]) == 5


def test_detail_review_and_attempt_clicks_return_linked_records():
    page = resolve_demo_response(
        "GET", "/api/v1/seo/site-pages/1601001/detail", query(tenant_id=16)
    )
    assert page.status_code == 200
    assert page.payload["latest_snapshot"]["source"] == "public_preflight"
    assert page.payload["latest_snapshot"]["site_id"] == DEMO_SITE_ID
    assert page.payload["latest_snapshot"]["fetch_error"] is None
    assert page.payload["page"]["id"] == 1601001
    assert page.payload["page"]["diagnostic"]["assessment_state"] == "assessed"

    keyword = resolve_demo_response(
        "GET", "/api/v1/seo/keywords/1604001", query(tenant_id=16)
    )
    assert len(keyword.payload["rank_history"]) == 3
    assert all(row["synthetic"] for row in keyword.payload["rank_history"])

    review = resolve_demo_response(
        "GET", "/api/v1/seo/content-assets/1602001/review-history", query(tenant_id=16)
    )
    assert [row["action"] for row in review.payload["items"]] == ["submitted", "approved"]

    attempts = resolve_demo_response(
        "GET",
        "/api/v1/seo/content-distribution/publications/1603004/attempts",
        query(tenant_id=16),
    )
    assert attempts.payload["items"][0]["status"] == "failed"


def test_site_pages_match_workbench_readonly_contract():
    result = resolve_demo_response(
        "GET",
        "/api/v1/seo/site-pages",
        query(tenant_id=16, site_id=1601, page=1, page_size=50),
    )
    assert result.status_code == 200
    payload = result.payload
    assert payload["total"] == 26
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    assert isinstance(payload["stats"], dict)
    for row in payload["items"]:
        assert row["tenant_id"] == DEMO_TENANT_ID
        assert row["site_id"] == DEMO_SITE_ID
        assert row["url"]
        assert row["http_status"] is None or row["http_status"] >= 0
        assert row["diagnostic"]["assessment_state"] in {"assessed", "unavailable"}
        assert row["diagnostic"]["checked_at"] == row["last_checked_at"]
        assert row["diagnostic"]["http_status"] is None or row["diagnostic"]["http_status"] >= 0

    evidence = resolve_demo_response(
        "GET",
        "/api/v1/seo/site-pages/image-evidence",
        query(tenant_id=16, site_id=1601, page_id=1601001),
    ).payload
    assert evidence["url"] == payload["items"][0]["url"]
    assert evidence["snapshot_id"] == 1701001
    assert evidence["fetched_at"] == payload["items"][0]["last_checked_at"]
    assert evidence["fetch_error"] is None
    assert evidence["evidence"] is None

    stale = resolve_demo_response(
        "GET",
        "/api/v1/seo/site-pages/image-evidence",
        query(tenant_id=16, site_id=1601, page_id=1601001, snapshot_id=1),
    )
    assert stale.status_code == 404


def test_search_clicks_are_explicitly_unavailable_not_fabricated():
    result = resolve_demo_response(
        "GET", "/api/v1/seo/traffic/gsc", query(tenant_id=16, site_id=1601)
    )
    assert result.payload["available"] is False
    assert result.payload["platform"] is None
    assert result.payload["items"] == []
    assert result.payload["reason_code"] == "search_console_not_connected"


@pytest.mark.parametrize(
    ("path", "assertion"),
    [
        ("/api/v1/seo/overview/task-center", lambda payload: payload["total"] == 2),
        ("/api/v1/seo/overview/customer-verification-queue", lambda payload: payload["total"] == 3 and payload["read_only"] is True),
        ("/api/v1/seo/alerts", lambda payload: payload["total"] == 4 and payload["high"] == 2),
        ("/api/v1/seo/rank-serp/brand-profile", lambda payload: payload["ranking_ready"] is True),
        ("/api/v1/seo/rank-serp/brand-assets", lambda payload: payload["total"] == 1),
        ("/api/v1/seo/internal-links", lambda payload: payload["stats"]["links"] == 5),
        ("/api/v1/seo/backlinks", lambda payload: payload["total"] == 3),
        ("/api/v1/seo/backlinks/discovery-sources", lambda payload: payload["total"] == 2),
        ("/api/v1/seo/backlinks/analysis", lambda payload: payload["referring_domains"] == 1),
        ("/api/v1/seo/backlinks/index-status", lambda payload: payload["configured"] is False),
        ("/api/v1/seo/backlinks/opportunities", lambda payload: payload["result"]["state"] == "completed"),
        ("/api/v1/seo/tasks", lambda payload: len(payload) == 1),
        ("/api/v1/seo/backlinks/outcomes", lambda payload: len(payload["items"]) == 2),
        ("/api/v1/seo/competitors", lambda payload: len(payload["items"]) == 2),
        ("/api/v1/seo/competitors/rankings", lambda payload: len(payload["items"]) == 4),
    ],
)
def test_enabled_menu_pages_have_deterministic_demo_read_models(path, assertion):
    result = resolve_demo_response("GET", path, query(tenant_id=16, site_id=1601))
    assert result.status_code == 200
    assert assertion(result.payload)
    if isinstance(result.payload, dict) and path != "/api/v1/seo/tasks":
        assert result.payload["demo_meta"]["dataset_version"] == DEMO_DATASET_VERSION


def test_demo_records_are_marked_synthetic_and_external_calls_stay_disabled():
    fixture = load_fixture()
    for section in ("alerts", "backlinks", "competitors", "competitor_events", "task_runs"):
        assert fixture[section]
        assert all(row["synthetic"] is True for row in fixture[section])
    provider = resolve_demo_response(
        "GET", "/api/v1/seo/backlinks/index-status", query(tenant_id=16, site_id=1601)
    ).payload
    assert provider["status"] == "not_connected"
    assert provider["configured"] is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/seo/content-assets/1602003/review",
        "/api/v1/seo/site-pages/1601001/audit",
        "/api/v1/seo/content-distribution/publications/1603004/retry",
        "/api/v1/seo/overview/collect-metrics",
    ],
)
def test_demo_actions_are_explicit_non_persistent_simulations(path):
    result = resolve_demo_response(
        "POST", path, query(tenant_id=16), {"tenant_id": 16, "site_id": 1601}
    )
    assert result.status_code == 200
    assert result.payload["simulated"] is True
    assert result.payload["persisted"] is False
    assert result.payload["side_effects"] == []


def test_middleware_intercepts_only_exact_demo_identity(monkeypatch):
    async def approved(_request):
        return demo_context()

    monkeypatch.setattr("app.seo_static_demo._authenticate_demo_request", approved)
    response = asyncio.run(serve_static_demo(
        request("/api/v1/seo/overview?tenant_id=16&site_id=1601")
    ))
    assert response is not None and response.status_code == 200
    payload = json.loads(response.body)
    assert payload["site"]["id"] == 1601
    assert payload["demo_meta"]["persisted"] is False

    omitted = asyncio.run(serve_static_demo(request("/api/v1/seo/overview?site_id=1601")))
    assert omitted is not None and omitted.status_code == 200


def test_other_identity_uses_original_production_route(monkeypatch):
    async def wrong_identity(_request):
        return demo_context(username="another_user")

    monkeypatch.setattr("app.seo_static_demo._authenticate_demo_request", wrong_identity)
    response = asyncio.run(serve_static_demo(request("/api/v1/seo/overview?tenant_id=16")))
    assert response is None


def test_demo_identity_still_requires_endpoint_permission(monkeypatch):

    async def no_permission(_request):
        return demo_context(permissions={})

    monkeypatch.setattr("app.seo_static_demo._authenticate_demo_request", no_permission)
    response = asyncio.run(serve_static_demo(request("/api/v1/seo/overview?tenant_id=16")))
    assert response.status_code == 403
    assert json.loads(response.body)["code"] == "seo_static_demo_permission_denied"


def test_middleware_enforces_exact_site_and_endpoint_permission(monkeypatch):
    async def approved(_request):
        return demo_context(permissions={"seo.dashboard": "view"})

    monkeypatch.setattr("app.seo_static_demo._authenticate_demo_request", approved)
    wrong_site = asyncio.run(
        serve_static_demo(request("/api/v1/seo/overview?tenant_id=16&site_id=1"))
    )
    assert wrong_site.status_code == 404

    content = asyncio.run(
        serve_static_demo(request("/api/v1/seo/content-assets?tenant_id=16&site_id=1601"))
    )
    assert content.status_code == 403


def test_demo_identity_cannot_bypass_scope_with_malformed_or_conflicting_tenant(monkeypatch):
    async def approved(_request):
        return demo_context()

    monkeypatch.setattr("app.seo_static_demo._authenticate_demo_request", approved)
    malformed = asyncio.run(
        serve_static_demo(request("/api/v1/seo/overview?tenant_id=16.0"))
    )
    assert malformed.status_code == 422
    conflict = asyncio.run(
        serve_static_demo(
            request(
                "/api/v1/seo/overview?tenant_id=16",
                method="POST",
                body={"tenant_id": 15},
            )
        )
    )
    assert conflict.status_code == 422

    tampered = asyncio.run(
        serve_static_demo(request("/api/v1/seo/overview?tenant_id=15&site_id=1601"))
    )
    assert tampered.status_code == 403


def test_superadmin_never_enters_static_demo(monkeypatch):
    async def superadmin(_request):
        return demo_context(is_superadmin=True)

    monkeypatch.setattr("app.seo_static_demo._authenticate_demo_request", superadmin)
    assert asyncio.run(
        serve_static_demo(request("/api/v1/seo/overview?tenant_id=16&site_id=1601"))
    ) is None


def test_unknown_tenant16_endpoint_fails_closed():
    result = resolve_demo_response(
        "GET", "/api/v1/seo/qa/questions", query(tenant_id=16, site_id=1601)
    )
    assert result.status_code == 404
    assert result.payload["code"] == "seo_static_demo_endpoint_unavailable"
