"""HTTP + real SQL in disposable CI schemas; synthetic identity, never real JWT.

Only the dedicated loopback geo_ci database is accepted. No app lifespan runs,
no live credentials are used, and every row is synthetic.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import BigInteger, Column, Date, MetaData, String, Table, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires isolated PostgreSQL')
DAY = date(2026, 9, 6)
WEEK = '2026-08-31'


class FrozenDate(date):
    @classmethod
    def today(cls):
        return DAY


@asynccontextmanager
async def environment(*, extra_models=(), legacy_routes=False):
    from ops.run_geo_checks import validate_ci_database
    from app.database import get_session
    from app.geo import read_routes as api
    from app.geo.integration import router as metrics
    from app.models import (Tenant, GeoAnswerSnapshot, GeoPrompt, GeoVisibilityPatrolRun,
                            GeoTrackingEngine, GeoPublishingChannel, GeoContentTask, GeoArticleVersion,
                            GeoChannelVariant, GeoPublication, GeoAsyncJob, GeoActionTicket, GeoAiSetting)
    from app.security.auth import AuthContext, require_auth

    url = os.environ['GEO_TEST_POSTGRES_URL']
    validate_ci_database(url)
    schema = 'geo_read_http_' + uuid4().hex
    admin = create_async_engine(url)
    engine = None
    created = False
    metadata = MetaData(schema=schema)
    for model in (Tenant, GeoAnswerSnapshot, GeoPrompt, GeoVisibilityPatrolRun, GeoTrackingEngine,
                  GeoPublishingChannel, GeoContentTask, GeoArticleVersion, GeoChannelVariant,
                  GeoPublication, GeoAsyncJob, GeoActionTicket, GeoAiSetting, *extra_models):
        Table(model.__tablename__, metadata, *(Column(c.name, c.type, nullable=True)
                                               for c in model.__table__.columns))
    Table('tenant_modules', metadata, Column('tenant_id', BigInteger), Column('module_code', String),
          Column('status', String), Column('expires_at', Date))
    tables = {t.name: t for t in metadata.tables.values()}
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA {schema}'))
            created = True
            await conn.run_sync(metadata.create_all)
        engine = create_async_engine(url, connect_args={'server_settings': {
            'search_path': schema, 'statement_timeout': '10000'}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def query_session():
            async with sessions(autoflush=False) as session:
                async with session.begin():
                    await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
                    yield session

        identity = {'ctx': AuthContext(user_id=9001, username='fixture', role_name='fixture',
                                      tenant_id=None, permissions={'geo.content': 'view'})}
        app = FastAPI()  # Deliberately no production app/lifespan/schedulers.
        app.include_router(api.router, prefix='/api/v1/geo')
        app.include_router(metrics, prefix='/api/v1/geo')
        if legacy_routes:
            from app.geo.content.routes import router as legacy
            app.include_router(legacy, prefix='/api/v1/geo')
        identity['app'] = app
        identity['sessions'] = sessions
        app.dependency_overrides[get_session] = query_session
        app.dependency_overrides[require_auth] = lambda: identity['ctx']
        with patch.object(api, 'async_session_factory', sessions), patch('app.geo.tenant_scope.date', FrozenDate):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url='http://fixture') as client:
                yield client, engine, tables, identity
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            async with admin.begin() as conn:
                await conn.run_sync(metadata.drop_all)
                await conn.execute(text(f'DROP SCHEMA {schema}'))
        await admin.dispose()


def test_entitlement_http_uses_real_module_rows_and_fails_closed():
    async def run():
        async with environment() as (client, engine, tables, identity):
            # Each case has an actual Tenant; SEM-only must not grant GEO.
            cases = [
                ('active', 'geo', 'active', None, True),
                ('trial', 'geo', 'trial', DAY + timedelta(days=1), True),
                ('today', 'geo', 'active', DAY, True),
                ('expired', 'geo', 'active', DAY - timedelta(days=1), False),
                ('trial_expired', 'geo', 'trial', DAY - timedelta(days=1), False),
                ('disabled', 'geo', 'disabled', None, False),
                ('cancelled', 'geo', 'cancelled', None, False),
                ('sem_only', 'sem', 'active', None, False),
                ('not_enabled', None, None, None, False),
            ]
            async with engine.begin() as conn:
                for tid, (label, module, status, expiry, _) in enumerate(cases, 1):
                    await conn.execute(tables['tenants'].insert().values(id=tid, name=label))
                    if module:
                        await conn.execute(tables['tenant_modules'].insert().values(
                            tenant_id=tid, module_code=module, status=status, expires_at=expiry))
            routes = [('/read/answers', 200), ('/read/answers/999', 404),
                      ('/read/period-context', 200), ('/read/capabilities', 200),
                      ('/read/content-tasks/999', 404), ('/read/patrol-runs', 200),
                      ('/read/patrol-runs/999', 404), ('/read/async-jobs', 200),
                      ('/read/async-jobs/999', 404), ('/metrics/snapshot', 200), ('/metrics/dictionary', 200)]
            for tid, (label, _, _, _, allowed) in enumerate(cases, 1):
                for path, accepted_status in routes:
                    response = await client.get('/api/v1/geo/integration' + path,
                                                params={'tenant_id': tid, 'week_end': WEEK})
                    assert response.status_code == (accepted_status if allowed else 403), (label, path, response.text)
                    if not allowed:
                        assert response.json()['detail']['code'] == 'geo_not_available'

            params = {'tenant_id': 1, 'week_end': WEEK}
            path = '/api/v1/geo/integration/read/period-context'
            # The actual scoped dependency is retained: only require_auth is a fixture.
            identity['ctx'].permissions = {}
            assert (await client.get(path, params=params)).status_code == 403
            identity['ctx'].permissions = {'geo.content': 'view'}
            identity['ctx'].tenant_id = 2
            assert (await client.get(path, params=params)).status_code == 403
            identity['ctx'].tenant_id = 1
            assert (await client.get(path, params=params)).status_code == 200
            # No cached grant after entitlement revocation.
            async with engine.begin() as conn:
                await conn.execute(tables['tenant_modules'].update().where(
                    tables['tenant_modules'].c.tenant_id == 1).values(status='disabled'))
            assert (await client.get(path, params=params)).status_code == 403
            # A missing entitlement table is a real database error, never a grant.
            async with engine.begin() as conn:
                await conn.run_sync(tables['tenant_modules'].drop)
            try:
                assert (await client.get(path, params=params)).status_code == 500
            finally:
                async with engine.begin() as conn:
                    await conn.run_sync(tables['tenant_modules'].create)
    asyncio.run(run())


def test_nonempty_answer_http_pagination_history_and_qualification():
    async def run():
        async with environment() as (client, engine, tables, _identity):
            captured = datetime(2026, 8, 27, 2)
            rows = [dict(id=i, tenant_id=1, prompt_id=(i-1) % 3+1, engine=str(i % 2),
                         captured_at=captured, sample_mode='openai_compat', simulated=False,
                         note='method=unprimed_json_v2 analysis=completed', citation_accuracy='unknown',
                         raw_text=f'Synthetic answer {i}', mentions_brand=True, cited_urls=[],
                         competitors=[], patrol_run_id=31) for i in range(1, 13)]
            # Seven valid current-week rows, with exclusions and an outside-window row.
            rows[7].update(sample_mode='mock_persona', simulated=True)
            rows[8].update(sample_mode='manual')
            rows[9].update(sample_mode='unknown', note=None)
            rows[10].update(captured_at=datetime(2026, 8, 30, 16))  # Shanghai Monday exactly.
            rows[11].update(captured_at=None)  # Defensive legacy-null support only.
            cells = [dict(snapshot_id=r['id'], prompt_id=r['prompt_id'], engine=r['engine'], ok=True,
                          sample_mode=r['sample_mode'], simulated=r['simulated'], sampling_method='unprimed_json_v2',
                          analysis_status='completed', raw_text=r['raw_text'], suggested_mentions_brand=True,
                          competitors=[], provider='historical-provider', model='historical-model',
                          prompt_question=f'Historical question {r["prompt_id"]}') for r in rows]
            async with engine.begin() as conn:
                await conn.execute(tables['tenants'].insert(), [{'id': 1, 'name': 'fixture'}, {'id': 2, 'name': 'other'}])
                await conn.execute(tables['tenant_modules'].insert(), [
                    {'tenant_id': i, 'module_code': 'geo', 'status': 'active'} for i in (1, 2)])
                await conn.execute(tables['geo_prompts'].insert(), [
                    {'id': i, 'tenant_id': 1 if i < 4 else 2, 'question': f'Edited question {i}', 'is_brand_probe': False}
                    for i in range(1, 5)])
                await conn.execute(tables['geo_visibility_patrol_runs'].insert().values(
                    id=31, tenant_id=1, status='completed', started_at=datetime(2026, 8, 26),
                    finished_at=datetime(2026, 9, 1), items=cells))
                await conn.execute(tables['geo_tracking_engines'].insert().values(
                    id=1, tenant_id=1, engine_key='1', model='current-model', display_name='Current engine'))
                await conn.execute(tables['geo_answer_snapshots'].insert(), rows)
                # Both foreign customer and corrupt cross-customer prompt join must be excluded.
                await conn.execute(tables['geo_answer_snapshots'].insert(), [
                    {**rows[0], 'id': 90, 'tenant_id': 2, 'prompt_id': 4},
                    {**rows[0], 'id': 91, 'prompt_id': 4}])

            path = '/api/v1/geo/integration/read/answers'
            params = {'tenant_id': 1, 'week_end': WEEK, 'limit': 3}
            first = await client.get(path, params=params)
            assert first.status_code == 200, first.text
            first = first.json()
            assert first['unknown_time_count'] == 1
            cursor = first['pagination']['next_cursor']
            # Insert between pages: watermark prevents later inserts leaking into this traversal.
            async with engine.begin() as conn:
                await conn.execute(tables['geo_answer_snapshots'].insert().values(**{**rows[0], 'id': 100}))
            items = list(first['items'])
            page_count = 1
            while cursor:
                response = await client.get(path, params={**params, 'cursor': cursor})
                assert response.status_code == 200, response.text
                page = response.json()
                items += page['items']
                cursor = page['pagination']['next_cursor']
                page_count += 1
                assert page_count <= 5
            assert [r['ref']['id'] for r in items] == [11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 12]
            by_id = {r['ref']['id']: r for r in items}
            good = by_id[1]
            assert good['engine']['model'] == 'historical-model'
            assert good['engine']['provider'] == 'historical-provider'
            assert good['question']['historical_text'] == 'Historical question 1'
            assert good['question']['current_text'] == 'Edited question 1'
            assert good['captured_at'] == '2026-08-27T02:00:00Z'
            assert good['captured_at_local'] == '2026-08-27T10:00:00+08:00'
            assert good['sample_eligibility']['eligible'] is True
            assert all(m['status'] == 'unavailable' for m in good['metric_adoption'])
            assert any(r['scope'] == 'week' for m in good['metric_adoption'] for r in m['reasons'])
            for ident, source in [(8, 'simulated'), (9, 'manual'), (10, 'unknown')]:
                assert by_id[ident]['source']['kind'] == source
                assert by_id[ident]['sample_eligibility']['eligible'] is False
                assert all(m['status'] == 'excluded' for m in by_id[ident]['metric_adoption'])
            assert by_id[11]['sample_eligibility']['eligible'] is True
            assert not by_id[11]['week_membership']['within_window']
            assert by_id[11]['metric_adoption'][0]['reasons'][0]['scope'] == 'window'
            assert by_id[12]['captured_at'] is None
            for change in [{'tenant_id': 2}, {'engine_key': '0'}, {'limit': 4}, {'source_kind': 'real'}]:
                response = await client.get(path, params={**params, **change, 'cursor': first['pagination']['next_cursor']})
                assert response.status_code == 400
            simulated = await client.get(path, params={**params, 'source_kind': 'simulated'})
            assert [r['ref']['id'] for r in simulated.json()['items']] == [8]
            window = await client.get(path, params={**params, 'limit': 50,
                'captured_from': '2026-08-24T00:00:00+08:00', 'captured_to': '2026-08-31T00:00:00+08:00'})
            assert window.status_code == 200
            assert 11 not in [r['ref']['id'] for r in window.json()['items']]
            detail = await client.get(path + '/1', params={'tenant_id': 1, 'week_end': WEEK})
            assert detail.status_code == 200
            assert detail.json()['item']['raw_text'] == 'Synthetic answer 1'
            assert (await client.get(path + '/90', params={'tenant_id': 1, 'week_end': WEEK})).status_code == 404
    asyncio.run(run())
