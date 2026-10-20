from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.customer_modules import (
    SeoSiteCreate,
    create_seo_site,
    list_seo_sites,
    seo_sites_router,
)
from app.database import get_session
from app.models import SeoSite, Tenant, TenantModule
from app.security.auth import AuthContext, require_auth


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class ReadOnlySiteScope:
    """Read-only handler stub; transaction claims are covered by PostgreSQL below."""

    def __init__(self, module, sites=()):
        self.module = module
        self.sites = list(sites)
        self.scalar_calls = 0
        self.scalars_calls = 0

    async def scalar(self, _statement):
        self.scalar_calls += 1
        return self.module

    async def scalars(self, _statement):
        self.scalars_calls += 1
        return _Rows(self.sites)


def _module(tenant_id=4):
    return SimpleNamespace(
        id=44,
        tenant_id=tenant_id,
        module_code="seo",
        status="trial",
        expires_at=date.today() + timedelta(days=30),
    )


def _actor(*, tenant_id=4, permissions=None):
    return AuthContext(
        user_id=9,
        username="site-onboarding-test",
        role_name="client",
        tenant_id=tenant_id,
        permissions=permissions or {},
    )


def _client(session, actor):
    app = FastAPI()
    app.include_router(seo_sites_router)

    async def auth_override():
        return actor

    async def session_override():
        yield session

    # Do not override require_scoped_auth. Its real dependency graph consumes
    # this require_auth override, then enforces _required and tenant query scope.
    app.dependency_overrides[require_auth] = auth_override
    app.dependency_overrides[get_session] = session_override
    return TestClient(app)


def test_trial_without_active_site_runs_real_scoped_auth_and_returns_empty_scope():
    session = ReadOnlySiteScope(_module())
    response = _client(
        session,
        _actor(permissions={"seo.content": "view"}),
    ).get("/api/v1/seo/workbench/sites", params={"tenant_id": 4})

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": 4,
        "selection_policy": {
            "selectable_statuses": ["active"],
            "disabled_statuses": ["paused", "archived"],
        },
        "sites": [],
    }
    assert session.scalar_calls == 1
    assert session.scalars_calls == 1


