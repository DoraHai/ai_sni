"""Permission and persistence semantics for the analytics API."""
import asyncio
import json
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api import seo_site_analytics as api
from app.api.seo_site_analytics import scope, monthly_payload
from app.seo_site_analytics import AnalyticsError, ProviderClient, pull_site_month, secrets_of
from app.models.module_workspace import SeoSite
from app.models.seo_site_analytics import SeoSiteAnalyticsSource, SeoSiteAnalyticsMonthly, SeoSiteExportTemplate
from app.security.auth import AuthContext


def actor(tenant=4, permission="view"):
    return AuthContext(9, "tester", "client", tenant, {"seo.site": permission})


class Session:
    async def get(self, model, ident):
        assert model is SeoSite
        return SimpleNamespace(id=ident, tenant_id=5 if ident == 3 else 4)


def test_site_view_edit_and_cross_tenant():
    async def run():
        assert (await scope(Session(), actor(), 4, 2)).id == 2
        with pytest.raises(Exception) as denied:
            await scope(Session(), actor(), 4, 2, True)
        assert denied.value.status_code == 403
        with pytest.raises(Exception) as foreign:
            await scope(Session(), actor(permission="edit"), 4, 3, True)
        assert foreign.value.status_code == 404
    asyncio.run(run())


def test_failed_pull_retains_prior_success_payload():
    row = SimpleNamespace(source="ga4", month="2026-09", uv=10, pv=20, status="ok",
        error_code=None, error_message=None, fetched_at=None, raw_meta={}, last_error_code="provider_error",
        last_error_message="连接失败", last_attempt_at=None)
    data = monthly_payload(row)
    assert data["uv"] == 10 and data["pv"] == 20
    assert data["status"] == "ok" and data["last_error_code"] == "provider_error"


