"""Focused tests for the reusable GEO read-only dependencies."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from tests.geo_postgres_guard import require_geo_test_url


def _run_dependency(dependency):
    async def run():
        generator = dependency()
        value = await anext(generator)
        with pytest.raises(StopAsyncIteration):
            await anext(generator)
        return value

    return asyncio.run(run())


def test_geo_read_session_sets_mode_first_then_rolls_back_and_closes():
    from app.geo.read_session import geo_read_session

    events = []
    session = Mock(
        execute=AsyncMock(side_effect=lambda statement: events.append(str(statement))),
        rollback=AsyncMock(side_effect=lambda: events.append("rollback")),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def factory(**kwargs):
        events.append(("open", kwargs))
        try:
            yield session
        finally:
            events.append("close")

    with patch("app.geo.read_session.async_session_factory", factory):
        assert _run_dependency(geo_read_session) is session

    assert events == [
        ("open", {"autoflush": False}),
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "rollback",
        "close",
    ]
    session.commit.assert_not_awaited()


def test_geo_read_session_rolls_back_and_closes_when_consumer_fails():
    from app.geo.read_session import geo_read_session

    events = []
    session = Mock(
        execute=AsyncMock(),
        rollback=AsyncMock(side_effect=lambda: events.append("rollback")),
    )

    @asynccontextmanager
    async def factory(**_kwargs):
        try:
            yield session
        finally:
            events.append("close")

    async def run():
        with patch("app.geo.read_session.async_session_factory", factory):
            generator = geo_read_session()
            assert await anext(generator) is session
            with pytest.raises(RuntimeError, match="consumer failed"):
                await generator.athrow(RuntimeError("consumer failed"))

    asyncio.run(run())
    assert events == ["rollback", "close"]


@pytest.mark.parametrize(
    ("row", "allowed"),
    [
        (Mock(status="active", expires_at=None), True),
        (Mock(status="trial", expires_at=date.today()), True),
        (Mock(status="active", expires_at=date.today() - timedelta(days=1)), False),
        (Mock(status="disabled", expires_at=None), False),
        (None, False),
    ],
)
def test_geo_entitlement_reuses_main_module_scope(row, allowed):
    from app.geo.tenant_scope import require_geo_read_entitlement

    ctx = Mock()
    session = Mock(scalar=AsyncMock(return_value=row))

    async def run():
        return await require_geo_read_entitlement(15, ctx, session)

    if allowed:
        assert asyncio.run(run()) is ctx
    else:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(run())
        assert exc.value.status_code == 403
    ctx.ensure_tenant.assert_called_once_with(15)


def test_geo_read_session_is_enforced_by_postgresql_and_releases_connection():
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.geo.read_session import geo_read_session

    url = require_geo_test_url()

    async def run():
        engine = create_async_engine(url, pool_size=1, max_overflow=0)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            with patch("app.geo.read_session.async_session_factory", factory):
                generator = geo_read_session()
                session = await anext(generator)
                assert await session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
                assert await session.scalar(text("SHOW transaction_read_only")) == "on"
                with pytest.raises(DBAPIError):
                    await session.execute(text("CREATE TABLE geo_read_session_must_not_write(id integer)"))
                with pytest.raises(StopAsyncIteration):
                    await anext(generator)
            assert engine.pool.checkedout() == 0
            async with engine.connect() as connection:
                exists = await connection.scalar(
                    text("SELECT to_regclass('public.geo_read_session_must_not_write')")
                )
            assert exists is None
        finally:
            await engine.dispose()

    asyncio.run(run())
