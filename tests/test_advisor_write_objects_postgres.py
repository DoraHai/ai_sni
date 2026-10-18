"""Opt-in isolated loopback PostgreSQL object ownership integration tests.

Only SEO_OBJECTS_TEST_DATABASE_URL with a database named seo_objects_test is
accepted; never fall back to the application DATABASE_URL. Each test creates a
random schema and drops only that schema. No migrations or providers are used.
"""
import asyncio
from contextlib import asynccontextmanager
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from app.models.module_workspace import SeoSite
from app.models.seo import SeoContentAsset, SeoKeywordAsset, SeoSiteAdvisorAssignment
from app.models.tenant import Tenant
from app.security.advisor_write_objects import check_write_objects, ensure_advisor_assignment
from app.security.auth import AuthContext


def dedicated_url(raw):
    try:
        url = make_url(raw)
    except Exception:
        raise ValueError("Invalid dedicated test URL") from None
    if (url.drivername != "postgresql+asyncpg" or url.host not in {"localhost", "127.0.0.1", "::1"}
            or url.database != "seo_objects_test" or url.query):
        raise ValueError("Only loopback asyncpg database seo_objects_test without query options is allowed")
    return url


@pytest.mark.parametrize("raw", [
    "postgresql+asyncpg://test@remote.invalid/seo_objects_test",
    "postgresql+asyncpg://test@127.0.0.1/production",
    "postgresql://test@127.0.0.1/seo_objects_test",
    "postgresql+asyncpg://test@127.0.0.1/seo_objects_test?host=remote.invalid",
])
def test_dedicated_database_guard(raw):
    with pytest.raises(ValueError):
        dedicated_url(raw)


@asynccontextmanager
async def database():
    raw = os.getenv("SEO_OBJECTS_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("No dedicated local PostgreSQL objects test database")
    url = dedicated_url(raw)
    if os.getenv("SEO_OBJECTS_TEST_ALLOW_SCHEMA_CREATE") != "yes":
        pytest.fail("Dedicated local test schema creation must be explicitly enabled")
    schema = "seo_objects_test_" + uuid4().hex
    engine = create_async_engine(url, connect_args={"server_settings": {
        "search_path": schema, "lock_timeout": "5000", "statement_timeout": "10000"}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            for model in (Tenant, SeoSite, SeoContentAsset, SeoKeywordAsset, SeoSiteAdvisorAssignment):
                await connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
        async with sessions() as session:
            session.add_all([
                Tenant(id=1, name="test1"), Tenant(id=2, name="test2"),
                SeoSite(id=11, tenant_id=1, tenant_module_id=1, name="one", domain="one.test", canonical_domain="one.test"),
                SeoSite(id=22, tenant_id=2, tenant_module_id=2, name="two", domain="two.test", canonical_domain="two.test"),
                SeoKeywordAsset(id=11, tenant_id=1, site_id=11, keyword="test"),
                SeoKeywordAsset(id=22, tenant_id=2, site_id=22, keyword="test"),
                SeoContentAsset(id=11, tenant_id=1, site_id=11, title="original", keyword_ids=[11]),
                SeoSiteAdvisorAssignment(id=11, tenant_id=1, site_id=11, advisor_user_id=7, active=True),
            ])
            await session.commit()
        yield sessions
    finally:
        try:
            if created:
                assert schema.startswith("seo_objects_test_") and len(schema) == len("seo_objects_test_") + 32
                async with engine.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            await engine.dispose()


def inputs():
    ctx = AuthContext(7, "test", "advisor", 1, {"seo.content": "edit"}, is_advisor=True,
                      scope_kind="advisor_tenant", grant_id=10, advisor_tenant_ids=frozenset({1, 2}))
    request = Request({"type": "http", "method": "PATCH", "path": "/test", "headers": [],
                       "query_string": b"tenant_id=1", "path_params": {"content_id": 11}})
    return ctx, request, SimpleNamespace(assignment="site")


def test_postgres_success_foreign_array_rejection_and_rollback():
    async def scenario():
        async with database() as sessions:
            ctx, req, rule = inputs()
            async with sessions() as session:
                await check_write_objects(session, ctx, req, {"keyword_ids": [11]}, rule)
                await ensure_advisor_assignment(session, ctx, req, {}, rule)
                await session.execute(update(SeoContentAsset).values(title="allowed").where(SeoContentAsset.id == 11))
                await session.commit()
                with pytest.raises(HTTPException) as error:
                    async with session.begin():
                        await session.execute(update(SeoContentAsset).values(title="must-rollback").where(SeoContentAsset.id == 11))
                        await check_write_objects(session, ctx, req, {"refs": [{"keyword_ids": [11, 22]}]}, rule)
                assert error.value.status_code == 403
            async with sessions() as verify:
                assert (await verify.get(SeoContentAsset, 11)).title == "allowed"
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["owner", "assignment"])
def test_postgres_new_sql_read_ignores_stale_identity_map(change):
    async def scenario():
        async with database() as sessions:
            ctx, req, rule = inputs()
            async with sessions() as request_session, sessions() as admin_session:
                content = await request_session.get(SeoContentAsset, 11)
                assignment = await request_session.get(SeoSiteAdvisorAssignment, 11)
                await check_write_objects(request_session, ctx, req, {}, rule)
                await ensure_advisor_assignment(request_session, ctx, req, {}, rule)
                if change == "owner":
                    await admin_session.execute(update(SeoContentAsset).where(SeoContentAsset.id == 11)
                                                .values(tenant_id=2, site_id=22))
                else:
                    await admin_session.execute(update(SeoSiteAdvisorAssignment).where(SeoSiteAdvisorAssignment.id == 11)
                                                .values(active=False))
                await admin_session.commit()
                # ORM values remain stale in this READ COMMITTED transaction.
                assert content.tenant_id == 1 and assignment.active
                with pytest.raises(HTTPException) as error:
                    if change == "owner":
                        await check_write_objects(request_session, ctx, req, {}, rule)
                    else:
                        await ensure_advisor_assignment(request_session, ctx, req, {}, rule)
                assert error.value.detail["code"] == (
                    "ADVISOR_TENANT_NOT_GRANTED" if change == "owner" else "ADVISOR_ASSIGNMENT_REQUIRED")
    asyncio.run(scenario())
