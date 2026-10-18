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
                content_match = model.title == 'New fact' if model is m.GeoFact else model.question == 'New imported question?'
                rows = list(await session.scalars(select(model).where(model.tenant_id == 10, content_match)))
                assert len(rows) == 1
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


@pytest.mark.parametrize('path,body', (
    ('/prompts/10', {'is_brand_probe': True}),
    ('/optimization-businesses/10', {'status': 'archived'}),
    ('/optimization-units/10', {'status': 'archived'}),
))
def test_operational_classification_and_archive_fields_persist(tmp_path, monkeypatch, backend, path, body):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            response = await env.request('PATCH', path, body=body)
            assert response.status_code == 200, response.text
            for key, value in body.items():
                assert response.json()[key] == value
    asyncio.run(run())


def test_manual_account_metadata_and_status_work_without_credentials(tmp_path, monkeypatch, backend):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from app.geo.content import routes

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend, extra_tables=('geo_channel_accounts',)) as env:
            monkeypatch.setattr(routes, 'ensure_geo_entitlement',
                AsyncMock(return_value=SimpleNamespace(is_demo=False, read_only=False)))
            async with env.factory() as session:
                session.add(m.GeoPublishingChannel(id=100, tenant_id=10, name='fixture destination',
                    channel_type='website', publish_mode='manual_only', enabled=True))
                await session.commit()
            response = await env.request('POST', '/channel-accounts', body={'tenant_id': 10,
                'channel_id': 100, 'display_name': 'manual account', 'auth_type': 'manual'})
            assert response.status_code == 200, response.text
            ident = response.json()['id']
            response = await env.request('PATCH', f'/channel-accounts/{ident}',
                body={'display_name': 'edited manual account', 'status': 'active'})
            assert response.status_code == 200, response.text
            before = await env.snapshot()
            response = await env.request('PATCH', f'/channel-accounts/{ident}', body={'credentials': {'api_key': 'fixture'}})
            assert response.status_code == 403 and await env.snapshot() == before
            response = await env.request('DELETE', f'/channel-accounts/{ident}')
            assert response.status_code == 200, response.text
    asyncio.run(run())


