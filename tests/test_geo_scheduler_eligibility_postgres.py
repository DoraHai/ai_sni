"""Disposable PostgreSQL proof that scheduler eligibility is strictly read-only."""

import asyncio
import os
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import Column, MetaData, Table, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.skipif(
    not os.getenv("GEO_TEST_POSTGRES_URL"),
    reason="requires explicitly configured PostgreSQL",
)
def test_scheduler_eligibility_uses_read_only_transaction_without_initialization():
    from app.geo import read_routes as api
    from app.models import GeoPrompt, GeoVisibilityPatrolSettings

    async def run():
        schema = "geo_scheduler_eligibility_" + uuid4().hex
        admin = create_async_engine(os.environ["GEO_TEST_POSTGRES_URL"])
        engine = None
        created = False
        metadata = MetaData(schema=schema)
        for model in (GeoVisibilityPatrolSettings, GeoPrompt):
            Table(
                model.__tablename__,
                metadata,
                *(Column(column.name, column.type, nullable=True) for column in model.__table__.columns),
            )
        try:
            async with admin.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
                await connection.run_sync(metadata.create_all)
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".geo_visibility_patrol_settings '
                        "(tenant_id, enabled) VALUES (4, false)"
                    )
                )
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".geo_prompts '
                        "(id, tenant_id, question, status) VALUES "
                        "(1, 4, 'active question', 'active'), "
                        "(2, 4, 'archived question', 'archived')"
                    )
                )

            engine = create_async_engine(
                os.environ["GEO_TEST_POSTGRES_URL"],
                connect_args={
                    "server_settings": {
                        "search_path": schema,
                        "statement_timeout": "10000",
                    }
                },
            )
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            with patch.object(api, "async_session_factory", sessions):
                async for session in api.read_session():
                    assert await session.scalar(text("SHOW transaction_read_only")) == "on"
                    result = await api.get_scheduler_eligibility(4, Mock(), session)
                    assert result["patrol_settings"] == {
                        "exists": True,
                        "enabled": False,
                    }
                    assert result["active_prompt_count"] == 1
                    assert result["scheduler_eligible"] is False
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(
                                text(
                                    "UPDATE geo_visibility_patrol_settings "
                                    "SET enabled=true WHERE tenant_id=4"
                                )
                            )

            async with admin.connect() as connection:
                enabled = await connection.scalar(
                    text(
                        f'SELECT enabled FROM "{schema}".'
                        "geo_visibility_patrol_settings WHERE tenant_id=4"
                    )
                )
                assert enabled is False
        finally:
            if engine is not None:
                await engine.dispose()
            if created:
                async with admin.begin() as connection:
                    await connection.run_sync(metadata.drop_all)
                    await connection.execute(text(f'DROP SCHEMA "{schema}"'))
            await admin.dispose()

    asyncio.run(run())


@pytest.mark.skipif(
    not os.getenv("GEO_TEST_POSTGRES_URL"),
    reason="requires explicitly configured PostgreSQL",
)
def test_tenant_lock_serializes_settings_enable_with_scheduler_decision():
    from app.geo.content.geo_scheduler import (
        current_patrol_settings,
        lock_scheduler_tenant,
    )
    from app.models import GeoVisibilityPatrolSettings, Tenant

    async def run():
        schema = "geo_scheduler_lock_" + uuid4().hex
        admin = create_async_engine(os.environ["GEO_TEST_POSTGRES_URL"])
        engine = None
        created = False
        metadata = MetaData(schema=schema)
        for model in (Tenant, GeoVisibilityPatrolSettings):
            Table(
                model.__tablename__,
                metadata,
                *(
                    Column(
                        column.name,
                        column.type,
                        primary_key=column.primary_key,
                        nullable=column.nullable,
                    )
                    for column in model.__table__.columns
                ),
            )
        try:
            async with admin.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
                await connection.run_sync(metadata.create_all)
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".tenants '
                        "(id, name, created_at) VALUES (4, 'Tiger', NOW())"
                    )
                )
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".geo_visibility_patrol_settings '
                        "(tenant_id, enabled, daily_hour, window_start_hour, "
                        "window_end_hour, interval_hours, auto_persist, prefer_real, "
                        "prompt_limit, updated_at) VALUES "
                        "(4, true, 6, 6, 22, 24, true, true, 20, NOW())"
                    )
                )

            engine = create_async_engine(
                os.environ["GEO_TEST_POSTGRES_URL"],
                connect_args={"server_settings": {"search_path": schema}},
            )
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            disabling = sessions()
            scheduler = sessions()
            try:
                assert await lock_scheduler_tenant(disabling, 4)
                await disabling.execute(
                    text(
                        "UPDATE geo_visibility_patrol_settings "
                        "SET enabled=false WHERE tenant_id=4"
                    )
                )

                async def scheduler_decision():
                    assert await lock_scheduler_tenant(scheduler, 4)
                    return await current_patrol_settings(scheduler, 4)

                decision_task = asyncio.create_task(scheduler_decision())
                await asyncio.sleep(0.1)
                assert not decision_task.done(), "scheduler must wait for settings transaction"
                await disabling.commit()
                current = await asyncio.wait_for(decision_task, timeout=2)
                assert current is not None and current.enabled is False
                await scheduler.commit()
            finally:
                await disabling.close()
                await scheduler.close()
        finally:
            if engine is not None:
                await engine.dispose()
            if created:
                async with admin.begin() as connection:
                    await connection.run_sync(metadata.drop_all)
                    await connection.execute(text(f'DROP SCHEMA "{schema}"'))
            await admin.dispose()

    asyncio.run(run())


