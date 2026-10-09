"""Durable collection, revocation and native PostgreSQL claim concurrency."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from test_seo_service_workflows import store, create, task
from app import seo_analytics_cycles as cycles
from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import SeoSiteAdvisorAssignment
from app.models.user import User
from app.models.role import Role
from app.models.seo_site_analytics import SeoSiteAnalyticsSource, SeoSiteAnalyticsMonthly
from app.seo_site_analytics import AnalyticsError

NOW = datetime(2026, 10, 9, 3, tzinfo=timezone.utc)
requires_pg = pytest.mark.skipif(not os.getenv("SEO_USAGE_TEST_DATABASE_URL"), reason="requires dedicated PostgreSQL")


@asynccontextmanager
async def database():
    url = make_url(os.environ["SEO_USAGE_TEST_DATABASE_URL"])
    assert url.drivername == "postgresql+asyncpg" and url.host in {"127.0.0.1", "localhost"}
    assert (url.database, url.username) in {("test", "test"), ("seo_workflow_test", "seo_workflow_tester")} and not url.query
    schema = "seo_analytics_test_" + uuid4().hex
    engine = create_async_engine(url, pool_size=10, connect_args={"server_settings": {
        "search_path": schema, "lock_timeout": "5000", "statement_timeout": "15000"}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            for model in (SeoSite, TenantModule, SeoSiteAdvisorAssignment, User, Role):
                await connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
        async with sessions() as session:
            session.add_all([TenantModule(id=1, tenant_id=4, module_code="seo", status="active"),
                Role(id=5, name="fixture", permissions={"seo.site": "edit", "seo.content": "edit"}),
                User(id=7, username="fixture", role_id=5, password_hash="unused", is_active=True),
                SeoSite(id=2, tenant_id=4, tenant_module_id=1, name="fixture", domain="example.com", canonical_domain="example.com",
                    status="active", site_settings={"seo_service_plan": {"revision": 1}}),
                SeoSiteAdvisorAssignment(id=3, tenant_id=4, site_id=2, advisor_user_id=7, active=True)])
            await session.commit()
        yield sessions
    finally:
        try:
            if created:
                assert schema.startswith("seo_analytics_test_") and len(schema) == len("seo_analytics_test_")+32
                async with engine.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            await engine.dispose()


def configured(store, monkeypatch):
    store.edit_plan(analytics_cycle_enabled=True)
    with store.engine.begin() as connection:
        for model in (User, Role):
            connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
    with Session(store.engine) as db:
        db.add_all([Role(id=5, name="fixture", permissions={"seo.site": "edit", "seo.content": "edit"}),
                    User(id=7, username="fixture", password_hash="unused", role_id=5, is_active=True)])
        db.add(SeoSiteAnalyticsSource(id=50, tenant_id=4, site_id=2, source="ga4", enabled=True,
                                     config={"property_id": "1"}))
        db.commit()
    provider = AsyncMock(return_value=(25, 50, {"method": "fixture"}))
    monkeypatch.setattr(cycles, "fetch_provider", provider)
    return provider


def run(store, now=NOW):
    asyncio.run(cycles.collect_site_analytics(2, provider=object(), now=now, session_factory=store.session))


def cursors(store):
    with Session(store.engine) as db:
        return db.get(SeoSite, 2).site_settings["seo_analytics_cycles"]


def test_previous_month_once_and_current_month_daily_refresh(store, monkeypatch):
    provider = configured(store, monkeypatch)
    run(store)
    run(store)
    run(store)
    assert provider.await_count == 2
    assert cursors(store)["ga4:2026-09"]["state"] == "complete"
    assert cursors(store)["ga4:2026-10"]["state"] == "refresh_wait"
    run(store, NOW + timedelta(hours=25))
    assert provider.await_count == 3
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoSiteAnalyticsMonthly)) == 2
        assert db.scalar(select(SeoSiteAnalyticsMonthly).where(SeoSiteAnalyticsMonthly.month == "2026-09")).uv == 25


def test_transient_failure_retries_three_times_then_requires_advisor(store, monkeypatch):
    provider = configured(store, monkeypatch)
    provider.side_effect = AnalyticsError("provider_error", "secret should not be saved")
    run(store)
    run(store, NOW + timedelta(minutes=10))
    assert cursors(store)["ga4:2026-09"]["attempts"] == 1
    run(store, NOW + timedelta(minutes=16))
    run(store, NOW + timedelta(minutes=47))
    assert cursors(store)["ga4:2026-09"]["state"] == "needs_attention"
    run(store, NOW + timedelta(hours=3))  # Current month may start; closed failed month cannot replay.
    assert cursors(store)["ga4:2026-09"]["attempts"] == 3
    assert "secret" not in str(cursors(store))


def test_authorization_failure_waits_for_changed_configuration(store, monkeypatch):
    provider = configured(store, monkeypatch)
    provider.side_effect = AnalyticsError("ga4_forbidden", "forbidden")
    run(store)
    assert cursors(store)["ga4:2026-09"]["state"] == "authorization_required"
    provider.side_effect = None
    with Session(store.engine) as db:
        source = db.get(SeoSiteAnalyticsSource, 50)
        source.config = {"property_id": "2"}
        db.commit()
    run(store)
    assert cursors(store)["ga4:2026-09"]["state"] == "complete"


@pytest.mark.parametrize("change", ["pause", "revoke", "source", "revision", "advisor_disabled", "role_revoked"])
def test_changes_during_provider_request_discard_result(store, monkeypatch, change):
    configured(store, monkeypatch)
    async def response(*args):
        with Session(store.engine) as db:
            if change == "revoke":
                db.get(TenantModule, 1).status = "disabled"
            elif change == "source":
                db.get(SeoSiteAnalyticsSource, 50).enabled = False
            elif change == "advisor_disabled":
                db.get(User, 7).is_active = False
            elif change == "role_revoked":
                db.get(Role, 5).permissions = {"seo.site": "view", "seo.content": "edit"}
            else:
                site = db.get(SeoSite, 2)
                plan = {**site.site_settings["seo_service_plan"], **({"status": "paused"} if change == "pause" else {"revision": 2})}
                site.site_settings = {**site.site_settings, "seo_service_plan": plan}
            db.commit()
        return 1, 2, {}
    monkeypatch.setattr(cycles, "fetch_provider", response)
    run(store)
    assert cursors(store)["ga4:2026-09"]["state"] == "discarded"
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoSiteAnalyticsMonthly)) == 0


def test_report_waits_for_collection_and_preserves_failure_disclosure(store, monkeypatch):
    configured(store, monkeypatch)
    store.edit_plan(report_cycle_enabled=True)
    ident = create(store, "report")["task"]["id"]
    from app import seo_service_workflows as workflows
    async def advance():
        async with store.session() as session:
            row = await session.get(workflows.SeoTask, ident)
            site = await session.get(SeoSite, 2)
            row.params = {**row.params, "month": "2026-09"}
            await workflows.advance_service_workflow(session, site, row)
            await session.commit()
    asyncio.run(advance())
    assert task(store, ident).params["phase"] == "awaiting_analytics_collection"
    run(store)
    asyncio.run(advance())
    report = task(store, ident).params["report"]
    assert report["analytics_row_ids"]
    assert report["analytics_collection"][0]["state"] == "complete"
    assert "25" in report["html"]


def test_public_projection_excludes_claim_and_secret_metadata(store, monkeypatch):
    configured(store, monkeypatch)
    run(store)
    with Session(store.engine) as db:
        result = str(cycles.public_cycles(db.get(SeoSite, 2)))
    assert "configuration_version" not in result
    assert "token" not in result


def test_authorization_failure_blocks_report_until_named_advisor_accepts_missing_data(store, monkeypatch):
    provider = configured(store, monkeypatch)
    provider.side_effect = AnalyticsError("ga4_forbidden", "private")
    store.edit_plan(report_cycle_enabled=True)
    ident = create(store, "report")["task"]["id"]
    run(store)
    from app import seo_service_workflows as workflows
    async def advance(allow=False, actor=None):
        async with store.session() as db:
            row = await db.get(workflows.SeoTask, ident)
            row.params = {**row.params, "month": "2026-09"}
            await workflows.advance_service_workflow(db, await db.get(SeoSite, 2), row,
                allow_incomplete_analytics=allow, actor_id=actor)
            await db.commit()
    asyncio.run(advance())
    assert task(store, ident).params["phase"] == "report_needs_attention"
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        asyncio.run(advance(True))
    asyncio.run(advance(True, 7))
    params = task(store, ident).params
    assert params["analytics_incomplete_ack"]["actor_user_id"] == 7
    assert params["report"]["analytics_collection"][0]["state"] == "authorization_required"
    assert "private" not in params["report"]["html"]


@requires_pg
def test_native_postgres_concurrent_claims_and_revocation(monkeypatch):
    async def scenario():
        async with database() as sessions:
            async with sessions() as session:
                for model in (SeoSiteAnalyticsSource, SeoSiteAnalyticsMonthly):
                    await session.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
                site = await session.get(SeoSite, 2)
                site.site_settings = {**site.site_settings, "seo_service_plan": {
                    **site.site_settings["seo_service_plan"], "analytics_cycle_enabled": True}}
                session.add(SeoSiteAnalyticsSource(id=50, tenant_id=4, site_id=2, source="ga4", enabled=True,
                                                  config={"property_id": "1"}))
                await session.commit()
            started, release = asyncio.Event(), asyncio.Event()
            calls = []
            async def provider(*args):
                calls.append(1)
                started.set()
                await release.wait()
                return 1, 2, {}
            monkeypatch.setattr(cycles, "fetch_provider", provider)
            first = asyncio.create_task(cycles.collect_site_analytics(2, provider=object(), now=NOW, session_factory=sessions))
            await asyncio.wait_for(started.wait(), 5)
            await asyncio.gather(*(cycles.collect_site_analytics(2, provider=object(), now=NOW, session_factory=sessions) for _ in range(8)))
            assert len(calls) == 1
            # Provider is in flight; revocation must not wait on its database locks.
            async with sessions() as session:
                module = await session.get(TenantModule, 1, with_for_update=True)
                module.status = "disabled"
                await session.commit()
            release.set()
            await first
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoSiteAnalyticsMonthly)) == 0
                site = await session.get(SeoSite, 2)
                assert site.site_settings["seo_analytics_cycles"]["ga4:2026-09"]["state"] == "discarded"
    asyncio.run(scenario())
