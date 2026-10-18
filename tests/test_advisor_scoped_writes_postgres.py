"""Opt-in real-handler and revocation tests, using existing owned PG schemas.

Set only SEO_WORKFLOW_TEST_DATABASE_URL (loopback / seo_workflow_test) and
SEO_WORKFLOW_TEST_ALLOW_SCHEMA_CREATE=yes. Never use application DATABASE_URL.
No migration, provider, production data, or application startup is run.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import importlib

import httpx
import jwt
from unittest.mock import AsyncMock, Mock
import pytest
from fastapi import Depends, FastAPI, Request
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateTable

from app import seo_demo_source as demo
from app.api import seo as api
from app.database import get_session
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.models.module_workspace import SeoSite, TenantModule
from app.models.role import Role
from app.models.seo import (SeoAiOperation, SeoAutomationRun, SeoBrandAsset, SeoContentAsset, SeoKeywordAsset,
                            SeoSiteAdvisorAssignment, SeoSitePage)
from app.models.seo_qa import SeoQaBatch, SeoQaFact
from app.models.tenant import Tenant
from app.models.user import User
from app.security import auth
from test_seo_workflow_postgres import database, requires_pg
from test_advisor_scoped_writes import (CASES, CASE_IDS, OUTSIDE, FORBIDDEN, PREFIX,
    actor, bearer, switches, routes_contract, objects_contract, complete_contract)  # noqa: F401

pytestmark = requires_pg


@pytest.fixture(autouse=True)
def no_external_side_effects(monkeypatch):
    """Fail on outbound HTTP, supplier, capture, charge, or queued background work."""
    probes = []
    for name in ("chat_json", "_seo_chat_json", "_queue_published_page_verification",
                 "execute_page_capture", "reserve_publication_page_capture",
                 "claim_seo_ai_operation", "consume_seo_usage"):
        if hasattr(api, name):
            probe = AsyncMock(side_effect=AssertionError("manual write called " + name))
            monkeypatch.setattr(api, name, probe)
            probes.append(probe)
    from starlette.background import BackgroundTasks
    background = Mock(side_effect=AssertionError("manual write queued background work"))
    monkeypatch.setattr(BackgroundTasks, "add_task", background)
    probes.append(background)
    for transport, method in ((httpx.AsyncHTTPTransport, "handle_async_request"),
                              (httpx.HTTPTransport, "handle_request")):
        probe = Mock(side_effect=AssertionError("unexpected outbound HTTP"))
        monkeypatch.setattr(transport, method, probe)
        probes.append(probe)
    yield
    assert all(probe.call_count == 0 for probe in probes)


@asynccontextmanager
async def store():
    async with database() as sessions:
        async with sessions() as session:
            connection = await session.connection()
            for model in (Grant, SeoBrandAsset, SeoSitePage, SeoQaBatch, SeoAutomationRun):
                await connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
            user = await session.get(User, 7)
            user.tenant_id = 4
            site = await session.get(SeoSite, 2)
            site.site_settings = {"seo_service_plan": {"revision": 1, "status": "paused",
                "content_ai_enabled": False, "content_cycle_enabled": False,
                "website_cycle_enabled": False, "website_incremental_cycle_enabled": False,
                "monitoring_cycle_enabled": False, "report_cycle_enabled": False,
                "analytics_cycle_enabled": False}}
            session.add_all([
                Role(id=6, name="customer", is_system=False, permissions={"seo.site": "view", "seo.content": "edit", "seo.keywords": "view"}),
                Role(id=8, name="管理员", is_system=True, permissions={"settings.accounts": "edit", "seo.site": "edit", "seo.content": "edit", "seo.keywords": "edit"}),
                User(id=8, username="customer", password_hash="unused", role_id=6, tenant_id=4, is_active=True),
                User(id=9, username="admin", password_hash="unused", role_id=8, is_active=True),
                Grant(id=10, user_id=7, tenant_id=4, granted_by=9, grant_source="admin"),
                Grant(id=20, user_id=7, tenant_id=6, granted_by=9, grant_source="admin"),
            ])
            for tid in (6, 8):
                session.add_all([Tenant(id=tid, name=f"tenant{tid}"),
                    TenantModule(id=tid, tenant_id=tid, module_code="seo", status="active"),
                    SeoSite(id=tid, tenant_id=tid, tenant_module_id=tid, name=f"site{tid}",
                            domain=f"site{tid}.test", canonical_domain=f"site{tid}.test", status="active")])
            session.add(SeoSite(id=3, tenant_id=4, tenant_module_id=1, name="same tenant second site",
                                domain="other-site.test", canonical_domain="other-site.test", status="active"))
            # Every resource exists, so denials cannot pass accidentally as missing rows.
            for offset, tid, sid in ((0, 4, 2), (100, 6, 6), (200, 8, 8), (300, 4, 3)):
                session.add_all([
                    SeoContentAsset(id=1+offset, tenant_id=tid, site_id=sid, content_type="landing",
                                    title="Original article", draft="Original body", status="drafting", version_count=1),
                    SeoBrandAsset(id=40+offset, tenant_id=tid, site_id=sid, asset_type="official_domain",
                                  name="Original rule", match_value=f"original{offset}.test"),
                    SeoSitePage(id=50+offset, tenant_id=tid, site_id=sid, url=f"https://page{offset}.test/"),
                ])
                if offset:
                    session.add_all([
                        SeoKeywordAsset(id=20+offset, tenant_id=tid, site_id=sid, keyword="other"),
                        SeoQaFact(id=30+offset, tenant_id=tid, site_id=sid, title="Other fact", statement="Other evidence", source_name="fixture"),
                    ])
            await session.commit()
            # Explicit fixture IDs do not advance PostgreSQL BIGSERIAL sequences.
            for table in ("seo_content_assets", "seo_brand_assets", "seo_qa_facts"):
                await session.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                                           f"(SELECT max(id) FROM {table}))"))
            await session.commit()
        yield sessions


def app_for(sessions, after_guard=None):
    async def primary_auth(ctx=Depends(auth.require_auth)):
        return ctx
    async def local_session():
        async with sessions() as session:
            try:
                yield session
            finally:
                await session.rollback()
    async def seo_session(session=Depends(get_session)):
        yield session
    async def boundary(request: Request, ctx=Depends(auth.require_auth)):
        if after_guard is not None:
            await after_guard(request, ctx)
    app = FastAPI(dependencies=[Depends(boundary)])
    app.dependency_overrides[get_session] = local_session
    app.dependency_overrides[demo.get_seo_session] = seo_session
    # Only demo data-source routing is replaced; real JWT / guard / RBAC / module
    # access / assignment / objects / handler / transaction remain in the request.
    app.dependency_overrides[demo.require_seo_auth] = primary_auth
    app.include_router(api.router)
    return app


@asynccontextmanager
async def client_for(sessions, after_guard=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(sessions, after_guard)),
                                 base_url="http://local.test") as client:
        yield client


async def send(client, case, *, body=None, query=None, path=None, headers=None):
    return await client.request(case.method, (path or case.path) + "?" +
        ("tenant_id=4&site_id=2" if query is None else query),
        json=dict(case.body) if body is None else body, headers=bearer() if headers is None else headers)


async def snapshot(sessions):
    # New session after the response proves committed state, including other tenants.
    async with sessions() as session:
        return {model.__tablename__: [tuple(row) for row in (await session.execute(
                select(model.__table__).order_by(model.id))).all()]
                for model in (SeoQaFact, SeoBrandAsset, SeoContentAsset, SeoSitePage,
                              SeoKeywordAsset, api.SeoTask, api.SeoContentPublication)}


def assert_denied(response, code=None, status=403):
    assert response.status_code == status, response.text
    if code:
        assert response.json()["detail"]["code"] == code


def test_native_fixture_seeds_distinct_tenants_sites_and_active_grant():
    """Runs even before A/B land, so skips cannot hide broken test scaffolding."""
    async def run():
        async with store() as sessions:
            state = await snapshot(sessions)
            assert len(state["seo_content_assets"]) == 4
            async with sessions() as session:
                assert (await session.get(Grant, 10)).revoked_at is None
                assert (await session.get(User, 7)).tenant_id == 4
                assert (await session.get(SeoSite, 2)).site_settings["seo_service_plan"]["status"] == "paused"
                assert (await session.get(SeoKeywordAsset, 320)).site_id == 3
                assert (await session.get(SeoQaFact, 130)).tenant_id == 6
                schema = await session.scalar(text("SELECT current_schema()"))
                assert schema.startswith("seo_workflow_test_")
    asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_every_allowlisted_mounted_handler_persists_manual_edit(monkeypatch, complete_contract, case):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            response = await send(client, case)
            assert response.status_code in (200, 201), response.text
            result = response.json()
            async with sessions() as session:
                if "/qa/facts" in case.template:
                    row = await session.get(SeoQaFact, result["id"])
                    assert row.title == case.body["title"] and row.statement == case.body["statement"]
                    assert row.status == "active"
                    if case.method == "PATCH":
                        assert row.version == 2
                elif "/brand-assets" in case.template:
                    row = await session.get(SeoBrandAsset, result["id"])
                    assert row.name == case.body["name"] and row.status == "active"
                else:
                    row = await session.get(SeoContentAsset, result["id"])
                    if case.method == "PUT":
                        assert row.source_page_id == 50
                    else:
                        assert row.title == case.body["title"]
                        assert row.draft == case.body["draft"]
                    assert row.status in {"planned", "drafting"}
                    assert row.published_at is None and row.page_url is None
                assert row.tenant_id == 4 and row.site_id == 2
            after = await snapshot(sessions)
            assert after != before
            # No new persisted dispatch or publication from manual content editing.
            for table in ("seo_tasks", "seo_content_publications"):
                assert after[table] == before[table]
    asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("old", [False, True])
def test_switch_off_http_has_no_committed_changes(monkeypatch, case, old):
    switches(monkeypatch, enabled=False, old=old)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            assert_denied(await send(client, case), "ADVISOR_HIGH_RISK_WRITES_DISABLED")
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("tid,sid,offset", [(6, 6, 100), (8, 8, 200)], ids=["granted-unselected", "ungranted"])
def test_http_other_tenant_is_403_and_atomic(monkeypatch, complete_contract, case, tid, sid, offset):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            body = dict(case.body)
            for key, value in (("tenant_id", tid), ("site_id", sid)):
                if key in body:
                    body[key] = value
            path = case.template.format(fact_id=30+offset, asset_id=40+offset, content_id=1+offset)
            assert_denied(await send(client, case, body=body, path=path, query=f"tenant_id={tid}&site_id={sid}"))
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("body", [
    {"keyword_id": 120}, {"keyword_ids": [20, 120]}, {"source_page_id": 150},
    {"keyword_ids": [20, 320]}, {"source_page_id": 350},
    {"metadata": {"references": [{"keyword_id": 20}, {"keyword_id": 120}]}},
    {"items": [{"tenant_id": 4}, {"tenant_id": 6}]},
    {"future_id": 123}, {"future_ids": [20, 120]},
])
def test_body_foreign_nested_array_or_unknown_id_is_atomic(monkeypatch, complete_contract, body):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            assert_denied(await send(client, CASES[5], body={**CASES[5].body, **body}))
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("case", [CASES[1], CASES[3], CASES[5]])
@pytest.mark.parametrize("field,value", [("tenant_id", 6), ("site_id", 6), ("project_id", 6)])
def test_patch_cannot_migrate_object_ownership(monkeypatch, complete_contract, case, field, value):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            assert_denied(await send(client, case, body={**case.body, field: value}))
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("consumer", ["enabled-plan", "unbound-running-task", "advisor-assigned-workflow", "missing-plan",
                                      "queued-qa-batch", "running-ai-operation", "running-automation"])
def test_existing_automatic_consumer_cannot_use_advisor_manual_edits(monkeypatch, complete_contract, case, consumer):
    """Design sections 6.1/7 also cover existing jobs consuming edited data."""
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            async with sessions() as session:
                if consumer == "enabled-plan":
                    site = await session.get(SeoSite, 2)
                    site.site_settings = {"seo_service_plan": {**site.site_settings["seo_service_plan"],
                        "status": "active", "content_cycle_enabled": True, "content_ai_enabled": True}}
                elif consumer == "missing-plan":
                    site = await session.get(SeoSite, 2)
                    site.site_settings = {}
                elif consumer == "queued-qa-batch":
                    session.add(SeoQaBatch(id=500, tenant_id=4, site_id=2, actor="fixture",
                        request_key="queued", request_hash="test", status="queued", items=[]))
                elif consumer == "running-ai-operation":
                    session.add(SeoAiOperation(id="running-test", tenant_id=4, site_id=2, actor="fixture",
                        request_key="running", request_hash="test", kind="draft", charged_on="2099-01-01",
                        status="running", expires_at=datetime(2099, 1, 1)))
                elif consumer == "running-automation":
                    session.add(SeoAutomationRun(id=500, tenant_id=4, site_id=2, job_type="ranking", status="running"))
                else:
                    session.add(api.SeoTask(id=500, tenant_id=4, site_id=2, action_type="content_delivery",
                        title="Preexisting unbound job", status="in_progress", created_by="system",
                        assignee_role="seo_advisor" if consumer == "advisor-assigned-workflow" else "system",
                        params={"content_id": 1, "phase": "draft", "plan_revision": 1}))
                await session.commit()
            before = await snapshot(sessions)
            assert_denied(await send(client, case))
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("target", ["plan", "assignment", "keyword", "module", "qa-resume"])
def test_scope_locks_prevent_activation_or_migration_until_commit(monkeypatch, complete_contract, target):
    """An admitted edit and a scope-changing transaction must serialize."""
    switches(monkeypatch)
    async def run():
        blocked = []
        async with store() as sessions:
            if target == "qa-resume":
                async with sessions() as seed:
                    seed.add(SeoQaBatch(id=500, tenant_id=4, site_id=2, actor="fixture",
                        request_key="paused", request_hash="test", status="paused", items=[]))
                    await seed.commit()
            async def after_guard(request, ctx):
                async with sessions() as competitor:
                    await competitor.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    try:
                        if target == "plan":
                            row = await competitor.get(SeoSite, 2)
                            row.site_settings = {"seo_service_plan": {"status": "active", "content_cycle_enabled": True}}
                        elif target == "assignment":
                            row = await competitor.get(SeoSiteAdvisorAssignment, 3)
                            row.active = False
                        elif target == "keyword":
                            row = await competitor.get(SeoKeywordAsset, 20)
                            row.site_id = 3
                        elif target == "module":
                            row = await competitor.get(TenantModule, 1)
                            row.status = "paused"
                        else:
                            row = await competitor.get(SeoQaBatch, 500)
                            row.status = "queued"
                        with pytest.raises(DBAPIError) as caught:
                            await competitor.commit()
                        assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
                        blocked.append(target)
                    finally:
                        await competitor.rollback()
            async with client_for(sessions, after_guard) as client:
                response = await send(client, CASES[5])
                assert response.status_code == 200, response.text
            assert blocked == [target]
            async with sessions() as verify:
                assert (await verify.get(SeoContentAsset, 1)).title == CASES[5].body['title']
                assert (await verify.get(SeoSite, 2)).site_settings['seo_service_plan']['status'] == 'paused'
                assert (await verify.get(SeoSiteAdvisorAssignment, 3)).active
                assert (await verify.get(SeoKeywordAsset, 20)).site_id == 2
                assert (await verify.get(TenantModule, 1)).status == 'active'
                if target == "qa-resume":
                    assert (await verify.get(SeoQaBatch, 500)).status == 'paused'
    asyncio.run(run())


@pytest.mark.parametrize("case", [CASES[1], CASES[3], CASES[5], CASES[6]])
@pytest.mark.parametrize("offset", [100, 200, 300])
def test_path_id_cannot_be_laundered_by_selected_query(monkeypatch, complete_contract, case, offset):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            path = case.template.format(fact_id=30+offset, asset_id=40+offset, content_id=1+offset)
            assert_denied(await send(client, case, path=path))
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("case", [CASES[1], CASES[3], CASES[5], CASES[6]])
def test_missing_path_object_is_404_and_atomic(monkeypatch, complete_contract, case):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            path = case.template.format(fact_id=99999, asset_id=99999, content_id=99999)
            assert_denied(await send(client, case, path=path), status=404)
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("claims_change,status", [
    ({"scope_kind": "advisor_identity", "aud": "advisor-session"}, 409),
    ({"gid": 999}, 401), ({"tid": 6, "gid": 10}, 401),
    ({"aud": "advisor-session"}, 401), ({"exp": 1}, 401),
])
def test_identity_or_invalid_business_session_cannot_write(monkeypatch, complete_contract, claims_change, status):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            assert_denied(await send(client, CASES[5], headers=bearer(**claims_change)), status=status)
            assert await snapshot(sessions) == before
    asyncio.run(run())


def test_no_grant_never_uses_user_default_tenant(monkeypatch, complete_contract):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            async with sessions() as session:
                await invalidate(session, "grant")
                other = await session.get(Grant, 20)
                other.revoked_at, other.revoked_by, other.revoke_reason = datetime.now(timezone.utc) + timedelta(seconds=1), 9, "admin_uncheck"
                await session.commit()
            before = await snapshot(sessions)
            response = await send(client, CASES[5])
            assert_denied(response, "ADVISOR_GRANT_REVOKED", status=401)
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("change", ["missing", "inactive", "another-advisor"])
def test_site_assignment_required_for_every_write(monkeypatch, complete_contract, case, change):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            async with sessions() as session:
                row = await session.get(SeoSiteAdvisorAssignment, 3)
                if change == "missing":
                    await session.delete(row)
                elif change == "inactive":
                    row.active = False
                else:
                    row.advisor_user_id = 8
                await session.commit()
            before = await snapshot(sessions)
            assert_denied(await send(client, case), "ADVISOR_ASSIGNMENT_REQUIRED")
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_view_permission_never_suffices(monkeypatch, complete_contract, case):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            async with sessions() as session:
                row = await session.get(Role, 5)
                row.permissions = {**row.permissions, case.permission: "view"}
                await session.commit()
            before = await snapshot(sessions)
            assert_denied(await send(client, case))
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
@pytest.mark.parametrize("field,value", FORBIDDEN.items())
def test_forbidden_fields_return_403_before_schema_or_handler(monkeypatch, complete_contract, case, field, value):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            assert_denied(await send(client, case, body={**case.body, field: value}), "ADVISOR_WRITE_FIELD_FORBIDDEN")
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("method,suffix", OUTSIDE)
def test_mounted_high_risk_routes_still_fail_closed(monkeypatch, complete_contract, method, suffix):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            path = (PREFIX + suffix).format(content_id=1, task_id=1)
            response = await client.request(method, path + "?tenant_id=4&site_id=2", json={}, headers=bearer())
            # Consult registration, not the response: a handler returning 404
            # must not masquerade as an unregistered route and pass this test.
            mounted = any(route.path == PREFIX + suffix and method in route.methods
                          for route in api.router.routes)
            if mounted:
                assert_denied(response, "ADVISOR_HIGH_RISK_WRITES_DISABLED")
            else:
                assert response.status_code in (404, 405), response.text
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("case,field", [(CASES[1], "version"), (CASES[5], "version_count"), (CASES[6], "version_count")])
@pytest.mark.parametrize("value", ["missing", None, 999])
def test_versions_are_required_and_stale_versions_cannot_write(monkeypatch, complete_contract, case, field, value):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            body = {key: val for key, val in case.body.items() if key != field}
            if value != "missing":
                body[field] = value
            response = await send(client, case, body=body)
            assert response.status_code in ((403, 422) if value in ("missing", None) else (409,)), response.text
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("case", [CASES[5], CASES[6]])
@pytest.mark.parametrize("status", ["review", "ready", "published", "archived"])
def test_protected_existing_content_cannot_be_edited(monkeypatch, complete_contract, case, status):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            async with sessions() as session:
                row = await session.get(SeoContentAsset, 1)
                row.status = status
                await session.commit()
            before = await snapshot(sessions)
            response = await send(client, case)
            assert response.status_code in (403, 409), response.text
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("status", ["review", "ready", "published", "archived"])
def test_no_status_escalation_and_explicit_archiving(monkeypatch, complete_contract, status):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            for case in ((CASES[4],) if status == 'archived' else (CASES[4], CASES[5])):
                assert_denied(await send(client, case, body={**case.body, "status": status}))
            assert_denied(await send(client, CASES[0], body={**CASES[0].body, "status": "verified"}))
            assert await snapshot(sessions) == before
            response = await send(client, CASES[3], body={"status": "archived"})
            assert response.status_code == 200, response.text
            assert response.json()['status'] == 'archived'
            if status == 'archived':
                response = await send(client, CASES[5], body={**CASES[5].body, 'status': 'archived'})
                assert response.status_code == 200, response.text
                assert response.json()['status'] == 'archived'
    asyncio.run(run())


@pytest.mark.parametrize("change", ["grant", "regrant", "user", "locked", "role", "edit"])
def test_revoke_before_next_request_cannot_persist(monkeypatch, complete_contract, change):
    switches(monkeypatch)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            async with sessions() as session:
                await invalidate(session, change)
                if change == "regrant":
                    session.add(Grant(id=30, user_id=7, tenant_id=4, granted_by=9, grant_source="admin"))
                await session.commit()
            before = await snapshot(sessions)
            response = await send(client, CASES[5])
            assert response.status_code in (401, 403), response.text
            if change in {"grant", "regrant"}:
                assert_denied(response, "ADVISOR_GRANT_REVOKED", status=401)
            assert await snapshot(sessions) == before
    asyncio.run(run())


async def invalidate(session, change):
    # Same user -> role -> grant order as central grant administration.
    user = await session.get(User, 7, with_for_update=True)
    role = await session.get(Role, 5, with_for_update=True)
    grant = await session.get(Grant, 10, with_for_update=True)
    if change in {"grant", "regrant"}:
        grant.revoked_at, grant.revoked_by, grant.revoke_reason = datetime.now(timezone.utc) + timedelta(seconds=1), 9, "admin_uncheck"
    elif change == "user":
        user.is_active = False
    elif change == "locked":
        user.locked_until = datetime.now() + timedelta(hours=1)
    elif change == "role":
        user.role_id = 6
    elif change == "edit":
        role.permissions = {**role.permissions, "seo.content": "view"}
    elif change == "assignment":
        assignment = await session.get(SeoSiteAdvisorAssignment, 3, with_for_update=True)
        assignment.active = False
    await session.flush()


@pytest.mark.parametrize("change", ["grant", "user", "edit"])
def test_http_revocation_after_guard_before_handler_commit(monkeypatch, complete_contract, change):
    """Control both transactions; accept only the two valid serialized outcomes."""
    switches(monkeypatch)
    async def run():
        passed_guard, resume = asyncio.Event(), asyncio.Event()
        async def boundary(request, ctx):
            passed_guard.set()
            await asyncio.wait_for(resume.wait(), 10)
        async with store() as sessions, client_for(sessions, boundary) as client:
            before = await snapshot(sessions)
            pending = asyncio.create_task(send(client, CASES[5]))
            revoke_won = False
            try:
                await asyncio.wait_for(passed_guard.wait(), 5)
                async with sessions() as revoker:
                    await revoker.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    try:
                        await invalidate(revoker, change)
                        await revoker.commit()
                        revoke_won = True
                    except DBAPIError as exc:
                        # Holding authorization locks from the guard through
                        # commit is also sound: that write precedes revocation.
                        # Only a real lock timeout is allowed in this branch.
                        await revoker.rollback()
                        assert getattr(exc.orig, "sqlstate", None) == "55P03"
            finally:
                resume.set()
            response = await asyncio.wait_for(pending, 10)
            if revoke_won:
                assert response.status_code in (401, 403), response.text
                assert await snapshot(sessions) == before
            else:
                assert response.status_code == 200, response.text
                async with sessions() as revoker:
                    await invalidate(revoker, change)
                    await revoker.commit()
                committed_before_revoke = await snapshot(sessions)
                response = await send(client, CASES[5])
                assert response.status_code in (401, 403), response.text
                assert await snapshot(sessions) == committed_before_revoke
    asyncio.run(run())


@pytest.mark.parametrize("change", ["grant", "user", "role", "edit"])
def test_commit_recheck_waits_for_revoker_and_rolls_back_staged_write(monkeypatch, complete_contract, change):
    """Native two-transaction test of the explicit commit hook contract.

    The cached ORM identities are deliberately loaded before revocation. No
    request re-authentication may mask a stale read in recheck_before_commit.
    """
    switches(monkeypatch)
    commit = importlib.import_module("app.security.advisor_write_commit")
    async def run():
        async with store() as sessions:
            before = await snapshot(sessions)
            async with sessions() as writer, sessions() as revoker:
                ctx = actor()
                ctx.advisor_write_rule = complete_contract.WRITE_ROUTES[(CASES[5].method, CASES[5].template)]
                cached = [await writer.get(model, ident) for model, ident in ((User, 7), (Role, 5), (Grant, 10))]
                assert all(cached)
                row = await writer.get(SeoContentAsset, 1)
                row.title = "MUST ROLL BACK"
                await writer.flush()
                await invalidate(revoker, change)
                started = asyncio.Event()
                async def try_commit():
                    started.set()
                    try:
                        await commit.recheck_advisor_before_commit(writer, ctx)
                        await writer.commit()
                    except Exception:
                        await writer.rollback()
                        raise
                pending = asyncio.create_task(try_commit())
                try:
                    await asyncio.wait_for(started.wait(), 5)
                    await asyncio.sleep(0.1)
                    assert not pending.done(), "commit check must serialize against revocation locks"
                finally:
                    await revoker.commit()
                from fastapi import HTTPException
                with pytest.raises(HTTPException) as caught:
                    await asyncio.wait_for(pending, 10)
                assert caught.value.status_code in (401, 403)
                if change == "grant":
                    assert caught.value.status_code == 401
                    assert caught.value.detail["code"] == "ADVISOR_GRANT_REVOKED"
            assert await snapshot(sessions) == before
    asyncio.run(run())


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_actual_handler_commit_invokes_recheck_and_rolls_back(monkeypatch, complete_contract, case):
    """A successful guard alone must not allow a commit after fresh denial."""
    switches(monkeypatch)
    commit = importlib.import_module("app.security.advisor_write_commit")
    from fastapi import HTTPException
    import sys
    called = []
    original = commit.recheck_advisor_before_commit
    def record_flush(session, _context):
        if any(isinstance(row, (SeoContentAsset, SeoBrandAsset, SeoQaFact))
               for row in (*session.new, *session.dirty)):
            session.info["scoped_write_test_flushed"] = True
    async def revoked(session, ctx):
        assert session.new or session.dirty or session.info.get("scoped_write_test_flushed"), (
            "recheck must run in the handler's business transaction, after staging the write")
        called.append(ctx.user_id)
        raise HTTPException(401, {"code": "ADVISOR_GRANT_REVOKED"})
    # Patch aliases too; production may import the contract at module scope.
    for name, module in tuple(sys.modules.items()):
        if name.startswith("app.") and getattr(module, "recheck_advisor_before_commit", None) is original:
            monkeypatch.setattr(module, "recheck_advisor_before_commit", revoked)
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            before = await snapshot(sessions)
            response = await send(client, case)
            assert_denied(response, "ADVISOR_GRANT_REVOKED", status=401)
            assert called == [7]
            assert await snapshot(sessions) == before
    event.listen(Session, "after_flush", record_flush)
    try:
        asyncio.run(run())
    finally:
        event.remove(Session, "after_flush", record_flush)


@pytest.mark.parametrize("user,case", [(8, CASES[5]), *((9, c) for c in CASES)],
                         ids=["customer-content", *("admin-" + name for name in CASE_IDS)])
@pytest.mark.parametrize("enabled", [False, True])
def test_non_advisor_actual_write_is_unchanged(monkeypatch, user, case, enabled):
    switches(monkeypatch, enabled=enabled)
    from test_advisor_tenant_auth import claims
    headers = {"Authorization": "Bearer " + jwt.encode({"sub": str(user), "exp": claims()["exp"]},
                "scoped-write-test-signing-key-only", algorithm=auth.JWT_ALG)}
    async def run():
        async with store() as sessions, client_for(sessions) as client:
            response = await send(client, case, headers=headers)
            assert response.status_code == 200, response.text
            async with sessions() as session:
                result = response.json()
                if "/qa/facts" in case.template:
                    row = await session.get(SeoQaFact, result["id"])
                    assert row.title == case.body["title"]
                elif "/brand-assets" in case.template:
                    row = await session.get(SeoBrandAsset, result["id"])
                    assert row.name == case.body["name"]
                else:
                    row = await session.get(SeoContentAsset, result["id"])
                    if case.method == "PUT":
                        assert row.source_page_id == 50
                    else:
                        assert row.title == case.body["title"]
                assert row.tenant_id == 4 and row.site_id == 2
    asyncio.run(run())
