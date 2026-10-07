"""Opt-in LOCAL dedicated PostgreSQL tests. No migrations or real providers.

Requires SEO_WORKFLOW_TEST_DATABASE_URL and SEO_WORKFLOW_TEST_ALLOW_SCHEMA_CREATE=yes.
Only loopback / database seo_workflow_test is accepted. Each test owns one random
schema and drops only that schema; never falls back to application DATABASE_URL.
"""
import asyncio
from contextlib import asynccontextmanager
import os
from unittest.mock import AsyncMock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, func
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.schema import CreateTable

from app import seo_content_workflow as flow, seo_content_drafting as drafts, seo_ai_operations as ops
from app.api import seo as api
from app.models.module_workspace import TenantModule, SeoSite
from app.models.seo import (SeoContentAsset, SeoContentConfirmation, SeoContentPublication, SeoSiteAdvisorAssignment,
                            SeoKeywordAsset, SeoAiOperation)
from app.models.seo_cockpit import SeoTask
from app.models.seo_page_capture import SeoPageCapture
from app.models.seo_qa import SeoQaFact
from app.models.tenant import Tenant
from app.models.user import User
from app.models.role import Role
from app.security.auth import AuthContext

ADVISOR = AuthContext(7, "test-advisor", "test", None,
                     {"seo.content": "edit", "seo.site": "edit", "seo.keywords": "edit"})
requires_pg = pytest.mark.skipif(not os.getenv("SEO_WORKFLOW_TEST_DATABASE_URL"), reason="no dedicated local PostgreSQL test DSN")


def dedicated_url(raw):
    try:
        url = make_url(raw)
    except Exception:
        raise ValueError("Invalid dedicated test database URL") from None
    if (url.drivername != "postgresql+asyncpg" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or url.database != "seo_workflow_test" or url.query):
        raise ValueError("Only loopback asyncpg database seo_workflow_test without URL query options is allowed")
    return url


@pytest.mark.parametrize("raw", [
    "postgresql+asyncpg://local:local@example.com/seo_workflow_test",
    "postgresql+asyncpg://local:local@127.0.0.1/production",
    "postgresql://local:local@127.0.0.1/seo_workflow_test",
    "postgresql+asyncpg://local:local@127.0.0.1/seo_workflow_test?host=example.com",
])
def test_environment_guard_rejects_other_hosts_databases_drivers_options(raw):
    with pytest.raises(ValueError): dedicated_url(raw)


@asynccontextmanager
async def database():
    if os.getenv("SEO_WORKFLOW_TEST_ALLOW_SCHEMA_CREATE") != "yes":
        pytest.fail("Set SEO_WORKFLOW_TEST_ALLOW_SCHEMA_CREATE=yes for the dedicated local test database only")
    url = dedicated_url(os.environ["SEO_WORKFLOW_TEST_DATABASE_URL"])
    schema = "seo_workflow_test_" + uuid4().hex
    engine = create_async_engine(url, pool_size=12, max_overflow=0, connect_args={"server_settings": {
        "search_path": schema, "lock_timeout": "5000", "statement_timeout": "15000"}})
    created = False
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            models = (Tenant, Role, User, TenantModule, SeoSite, SeoSiteAdvisorAssignment, SeoContentAsset,
                      SeoContentConfirmation, SeoContentPublication, SeoTask, SeoPageCapture, SeoKeywordAsset, SeoQaFact, SeoAiOperation)
            for model in models:
                await connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
            await connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
            await connection.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": flow.SCHEMA})
        async with sessions() as session:
            session.add_all([
                Tenant(id=4, name="isolated"), Role(id=5, name="test", permissions=ADVISOR.permissions),
                User(id=7, username="test", password_hash="unused", role_id=5, is_active=True),
                TenantModule(id=1, tenant_id=4, module_code="seo", status="active"),
                SeoSite(id=2, tenant_id=4, tenant_module_id=1, name="isolated", domain="example.com",
                    canonical_domain="example.com", status="active", site_settings={"seo_service_plan": {
                        "revision": 1, "status": "active", "optimization_directions": ["fact based"],
                        "content_topics": ["selection"], "content_cycle_enabled": True}}),
                SeoSiteAdvisorAssignment(id=3, tenant_id=4, site_id=2, advisor_user_id=7, active=True),
                SeoKeywordAsset(id=20, tenant_id=4, site_id=2, keyword="selection", status="active"),
                SeoQaFact(id=30, tenant_id=4, site_id=2, title="selection", statement="Read official guidance.",
                    source_name="fixture", status="active", version=1),
            ])
            await session.commit()
        yield sessions
    finally:
        try:
            if created:
                assert schema.startswith("seo_workflow_test_") and len(schema) == len("seo_workflow_test_") + 32
                async with engine.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await engine.dispose()


async def trigger(sessions, key):
    async with sessions() as session:
        return await api.trigger_content_workflow(api.ContentWorkflowTrigger(
            tenant_id=4, site_id=2, expected_revision=1, request_id=key), session, ADVISOR)


