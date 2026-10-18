"""Real row-lock/conflict test, opt-in disposable CI PostgreSQL only."""
import asyncio
import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.api import users
from app.config import get_settings
from app.database import Base
from app.models import Role, User, Tenant, TenantModule
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.security.advisor_management import grants_version
from app.security.auth import AuthContext


def test_native_concurrent_grant_saves_lock_and_reject_stale_version(monkeypatch):
    raw = os.getenv("SEM_ALERT_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("requires explicit local CI sem_writeback_test database")
    parsed = make_url(raw)
    assert parsed.drivername == "postgresql+asyncpg" and parsed.host in {"127.0.0.1", "localhost"}
    assert parsed.database == "sem_writeback_test" and not parsed.query
    schema = "advisor_test_" + uuid4().hex
    settings = get_settings().model_copy(update={"advisor_multi_tenant_enabled": True})
    monkeypatch.setattr(users, "get_settings", lambda: settings)
    ctx = AuthContext(2, "admin", "管理员", None, {"settings.accounts": "edit"})

    async def scenario():
        setup = create_async_engine(raw, poolclass=NullPool)
        engine = create_async_engine(raw, poolclass=NullPool,
            connect_args={"server_settings": {"search_path": schema}})
        factory = async_sessionmaker(engine, expire_on_commit=False)
        created = False
        try:
            async with setup.begin() as c:
                await c.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
            async with engine.begin() as c:
                await c.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[
                    Role.__table__, User.__table__, Tenant.__table__, TenantModule.__table__, Grant.__table__]))
            async with factory() as s:
                s.add_all([Role(id=1, name="fixture-advisor", is_system=False, permissions={
                    "seo.site": "edit", "seo.content": "edit"}),
                    Role(id=2, name="管理员", is_system=True, permissions={}),
                    Tenant(id=10, name="A"), Tenant(id=20, name="B")])
                await s.flush()
                s.add_all([User(id=1, username="advisor", role_id=1, tenant_id=10, password_hash="unused"),
                           User(id=2, username="admin", role_id=2, password_hash="unused")])
                await s.flush()
                s.add_all([TenantModule(tenant_id=tid, module_code="seo", status="active") for tid in (10, 20)])
                initial = Grant(user_id=1, tenant_id=10, grant_source="backfill")
                s.add(initial)
                await s.commit()
                version = grants_version(10, [initial])
            locked, release, second_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
            original_lock = users.lock_named_admin
            calls = 0
            async def gated_lock(*args):
                nonlocal calls
                calls += 1
                first = calls == 1
                if not first:
                    second_entered.set()
                result = await original_lock(*args)
                if first:
                    locked.set()
                    await asyncio.wait_for(release.wait(), 5)
                return result
            monkeypatch.setattr(users, "lock_named_admin", gated_lock)
            async def save(ids, default):
                async with factory() as s:
                    try:
                        return await users.update_user(1, users.UpdateUserRequest(tenant_ids=ids,
                            default_tenant_id=default, expected_grants_version=version), s, ctx)
                    except HTTPException as error:
                        return error
            one = asyncio.create_task(save([10, 20], 20))
            await asyncio.wait_for(locked.wait(), 5)
            two = asyncio.create_task(save([10], 10))
            await asyncio.wait_for(second_entered.wait(), 5)
            await asyncio.sleep(0.1)
            assert not two.done()
            release.set()
            first, second = await asyncio.wait_for(asyncio.gather(one, two), 10)
            assert first["tenant_ids"] == [10, 20] and first["default_tenant_id"] == 20
            assert second.status_code == 409 and second.detail["code"] == "ADVISOR_GRANTS_CONFLICT"
            async with factory() as s:
                active = list((await s.scalars(select(Grant).where(Grant.revoked_at.is_(None)))).all())
                assert len(active) == 2 and {g.tenant_id for g in active} == {10, 20}
                assert (await s.get(User, 1)).tenant_id == 20
        finally:
            await engine.dispose()
            if created:
                async with setup.begin() as c:
                    await c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await setup.dispose()
    asyncio.run(scenario())
