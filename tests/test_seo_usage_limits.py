import asyncio
import os
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.seo_usage_limits import SeoUsageLimitError, charge_seo_usage, refund_seo_usage


def test_daily_usage_is_atomic_and_preserves_other_module_settings() -> None:
    module = SimpleNamespace(module_settings={"feature": {"enabled": True}})
    session = AsyncMock()
    session.scalar.return_value = module

    result = asyncio.run(charge_seo_usage(session, 7, "ai_requests", 2, 5))

    assert result["used"] == 2
    assert module.module_settings["feature"] == {"enabled": True}
    assert module.module_settings["seo_daily_usage"]["ai_requests"] == 2
    session.commit.assert_awaited_once()


def test_daily_usage_rejects_over_limit_and_can_refund_failures() -> None:
    module = SimpleNamespace(
        module_settings={
            "seo_daily_usage": {
                "date": __import__("datetime").datetime.now(
                    __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
                ).date().isoformat(),
                "crawl_urls": 90,
            }
        }
    )
    session = AsyncMock()
    session.scalar.return_value = module

    with pytest.raises(SeoUsageLimitError):
        asyncio.run(charge_seo_usage(session, 7, "crawl_urls", 20, 100))
    session.rollback.assert_awaited_once()

    session.reset_mock()
    asyncio.run(refund_seo_usage(session, 7, "crawl_urls", 30))
    assert module.module_settings["seo_daily_usage"]["crawl_urls"] == 60
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("stored_date,expected", [("2026-09-05", 0), ("2026-09-06", 1)])
def test_delayed_refund_only_changes_original_charge_day(stored_date, expected) -> None:
    module = SimpleNamespace(module_settings={
        "feature": {"enabled": True},
        "seo_daily_usage": {"date": stored_date, "ai_requests": 1, "crawl_urls": 4},
    })
    session = AsyncMock()
    session.scalar.return_value = module
    from datetime import datetime

    with patch("app.seo_usage_limits.datetime") as clock:
        clock.now.return_value = datetime(2026, 9, 6, 0, 0, 10)
        asyncio.run(refund_seo_usage(session, 7, "ai_requests", 1, charged_on="2026-09-05"))

    assert module.module_settings["seo_daily_usage"]["ai_requests"] == expected
    assert module.module_settings["seo_daily_usage"]["crawl_urls"] == 4
    assert module.module_settings["feature"] == {"enabled": True}
    if stored_date == "2026-09-06":
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once()
    else:
        session.commit.assert_awaited_once()


@pytest.mark.skipif(not os.getenv("SEO_USAGE_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
def test_postgres_concurrent_usage_refreshes_preloaded_module() -> None:
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.models.module_workspace import TenantModule

    async def scenario():
        engine = create_async_engine(os.environ["SEO_USAGE_TEST_DATABASE_URL"], pool_size=20)
        schema = "seo_usage_test_" + uuid4().hex
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'''CREATE TABLE "{schema}".tenant_modules (
                    id bigint PRIMARY KEY, tenant_id bigint NOT NULL,
                    module_code varchar(16) NOT NULL, status varchar(20),
                    opened_at timestamp, expires_at date, module_settings jsonb,
                    created_at timestamp, updated_at timestamp,
                    UNIQUE (tenant_id, module_code))'''))
                await connection.execute(text(f'''INSERT INTO "{schema}".tenant_modules
                    (id, tenant_id, module_code, module_settings)
                    VALUES (1, 7, 'seo', '{{"feature": {{"enabled": true}}}}'),
                           (2, 8, 'seo', '{{"feature": {{"enabled": false}}}}')'''))
            sessions = async_sessionmaker(engine, expire_on_commit=False)

            async def workers(operations):
                barrier = asyncio.Barrier(len(operations))

                async def worker(operation):
                    async with sessions() as session:
                        await session.execute(text(f'SET search_path TO "{schema}"'))
                        # Hold this identity-map object across another session's commit.
                        loaded = await session.scalar(select(TenantModule).where(TenantModule.tenant_id == 7))
                        await barrier.wait()
                        try:
                            if operation == "charge":
                                await charge_seo_usage(session, 7, "ai_requests", 1, 5)
                            else:
                                await refund_seo_usage(session, 7, "ai_requests", 1)
                            assert loaded.id == 1
                            return True
                        except SeoUsageLimitError:
                            return False

                return await asyncio.gather(*(worker(operation) for operation in operations))

            charged = await workers(["charge"] * 20)
            assert sum(charged) == 5
            assert all(await workers(["refund"] * 3))
            async with engine.connect() as connection:
                rows = (await connection.execute(text(
                    f'SELECT tenant_id, module_settings FROM "{schema}".tenant_modules ORDER BY tenant_id'
                ))).all()
                assert rows[0][1]["seo_daily_usage"]["ai_requests"] == 2
                assert rows[0][1]["feature"] == {"enabled": True}
                assert rows[1][1] == {"feature": {"enabled": False}}
        finally:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()

    asyncio.run(scenario())