@pytest.mark.skipif(
    not os.getenv("GEO_TEST_POSTGRES_URL"),
    reason="requires explicitly configured PostgreSQL",
)
def test_scheduler_safe_foundation_is_atomic_idempotent_and_keeps_patrol_disabled():
    from app.geo.content.geo_scheduler import current_patrol_settings
    from app.geo.content.routes import (
        create_scheduler_safe_foundation,
        create_visibility_patrol_run,
        put_visibility_patrol_settings,
    )
    from app.geo.content.schemas import (
        SchedulerSafeFoundationRequest,
        VisibilityPatrolCreate,
        VisibilityPatrolSettingsUpdate,
    )
    from app.models import (
        GeoOptimizationBusiness,
        GeoPrompt,
        GeoPublishingChannel,
        GeoVisibilityPatrolRun,
        GeoVisibilityPatrolSettings,
        Tenant,
    )
    from app.security.auth import AuthContext

    async def run():
        schema = "geo_safe_foundation_" + uuid4().hex
        admin = create_async_engine(os.environ["GEO_TEST_POSTGRES_URL"])
        engine = None
        created = False
        metadata = MetaData(schema=schema)
        models = (
            Tenant,
            GeoVisibilityPatrolSettings,
            GeoVisibilityPatrolRun,
            GeoOptimizationBusiness,
            GeoPrompt,
            GeoPublishingChannel,
        )
        for model in models:
            Table(
                model.__tablename__,
                metadata,
                *(
                    Column(
                        column.name,
                        column.type,
                        primary_key=column.primary_key,
                        nullable=True,
                    )
                    for column in model.__table__.columns
                ),
            )
        Table(
            "tenant_modules",
            metadata,
            Column("tenant_id", Tenant.id.type),
            Column("module_code", GeoPrompt.status.type),
            Column("status", GeoPrompt.status.type),
            Column("expires_at", GeoPrompt.created_at.type),
        )
        request = SchedulerSafeFoundationRequest.model_validate(
            {
                "tenant_id": 4,
                "business": {
                    "name": "Powder coatings",
                    "description": "Safe profile",
                    "profile": {"product_name": "Tiger"},
                },
                "prompts": [
                    {"question": "How should powder coatings be selected?"},
                    {"question": "How should coating failures be diagnosed?"},
                ],
                "channel": {
                    "name": "Tiger website",
                    "channel_type": "website",
                    "publish_mode": "manual_only",
                    "base_url": "https://www.tiger-coatings.cn/",
                    "enabled": False,
                },
            }
        )
        try:
            async with admin.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
                await connection.run_sync(metadata.create_all)
                await connection.execute(
                    text(f'INSERT INTO "{schema}".tenants (id, name) VALUES (4, \'Tiger\')')
                )
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".tenant_modules '
                        "(tenant_id, module_code, status) VALUES (4, 'geo', 'active')"
                    )
                )
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".geo_visibility_patrol_settings '
                        "(tenant_id, enabled) VALUES (4, false)"
                    )
                )

            engine = create_async_engine(
                os.environ["GEO_TEST_POSTGRES_URL"],
                connect_args={"server_settings": {"search_path": schema}},
            )
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            ctx = AuthContext(
                user_id=9,
                username="tiger_operator",
                role_name="tenant-editor",
                tenant_id=4,
                permissions={"geo.content": "edit"},
            )
            async with sessions() as session:
                first = await create_scheduler_safe_foundation(request, ctx, session)
            async with sessions() as session:
                second = await create_scheduler_safe_foundation(request, ctx, session)

            assert first["atomic"] is True
            assert first["scheduler_eligible"] is False
            assert first["decisions"]["business"]["decision"] == "created"
            assert all(item["decision"] == "created" for item in first["decisions"]["prompts"])
            assert first["decisions"]["channel"]["decision"] == "created"
            assert second["decisions"]["business"]["decision"] == "reused"
            assert all(item["decision"] == "reused" for item in second["decisions"]["prompts"])
            assert second["decisions"]["channel"]["decision"] == "reused"

            # A real settings mutation cannot pass the shared tenant row lock
            # until the atomic foundation transaction commits. It may enable
            # scheduling afterwards; the endpoint deliberately promises only
            # transaction-window exclusion.
            foundation_locked = asyncio.Event()
            release_foundation = asyncio.Event()

            async def pause_after_foundation_lock(session, tenant_id):
                row = await current_patrol_settings(session, tenant_id)
                if asyncio.current_task().get_name() == "safe-foundation-settings":
                    foundation_locked.set()
                    await release_foundation.wait()
                return row

            async with sessions() as foundation_session, sessions() as settings_session:
                with patch(
                    "app.geo.content.geo_scheduler.current_patrol_settings",
                    side_effect=pause_after_foundation_lock,
                ):
                    foundation_task = asyncio.create_task(
                        create_scheduler_safe_foundation(request, ctx, foundation_session),
                        name="safe-foundation-settings",
                    )
                    await asyncio.wait_for(foundation_locked.wait(), timeout=2)
                    settings_task = asyncio.create_task(
                        put_visibility_patrol_settings(
                            VisibilityPatrolSettingsUpdate(tenant_id=4, enabled=True),
                            ctx,
                            settings_session,
                        )
                    )
                    await asyncio.sleep(0.1)
                    assert not settings_task.done(), "settings PUT must wait for foundation"
                    release_foundation.set()
                    await asyncio.wait_for(foundation_task, timeout=2)
                    await asyncio.wait_for(settings_task, timeout=2)

            async with sessions() as session:
                await session.execute(
                    text(
                        "UPDATE geo_visibility_patrol_settings "
                        "SET enabled=false WHERE tenant_id=4"
                    )
                )
                await session.commit()

            # The real manual patrol handler is serialized by the same lock.
            # Once foundation commits, a separately authorized manual request
            # may create its run; it cannot overlap the protected transaction.
            foundation_locked = asyncio.Event()
            release_foundation = asyncio.Event()

            async def pause_before_manual_patrol(session, tenant_id):
                row = await current_patrol_settings(session, tenant_id)
                if asyncio.current_task().get_name() == "safe-foundation-patrol":
                    foundation_locked.set()
                    await release_foundation.wait()
                return row

            async with sessions() as foundation_session, sessions() as patrol_session:
                with (
                    patch(
                        "app.geo.content.geo_scheduler.current_patrol_settings",
                        side_effect=pause_before_manual_patrol,
                    ),
                    patch("app.geo.retest.reserved_week", AsyncMock(return_value=None)),
                    patch(
                        "app.geo.content.patrol.count_patrol_runs_today",
                        AsyncMock(return_value=0),
                    ),
                ):
                    foundation_task = asyncio.create_task(
                        create_scheduler_safe_foundation(request, ctx, foundation_session),
                        name="safe-foundation-patrol",
                    )
                    await asyncio.wait_for(foundation_locked.wait(), timeout=2)
                    patrol_task = asyncio.create_task(
                        create_visibility_patrol_run(
                            VisibilityPatrolCreate(tenant_id=4, run_async=True),
                            BackgroundTasks(),
                            ctx,
                            patrol_session,
                        )
                    )
                    await asyncio.sleep(0.1)
                    assert not patrol_task.done(), "manual patrol must wait for foundation"
                    release_foundation.set()
                    await asyncio.wait_for(foundation_task, timeout=2)
                    patrol_result = await asyncio.wait_for(patrol_task, timeout=2)
                    assert patrol_result["started"] is True

            async with sessions() as session:
                counts = {
                    "business": await session.scalar(text("SELECT count(*) FROM geo_optimization_businesses")),
                    "prompts": await session.scalar(text("SELECT count(*) FROM geo_prompts")),
                    "channels": await session.scalar(text("SELECT count(*) FROM geo_publishing_channels")),
                    "runs": await session.scalar(text("SELECT count(*) FROM geo_visibility_patrol_runs")),
                }
                enabled = await session.scalar(
                    text("SELECT enabled FROM geo_visibility_patrol_settings WHERE tenant_id=4")
                )
            assert counts == {"business": 1, "prompts": 2, "channels": 1, "runs": 1}
            assert enabled is False
        finally:
            if engine is not None:
                await engine.dispose()
            if created:
                async with admin.begin() as connection:
                    await connection.run_sync(metadata.drop_all)
                    await connection.execute(text(f'DROP SCHEMA "{schema}"'))
            await admin.dispose()

    asyncio.run(run())