def test_malformed_visibility_request_does_not_spend_a_daily_attempt(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            response = await env.request('POST', '/answer-snapshots/probe', body={'tenant_id': 10})
            assert response.status_code == 422, response.text
            assert await env.snapshot() == before
    asyncio.run(run())


def test_project_restore_only_changes_status_and_keeps_inactive_content_hidden(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            from app.geo.project_routes import geo_projects_router
            env.app.include_router(geo_projects_router)
            response = await env.request('PATCH', '/projects/10', body={'status': 'paused'})
            assert response.status_code == 200, response.text
            assert (await env.request('GET', '/facts')).json()['items'] == []
            assert (await env.request('PATCH', '/facts/10', body={'title': 'blocked'})).status_code == 403
            response = await env.request('PATCH', '/projects/10', body={'status': 'active', 'description': 'blocked'})
            assert response.status_code == 403, response.text
            response = await env.request('PATCH', '/projects/10', body={'status': 'active'})
            assert response.status_code == 200, response.text
            assert (await env.request('GET', '/facts')).json()['items']
    asyncio.run(run())


def test_ticket_cannot_borrow_an_owned_project_for_foreign_content(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            await foreign_project(env)
            from app.geo.integration import router
            env.app.include_router(router, prefix='/api/v1/geo')
            async with env.factory() as session:
                session.add(m.GeoActionTicket(id=99, tenant_id=10, content_task_id=50,
                    title='inconsistent foreign ticket', advice_code='cockpit:v1:task',
                    progress={'project_workflow': {'project_id': 10}}, progress_first={'params': {}}))
                await session.commit()
            response = await env.request('GET', '/integration/tasks/99')
            assert response.status_code == 403, response.text
            response = await env.request('PATCH', '/integration/tasks/99', body={'status': 'in_progress'})
            assert response.status_code == 403, response.text
    asyncio.run(run())


def test_real_advisor_cannot_read_platform_billing_or_key_state(tmp_path, monkeypatch, backend):
    from unittest.mock import AsyncMock
    from app.geo.content import search_visibility_routes as routes
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            env.app.include_router(routes.router, prefix='/api/v1/geo')
            billing = AsyncMock()
            monkeypatch.setattr(routes, 'month_usage', billing)
            response = await env.request('GET', '/search-visibility/usage')
            assert response.status_code == 403, response.text
            billing.assert_not_awaited()
    asyncio.run(run())


def test_null_business_tasks_follow_prompt_ownership_in_lists(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            await foreign_project(env)
            for ident in (10, 50):
                await mutate(env, m.GeoContentTask, ident, business_id=None)
            response = await env.request('GET', '/content-tasks')
            assert response.status_code == 200, response.text
            ids = {row['id'] for row in response.json()['items']}
            assert 10 in ids and not ids & {20, 30, 50}
    asyncio.run(run())


@pytest.mark.parametrize('cleanup', (False, True))
def test_patrol_delete_keeps_samples_and_repairs_retest_references(tmp_path, monkeypatch, backend, cleanup):
    from sqlalchemy import select
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            async with env.factory() as session:
                session.add(m.GeoVisibilityPatrolRun(id=100, tenant_id=10, status='completed',
                    trigger='contract_retest', created_by=1, items=[{'prompt_id': 10}], summary={
                        'prompts': 1, 'contract_plan': {'cells': [{'prompt_id': 10}]}}))
                await session.flush()
                session.add(m.GeoAnswerSnapshot(id=100, tenant_id=10, prompt_id=10, engine='other',
                    raw_text='retained answer', captured_at=datetime(2026, 10, 19),
                    patrol_run_id=100, sample_mode='openai_compat', simulated=False))
                session.add(m.GeoActionTicket(id=100, tenant_id=10, title='retest ticket',
                    progress={'project_workflow': {'project_id': 10}, 'retest_runs': {'fixture-week': 100}}))
                await session.commit()
            response = await env.request('POST', '/visibility-patrol/runs/cleanup',
                params={'keep_latest': 0, 'project_id': 10}) if cleanup else await env.request(
                    'DELETE', '/visibility-patrol/runs/100')
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                assert await session.get(m.GeoVisibilityPatrolRun, 100) is None
                snapshot = await session.get(m.GeoAnswerSnapshot, 100)
                assert snapshot.patrol_run_id is None and snapshot.raw_text == 'retained answer'
                assert snapshot.sample_mode == 'openai_compat' and not snapshot.simulated
                assert '#100' in snapshot.note
                ticket = await session.get(m.GeoActionTicket, 100)
                assert ticket.progress['retest_runs'] == {}
                assert ticket.progress['deleted_retest_runs']['100']['deleted_by'] == 1
                from app.geo.content.patrol import count_patrol_runs_today
                assert await count_patrol_runs_today(session, 10, created_by=1) == 1
    asyncio.run(run())


def test_onboarding_new_business_questions_keep_their_new_unit(tmp_path, monkeypatch, backend):
    from sqlalchemy import select
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            response = await env.request('POST', '/onboarding/apply', params={'project_id': 10}, body={
                'tenant_id': 10, 'businesses': [{'name': 'new owned business'}],
                'prompts': [{'question': 'Which new business fits?', 'business_name': 'new owned business'}],
                'create_website_channel': False})
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                business = await session.scalar(select(m.GeoOptimizationBusiness).where(
                    m.GeoOptimizationBusiness.name == 'new owned business'))
                prompt = await session.scalar(select(m.GeoPrompt).where(m.GeoPrompt.question == 'Which new business fits?'))
                unit = await session.get(m.GeoOptimizationUnit, prompt.unit_id)
                assert unit.business_id == business.id and business.id != 10
                project = await session.get(m.GeoProject, 10)
                assert business.id in project.project_settings['geo_business_scope']['business_ids']
    asyncio.run(run())


def test_diagnosis_can_create_scoped_content_with_multiple_businesses_and_units(tmp_path, monkeypatch, backend):
    from sqlalchemy import select
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            async with env.factory() as session:
                project = await session.get(m.GeoProject, 10)
                settings = {**project.project_settings}
                settings['geo_business_scope'] = {**settings['geo_business_scope'], 'business_ids': [10, 11]}
                project.project_settings = settings
                session.add(m.GeoOptimizationBusiness(id=11, tenant_id=10, name='second owned business', status='active'))
                await session.flush()
                session.add_all([
                    m.GeoOptimizationUnit(id=11, tenant_id=10, business_id=11, name='second owned unit', status='active'),
                    m.GeoOptimizationUnit(id=12, tenant_id=10, business_id=10, name='extra first unit', status='active'),
                    m.GeoAuditRun(id=100, tenant_id=10, url='https://' + project.canonical_domain,
                        page_title='fixture diagnosis', status='completed')])
                await session.commit()
            response = await env.request('POST', '/content-tasks/from-diagnosis',
                params={'project_id': 10}, body={'tenant_id': 10, 'audit_id': 100})
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                task = await session.scalar(select(m.GeoContentTask).where(m.GeoContentTask.diagnosis_audit_id == 100))
                prompt = await session.get(m.GeoPrompt, task.prompt_id)
                unit = await session.get(m.GeoOptimizationUnit, prompt.unit_id)
                assert unit.business_id == 10 and unit.id == 10
            listed = await env.request('GET', '/content-tasks')
            assert task.id in {item['id'] for item in listed.json()['items']}
    asyncio.run(run())


@pytest.mark.parametrize('missing', ('article', 'credentials'))
def test_ai_review_preconditions_do_not_burn_suggestion_attempts(tmp_path, monkeypatch, backend, missing):
    from unittest.mock import AsyncMock
    from app.geo.content import routes, ai_settings, ai_reviewer
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            reviewer = AsyncMock()
            monkeypatch.setattr(ai_reviewer, 'run_ai_review', reviewer)
            if missing == 'article':
                monkeypatch.setattr(routes, '_latest_article', AsyncMock(return_value=None))
            else:
                monkeypatch.setattr(ai_settings, 'resolve_llm_credentials', AsyncMock(return_value=None))
            before = await env.snapshot()
            response = await env.request('POST', '/content-tasks/10/ai-review', body={'persist': False})
            assert response.status_code == (400 if missing == 'article' else 503), response.text
            reviewer.assert_not_awaited()
            assert await env.snapshot() == before
    asyncio.run(run())


def test_admitted_ai_review_provider_failure_still_counts(tmp_path, monkeypatch, backend):
    from unittest.mock import AsyncMock
    from sqlalchemy import func, select
    from app.ai.deepseek import DeepSeekError
    from app.geo.content import ai_settings, ai_reviewer
    from app.security.advisor_write_ai import SUGGEST_KIND
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            monkeypatch.setattr(ai_settings, 'resolve_llm_credentials',
                AsyncMock(return_value={'api_key': 'fixture', 'model': 'fixture'}))
            monkeypatch.setattr(ai_reviewer, 'run_ai_review',
                AsyncMock(side_effect=DeepSeekError('fixture provider failure')))
            response = await env.request('POST', '/content-tasks/10/ai-review', body={'persist': False})
            assert response.status_code == 502, response.text
            async with env.factory() as session:
                used = await session.scalar(select(func.count()).select_from(m.GeoAsyncJob).where(
                    m.GeoAsyncJob.tenant_id == 10, m.GeoAsyncJob.created_by == 1, m.GeoAsyncJob.kind == SUGGEST_KIND))
                assert used == 1
    asyncio.run(run())
