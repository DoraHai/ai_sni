"""Import authorization through real auth/handlers and synthetic fixture SQL."""
import asyncio
import copy
from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from app.models import GeoOptimizationPeriod, GeoProject, GeoPrompt, GeoVisibilityPatrolSettings
from test_advisor_scoped_writes import (
    backend, fixture_token, mutate, no_external_http_or_background_dispatch, write_sandbox,
)

PATH = '/content-imports/create-task'
BODY = {'tenant_id': 10, 'prompt_id': 10, 'title': 'Imported fixture article',
        'body_markdown': 'Existing article text.', 'source_type': 'paste',
        'target_channels': ['website']}


@pytest.mark.parametrize('change', [
    {'source_type': 'unknown'}, {'source_type': None},
    {'status': 'published'}, {'owner_user_id': 2}, {'version_no': 8},
    {'published': True}, {'review_status': 'approved'}, {'prompt_id': 20},
    {'tenant_id': 20}, {'tenant_id': 30},
])
def test_import_rejects_protected_fields_and_foreign_owners(tmp_path, monkeypatch, backend, change):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            response = await env.request('POST', PATH, body={**BODY, **change})
            assert response.status_code == 403, response.text
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('query', ['', 'tenant_id=20', 'tenant_id=30'])
def test_import_requires_selected_customer_query(tmp_path, monkeypatch, backend, query):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            import httpx
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url='http://fixture') as client:
                response = await client.post('/api/v1/geo' + PATH + '?' + query,
                    json=BODY, headers={'Authorization': 'Bearer ' + fixture_token()})
            assert response.status_code == 403, response.text
    asyncio.run(run())


@pytest.mark.parametrize('problem', ['unscoped', 'unassigned', 'inactive', 'ambiguous'])
def test_import_requires_prompt_in_unique_assigned_active_project(tmp_path, monkeypatch, backend, problem):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            if problem == 'unscoped':
                await mutate(env, GeoPrompt, 10, unit_id=None)
            elif problem == 'inactive':
                await mutate(env, GeoProject, 10, status='archived')
            else:
                async with env.factory() as session:
                    project = await session.get(GeoProject, 10)
                    settings = copy.deepcopy(project.project_settings)
                    if problem == 'unassigned':
                        settings['geo_service_plan']['advisor_user_id'] = 2
                        project.project_settings = settings
                    else:
                        session.add(GeoProject(tenant_id=10, tenant_module_id=10,
                            name='ambiguous fixture', primary_domain='duplicate.example.test',
                            canonical_domain='duplicate.example.test', status='active', project_settings=settings))
                    await session.commit()
            before = await env.snapshot()
            response = await env.request('POST', PATH, body=BODY)
            assert response.status_code == 403, response.text
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('chain', ['patrol', 'period', 'plan'])
def test_import_allowed_during_enabled_execution_chain(tmp_path, monkeypatch, backend, chain):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            async with env.factory() as session:
                if chain == 'patrol':
                    row = await session.get(GeoVisibilityPatrolSettings, 10)
                    row.enabled = True
                elif chain == 'period':
                    session.add(GeoOptimizationPeriod(tenant_id=10, status='active', name='fixture period',
                        starts_at=datetime.now(), ends_at=datetime.now() + timedelta(days=7)))
                else:
                    project = await session.get(GeoProject, 10)
                    settings = copy.deepcopy(project.project_settings)
                    settings['geo_service_plan']['enabled'] = True
                    project.project_settings = settings
                await session.commit()
            before = await env.snapshot()
            response = await env.request('POST', PATH, body=BODY)
            assert response.status_code == 200, response.text
            assert await env.snapshot() != before
    asyncio.run(run())


@pytest.mark.parametrize('source', ['paste', 'file', 'url'])
def test_import_server_derives_owner_state_and_first_version(tmp_path, monkeypatch, backend, source):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            response = await env.request('POST', PATH, body={**BODY, 'source_type': source})
            assert response.status_code == 200, response.text
            after = await env.snapshot()
            task = next(r for r in after['geo_content_tasks'] if r['title'] == BODY['title'])
            article = next(r for r in after['geo_article_versions'] if r['task_id'] == task['id'])
            assert task['owner_user_id'] == 1 and task['status'] in {'editing', 'needs_fix'}
            assert task['business_id'] == 10 and task['period_id'] is None
            assert task['review_status'] != 'approved'
            assert article['version_no'] == 1 and article['created_by'] == 1
            assert article['body_markdown'] == BODY['body_markdown']
            assert article['generation_meta']['source_type'] == source
            for table in ('geo_publications', 'geo_channel_variants', 'geo_async_jobs'):
                assert after[table] == before[table]
    asyncio.run(run())


def test_import_into_another_explicitly_granted_selected_customer(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            response = await env.request('POST', PATH,
                body={**BODY, 'tenant_id': 20, 'prompt_id': 20},
                params={'tenant_id': 20}, auth=fixture_token(tid=20, gid=102))
            assert response.status_code == 200, response.text
            rows = (await env.snapshot())['geo_content_tasks']
            assert any(r['tenant_id'] == 20 and r['owner_user_id'] == 1 and
                       r['title'] == BODY['title'] for r in rows)
    asyncio.run(run())


@pytest.mark.parametrize('change', ['assignment'])
@pytest.mark.parametrize('source', ['paste', 'file', 'url'])
def test_import_rechecks_scope_at_actual_commit_and_rolls_back(tmp_path, monkeypatch, backend, change, source):
    from app.geo.content import routes
    original = routes._evaluate_and_store_rules

    async def changed_before_commit(session, *args, **kwargs):
        result = await original(session, *args, **kwargs)
        if change == 'patrol':
            await session.execute(update(GeoVisibilityPatrolSettings).where(
                GeoVisibilityPatrolSettings.tenant_id == 10).values(enabled=True))
        else:
            project = await session.get(GeoProject, 10)
            settings = copy.deepcopy(project.project_settings)
            settings['geo_service_plan']['advisor_user_id'] = 2
            project.project_settings = settings
        return result

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            monkeypatch.setattr(routes, '_evaluate_and_store_rules', changed_before_commit)
            before = await env.snapshot()
            response = await env.request('POST', PATH, body={**BODY, 'source_type': source})
            assert response.status_code == 403, response.text
            assert await env.snapshot() == before
    asyncio.run(run())
