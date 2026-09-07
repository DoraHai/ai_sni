"""Native PostgreSQL races for the last-platform-admin invariant."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import ForeignKeyConstraint, MetaData, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api import roles as roles_api
from app.api import users as users_api
from app.api.roles import UpdateRoleRequest
from app.api.users import UpdateUserRequest
from app.models import Role, User
from app.security.auth import AuthContext
from app.security.platform_admin import acquire_platform_admin_lock


FULL = {"settings.accounts": "edit", "settings.customers": "edit"}
ACCOUNTS_ONLY = {"settings.accounts": "edit"}


@asynccontextmanager
async def database():
    url = os.environ.get("PLATFORM_ADMIN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable PLATFORM_ADMIN_TEST_DATABASE_URL")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host == "127.0.0.1"
    schema = "platform_admin_test_" + uuid4().hex
    engine = create_async_engine(
        url,
        connect_args={"server_settings": {"statement_timeout": "5000"}},
        execution_options={"schema_translate_map": {None: schema}},
    )
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            metadata = MetaData()
            Role.__table__.to_metadata(metadata)
            user_table = User.__table__.to_metadata(metadata)
            for constraint in list(user_table.constraints):
                if isinstance(constraint, ForeignKeyConstraint):
                    user_table.constraints.remove(constraint)
            await connection.run_sync(metadata.create_all)
        created = True
        yield engine
    finally:
        if created:
            assert schema.startswith("platform_admin_test_") and len(schema) == 52
            async with engine.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


async def seed(engine, *, split_roles: bool) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        roles = [Role(id=1, name="平台管理员一", permissions=FULL, is_system=False)]
        if split_roles:
            roles.append(Role(id=2, name="平台管理员二", permissions=FULL, is_system=False))
        session.add_all(roles)
        session.add_all(
            [
                User(id=1, username="admin-one", password_hash="x", role_id=1),
                User(
                    id=2,
                    username="admin-two",
                    password_hash="x",
                    role_id=2 if split_roles else 1,
                ),
            ]
        )
        await session.commit()


def pause_first_lock(monkeypatch, module, first, acquired, release):
    async def lock(session):
        await acquire_platform_admin_lock(session)
        if session is first:
            acquired.set()
            await release.wait()

    monkeypatch.setattr(module, "acquire_platform_admin_lock", lock)


async def outcome(call, session):
    try:
        await call()
        return "committed"
    except HTTPException as exc:
        await session.rollback()
        return exc.detail


def test_two_user_demotions_cannot_commit_zero_platform_admins(monkeypatch):
    async def exercise():
        async with database() as engine:
            await seed(engine, split_roles=False)
            async with AsyncSession(engine, expire_on_commit=False) as first, AsyncSession(
                engine, expire_on_commit=False
            ) as second:
                acquired, release = asyncio.Event(), asyncio.Event()
                pause_first_lock(monkeypatch, users_api, first, acquired, release)
                ctx = AuthContext(None, "api-key", "超级管理员", None, is_superadmin=True)
                first_task = asyncio.create_task(
                    outcome(
                        lambda: users_api.update_user(
                            1, UpdateUserRequest(is_active=False), first, ctx
                        ),
                        first,
                    )
                )
                await asyncio.wait_for(acquired.wait(), 2)
                second_task = asyncio.create_task(
                    outcome(
                        lambda: users_api.update_user(
                            2, UpdateUserRequest(is_active=False), second, ctx
                        ),
                        second,
                    )
                )
                await asyncio.sleep(0.1)
                assert not second_task.done(), "second user mutation must wait on the global lock"
                release.set()
                assert await asyncio.wait_for(first_task, 5) == "committed"
                assert "最后一个平台管理员" in await asyncio.wait_for(second_task, 5)
            async with AsyncSession(engine) as check:
                assert await check.scalar(
                    select(func.count()).select_from(User).where(User.is_active.is_(True))
                ) == 1

    asyncio.run(exercise())


def test_two_role_demotions_cannot_commit_zero_platform_admins(monkeypatch):
    async def exercise():
        async with database() as engine:
            await seed(engine, split_roles=True)
            async with AsyncSession(engine, expire_on_commit=False) as first, AsyncSession(
                engine, expire_on_commit=False
            ) as second:
                acquired, release = asyncio.Event(), asyncio.Event()
                pause_first_lock(monkeypatch, roles_api, first, acquired, release)
                ctx = AuthContext(None, "api-key", "超级管理员", None, is_superadmin=True)
                first_task = asyncio.create_task(
                    outcome(
                        lambda: roles_api.update_role(
                            1, UpdateRoleRequest(permissions=ACCOUNTS_ONLY), first, ctx
                        ),
                        first,
                    )
                )
                await asyncio.wait_for(acquired.wait(), 2)
                second_task = asyncio.create_task(
                    outcome(
                        lambda: roles_api.update_role(
                            2, UpdateRoleRequest(permissions=ACCOUNTS_ONLY), second, ctx
                        ),
                        second,
                    )
                )
                await asyncio.sleep(0.1)
                assert not second_task.done(), "second role mutation must wait on the global lock"
                release.set()
                assert await asyncio.wait_for(first_task, 5) == "committed"
                assert "最后一个平台管理员" in await asyncio.wait_for(second_task, 5)
            async with AsyncSession(engine) as check:
                roles = list((await check.scalars(select(Role).order_by(Role.id))).all())
                assert sum(role.permissions == FULL for role in roles) == 1

    asyncio.run(exercise())
