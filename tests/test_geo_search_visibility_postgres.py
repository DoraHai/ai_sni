"""Native races and durable accounting in a random, disposable loopback schema.

No migrations, business data, supplier network or non-loopback DB are used.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import BigInteger, Column, MetaData, String, Table, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.geo.content import search_visibility as sv
from app.models import GeoAsyncJob, GeoProject, Tenant, TenantModule


@asynccontextmanager
async def database(monkeypatch):
    url = os.environ.get("GEO_SEARCH_TEST_DATABASE_URL") or os.environ.get("PLATFORM_ADMIN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable GEO_SEARCH_TEST_DATABASE_URL")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg" and parsed.host == "127.0.0.1"
    assert parsed.database in {"postgres", "platform_admin_test", "geo_search_test", "geo_ci"}
    schema = "geo_search_test_" + uuid4().hex
    engine = create_async_engine(url, pool_size=3, max_overflow=0,
        execution_options={"schema_translate_map": {None: schema, "public": schema}},
        connect_args={"server_settings": {"statement_timeout": "10000"}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(sv, "engine", engine)
    monkeypatch.setattr(sv, "async_session_factory", factory)
    monkeypatch.setattr(sv.LIMITER, "wait", AsyncMock())
    monkeypatch.setattr(sv, "article_urls", AsyncMock(return_value=[]))
    from types import SimpleNamespace
    monkeypatch.setattr(sv, "get_settings", lambda: SimpleNamespace(
        deepseek_search_api_key="synthetic-only", deepseek_search_base_url="https://api.deepseek.com",
        deepseek_search_run_request_limit=60, deepseek_search_monthly_limit_cny=30, deepseek_search_qps=4))
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            metadata = MetaData()
            for model in (Tenant, TenantModule, GeoProject, GeoAsyncJob):
                model.__table__.to_metadata(metadata)
            Table("demo_tenant_bindings", metadata,
                Column("tenant_id", BigInteger, primary_key=True),
                Column("demo_tenant_id", BigInteger), Column("dataset_key", String),
                Column("dataset_version", String), Column("status", String),
                Column("version", BigInteger), schema="public")
            # Lightweight production table clauses do not apply schema translation.
            # Use equivalent Tables so the real guard stays in our disposable schema.
            from app.geo import tenant_scope
            monkeypatch.setattr(tenant_scope, "_TENANT_MODULES", metadata.tables["tenant_modules"])
            monkeypatch.setattr(tenant_scope, "_DEMO_BINDINGS", metadata.tables["public.demo_tenant_bindings"])
            await connection.run_sync(metadata.create_all)
        created = True
        async with factory() as session:
            session.add(Tenant(id=1, name="合成测试客户"))
            await session.flush()
            session.add(TenantModule(id=1, tenant_id=1, module_code="geo", status="active"))
            await session.flush()
            for i in (1, 2):
                session.add(GeoProject(id=i, tenant_id=1, tenant_module_id=1, name=f"合成项目{i}",
                    primary_domain=f"site{i}.example.com", canonical_domain=f"site{i}.example.com",
                    project_settings={"deepseek_visibility": {"enabled": True}}))
            await session.commit()
        yield factory
    finally:
        if created:
            assert schema.startswith("geo_search_test_") and len(schema) == 48
            async with engine.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


async def admit(factory, project_id=1):
    async with factory() as session:
        project = await session.get(GeoProject, project_id)
        config = sv.VisibilityConfig(enabled=True, domains=[project.primary_domain])
        return await sv.create_run(session, project, config, trigger="manual", actor=7)


def supplier_mock(monkeypatch, paths):
    original = httpx.AsyncClient
    async def handler(request):
        paths.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json={"is_available": True})
        await asyncio.sleep(.01)
        return httpx.Response(200, json={"results": [{"url": "https://site1.example.com/cn", "title": "官网"}]})
    monkeypatch.setattr(sv.httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))


def test_simultaneous_manual_admission_is_atomic(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as factory:
            outcomes = await asyncio.gather(admit(factory), admit(factory), return_exceptions=True)
            assert sum(isinstance(x, sv.StopRun) for x in outcomes) == 1, outcomes
            async with factory() as session:
                assert await session.scalar(select(func.count()).select_from(GeoAsyncJob)) == 1
    asyncio.run(scenario())


def test_two_workers_respect_global_month_budget_and_persist_first_attempt(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as factory:
            async with factory() as session:
                session.add(GeoAsyncJob(tenant_id=1, kind=sv.KIND, status="succeeded", ref_type="geo_project", ref_id=1,
                    request_meta={"trigger": "schedule"}, result_meta={"monthly_usage": {
                        sv.month_key(): {"requests": 5999, "billable": 5999, "reserved_billable": 0}}}))
                await session.commit()
            first, second = await admit(factory, 1), await admit(factory, 2)
            paths = []
            supplier_mock(monkeypatch, paths)
            await asyncio.gather(sv.execute_run(first.id), sv.execute_run(second.id))
            async with factory() as session:
                usage = await sv.month_usage(session)
                assert usage["cost_cny"] == 30 and usage["reserved_cny"] == 0
                row = await session.get(GeoAsyncJob, first.id)
                assert row.result_meta["summary"]["requests"] == 2
                assert row.result_meta["summary"]["billable"] == 1
                assert row.result_meta["summary"]["indexed_count"] == 1
                blocked = await session.get(GeoAsyncJob, second.id)
                assert blocked.error == sv.MONTH_LIMIT
            assert paths == ["/user/balance", "/v1/tools/search"]
    asyncio.run(scenario())


def test_duplicate_worker_executes_supplier_once(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as factory:
            job = await admit(factory)
            paths = []
            supplier_mock(monkeypatch, paths)
            await asyncio.gather(sv.execute_run(job.id), sv.execute_run(job.id))
            assert paths == ["/user/balance", "/v1/tools/search"]
            async with factory() as session:
                row = await session.get(GeoAsyncJob, job.id)
                assert row.status == "succeeded"
                assert row.result_meta["summary"]["cost_cny"] == .005
    asyncio.run(scenario())


def test_abandoned_running_retains_reservation_and_never_replays(monkeypatch):
    async def scenario():
        async with database(monkeypatch) as factory:
            job = await admit(factory)
            async with factory() as session:
                row = await session.get(GeoAsyncJob, job.id)
                row.status = "running"
                result = sv.empty_result(sv.VisibilityConfig(), 0)
                result["monthly_usage"] = {sv.month_key(): {"requests": 1, "billable": 0, "reserved_billable": 1}}
                result["summary"].update(requests=1, reserved_cny=.005)
                row.result_meta = result
                await session.commit()
            paths = []
            supplier_mock(monkeypatch, paths)
            await sv.execute_run(job.id)
            assert not paths
            async with factory() as session:
                row = await session.get(GeoAsyncJob, job.id)
                assert row.status == "failed" and "未重新请求" in row.error
                assert (await sv.month_usage(session))["reserved_cny"] == .005
    asyncio.run(scenario())


async def bind_demo(factory, *, status="active", dataset_version="synthetic-v1"):
    from app.geo.tenant_scope import _DEMO_BINDINGS
    async with factory() as session:
        await session.execute(_DEMO_BINDINGS.insert().values(
            tenant_id=1, demo_tenant_id=10001, dataset_key="gsnipers_demo",
            dataset_version=dataset_version, status=status, version=1))
        await session.commit()


@pytest.mark.parametrize("status,version", [("active", "synthetic-v1"), ("disabled", "synthetic-v1"), ("active", "")])
def test_demo_and_invalid_binding_reject_admission_without_job(monkeypatch, status, version):
    """Regression of policy-gap-reproduction.py using the real existing guard."""
    from app.geo.tenant_scope import GeoEntitlementUnavailable
    async def scenario():
        async with database(monkeypatch) as factory:
            await bind_demo(factory, status=status, dataset_version=version)
            with pytest.raises(GeoEntitlementUnavailable) as error:
                await admit(factory)
            assert error.value.status_code == 403
            assert error.value.detail["code"] == "geo_not_available"
            async with factory() as session:
                assert await session.scalar(select(func.count()).select_from(GeoAsyncJob)) == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["active", "disabled"])
@pytest.mark.parametrize("running", [False, True])
def test_recovery_denies_old_work_after_demo_binding(monkeypatch, status, running, caplog):
    from app.geo import scheduler
    async def scenario():
        async with database(monkeypatch) as factory:
            job = await admit(factory)
            if running:
                async with factory() as session:
                    row = await session.get(GeoAsyncJob, job.id)
                    row.status = "running"
                    await session.commit()
            await bind_demo(factory, status=status)
            paths = []
            supplier_mock(monkeypatch, paths)
            monkeypatch.setattr(scheduler, "async_session_factory", factory)
            monkeypatch.setattr(scheduler, "get_settings", sv.get_settings)
            with caplog.at_level("INFO"):
                await scheduler.resume_geo_search_visibility()
            async with factory() as session:
                row = await session.get(GeoAsyncJob, job.id)
                assert row.status == "failed"
                assert row.error == "该客户未开通 GEO、已停用或已到期"
                assert row.result_meta["summary"]["stopped_reason"] == row.error
            assert not paths and "blocked" in caplog.text
    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["active", "disabled"])
def test_weekly_scheduler_skips_demo_and_invalid_binding(monkeypatch, status, caplog):
    from app.geo import scheduler
    async def scenario():
        async with database(monkeypatch) as factory:
            await bind_demo(factory, status=status)
            monkeypatch.setattr(scheduler, "async_session_factory", factory)
            monkeypatch.setattr(scheduler, "get_settings", sv.get_settings)
            monkeypatch.setattr(asyncio, "sleep", AsyncMock())
            paths = []
            supplier_mock(monkeypatch, paths)
            with caplog.at_level("INFO"):
                await scheduler.run_geo_search_visibility()
            async with factory() as session:
                assert await session.scalar(select(func.count()).select_from(GeoAsyncJob)) == 0
            assert not paths and "skipped" in caplog.text
    asyncio.run(scenario())


@pytest.mark.parametrize("revoke_at", ["balance", "search", "retry", "before_send"])
def test_permission_change_stops_next_supplier_request_and_preserves_usage(monkeypatch, revoke_at):
    async def scenario():
        async with database(monkeypatch) as factory:
            job = await admit(factory)
            paths = []
            original = httpx.AsyncClient
            async def revoke(*_):
                # Independent transaction must commit while provider call is in flight.
                async with factory() as session:
                    module = await session.get(TenantModule, 1)
                    module.status = "disabled"
                    await session.commit()
            async def handler(request):
                paths.append(request.url.path)
                if request.method == "GET":
                    if revoke_at == "balance":
                        await revoke()
                    return httpx.Response(200, json={"is_available": True})
                await revoke()
                return httpx.Response(503 if revoke_at == "retry" else 200,
                    json={"results": [{"url": "https://site1.example.com/cn"}]})
            monkeypatch.setattr(sv.httpx, "AsyncClient", lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
            if revoke_at == "before_send":
                monkeypatch.setattr(sv.LIMITER, "wait", AsyncMock(side_effect=revoke))
            await sv.execute_run(job.id)
            assert paths == ([] if revoke_at == "before_send" else ["/user/balance"] if revoke_at == "balance"
                             else ["/user/balance", "/v1/tools/search"])
            async with factory() as session:
                row = await session.get(GeoAsyncJob, job.id)
                assert row.status == "failed" and "未开通 GEO" in row.error
                assert row.result_meta["summary"]["stopped_reason"] == row.error
                if revoke_at == "search":
                    assert row.result_meta["summary"]["billable"] == 1
                    assert (await sv.month_usage(session))["cost_cny"] == .005
    asyncio.run(scenario())
