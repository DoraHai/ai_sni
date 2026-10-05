"""Monthly report API scoping, PDF response and template lifecycle."""
import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api import seo_monthly_report as api
from app.models.module_workspace import SeoSite
from app.models.seo_monthly_report import SeoSiteReportTemplate
from app.models.tenant import Tenant
from app.security.auth import AuthContext


@compiles(JSONB, "sqlite")
def _jsonb(_type, _compiler, **_kwargs): return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint(_type, _compiler, **_kwargs): return "INTEGER"


class Adapter:
    def __init__(self, db): self.db = db
    async def get(self, *args): return self.db.get(*args)
    async def scalars(self, query): return self.db.scalars(query)
    async def execute(self, query): return self.db.execute(query)
    async def commit(self): self.db.commit()
    async def delete(self, row): self.db.delete(row)
    def add(self, row): self.db.add(row)


def client(permission="edit"):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        for model in (Tenant, SeoSite, SeoSiteReportTemplate):
            conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
    with Session(engine) as db:
        db.add_all([Tenant(id=4, name="客户"),
            SeoSite(id=2, tenant_id=4, tenant_module_id=1, name="测试站", domain="example.com", canonical_domain="example.com", status="active"),
            SeoSite(id=3, tenant_id=5, tenant_module_id=2, name="其他站", domain="other.com", canonical_domain="other.com", status="active")])
        db.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/seo")
    async def auth(): return AuthContext(9, "tester", "client", 4, {"seo.site": permission})
    async def session():
        with Session(engine, expire_on_commit=False) as db:
            yield Adapter(db)
    app.dependency_overrides[api.require_scoped_auth] = auth
    app.dependency_overrides[api.get_session] = session
    return TestClient(app)


def test_template_scope_and_lifecycle():
    http = client("view")
    path = "/api/v1/seo/site/reports/monthly-template"
    params = {"tenant_id": 4, "site_id": 2}
    initial = http.get(path, params=params)
    assert initial.status_code == 200 and initial.json()["is_default"]
    assert http.get(path, params={**params, "site_id": 3}).status_code == 404
    assert http.put(path, json={**params, "sections": initial.json()["sections"]}).status_code == 403
    http = client()
    assert http.put(path, json={**params, "sections": []}).status_code == 422
    sections = initial.json()["sections"]
    sections[0]["title"] = "封皮"
    saved = http.put(path, json={**params, "sections": sections})
    assert saved.status_code == 200 and not saved.json()["is_default"]
    assert http.get(path, params=params).json()["sections"][0]["title"] == "封皮"
    assert http.delete(path, params=params).json()["is_default"]


def test_future_month_and_view_permission():
    path = "/api/v1/seo/site/reports/monthly"
    params = {"tenant_id": 4, "site_id": 2, "month": "2099-01"}
    assert client("view").get(path, params=params).status_code == 422
    assert client("none").get(path, params=params).status_code == 403
    assert client("view").get(path, params={**params, "site_id": 3}).status_code == 404


def test_pdf_bytes_and_missing_runtime(monkeypatch):
    # Empty result sets exercise the complete endpoint without provider calls.
    class Result:
        def all(self): return []
    class EmptyAdapter(Adapter):
        async def scalars(self, query): return Result()
        async def execute(self, query): return Result()
        async def get(self, model, ident):
            if model is SeoSite: return SimpleNamespace(id=2, tenant_id=4, name="测试站")
            if model is Tenant: return SimpleNamespace(name="客户")
            return None
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/seo")
    async def auth(): return AuthContext(9, "tester", "client", 4, {"seo.site": "view"})
    async def session(): yield EmptyAdapter(None)
    app.dependency_overrides[api.require_scoped_auth] = auth
    app.dependency_overrides[api.get_session] = session
    http = TestClient(app)
    options_seen = {}
    class Page:
        async def set_content(self, html, **kwargs):
            assert "本月流量" in html
        async def pdf(self, **kwargs):
            assert kwargs["format"] == "A4" and kwargs["print_background"]
            return b"%PDF-1.7 fake"
    class Context:
        async def route(self, *_args): pass
        async def new_page(self): return Page()
        async def close(self): pass
    class Browser:
        async def new_context(self, **kwargs):
            options_seen.update(kwargs)
            return Context()
        async def close(self): pass
    class Chromium:
        async def launch(self, **kwargs): return Browser()
    class Factory:
        chromium = Chromium()
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
    monkeypatch.setattr(api, "_playwright_factory", Factory)
    params = {"tenant_id": 4, "site_id": 2, "month": "2026-09"}
    response = http.get("/api/v1/seo/site/reports/monthly", params=params)
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert options_seen["offline"] is True and options_seen["java_script_enabled"] is False
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, no-store"
    async def missing(*_args, **_kwargs): raise FileNotFoundError("chromium")
    monkeypatch.setattr(api, "render_report_pdf", missing)
    failed = http.get("/api/v1/seo/site/reports/monthly", params=params)
    assert failed.status_code == 503 and "未安装浏览器" in failed.json()["detail"]["message"]
    async def timed_out(*_args, **_kwargs): raise asyncio.TimeoutError()
    monkeypatch.setattr(api, "render_report_pdf", timed_out)
    timeout = http.get("/api/v1/seo/site/reports/monthly", params=params)
    assert timeout.status_code == 503 and "生成超时" in timeout.json()["detail"]["message"]