@requires_pg
@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_content_reservations_create_one_task_and_asset(same_key):
    async def scenario():
        async with database() as sessions:
            key = uuid4()
            results = await asyncio.gather(*(trigger(sessions, key if same_key else uuid4()) for _ in range(12)), return_exceptions=True)
            assert sum(isinstance(r, dict) and r["created"] for r in results) == 1
            if same_key:
                assert all(isinstance(r, dict) for r in results)
            else:
                assert sum(isinstance(r, HTTPException) and r.status_code == 409 for r in results) == 11
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoTask)) == 1
                assert await session.scalar(select(func.count()).select_from(SeoContentAsset)) == 1
    asyncio.run(scenario())


@requires_pg
def test_concurrent_cycle_ticks_do_not_duplicate_cursor_or_task(monkeypatch):
    async def scenario():
        async with database() as sessions:
            monkeypatch.setattr(flow, "async_session_factory", sessions)
            await asyncio.gather(*(flow.process_site(2) for _ in range(12)))
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoTask)) == 1
                assert (await session.get(SeoSite, 2)).site_settings["seo_content_workflow_cursor"]["sequence"] == 1
    asyncio.run(scenario())


@requires_pg
def test_committed_advisor_revocation_wins_against_waiting_reservation():
    async def scenario():
        async with database() as sessions:
            async with sessions() as revoker:
                assignment = await revoker.get(SeoSiteAdvisorAssignment, 3, with_for_update=True)
                assignment.active = False
                await revoker.flush()
                pending = asyncio.create_task(trigger(sessions, uuid4()))
                try:
                    await asyncio.sleep(0.1)
                    assert not pending.done()
                finally:
                    await revoker.commit()
                with pytest.raises(HTTPException) as exc:
                    await asyncio.wait_for(pending, timeout=10)
                assert exc.value.status_code == 403
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoTask)) == 0
    asyncio.run(scenario())


@requires_pg
def test_concurrent_draft_workers_call_provider_and_charge_only_once(monkeypatch):
    async def scenario():
        async with database() as sessions:
            for module in (flow, drafts, ops): monkeypatch.setattr(module, "async_session_factory", sessions)
            monkeypatch.setattr(api, "is_enabled", lambda: True)
            monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(seo_ai_max_requests_per_tenant_per_day=5))
            async with sessions() as session:
                site = await session.get(SeoSite, 2)
                site.site_settings = {"seo_service_plan": {**site.site_settings["seo_service_plan"],
                    "content_ai_enabled": True, "content_ai_authorized_by": 7,
                    "content_ai_fact_ids": [30], "content_ai_keyword_ids": [20]}}
                await session.commit()
            ident = (await trigger(sessions, uuid4()))["task"]["id"]
            started, release = asyncio.Event(), asyncio.Event()
            async def provider(*args, **kwargs):
                started.set()
                await release.wait()
                return {"title": "selection", "outline": "Guidance", "content": "selection: Read official guidance.[F30]"}
            mocked = AsyncMock(side_effect=provider)
            monkeypatch.setattr(api, "chat_json", mocked)
            first = asyncio.create_task(drafts.execute_content_draft(ident))
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                await asyncio.wait_for(asyncio.gather(*(drafts.execute_content_draft(ident) for _ in range(10))), timeout=15)
            finally:
                release.set()
                await asyncio.wait_for(first, timeout=10)
            mocked.assert_awaited_once()
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoAiOperation)) == 1
                assert (await session.get(TenantModule, 1)).module_settings["seo_daily_usage"]["ai_requests"] == 1
                assert (await session.get(SeoTask, ident)).params["ai_draft"]["status"] == "succeeded"
    asyncio.run(scenario())


@requires_pg
def test_manual_registration_waits_for_concurrent_edit_then_rejects_old_version(monkeypatch):
    async def scenario():
        async with database() as sessions:
            await trigger(sessions, uuid4())
            async with sessions() as session:
                content = await session.scalar(select(SeoContentAsset))
                content.status, content.draft = "ready", "Approved original"
                await session.flush()
                ident, source_hash = content.id, api._content_confirmation_hash(content)
                session.add(SeoContentConfirmation(tenant_id=4, site_id=2, content_asset_id=ident,
                    content_version=1, content_hash=source_hash, decision="approve", actor_mode="advisor_proxy",
                    actor_user_id=7, actor_role_name="test"))
                await session.commit()
            queued = AsyncMock()
            monkeypatch.setattr(api, "_queue_published_page_verification", queued)
            async def register():
                async with sessions() as session:
                    return await api.create_manual_publication(api.DistributionManualPublicationCreate(
                        tenant_id=4, site_id=2, content_id=ident, source_version=1, payload_hash=source_hash,
                        platform_name="test", page_url="https://example.com/article"), session, ADVISOR)
            async with sessions() as editor:
                content = await editor.get(SeoContentAsset, ident, with_for_update=True)
                content.draft, content.version_count = "Concurrent change", 2
                await editor.flush()
                pending = asyncio.create_task(register())
                try:
                    await asyncio.sleep(0.1)
                    assert not pending.done()
                finally:
                    await editor.commit()
                with pytest.raises(HTTPException) as exc:
                    await asyncio.wait_for(pending, timeout=10)
                assert exc.value.status_code == 409 and exc.value.detail["code"] == "content_version_conflict"
            queued.assert_not_awaited()
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoContentPublication)) == 0
    asyncio.run(scenario())
