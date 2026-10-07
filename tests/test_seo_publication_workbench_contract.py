"""Accurate-version manual evidence and per-record read-only action contracts."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from test_seo_content_drafting import store, ADVISOR, edit, content
from test_seo_content_workflow import trigger
from app.api import seo as api
from app.models.seo import SeoContentAsset, SeoContentConfirmation, SeoContentPublication
from app.security.auth import AuthContext


def prepare(store, monkeypatch):
    trigger(store)
    store.draft_ready()
    monkeypatch.setattr(api, "_queue_published_page_verification", AsyncMock(return_value={"state": "not_queued", "reason": "isolated_test"}))


def request(store, **values):
    row = content(store)
    return api.DistributionManualPublicationCreate(**{
        "tenant_id": 4, "site_id": 2, "content_id": row.id, "source_version": row.version_count,
        "payload_hash": api._content_confirmation_hash(row), "platform_name": "隔离测试记录",
        "page_url": "https://example.com/published", **values})


def create(store, req, actor=ADVISOR):
    async def run():
        async with store.session() as session:
            return await api.create_manual_publication(req, session, actor)
    return asyncio.run(run())


def listed(store, actor=ADVISOR):
    async def run():
        async with store.session() as session:
            return await api.list_content_publications(4, 2, None, None, session, actor)
    return asyncio.run(run())


def complete(store, actor=ADVISOR):
    async def run():
        async with store.session() as session:
            return await api.complete_manual_publication(91, api.DistributionManualComplete(
                tenant_id=4, site_id=2, page_url="https://example.com/published", source_version=1), session, actor)
    return asyncio.run(run())


def test_manual_create_requires_exact_version_and_hash_and_does_not_publish(store, monkeypatch):
    prepare(store, monkeypatch)
    result = create(store, request(store))
    assert result["status"] == "published" and result["source_version"] == 1
    assert result["page_url"] == "https://example.com/published"
    store.provider.assert_not_awaited()
    api._queue_published_page_verification.assert_awaited_once()
    assert api._content_payload(content(store))["payload_hash"] == request(store).payload_hash


@pytest.mark.parametrize("change", ["version", "hash", "missing_version", "missing_hash", "site", "tenant", "confirmation"])
def test_manual_create_conflicts_are_atomic_and_no_evidence_is_queued(store, monkeypatch, change):
    prepare(store, monkeypatch)
    req = request(store)
    if change == "version": edit(store, SeoContentAsset, req.content_id, version_count=2)
    elif change == "hash": edit(store, SeoContentAsset, req.content_id, draft="不同正文但版本异常未递增")
    elif change == "missing_version": req.source_version = None
    elif change == "missing_hash": req.payload_hash = None
    elif change == "site": edit(store, SeoContentAsset, req.content_id, site_id=99)
    elif change == "tenant": edit(store, SeoContentAsset, req.content_id, tenant_id=99)
    elif change == "confirmation": edit(store, SeoContentConfirmation, 90, decision="reject")
    with pytest.raises(HTTPException) as exc: create(store, req)
    expected = 428 if change.startswith("missing_") else 404 if change in {"site", "tenant"} else 409
    assert exc.value.status_code == expected
    if change in {"version", "hash"}: assert exc.value.detail["code"] == "content_version_conflict"
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoContentPublication)) == 0
    api._queue_published_page_verification.assert_not_awaited()


def test_readonly_complete_capability_and_permission_revocation(store, monkeypatch):
    prepare(store, monkeypatch)
    store.publication()
    item = listed(store)["items"][0]
    assert item["allowed_actions"] == {"complete": True}
    assert item["action_requirements"]["complete"]["source_version"] == 1
    assert item["action_denial_reasons"]["complete"] is None
    viewer = AuthContext(7, "advisor", "now-view-only", None, {"seo.content": "view", "seo.site": "view"})
    assert listed(store, viewer)["items"][0]["action_denial_reasons"]["complete"] == "content_edit_permission_required"
    with pytest.raises(HTTPException) as exc: complete(store, viewer)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc: create(store, request(store), viewer)
    assert exc.value.status_code == 403
    api._queue_published_page_verification.assert_not_awaited()
    assert complete(store)["status"] == "published"
    assert listed(store)["items"][0]["allowed_actions"]["complete"] is False


@pytest.mark.parametrize("change,reason", [
    ("version", "content_version_conflict"), ("hash", "content_confirmation_stale"),
    ("confirmation", "content_confirmation_rejected"), ("publishing", "publication_status_not_completable"),
])
def test_per_record_denials_match_complete_write_guard(store, monkeypatch, change, reason):
    prepare(store, monkeypatch)
    store.publication()
    if change == "version": edit(store, SeoContentAsset, content(store).id, version_count=2)
    elif change == "hash": edit(store, SeoContentAsset, content(store).id, draft="changed")
    elif change == "confirmation": edit(store, SeoContentConfirmation, 90, decision="reject")
    else: edit(store, SeoContentPublication, 91, status="publishing")
    assert listed(store)["items"][0]["action_denial_reasons"]["complete"] == reason
    with pytest.raises(HTTPException) as exc: complete(store)
    assert exc.value.status_code == 409
    api._queue_published_page_verification.assert_not_awaited()


def test_tenant_bound_actor_cannot_read_or_record_other_tenant(store, monkeypatch):
    prepare(store, monkeypatch)
    store.publication()
    other = AuthContext(8, "other", "advisor", 99, ADVISOR.permissions)
    for action in (lambda: listed(store, other), lambda: create(store, request(store), other), lambda: complete(store, other)):
        with pytest.raises(HTTPException) as exc: action()
        assert exc.value.status_code == 403
    api._queue_published_page_verification.assert_not_awaited()


@pytest.mark.parametrize("revision", ["0104_seo_page_ai_tdk", "0105_seo_content_confirmations"])
def test_http_legacy_patch_cannot_publish_and_draft_version_policy(store, monkeypatch, revision):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    trigger(store)
    with store.engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num=:v"), {"v": revision})
    app = FastAPI()
    app.include_router(api.router)
    async def session_dependency():
        async with store.session() as session: yield session
    app.dependency_overrides[api.get_session] = session_dependency
    app.dependency_overrides[api.require_scoped_auth] = lambda: ADVISOR
    app.dependency_overrides[api.require_seo_module_access] = lambda: ADVISOR
    ident = content(store).id
    with TestClient(app) as client:
        path = f"/api/v1/seo/content-assets/{ident}?tenant_id=4"
        bypass = client.patch(path, json={"status": "published", "page_url": "https://example.com/fake"})
        assert bypass.status_code == 409 and "流程" in bypass.json()["detail"]
        assert content(store).status == "planned" and content(store).page_url is None
        missing = client.patch(path, json={"draft": "草稿正文"})
        assert missing.status_code == (428 if revision.startswith("0105") else 200)
        if revision.startswith("0105"):
            assert missing.json()["detail"]["code"] == "content_version_precondition_required"
        before = content(store).version_count
        valid = client.patch(path, json={"draft": "真实版本的新草稿", "version_count": before})
        assert valid.status_code == 200 and valid.json()["version_count"] == before + 1
        stale = client.patch(path, json={"draft": "旧页面覆盖", "version_count": before})
        assert stale.status_code == 409
        assert content(store).draft == "真实版本的新草稿"
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoContentPublication)) == 0


def test_http_manual_request_and_read_capabilities_contract(store, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    prepare(store, monkeypatch)
    store.publication()
    app = FastAPI()
    app.include_router(api.router)
    async def session_dependency():
        async with store.session() as session: yield session
    app.dependency_overrides[api.get_session] = session_dependency
    app.dependency_overrides[api.require_scoped_auth] = lambda: ADVISOR
    app.dependency_overrides[api.require_seo_module_access] = lambda: ADVISOR
    with TestClient(app) as client:
        path = "/api/v1/seo/content-distribution/publications"
        listing = client.get(path, params={"tenant_id": 4, "site_id": 2})
        assert listing.status_code == 200 and listing.json()["items"][0]["allowed_actions"]["complete"]
        body = request(store).model_dump(mode="json")
        missing = client.post(path + "/manual", json={k: v for k, v in body.items() if k != "source_version"})
        assert missing.status_code == 428
        invalid = client.post(path + "/manual", json={**body, "payload_hash": "invalid"})
        assert invalid.status_code == 422
        created = client.post(path + "/manual", json=body)
        assert created.status_code == 200 and created.json()["source_version"] == 1
