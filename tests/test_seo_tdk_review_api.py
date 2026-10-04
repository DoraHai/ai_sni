"""Mocked TDK review API authorization, export and template lifecycle."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from io import BytesIO
from docx import Document
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api import seo_tdk_review as api
from app.models.module_workspace import SeoSite
from app.models.seo import SeoInternalLink, SeoKeywordAsset, SeoSitePage
from app.models.seo_page_capture import SeoPageCapture
from app.models.seo_tdk_review import SeoSiteTdkReviewTemplate, SeoTdkReviewBatch
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
    async def commit(self): self.db.commit()
    async def flush(self): self.db.flush()
    async def delete(self, row): self.db.delete(row)
    def add(self, row): self.db.add(row)


def client(permission="edit"):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        for model in (Tenant, SeoSite, SeoSitePage, SeoKeywordAsset, SeoInternalLink,
                      SeoPageCapture, SeoTdkReviewBatch, SeoSiteTdkReviewTemplate):
            conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
    with Session(engine) as db:
        db.add_all([Tenant(id=4, name="客户"),
            SeoSite(id=2, tenant_id=4, tenant_module_id=1, name="测试站", domain="example.com", canonical_domain="example.com", status="active"),
            SeoSite(id=3, tenant_id=5, tenant_module_id=2, name="其他站", domain="other.com", canonical_domain="other.com", status="active"),
            SeoSitePage(id=11, tenant_id=4, site_id=2, url="https://example.com/a", title="页面 A", title_suggestion="建议 A", status="proposed"),
            SeoSitePage(id=12, tenant_id=5, site_id=3, url="https://other.com/b", title="页面 B", status="pending")])
        db.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/seo")
    async def auth(): return AuthContext(9, "tester", "client", 4, {"seo.site": permission})
    async def session():
        with Session(engine, expire_on_commit=False) as db:
            yield Adapter(db)
    app.dependency_overrides[api.require_scoped_auth] = auth
    app.dependency_overrides[api.get_session] = session
    return TestClient(app), engine


BASE = "/api/v1/seo/site/tdk-review"
PAYLOAD = {"tenant_id": 4, "site_id": 2, "page_ids": [11], "format": "docx"}


def test_permissions_scope_and_validation():
    http, _ = client("none")
    assert http.post(BASE + "/export", json=PAYLOAD).status_code == 403
    http, _ = client("view")
    assert http.post(BASE + "/export", json={**PAYLOAD, "trigger_capture": True}).status_code == 403
    assert http.post(BASE + "/export", json={**PAYLOAD, "page_ids": [12]}).status_code == 404
    assert http.post(BASE + "/export", json={**PAYLOAD, "site_id": 3}).status_code == 404
    assert http.post(BASE + "/export", json={**PAYLOAD, "page_ids": [11] * 51}).status_code == 200  # Deduped.
    assert http.post(BASE + "/export", json={**PAYLOAD, "page_ids": list(range(100, 151))}).status_code == 422


def test_docx_batch_and_template_lifecycle():
    http, engine = client("view")
    response = http.post(BASE + "/export", json=PAYLOAD)
    assert response.status_code == 200 and response.content.startswith(b"PK")
    assert response.headers["cache-control"] == "private, no-store"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    with Session(engine) as db:
        batch = db.query(SeoTdkReviewBatch).one()
        assert batch.page_ids == [11] and batch.status == "succeeded"
    initial = http.get(BASE + "/template", params={"tenant_id": 4, "site_id": 2})
    assert initial.status_code == 200 and initial.json()["is_default"]
    assert http.put(BASE + "/template", json={"tenant_id": 4, "site_id": 2, **{k: initial.json()[k] for k in ("sections", "columns")}}).status_code == 403
    http, _ = client("edit")
    template = http.get(BASE + "/template", params={"tenant_id": 4, "site_id": 2}).json()
    assert http.put(BASE + "/template", json={"tenant_id": 4, "site_id": 2, "sections": [], "columns": template["columns"]}).status_code == 422
    template["sections"][0]["title"] = "自定义页面信息"
    saved = http.put(BASE + "/template", json={"tenant_id": 4, "site_id": 2, "sections": template["sections"], "columns": template["columns"]})
    assert saved.status_code == 200
    assert http.get(BASE + "/template", params={"tenant_id": 4, "site_id": 2}).json()["sections"][0]["title"] == "自定义页面信息"
    assert http.delete(BASE + "/template", params={"tenant_id": 4, "site_id": 2}).json()["is_default"]


def test_edit_trigger_respects_disabled_capture_service(monkeypatch):
    http, _ = client("edit")
    original = api.get_settings
    class Disabled:
        def __init__(self, base):
            self.seo_page_capture_enabled = False
            self.seo_page_capture_storage_dir = base.seo_page_capture_storage_dir
    monkeypatch.setattr(api, "get_settings", lambda: Disabled(original()))
    response = http.post(BASE + "/export", json={**PAYLOAD, "trigger_capture": True})
    assert response.status_code == 200
    doc = Document(BytesIO(response.content))
    assert any("截图服务未启用" in paragraph.text for paragraph in doc.paragraphs)


def test_pdf_uses_isolated_renderer_and_runtime_failure(monkeypatch):
    http, _ = client("view")
    seen = {}
    class Page:
        async def set_content(self, html, **_kwargs): assert "页面 A" in html
        async def pdf(self, **kwargs):
            assert kwargs["display_header_footer"]
            return b"%PDF-1.7 fake"
    class Context:
        async def route(self, *_args): pass
        async def new_page(self): return Page()
        async def close(self): pass
    class Browser:
        async def new_context(self, **kwargs):
            seen.update(kwargs)
            return Context()
        async def close(self): pass
    class Chromium:
        async def launch(self, **_kwargs): return Browser()
    class Factory:
        chromium = Chromium()
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
    monkeypatch.setattr(api, "_playwright_factory", Factory)
    response = http.post(BASE + "/export", json={**PAYLOAD, "format": "pdf"})
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert seen["offline"] and not seen["java_script_enabled"]
    class Missing:
        def __call__(self): raise FileNotFoundError("browser")
    monkeypatch.setattr(api, "_playwright_factory", Missing())
    assert http.post(BASE + "/export", json={**PAYLOAD, "format": "pdf"}).status_code == 503
