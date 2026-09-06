"""Real query/READ ONLY regression in a disposable CI schema, never production data."""
import asyncio
import os
from uuid import uuid4
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import Column, MetaData, Table, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires explicitly configured PostgreSQL')
def test_workbench_reads_use_real_sql_and_cannot_write_or_reconcile():
    from app.models import (Tenant, GeoAnswerSnapshot, GeoPrompt, GeoVisibilityPatrolRun, GeoTrackingEngine,
                            GeoPublishingChannel, GeoContentTask, GeoArticleVersion, GeoChannelVariant,
                            GeoPublication, GeoAsyncJob, GeoActionTicket, GeoAiSetting)
    from app.geo import read_routes as api

    async def run():
        schema = 'geo_read_test_' + uuid4().hex
        admin = create_async_engine(os.environ['GEO_TEST_POSTGRES_URL'])
        engine = None
        created = False
        metadata = MetaData(schema=schema)
        for model in (Tenant, GeoAnswerSnapshot, GeoPrompt, GeoVisibilityPatrolRun, GeoTrackingEngine,
                      GeoPublishingChannel, GeoContentTask, GeoArticleVersion, GeoChannelVariant,
                      GeoPublication, GeoAsyncJob, GeoActionTicket, GeoAiSetting):
            Table(model.__tablename__, metadata, *(Column(c.name, c.type, nullable=True) for c in model.__table__.columns))
        try:
            async with admin.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA {schema}'))
                created = True
                await conn.run_sync(metadata.create_all)
                await conn.execute(text(f"INSERT INTO {schema}.geo_content_tasks (id, tenant_id, prompt_id, title, status) VALUES (14,1,1,'test','editing')"))
                await conn.execute(text(f"INSERT INTO {schema}.geo_async_jobs (id, tenant_id, status, created_at, started_at, kind) VALUES (1,1,'running','2020-01-01','2020-01-01','generate_article')"))
                await conn.execute(text(f"INSERT INTO {schema}.geo_visibility_patrol_runs (id, tenant_id, status, created_at, started_at) VALUES (1,1,'running','2020-01-01','2020-01-01')"))
            engine = create_async_engine(os.environ['GEO_TEST_POSTGRES_URL'], connect_args={'server_settings': {'search_path': schema, 'statement_timeout': '10000'}})
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            with patch.object(api, 'async_session_factory', sessions):
                async for session in api.read_session():
                    assert await session.scalar(text('SHOW transaction_read_only')) == 'on'
                    assert await session.scalar(text('SHOW transaction_isolation')) == 'repeatable read'
                    result = await api.get_answers(tenant_id=1, limit=50, ctx=Mock(), session=session)
                    assert result['items'] == [] and not result['pagination']['has_more']
                    assert (await api.get_period_context(1, None, Mock(), session))['current']['status'] == 'insufficient'
                    assert (await api.get_capabilities(1, Mock(), session))['engines'] == []
                    assert (await api.get_content_task(14, 1, Mock(), session))['versions'] == []
                    assert (await api.get_async_job(1, 1, Mock(), session))['stored_status'] == 'running'
                    assert (await api.get_patrol_run(1, 1, Mock(), session))['stored_status'] == 'running'
                    assert (await api.get_async_jobs(1, 20, None, Mock(), session))['items'][0]['stale']
                    assert (await api.get_patrol_runs(1, 20, None, Mock(), session))['items'][0]['stale']
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(text('UPDATE geo_async_jobs SET status=\'failed\' WHERE id=1'))
                    assert await session.scalar(text('SELECT status FROM geo_async_jobs WHERE id=1')) == 'running'
        finally:
            if engine:
                await engine.dispose()
            if created:
                async with admin.begin() as conn:
                    await conn.run_sync(metadata.drop_all)
                    await conn.execute(text(f'DROP SCHEMA {schema}'))
            await admin.dispose()
    asyncio.run(run())
