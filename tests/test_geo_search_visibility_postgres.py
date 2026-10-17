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
from sqlalchemy import MetaData, func, select
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
        execution_options={"schema_translate_map": {None: schema}},
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
            assert sum(isinstance(x, sv.StopRun) for x in outcomes) == 1
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
