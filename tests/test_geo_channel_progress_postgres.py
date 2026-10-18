"""Progress HTTP reads must not queue behind a channel worker's tenant lock."""
import asyncio
import os

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from test_geo_read_http_postgres import environment

pytestmark = pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires isolated PostgreSQL')


def test_channel_progress_remains_readable_under_worker_lock_and_tenant_scoped():
    from app.database import get_session
    from app.geo.content import routes as content
    from app.geo.routes import router
    from app.security.auth import AuthContext, require_auth

    async def run():
        async with environment() as (_, engine, tables, identity):
            async with engine.begin() as conn:
                for tenant in (17, 18):
                    await conn.execute(tables['tenants'].insert().values(id=tenant, name='synthetic fixture'))
                    await conn.execute(tables['tenant_modules'].insert().values(
                        tenant_id=tenant, module_code='geo', status='active'))
                    await conn.execute(tables['geo_async_jobs'].insert().values(
                        id=tenant, tenant_id=tenant, kind='create_variants', status='running',
                        ref_type='content_task', ref_id=16, request_meta={}))

            sessions = identity['sessions']

            async def control_session():
                async with sessions() as session:
                    yield session

            async def read_session():
                async with sessions() as session:
                    await session.execute(text('SET TRANSACTION READ ONLY'))
                    yield session

            # Mount the actual outer router, including request entitlement. A
            # content-only router would miss the locking bug that caused 499s.
            app = FastAPI()
            app.include_router(router)
            app.dependency_overrides[get_session] = control_session
            app.dependency_overrides[content.geo_read_session] = read_session
            app.dependency_overrides[require_auth] = lambda: AuthContext(
                user_id=9001, username='fixture', role_name='fixture', tenant_id=17,
                permissions={'geo.content': 'view'})
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                async with engine.begin() as worker:
                    await worker.execute(text('SELECT id FROM tenants WHERE id=17 FOR UPDATE'))
                    for path in ['/async-jobs', '/async-jobs/17']:
                        response = await asyncio.wait_for(client.get('/api/v1/geo' + path,
                            params={'tenant_id': 17}), timeout=2)
                        assert response.status_code == 200
                        payload = response.json()
                        job = payload['items'][0] if path == '/async-jobs' else payload
                        assert job['tenant_id'] == 17 and job['status'] == 'running'

                # The same polling endpoint observes the worker's terminal state.
                async with engine.begin() as conn:
                    await conn.execute(tables['geo_async_jobs'].update().where(
                        tables['geo_async_jobs'].c.id == 17).values(status='succeeded'))
                completed = await client.get('/api/v1/geo/async-jobs/17', params={'tenant_id': 17})
                assert completed.json()['status'] == 'succeeded'
                other_customer = await client.get('/api/v1/geo/async-jobs/18', params={'tenant_id': 18})
                assert other_customer.status_code == 403
                other_job = await client.get('/api/v1/geo/async-jobs/18', params={'tenant_id': 17})
                assert other_job.status_code == 404
                async with engine.begin() as conn:
                    await conn.execute(tables['tenant_modules'].update().where(
                        tables['tenant_modules'].c.tenant_id == 17).values(status='disabled'))
                revoked = await client.get('/api/v1/geo/async-jobs/17', params={'tenant_id': 17})
                assert revoked.status_code == 403

    asyncio.run(run())