@pytest.mark.parametrize(
    ("actor", "tenant_id", "detail"),
    [
        (_actor(permissions={}), 4, "当前角色无权访问此功能"),
        (
            _actor(tenant_id=4, permissions={"seo.site": "view"}),
            5,
            "无权访问该客户的数据",
        ),
    ],
)
def test_scoped_auth_rejects_missing_permission_and_tenant_query_conflict(
    actor, tenant_id, detail
):
    session = ReadOnlySiteScope(_module())
    response = _client(session, actor).get(
        "/api/v1/seo/workbench/sites",
        params={"tenant_id": tenant_id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == detail
    assert session.scalar_calls == 0
    assert session.scalars_calls == 0


@pytest.mark.skipif(
    not os.getenv("SEO_USAGE_TEST_DATABASE_URL"),
    reason="requires isolated PostgreSQL; handler-only evidence runs without it",
)
def test_postgres_canonical_create_conflict_rollback_and_readback_contract():
    """Exercise the real unique constraint and same-session rollback semantics."""

    async def scenario():
        schema = "seo_site_onboarding_" + uuid4().hex
        engine = create_async_engine(
            os.environ["SEO_USAGE_TEST_DATABASE_URL"],
            connect_args={"server_settings": {"search_path": schema}},
        )
        metadata = MetaData()
        Tenant.__table__.to_metadata(metadata)
        TenantModule.__table__.to_metadata(metadata)
        SeoSite.__table__.to_metadata(metadata)

        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.run_sync(metadata.create_all)

            sessions = async_sessionmaker(engine, expire_on_commit=False)
            actor = _actor(permissions={"seo.assets": "edit"})
            payload = SeoSiteCreate(
                tenant_id=4,
                name="TIGER 老虎中国官网",
                domain="https://www.tiger-coatings.cn/",
            )

            async with sessions() as session:
                session.add(Tenant(id=4, name="TIGER contract test"))
                await session.commit()
                session.add(TenantModule(
                    id=44,
                    tenant_id=4,
                    module_code="seo",
                    status="trial",
                    expires_at=date.today() + timedelta(days=30),
                ))
                await session.commit()

                # Tenant-scoped GET is the precheck. Only its empty result
                # permits this test scenario to proceed to POST.
                assert await list_seo_sites(tenant_id=4, ctx=actor, session=session) == {"sites": []}
                created = await create_seo_site(payload, ctx=actor, session=session)
                assert created["tenant_id"] == 4
                assert created["name"] == "TIGER 老虎中国官网"
                assert created["domain"] == "https://www.tiger-coatings.cn/"
                assert created["canonical_domain"] == "tiger-coatings.cn"
                assert created["default_url"] == "https://www.tiger-coatings.cn/"
                assert created["status"] == "active"

                readback = await list_seo_sites(tenant_id=4, ctx=actor, session=session)
                assert readback["sites"] == [created]
                stored = await session.scalar(select(SeoSite).where(SeoSite.id == created["id"]))
                assert stored.tenant_module_id == 44

                # This spelling/path reaches the real composite unique
                # constraint after canonicalization. The handler rolls back.
                with pytest.raises(HTTPException) as duplicate:
                    await create_seo_site(
                        payload.model_copy(update={"domain": "HTTPS://TIGER-COATINGS.CN/catalog"}),
                        ctx=actor,
                        session=session,
                    )
                assert duplicate.value.status_code == 409

                # The same AsyncSession remains readable and contains only the
                # committed row after the failed insert and handler rollback.
                count = await session.scalar(
                    select(func.count()).select_from(SeoSite).where(SeoSite.tenant_id == 4)
                )
                assert count == 1
                assert (await list_seo_sites(tenant_id=4, ctx=actor, session=session))["sites"] == [created]

                with pytest.raises(HTTPException) as cross_tenant:
                    await create_seo_site(
                        payload.model_copy(update={"tenant_id": 5}),
                        ctx=actor,
                        session=session,
                    )
                assert cross_tenant.value.status_code == 403
                assert await session.scalar(select(func.count()).select_from(SeoSite)) == 1
        finally:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not os.getenv("SEO_USAGE_TEST_DATABASE_URL"),
                    reason="requires isolated PostgreSQL")
def test_postgres_advisor_concurrent_creation_is_atomic_and_private(monkeypatch, caplog):
    """Real PostgreSQL keys/FKs/transactions, including simultaneous retries."""
    from app.config import get_settings
    from app.models.advisor_tenant_grant import AdvisorTenantGrant
    from app.models.role import Role
    from app.models.seo import SeoSiteAdvisorAssignment
    from app.models.user import User
    from app.security.advisor_tenant_auth import enforce_advisor_request
    from app.security.seo_advisor_reads import install_query_scope
    from test_seo_advisor_site_creation import actor, request, BODY

    settings = get_settings().model_copy(update={'advisor_scoped_content_writes_enabled': True})
    monkeypatch.setattr('app.config.get_settings', lambda: settings)

    async def scenario():
        schema = 'seo_advisor_onboarding_' + uuid4().hex
        engine = create_async_engine(os.environ['SEO_USAGE_TEST_DATABASE_URL'],
            connect_args={'server_settings': {'search_path': schema}})
        metadata = MetaData()
        for model in (Tenant, TenantModule, SeoSite, Role, User,
                      AdvisorTenantGrant, SeoSiteAdvisorAssignment):
            model.__table__.to_metadata(metadata)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        permissions = {'seo.assets': 'edit', 'seo.site': 'edit', 'seo.content': 'edit'}
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.run_sync(metadata.create_all)
            async with sessions() as session:
                session.add_all([Tenant(id=4, name='fixture'),
                    Role(id=1, name='advisor', is_system=False, permissions=permissions)])
                await session.commit()
                session.add_all([TenantModule(id=44, tenant_id=4, module_code='seo', status='active'),
                    User(id=7, username='fixture-advisor', password_hash='unused', role_id=1,
                         tenant_id=4, is_active=True)])
                await session.commit()
                session.add(AdvisorTenantGrant(id=10, user_id=7, tenant_id=4,
                                               granted_by=7, grant_source='admin'))
                await session.commit()

            async def attempt(domain):
                async with sessions() as session:
                    ctx = actor()
                    body = BODY | {'domain': domain}
                    await enforce_advisor_request(request(body), ctx, session)
                    try:
                        return await create_seo_site(SeoSiteCreate(**body), ctx, session)
                    except HTTPException as exc:
                        assert exc.status_code == 409
                        return None

            results = await asyncio.gather(attempt('https://www.concurrent.example.test/'),
                                            attempt('CONCURRENT.EXAMPLE.TEST'))
            created = [row for row in results if row is not None]
            assert len(created) == 1
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoSite)) == 1
                assert await session.scalar(select(func.count()).select_from(SeoSiteAdvisorAssignment)) == 1
                assignment = await session.scalar(select(SeoSiteAdvisorAssignment))
                assert (assignment.site_id, assignment.advisor_user_id, assignment.assigned_by,
                        assignment.active) == (created[0]['id'], 7, 7, True)
                assert created[0]['created_at']
                for ctx, expected in ((actor(), [created[0]['id']]), (actor(user_id=8), [])):
                    install_query_scope(session, ctx)
                    assert [s['id'] for s in (await list_seo_sites(4, ctx, session))['sites']] == expected
            assert len([r for r in caplog.records if 'SEO_ACTION_AUDIT ' in r.message]) == 1
        finally:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()

    asyncio.run(scenario())
