"""SQLite scoped API tests; DeepSeek is always mocked."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable
from types import SimpleNamespace

from app.api import seo_ai_tdk as api
from app.models.module_workspace import SeoSite
from app.models.seo import SeoKeywordAsset, SeoPageSnapshot, SeoSitePage
from app.models.seo_ai_tdk import SeoPageAiTdkSuggestion as Suggestion
from app.models.tenant import Tenant
from app.security.auth import AuthContext


@compiles(JSONB, "sqlite")
def _jsonb(_type, _compiler, **_kwargs): return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint(_type, _compiler, **_kwargs): return "INTEGER"


class Adapter:
    def __init__(self, db): self.db = db
    async def get(self, *args): return self.db.get(*args)
    async def scalar(self, query): return self.db.scalar(query)
    async def scalars(self, query): return self.db.scalars(query)
    async def commit(self): self.db.commit()
    async def flush(self): self.db.flush()
    def add(self, row): self.db.add(row)


def client(permission="edit", actor=9):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        for model in (Tenant, SeoSite, SeoSitePage, SeoKeywordAsset, SeoPageSnapshot, Suggestion):
            conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
    with Session(engine) as db:
        db.add_all([Tenant(id=4, name="客户"),
            SeoSite(id=2, tenant_id=4, tenant_module_id=1, name="站点", domain="example.test", canonical_domain="example.test", status="active"),
            SeoSitePage(id=11, tenant_id=4, site_id=2, url="https://example.test/a", title="页面", status="pending"),
            SeoSitePage(id=12, tenant_id=5, site_id=3, url="https://other.test/b", title="外站", status="pending")])
        db.commit()
    app = FastAPI(); app.include_router(api.router, prefix="/api/v1/seo")
    async def auth(): return AuthContext(actor, "tester", "client", 4, {"seo.site": permission})
    async def session():
        with Session(engine, expire_on_commit=False) as db: yield Adapter(db)
    app.dependency_overrides[api.require_scoped_auth] = auth
    app.dependency_overrides[api.get_session] = session
    return TestClient(app), engine


BASE = "/api/v1/seo/site/pages"
SCOPE = {"tenant_id": 4, "site_id": 2}


def test_scope_permissions_and_batch_limits():
    http, _ = client("none")
    assert http.get(BASE + "/11/ai-tdk", params=SCOPE).status_code == 403
    assert http.post(BASE + "/ai-tdk/generate", json={**SCOPE, "page_ids": [11]}).status_code == 403
    http, _ = client("view")
    assert http.get(BASE + "/11/ai-tdk", params=SCOPE).status_code == 200
    assert http.get(BASE + "/12/ai-tdk", params=SCOPE).status_code == 404
    assert http.post(BASE + "/ai-tdk/generate", json={**SCOPE, "page_ids": [11]}).status_code == 403
    http, _ = client()
    assert http.post(BASE + "/ai-tdk/generate", json={**SCOPE, "page_ids": []}).status_code == 422
    assert http.post(BASE + "/ai-tdk/generate", json={**SCOPE, "page_ids": list(range(1, 22))}).status_code == 422
    assert http.post(BASE + "/ai-tdk/generate", json={**SCOPE, "page_ids": [12]}).status_code == 404


def test_review_actions_and_validation():
    http, engine = client()
    with Session(engine) as db:
        db.add(Suggestion(id=20, tenant_id=4, site_id=2, page_id=11, batch_id="batch", model_name="deepseek-chat",
            prompt_version="v1", input_digest="a" * 64, title_ai_value="AI 标题",
            description_ai_value="页面描述" * 20, keywords_ai_value="甲, 乙, 丙",
            internal_link_suggestions=[], warnings=[], dropped_links=0))
        db.commit()
    url = BASE + "/11/ai-tdk/20/review"
    assert http.post(url, json={**SCOPE, "fields": {"title": {"action": "edit", "final_value": ""}}}).status_code == 422
    assert http.post(url, json={**SCOPE, "fields": {"description": {"action": "accept"}}}).status_code == 200
    changed = http.post(url, json={**SCOPE, "fields": {"title": {"action": "edit", "final_value": "人工标题"},
        "keywords": {"action": "reject"}}})
    assert changed.status_code == 200
    assert changed.json()["title_status"] == "modified" and changed.json()["keywords_status"] == "rejected"
    assert changed.json()["reviewed_by"] == 9
    http, _ = client("view")
    assert http.post(url, json={**SCOPE, "fields": {"title": {"action": "accept"}}}).status_code == 403


def test_generation_uses_mocked_deepseek_and_digest_idempotency(monkeypatch):
    http, _ = client()
    calls = []
    async def fake_chat(*_args, **_kwargs):
        calls.append(True)
        return {"title": "页面说明", "description": "这个页面介绍已经保存在系统中的页面信息和相关内容。" * 4,
                "keywords": ["页面", "信息", "内容"], "reason": "依据页面标题", "internal_links": []}
    monkeypatch.setattr(api, "chat_json", fake_chat)
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(deepseek_api_key="fake",
        deepseek_base_url="https://unused.invalid", deepseek_model="deepseek-chat",
        seo_ai_tdk_min_interval_seconds=0))
    payload = {**SCOPE, "page_ids": [11]}
    first = http.post(BASE + "/ai-tdk/generate", json=payload)
    assert first.status_code == 200 and first.json()["items"][0]["status"] == "generated"
    second = http.post(BASE + "/ai-tdk/generate", json=payload)
    assert second.json()["items"][0]["status"] == "skipped" and len(calls) == 1
    third = http.post(BASE + "/ai-tdk/generate", json={**payload, "force": True})
    assert third.json()["items"][0]["status"] == "generated" and len(calls) == 2
    history = http.get(BASE + "/11/ai-tdk", params=SCOPE).json()
    assert history["latest"]["id"] != history["history"][0]["id"]