@compiles(JSONB, "sqlite")
def _jsonb(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


class Adapter:
    def __init__(self, db): self.db = db
    async def get(self, *args): return self.db.get(*args)
    async def scalar(self, query): return self.db.scalar(query)
    async def scalars(self, query): return self.db.scalars(query)
    async def commit(self): self.db.commit()
    async def delete(self, row): self.db.delete(row)
    def add(self, row): self.db.add(row)


def client(permission="edit"):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        for model in (SeoSite, SeoSiteAnalyticsSource, SeoSiteAnalyticsMonthly, SeoSiteExportTemplate):
            conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
    with DbSession(engine) as db:
        db.add_all([SeoSite(id=2, tenant_id=4, tenant_module_id=1, name="测试站", domain="example.com", canonical_domain="example.com", status="active"),
                    SeoSite(id=3, tenant_id=5, tenant_module_id=2, name="其他站", domain="other.com", canonical_domain="other.com", status="active")])
        db.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/seo")
    async def auth(): return actor(permission=permission)
    async def session():
        with DbSession(engine, expire_on_commit=False) as db:
            yield Adapter(db)
    app.dependency_overrides[api.require_scoped_auth] = auth
    app.dependency_overrides[api.get_session] = session
    result = TestClient(app)
    result.engine = engine
    return result


def test_source_api_masked_keep_existing_and_site_permissions(monkeypatch):
    http = client()
    path = "/api/v1/seo/site/analytics-sources"
    payload = {"tenant_id": 4, "site_id": 2, "source": "baidu_tongji",
        "config": {"mode": "account", "tongji_site_id": "123", "api_key": "public"},
        "secrets": {"secret_key": "never-return-this", "refresh_token": "another-secret"}}
    response = http.put(path, json=payload)
    assert response.status_code == 200, response.text
    assert "never-return-this" not in response.text and "another-secret" not in response.text
    assert response.json()["has_secret_key"] is True
    response = http.put(path, json={**payload, "secrets": {"secret_key": ""}})
    assert response.status_code == 200 and response.json()["has_secret_key"] is True
    response = http.get(path, params={"tenant_id": 4, "site_id": 2})
    assert response.status_code == 200 and "never-return-this" not in response.text
    assert http.put(path, json={**payload, "site_id": 3}).status_code == 404
    assert client("view").put(path, json=payload).status_code == 403
    assert client("view").get(path, params={"tenant_id": 4, "site_id": 2}).status_code == 200
    async def rejected(*_args, **_kwargs):
        raise AnalyticsError("baidu_site_missing", "该百度统计账号下找不到站点ID 123")
    monkeypatch.setattr(api, "fetch_provider", rejected)
    failed = http.post(path + "/baidu_tongji/test", json={"tenant_id": 4, "site_id": 2})
    assert failed.status_code == 400
    assert failed.json()["detail"] == {"code": "baidu_site_missing", "message": "该百度统计账号下找不到站点ID 123"}
    saved = http.get(path, params={"tenant_id": 4, "site_id": 2}).json()["items"][0]
    assert saved["last_test_status"] == "failed" and saved["last_test_at"]


def test_template_api_validation_and_reset():
    http = client()
    path = "/api/v1/seo/site/publications/export-template"
    scope_params = {"tenant_id": 4, "site_id": 2}
    assert http.get(path, params=scope_params).json()["is_default"] is True
    assert http.put(path, json={**scope_params, "columns": []}).status_code == 422
    response = http.put(path, json={**scope_params, "columns": [{"key": "image_key", "title": "图片"}, {"key": "number", "title": "序号"}]})
    assert response.status_code == 200 and [x["key"] for x in response.json()["columns"]] == ["image_key", "number"]
    assert all("type" not in x for x in response.json()["columns"])
    assert all("type" not in x for x in http.get(path, params=scope_params).json()["columns"])
    assert all("type" in x for x in http.get(path, params=scope_params).json()["available"])
    with DbSession(http.engine) as db:
        row = db.get(SeoSiteExportTemplate, 2)
        row.columns = [{"key": "title", "title": "旧配置", "type": "image"}, {"key": "removed", "title": "旧列"}]
        db.commit()
    assert http.get(path, params=scope_params).json()["columns"] == [{"key": "title", "title": "旧配置"}]
    assert http.delete(path, params=scope_params).json()["is_default"] is True


def test_pull_failure_preserves_prior_ok_measurements():
    http = client()
    with DbSession(http.engine) as db:
        db.add(SeoSiteAnalyticsSource(tenant_id=4, site_id=2, source="ga4", enabled=True,
            config={"property_id": "123"}, secret_ciphertext=None))
        db.add(SeoSiteAnalyticsMonthly(tenant_id=4, site_id=2, source="ga4", month="2026-09",
            uv=12, pv=34, status="ok", raw_meta={"method": "runReport"}))
        db.commit()
    class FailingProvider:
        async def ga4(self, *_args, **_kwargs):
            raise AnalyticsError("ga4_forbidden", "没有查看权限")
    async def run():
        with DbSession(http.engine, expire_on_commit=False) as db:
            rows = await pull_site_month(Adapter(db), tenant_id=4, site_id=2, month="2026-09",
                fetched_by=9, provider=FailingProvider())
            assert rows[0].uv == 12 and rows[0].pv == 34 and rows[0].status == "ok"
            assert rows[0].last_error_code == "ga4_forbidden"
    asyncio.run(run())


def test_full_api_flow_never_serializes_secret_values(monkeypatch):
    http = client()
    path = "/api/v1/seo/site/analytics-sources"
    scope_params = {"tenant_id": 4, "site_id": 2}
    secret_key = "FAKE-SECRET-KEY-SENTINEL"
    refresh = "FAKE-REFRESH-SENTINEL"
    access = "FAKE-ACCESS-SENTINEL"
    code = "FAKE-CODE-SENTINEL"
    responses = []
    responses.append(http.put(path, json={**scope_params, "source": "baidu_tongji", "config": {
        "mode": "account", "tongji_site_id": "123", "api_key": "public-key"}, "secrets": {"secret_key": secret_key}}))
    async def token(self, grant_type, params):
        return {"access_token": access, "refresh_token": refresh, "expires_in": 3600}
    async def data(self, method, url, **kwargs):
        if "getSiteList" in url:
            return {"list": [{"site_id": 123, "domain": "example.com"}]}
        return {"result": {"fields": ["simple_date_title", "pv_count", "visitor_count"],
            "items": [[], [["2026-09", "19", "7"]]]}}
    monkeypatch.setattr(ProviderClient, "_baidu_token", token)
    monkeypatch.setattr(ProviderClient, "_json", data)
    responses.append(http.post(path + "/baidu_tongji/oauth/exchange", json={**scope_params, "code": code}))
    responses.append(http.post(path + "/baidu_tongji/test", json=scope_params))
    responses.append(http.post("/api/v1/seo/site/analytics/pull", json={**scope_params, "month": "2026-09"}))
    responses.append(http.get(path, params=scope_params))
    responses.append(http.get("/api/v1/seo/site/analytics/monthly", params={**scope_params, "from_month": "2026-09", "to_month": "2026-09"}))
    assert all(response.status_code == 200 for response in responses), [response.text for response in responses]
    serialized = json.dumps([response.json() for response in responses], ensure_ascii=False)
    assert all(value not in serialized for value in (secret_key, refresh, access, code))
    assert responses[2].json()["last_test_message"] == "连接成功"
    assert responses[3].json()["items"][0]["uv"] == 7
    with DbSession(http.engine) as db:
        row = db.query(SeoSiteAnalyticsMonthly).one()
        assert all(value not in json.dumps(row.raw_meta) for value in (secret_key, refresh, access, code))


def test_failed_connection_commits_rotated_refresh_token(monkeypatch):
    http = client()
    path = "/api/v1/seo/site/analytics-sources"
    scope_params = {"tenant_id": 4, "site_id": 2}
    http.put(path, json={**scope_params, "source": "baidu_tongji", "config": {
        "mode": "account", "tongji_site_id": "123", "api_key": "public-key"},
        "secrets": {"secret_key": "SECRET-SENTINEL", "refresh_token": "OLD-REFRESH-SENTINEL"}})
    async def token(self, grant_type, params):
        return {"access_token": "NEW-ACCESS-SENTINEL", "refresh_token": "NEW-REFRESH-SENTINEL", "expires_in": 3600}
    async def data(self, method, url, **kwargs):
        return {"error_code": 403, "error_msg": "permission denied NEW-ACCESS-SENTINEL"}
    monkeypatch.setattr(ProviderClient, "_baidu_token", token)
    monkeypatch.setattr(ProviderClient, "_json", data)
    failed = http.post(path + "/baidu_tongji/test", json=scope_params)
    assert failed.status_code == 400
    assert "NEW-ACCESS-SENTINEL" not in failed.text
    with DbSession(http.engine) as db:
        row = db.query(SeoSiteAnalyticsSource).one()
        assert secrets_of(row)["refresh_token"] == "NEW-REFRESH-SENTINEL"
        assert row.token_expires_at is not None


def test_ga4_connection_success_reports_yesterday_metrics(monkeypatch):
    http = client()
    scope_params = {"tenant_id": 4, "site_id": 2}
    with DbSession(http.engine) as db:
        db.add(SeoSiteAnalyticsSource(tenant_id=4, site_id=2, source="ga4", enabled=True,
            config={"property_id": "123"}, secret_ciphertext=None))
        db.commit()
    async def fetched(_provider, _row, start, end, *, test=False):
        assert test and start == end
        return 7, 19, {"method": "runReport"}
    monkeypatch.setattr(api, "fetch_provider", fetched)
    response = http.post("/api/v1/seo/site/analytics-sources/ga4/test", json=scope_params)
    assert response.status_code == 200
    assert response.json()["last_test_message"] == "连接成功，昨日 UV 7 / PV 19"
