"""Synthetic isolated CI fixtures; local runner only executes the pure policy suite."""
import asyncio
from datetime import datetime

import pytest

from app import models as m
from test_advisor_scoped_writes import backend, fixture_token, mutate, write_sandbox


async def foreign_project(env):
    async with env.factory() as session:
        session.add(m.GeoOptimizationBusiness(id=50, tenant_id=10, name='foreign business'))
        await session.flush()
        session.add(m.GeoOptimizationUnit(id=50, tenant_id=10, business_id=50, name='foreign unit'))
        session.add(m.GeoProject(id=50, tenant_id=10, tenant_module_id=10, name='foreign project',
            primary_domain='foreign.test', canonical_domain='foreign.test', status='active',
            project_settings={'geo_business_scope': {'business_ids': [50]},
                              'geo_service_plan': {'advisor_user_id': 3}}))
        await session.flush()
        session.add(m.GeoPrompt(id=50, tenant_id=10, unit_id=50, question='foreign question'))
        session.add(m.GeoFact(id=50, tenant_id=10, business_id=50, title='foreign fact',
            statement='foreign statement', source_name='fixture', trust_level='draft', status='active'))
        await session.flush()
        session.add(m.GeoContentTask(id=50, tenant_id=10, prompt_id=50, business_id=50,
            title='foreign task', status='editing', target_channels=['website'], brief={}))
        session.add(m.GeoAnswerSnapshot(id=50, tenant_id=10, prompt_id=50, engine='other',
            raw_text='foreign snapshot', captured_at=datetime(2026, 10, 19)))
        await session.commit()


@pytest.mark.parametrize('path', ('/facts', '/prompts', '/content-tasks', '/answer-snapshots',
                                 '/optimization-businesses', '/optimization-units'))
def test_list_filters_unselected_customers_and_same_customer_other_project(tmp_path, monkeypatch, backend, path):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            await foreign_project(env)
            response = await env.request('GET', path)
            assert response.status_code == 200, response.text
            assert 'foreign' not in response.text
            ids = {item['id'] for item in response.json()['items']}
            assert not ids & {20, 30, 50}
    asyncio.run(run())


@pytest.mark.parametrize('path', ('/content-tasks/50', '/projects/50/executions',
    '/optimization-businesses/50/dashboard', '/facts?business_id=50'))
def test_foreign_details_are_rejected(tmp_path, monkeypatch, backend, path):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            from app.geo.project_routes import geo_projects_router
            env.app.include_router(geo_projects_router)
            await foreign_project(env)
            if '?' in path:
                response = await env.request('GET', path.split('?')[0], params={'business_id': 50})
            else:
                response = await env.request('GET', path)
            assert response.status_code in {403, 404}, response.text
    asyncio.run(run())


@pytest.mark.parametrize('resource,parent,content', (
    ('facts/import', {'business_id': 10}, b'title,statement,source_name\nNew fact,synthetic statement,fixture\n'),
    ('prompts/import-csv', {'unit_id': 10}, b'question\nNew imported question?\n'),
))
def test_csv_imports_persist_real_project_ownership(tmp_path, monkeypatch, backend, resource, parent, content):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            response = await env.request('POST', '/' + resource, params=parent,
                files={'file': ('fixture.csv', content, 'text/csv')})
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                from sqlalchemy import select
                model = m.GeoFact if resource.startswith('facts') else m.GeoPrompt
                rows = list(await session.scalars(select(model).where(model.tenant_id == 10, model.id > 30)))
                assert rows
                assert all(getattr(row, 'business_id' if model is m.GeoFact else 'unit_id') == 10 for row in rows)
    asyncio.run(run())


@pytest.mark.parametrize('failure', ('unassigned', 'inactive', 'disabled', 'foreign'))
def test_new_import_scope_rejects_every_invalid_owner(tmp_path, monkeypatch, backend, failure):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend, enabled=failure != 'disabled') as env:
            await foreign_project(env)
            if failure == 'unassigned':
                await mutate(env, m.GeoProject, 10, project_settings={'geo_business_scope': {'business_ids': [10]},
                    'geo_service_plan': {'advisor_user_id': 3}})
            elif failure == 'inactive':
                await mutate(env, m.GeoProject, 10, status='paused')
            before = await env.snapshot()
            response = await env.request('POST', '/facts/import', params={'business_id': 50 if failure == 'foreign' else 10},
                files={'file': ('fixture.csv', b'title,statement,source_name\nNew fact,synthetic statement,fixture\n', 'text/csv')})
            assert response.status_code == 403, response.text
            assert await env.snapshot() == before
    asyncio.run(run())
