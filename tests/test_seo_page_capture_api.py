"""API contract checks with an in-memory metadata store and no browser/network."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.api import seo_page_captures as api
from app.api.seo import router as seo_router, require_seo_module_access
from app.models.module_workspace import SeoSite
from app.models.seo import SeoContentAsset, SeoContentPublication, SeoSitePage
from app.models.seo_page_capture import SeoPageCapture
from app.security.auth import AuthContext
from app.seo_demo_source import require_seo_auth
from app.seo_page_capture import CaptureResult


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class Store:
    def __init__(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        with self.engine.begin() as conn:
            conn.execute(CreateTable(SeoPageCapture.__table__, include_foreign_key_constraints=[]))
        self.objects = {
            (SeoSite, 2): SimpleNamespace(id=2, tenant_id=4, canonical_domain="example.com", status="active"),
            (SeoSite, 3): SimpleNamespace(id=3, tenant_id=5, canonical_domain="other.com", status="active"),
            (SeoSitePage, 7): SimpleNamespace(id=7, tenant_id=4, site_id=2, url="https://example.com/page"),
            (SeoSitePage, 8): SimpleNamespace(id=8, tenant_id=4, site_id=3, url="https://other.com/page"),
            (SeoContentAsset, 11): SimpleNamespace(id=11, tenant_id=4, site_id=2),
            (SeoContentAsset, 12): SimpleNamespace(id=12, tenant_id=4, site_id=3),
            (SeoContentPublication, 21): SimpleNamespace(id=21, tenant_id=4, content_asset_id=11,
                                                         status="published", page_url="https://ZHIHU.example:443/article/?a=1&b=2#section"),
            (SeoContentPublication, 22): SimpleNamespace(id=22, tenant_id=4, content_asset_id=12,
                                                         status="published", page_url="https://example.com/page"),
            (SeoContentPublication, 23): SimpleNamespace(id=23, tenant_id=5, content_asset_id=11,
                                                         status="published", page_url="https://zhihu.example/article/"),
            (SeoContentPublication, 24): SimpleNamespace(id=24, tenant_id=4, content_asset_id=11,
                                                         status="published", page_url=None),
            (SeoContentPublication, 25): SimpleNamespace(id=25, tenant_id=4, content_asset_id=11,
                                                         status="draft_created", page_url="https://zhihu.example/draft"),
        }
        self.next_id = 1

    def session(self):
        return Adapter(Session(self.engine), self)


class Adapter:
    def __init__(self, session, store):
        self.db, self.store = session, store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.db.close()

    async def get(self, model, ident):
        if model is SeoPageCapture:
            return self.db.get(model, ident)
        return self.store.objects.get((model, ident))

    async def scalar(self, statement):
        if "FROM seo_sites" in str(statement):
            site_id = 3 if 3 in statement.compile().params.values() else 2
            return self.store.objects[(SeoSite, site_id)]
        return self.db.scalar(statement)

    async def scalars(self, statement):
        if "FROM seo_site_pages" in str(statement):
            requested_url = next((value for value in statement.compile().params.values()
                                  if isinstance(value, str) and value.startswith("http")), None)
            return [page for (model, _), page in self.store.objects.items()
                    if model is SeoSitePage and page.url == requested_url and page.site_id == 2]
        return self.db.scalars(statement)

    async def execute(self, statement):
        return self.db.execute(statement)

    def add(self, row):
        if isinstance(row, SeoPageCapture) and row.id is None:
            row.id = self.store.next_id
            self.store.next_id += 1
        self.db.add(row)

    async def commit(self):
        self.db.commit()

    async def refresh(self, row):
        self.db.refresh(row)


def _actor(tenant=4, permission="edit"):
    return AuthContext(9, "capture-user", "client", tenant, {"seo.site": permission})


def _client(monkeypatch, store, actor=None, *, enabled=True, worker=None, storage_dir=None):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(seo_router)
    actor = _actor() if actor is None else actor

    async def auth():
        if actor == "anonymous":
            raise HTTPException(401, "not authenticated")
        return actor

    async def module_access():
        return await auth()

    async def session():
        async with store.session() as scoped:
            yield scoped

    app.dependency_overrides[require_seo_auth] = auth
    app.dependency_overrides[require_seo_module_access] = module_access
    app.dependency_overrides[api.get_session] = session
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(
        seo_page_capture_enabled=enabled, seo_page_capture_timeout_seconds=5,
        seo_page_capture_storage_dir=str(storage_dir or "C:/outside/page-captures"),
        seo_page_capture_viewport_width=800, seo_page_capture_viewport_height=600,
    ))
    if worker is not None:
        monkeypatch.setattr(api, "execute_page_capture", worker)
    return TestClient(app)


def _create(client, **changes):
    body = {"tenant_id": 4, "site_id": 2, "url": "https://example.com/page",
            "relation_type": "site_page", "relation_id": 7}
    body.update(changes)
    return client.post("/api/v1/seo/site/page-captures", json=body)


async def _noop(_capture_id):
    pass


def test_auth_tenant_site_domain_relation_and_switch(monkeypatch):
    store = Store()
    assert _create(_client(monkeypatch, store, "anonymous", worker=_noop)).status_code == 401
    assert _create(_client(monkeypatch, store, _actor(tenant=5), worker=_noop)).status_code == 403
    assert _create(_client(monkeypatch, store, _actor(permission="view"), worker=_noop)).status_code == 403
    client = _client(monkeypatch, store, worker=_noop)
    assert _create(client, site_id=3).status_code == 404
    assert _create(client, url="https://example.com.evil.test/page").json()["detail"]["code"] == "invalid_site_url"
    assert _create(client, url="ftp://example.com/page").status_code == 422
    assert _create(client, relation_id=8).json()["detail"]["code"] == "relation_not_found"
    assert _create(client, relation_type="publication", relation_id=22).status_code == 404
    assert _create(client, relation_type="publication", relation_id=21, url=None).status_code == 202
    assert _create(_client(monkeypatch, store, worker=_noop, enabled=False)).json()["detail"]["code"] == "capture_disabled"


def test_create_pending_default_relation_and_duplicate(monkeypatch):
    store = Store()
    client = _client(monkeypatch, store, worker=_noop)
    response = _create(client, relation_type=None, relation_id=None)
    assert response.status_code == 202
    assert response.json() == {"id": 1, "status": "pending"}
    with store.session().db as db:
        row = db.get(SeoPageCapture, 1)
        assert (row.relation_type, row.relation_id, row.status) == ("site_page", 7, "pending")
    assert _create(client).json()["detail"]["code"] == "capture_recent"
    assert _create(client, relation_type=None, relation_id=None, url="https://example.com/missing").json()["detail"]["code"] == "site_page_required"


def test_publication_external_url_identity_and_scope(monkeypatch):
    store = Store()
    client = _client(monkeypatch, store, worker=_noop)
    body = {"relation_type": "publication", "relation_id": 21}
    assert _create(client, **body, url="https://zhihu.example/article/?a=1&b=2#other").status_code == 202
    with store.session().db as db:
        assert db.get(SeoPageCapture, 1).source_url == "https://zhihu.example/article/?a=1&b=2#other"
    assert _create(client, **body, url="https://zhihu.example/article?a=1&b=2").json()["detail"]["code"] == "publication_url_mismatch"
    assert _create(client, **body, url="https://zhihu.example/article/?b=2&a=1").json()["detail"]["code"] == "publication_url_mismatch"
    assert _create(client, relation_type="publication", relation_id=24, url=None).json()["detail"]["code"] == "publication_url_missing"
    assert _create(client, relation_type="publication", relation_id=25, url=None).json()["detail"]["code"] == "publication_url_missing"
    assert _create(client, relation_type="publication", relation_id=23, url=None).status_code == 404
    assert _create(client, relation_type="publication", relation_id=22, url=None).status_code == 404
    assert _create(client, relation_type="site_page", relation_id=7, url="https://zhihu.example/article/").json()["detail"]["code"] == "invalid_site_url"


def test_worker_sets_success_and_failure(monkeypatch):
    store = Store()
    worker_fn = api.execute_page_capture
    client = _client(monkeypatch, store, worker=_noop)
    first = _create(client).json()["id"]
    second = _create(client, relation_type="publication", relation_id=21, url=None).json()["id"]

    @asynccontextmanager
    async def factory():
        async with store.session() as session:
            yield session

    class Service:
        async def capture_page(self, **kw):
            status = "succeeded" if kw["relation_type"] == "site_page" else "failed"
            return CaptureResult(tenant_id=kw["tenant_id"], site_id=kw["site_id"],
                relation_type=kw["relation_type"], relation_id=kw["relation_id"],
                source_url=kw["url"], captured_at=datetime.now(timezone.utc), status=status,
                viewport_width=800, viewport_height=600, error_code=None if status == "succeeded" else "timeout",
                storage_key="a" * 32 + ".png" if status == "succeeded" else None)

    monkeypatch.setattr(api, "async_session_factory", factory)
    monkeypatch.setattr(api, "PageCaptureService", Service)
    async def operational(*_args):
        return True
    monkeypatch.setattr(api, "seo_site_is_operational", operational)
    asyncio.run(worker_fn(first))
    asyncio.run(worker_fn(second))
    with store.session().db as db:
        assert db.get(SeoPageCapture, first).status == "succeeded"
        failed = db.get(SeoPageCapture, second)
        assert (failed.status, failed.error_code) == ("failed", "timeout")


def test_detail_image_scope_headers_and_escape(monkeypatch, tmp_path):
    from app import seo_page_capture as capture
    monkeypatch.setattr(capture, "__file__", "C:/outside/app/seo_page_capture.py")
    store = Store()
    key = "a" * 32 + ".png"
    png = b"\x89PNG\r\n\x1a\n" + b"test"
    (tmp_path / key).write_bytes(png)
    client = _client(monkeypatch, store, worker=_noop, storage_dir=tmp_path)
    capture_id = _create(client).json()["id"]
    with store.session().db as db:
        row = db.get(SeoPageCapture, capture_id)
        row.status, row.storage_key = "succeeded", key
        db.commit()
    path = f"/api/v1/seo/site/page-captures/{capture_id}"
    detail = client.get(path, params={"tenant_id": 4})
    assert detail.status_code == 200 and detail.json()["status"] == "succeeded"
    assert "storage_key" not in detail.json()
    assert client.get(path, params={"tenant_id": 5}).status_code == 403
    image = client.get(path + "/image", params={"tenant_id": 4})
    assert image.content == png and image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "private, no-store"
    assert image.headers["x-content-type-options"] == "nosniff"
    assert client.get(path + "/image", params={"tenant_id": 5}).status_code == 403
    assert _client(monkeypatch, store, _actor(permission=""), worker=_noop, storage_dir=tmp_path).get(
        path, params={"tenant_id": 4}).status_code == 403
    assert _client(monkeypatch, store, _actor(permission="view"), worker=_noop, storage_dir=tmp_path).get(
        path + "/image", params={"tenant_id": 4}).status_code == 200
    assert _client(monkeypatch, store, "anonymous", worker=_noop, storage_dir=tmp_path).get(
        path + "/image", params={"tenant_id": 4}).status_code == 401
    with store.session().db as db:
        db.get(SeoPageCapture, capture_id).storage_key = "../secret.png"
        db.commit()
    assert client.get(path + "/image", params={"tenant_id": 4}).status_code == 404


def test_list_filter_pagination_and_stale_timeout(monkeypatch):
    store = Store()
    client = _client(monkeypatch, store, worker=_noop)
    first = _create(client).json()["id"]
    _create(client, relation_type="publication", relation_id=21, url=None)
    with store.session().db as db:
        db.get(SeoPageCapture, first).captured_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db.commit()
    base = "/api/v1/seo/site/page-captures"
    params = {"tenant_id": 4, "site_id": 2, "page_size": 1}
    newest = client.get(base, params=params).json()
    assert newest["total"] == 2 and newest["items"][0]["relation_type"] == "publication"
    older = client.get(base, params={**params, "page": 2}).json()
    assert older["items"][0]["status"] == "failed"
    assert older["items"][0]["error_code"] == "timeout"
    filtered = client.get(base, params={**params, "relation_type": "site_page", "relation_id": 7}).json()
    assert filtered["total"] == 1 and filtered["items"][0]["id"] == first
    assert _client(monkeypatch, store, _actor(permission=""), worker=_noop).get(base, params=params).status_code == 403


def test_list_date_status_latest_per_relation_and_pagination(monkeypatch):
    store = Store()
    client = _client(monkeypatch, store, worker=_noop)
    with store.session().db as db:
        for ident, relation_type, relation_id, day, status in [
            (1, "publication", 21, 1, "succeeded"),
            (2, "publication", 21, 2, "succeeded"),
            (3, "publication", 21, 3, "failed"),
            (4, "site_page", 7, 2, "succeeded"),
            (5, "site_page", 7, 4, "succeeded"),
        ]:
            db.add(SeoPageCapture(id=ident, tenant_id=4, site_id=2, relation_type=relation_type,
                relation_id=relation_id, source_url="https://example.com/page", status=status,
                captured_at=datetime(2026, 10, day, 12, tzinfo=timezone.utc),
                redirect_chain=[], warnings={}, viewport_width=800, viewport_height=600))
        db.commit()
    base = "/api/v1/seo/site/page-captures"
    params = {"tenant_id": 4, "site_id": 2, "captured_from": "2026-10-02",
              "captured_to": "2026-10-04", "status": "succeeded", "latest_per_relation": "true",
              "page_size": 1}
    first = client.get(base, params=params).json()
    second = client.get(base, params={**params, "page": 2}).json()
    assert first["total"] == second["total"] == 2
    assert [first["items"][0]["id"], second["items"][0]["id"]] == [5, 2]
    only_publications = client.get(base, params={**params, "relation_type": "publication"}).json()
    assert only_publications["total"] == 1 and only_publications["items"][0]["id"] == 2
    assert client.get(base, params={**params, "captured_from": "2026-10-03T00:00:00+08:00"}).json()["total"] == 1
    assert client.get(base, params={**params, "captured_from": "2026-10-05"}).json()["detail"]["code"] == "invalid_capture_range"
    assert client.get(base, params={**params, "captured_from": "2026-10-02T00:00:00"}).json()["detail"]["code"] == "invalid_capture_range"
