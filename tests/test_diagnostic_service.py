import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

for key, value in {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "BAIDU_APP_ID": "test", "BAIDU_SECRET_KEY": "test",
    "BAIDU_DEFAULT_USERNAME": "test", "BAIDU_DEFAULT_UCID": "0",
    "BAIDU_SELF_ACCESS_TOKEN": "test", "BAIDU_SELF_TOKEN_EXPIRES_AT": "2099-01-01T00:00:00Z",
    "CRYPTO_MASTER_KEY_B64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "ADMIN_API_KEY": "test-admin-key",
}.items():
    os.environ.setdefault(key, value)

import pytest
from fastapi.testclient import TestClient
from app.diagnostic_main import app
from app.diagnostic import routes
from app.database import get_session
from app.security.auth import AuthContext, require_auth


@pytest.fixture
def context():
    return AuthContext(1, "diagnostic-test", "operator", 7, {"geo.diagnosis": "edit"})


@pytest.fixture
def db():
    return SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=7)),
                           commit=AsyncMock(), refresh=AsyncMock())


@pytest.fixture
def client(context, db):
    app.dependency_overrides[require_auth] = lambda: context
    app.dependency_overrides[get_session] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_route_surface_is_isolated():
    paths = {r.path for r in app.routes}
    assert "/api/v1/diagnostic/assets/brand/discover" in paths
    assert "/api/v1/diagnostic/assets/brand" in paths
    assert "/api/v1/diagnostic/audits" in paths
    assert "/api/v1/diagnostic/pagespeed" in paths
    assert not any(p.startswith("/api/v1/geo/") for p in paths)


def test_discovery_rejects_cross_tenant_before_fetch(client, monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(routes, "discover_brand_profile", fetch)
    response = client.post("/api/v1/diagnostic/assets/brand/discover",
                           json={"tenant_id": 8, "website": "https://example.com"})
    assert response.status_code == 403
    fetch.assert_not_awaited()


def test_discovery_returns_candidate_and_preserves_fetch_error(client, monkeypatch):
    fetch = AsyncMock(return_value={"brand": {"name": "Example"}, "ai_used": False})
    monkeypatch.setattr(routes, "discover_brand_profile", fetch)
    payload = {"tenant_id": 7, "website": "https://example.com"}
    assert client.post("/api/v1/diagnostic/assets/brand/discover", json=payload).json()["brand"]["name"] == "Example"
    fetch.side_effect = routes.GeoAuditError("网站访问失败：HTTP 403")
    response = client.post("/api/v1/diagnostic/assets/brand/discover", json=payload)
    assert response.status_code == 400
    assert "HTTP 403" in response.json()["detail"]


def test_readonly_user_cannot_save_brand(client, context):
    context.permissions = {"geo.diagnosis": "view"}
    assert client.put("/api/v1/diagnostic/assets/brand",
                      json={"tenant_id": 7, "name": "Example"}).status_code == 403


def test_brand_save_preserves_other_domains_and_tenant_master(client, db, monkeypatch):
    monkeypatch.setattr(routes, "_diagnosis_brand_store", AsyncMock(return_value={
        "active_key": "old.example", "profiles": {"old.example": {"name": "Old"}}}))
    upsert = AsyncMock()
    monkeypatch.setattr(routes, "_upsert_memory", upsert)
    response = client.put("/api/v1/diagnostic/assets/brand", json={
        "tenant_id": 7, "name": "Example", "website": "https://example.com",
        "industry": "Manufacturing", "core_products": ["Motors"]})
    assert response.status_code == 200
    saved = upsert.await_args.kwargs["data"]
    assert saved["profiles"]["old.example"]["name"] == "Old"
    assert saved["profiles"]["example.com"]["name"] == "Example"
    assert vars(db.get.return_value) == {"id": 7}


def test_audit_attaches_chinaz_and_keeps_existing_schema(client, db, monkeypatch):
    monkeypatch.setattr(routes, "_diagnosis_brand_store", AsyncMock(return_value={
        "active_key": "example.com", "profiles": {"example.com": {
            "name": "Example", "website": "https://example.com",
            "industry": "Manufacturing", "core_products": ["Motors"]}}}))
    scan = {"url": "https://example.com", "final_url": "https://example.com",
            "score": 80, "title": "Example", "description": "Example company",
            "snapshot": {}, "checks": []}
    monkeypatch.setattr(routes, "audit_site", AsyncMock(return_value=scan))
    monkeypatch.setattr(routes, "fetch_chinaz_seo_metrics", AsyncMock(return_value={
        "baidu_index": {"status": "available", "site_count": 12}}))
    inserted = []
    db.add = inserted.append
    response = client.post("/api/v1/diagnostic/audits", json={
        "tenant_id": 7, "url": "https://example.com", "scope": "site"})
    assert response.status_code == 200
    assert response.json()["snapshot"]["external_metrics"]["baidu_index"]["site_count"] == 12
    assert inserted[0].__tablename__ == "geo_audit_runs"
