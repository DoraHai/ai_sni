"""Paid advisor visibility: mounted HTTP/auth/commit, owned SQL, no providers."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from starlette.background import BackgroundTasks

from app.config import Settings, get_settings
from app.models import (GeoProject, GeoPrompt, GeoTrackingEngine, GeoVisibilityPatrolRun,
                        GeoVisibilityPatrolSettings, GeoOptimizationPeriod, TenantModule)
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from test_advisor_scoped_writes import backend, fixture_token, mutate, write_sandbox


PATH = '/visibility-patrol/runs'


@asynccontextmanager
async def visibility_sandbox(tmp_path, monkeypatch, backend='sqlite', **kwargs):
    from app.geo.content import routes
    queued = []
    monkeypatch.setattr(BackgroundTasks, 'add_task', lambda _self, fn, *args, **kw: queued.append((fn, args)))
    def no_http(*_args, **_kwargs):
        pytest.fail('visibility tests must never call a supplier')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', no_http)
    entitlement = AsyncMock()
    monkeypatch.setattr(routes, 'ensure_geo_entitlement', entitlement)
    # Exact retest reservations use PostgreSQL JSON operators. Keep that real
    # path in PostgreSQL; SQLite tests exercise this denial via the same boundary.
    if backend == 'sqlite':
        import app.geo.retest as retest
        monkeypatch.setattr(retest, 'reserved_week', AsyncMock(return_value=None))
    async with write_sandbox(tmp_path, monkeypatch, backend=backend, **kwargs) as env:
        async with env.factory() as session:
            session.add_all([
                GeoTrackingEngine(tenant_id=10, engine_key='deepseek', display_name='test', enabled=True),
                GeoTrackingEngine(tenant_id=10, engine_key='kimi', display_name='off', enabled=False),
                GeoTrackingEngine(tenant_id=10, engine_key='other', display_name='other', enabled=True),
                GeoPrompt(id=99, tenant_id=10, question='unassigned question', status='active'),
            ])
            await session.commit()
        env.queued, env.entitlement = queued, entitlement
        yield env


def test_default_daily_limit_and_exact_rule():
    from types import SimpleNamespace
    from app.security.advisor_write_routes import VISIBILITY_RUN_RULE, match_write_rule
    assert Settings.model_fields['advisor_visibility_max_runs_per_day'].default == 10
    request = SimpleNamespace(method='POST', scope={'route': SimpleNamespace(path='/api/v1/geo' + PATH)})
    assert match_write_rule(request) == VISIBILITY_RUN_RULE
    request.scope = {}
    assert match_write_rule(request) is None


def test_advisor_can_read_and_start_only_assigned_questions(tmp_path, monkeypatch, backend):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            response = await env.request('POST', PATH, body={'tenant_id': 10})
            assert response.status_code == 200, response.text
            row = response.json()['run']
            assert row['trigger'] == 'manual' and row['created_by'] == 1
            assert row['prompt_limit'] == 20 and row['engine_keys'] == ['deepseek']
            assert row['auto_persist'] and row['prefer_real']
            assert row['summary']['advisor_visibility_prompt_ids'] == [10]
            assert len(env.queued) == 1 and env.queued[0][1] == (row['id'], 10)
            env.entitlement.assert_awaited_once()
            for path in [PATH, PATH + '/' + str(row['id']), '/answer-snapshots', '/tracking-engines']:
                read = await env.request('GET', path)
                assert read.status_code == 200, read.text
    asyncio.run(run())


def test_selected_second_customer_can_start_detection_without_changing_default(tmp_path, monkeypatch, backend):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            async with env.factory() as session:
                session.add(GeoTrackingEngine(tenant_id=20, engine_key='deepseek', display_name='test', enabled=True))
                session.add_all([GeoVisibilityPatrolRun(tenant_id=10, created_by=1, status='failed') for _ in range(10)])
                await session.commit()
            response = await env.request('POST', PATH, body={'tenant_id': 20}, params={'tenant_id': 20},
                auth=fixture_token(tid=20, gid=102))
            assert response.status_code == 200, response.text
            assert response.json()['run']['summary']['advisor_visibility_prompt_ids'] == [20]
            assert len(env.queued) == 1 and env.queued[0][1][-1] == 20
    asyncio.run(run())


@pytest.mark.parametrize('case', ['off', 'query-missing', 'wrong-tenant', 'ungranted', 'identity', 'unassigned', 'inactive', 'module'])
def test_all_authority_boundaries_reject_without_dispatch(tmp_path, monkeypatch, backend, case):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend, enabled=case != 'off') as env:
            params, auth = {}, None
            if case == 'query-missing':
                params = {'tenant_id': None}
            if case in {'wrong-tenant', 'ungranted'}:
                params = {'tenant_id': 20 if case == 'wrong-tenant' else 30}
            if case == 'identity':
                auth = fixture_token(scope_kind='advisor_identity', aud='advisor-session')
            if case in {'unassigned', 'inactive'}:
                async with env.factory() as session:
                    p = await session.get(GeoProject, 10)
                    if case == 'unassigned':
                        p.project_settings = {**p.project_settings, 'geo_service_plan': {'advisor_user_id': 2}}
                    else:
                        p.status = 'paused'
                    await session.commit()
            if case == 'module':
                await mutate(env, TenantModule, 10, status='disabled')
            response = await env.request('POST', PATH, body={'tenant_id': 10}, params=params, auth=auth)
            assert response.status_code in {403, 409, 422}, response.text
            assert not env.queued
            async with env.factory() as session:
                assert not list(await session.scalars(select(GeoVisibilityPatrolRun)))
    asyncio.run(run())


@pytest.mark.parametrize('extra', [{'run_async': False}, {'engine_keys': ['kimi']}, {'prompt_limit': 50},
    {'auto_persist': False}, {'prefer_real': False}, {'trigger': 'schedule'}, {'enabled': True}, {'items': []}])
def test_client_cannot_change_fixed_run_or_schedule(tmp_path, monkeypatch, extra):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch) as env:
            response = await env.request('POST', PATH, body={'tenant_id': 10, **extra})
            assert response.status_code == 403, response.text
            assert not env.queued
    asyncio.run(run())


@pytest.mark.parametrize('method,path', [
    ('PUT', '/tracking-engines'), ('PUT', '/ai-settings'), ('POST', '/ai-settings/test'),
    ('PUT', '/visibility-patrol/settings'), ('POST', '/answer-snapshots/probe'),
    ('POST', '/answer-snapshots/probe-batch'), ('POST', '/integration/scheduler-safe-foundation'),
    ('POST', '/content-tasks/10/ai-review'), ('POST', '/content-tasks/10/variants'),
    ('POST', '/content-tasks/10/submit-review'), ('POST', '/content-tasks/10/review'),
     ('DELETE', '/content-tasks/10'),
    ('POST', '/facts/10/verify'),
])
def test_other_paid_or_high_risk_operations_stay_403(tmp_path, monkeypatch, method, path):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch) as env:
            before = await env.snapshot()
            response = await env.request(method, path, body={'tenant_id': 10})
            assert response.status_code == 403, response.text
            assert await env.snapshot() == before and not env.queued
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['patrol', 'period', 'plan'])
def test_manual_detection_allowed_during_automatic_execution(tmp_path, monkeypatch, backend, kind):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            async with env.factory() as session:
                if kind == 'patrol':
                    (await session.get(GeoVisibilityPatrolSettings, 10)).enabled = True
                elif kind == 'period':
                    session.add(GeoOptimizationPeriod(tenant_id=10, name='test', status='active',
                        starts_at=datetime(2026, 1, 1), ends_at=datetime(2027, 1, 1)))
                else:
                    p = await session.get(GeoProject, 10)
                    p.project_settings = {**p.project_settings, 'geo_service_plan': {'enabled': True, 'advisor_user_id': 1}}
                await session.commit()
            response = await env.request('POST', PATH, body={'tenant_id': 10})
            assert response.status_code == 200, response.text
            assert len(env.queued) == 1
    asyncio.run(run())


@pytest.mark.parametrize('status', ['completed', 'failed'])
@pytest.mark.parametrize('configured_limit', [None, 2])
def test_daily_limit_counts_attempts_and_stays_ten(tmp_path, monkeypatch, backend, status, configured_limit):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            if configured_limit is not None:
                monkeypatch.setattr(get_settings(), 'advisor_visibility_max_runs_per_day', configured_limit)
            limit = 10
            async with env.factory() as session:
                session.add_all([
                    GeoVisibilityPatrolRun(tenant_id=10, created_by=1, status=status)
                    for _ in range(limit - 1)
                ])
                await session.commit()
            response = await env.request('POST', PATH, body={'tenant_id': 10})
            assert response.status_code == 200, response.text
            assert len(env.queued) == 1
            await mutate(env, GeoVisibilityPatrolRun, response.json()['run']['id'], status=status)
            response = await env.request('POST', PATH, body={'tenant_id': 10})
            assert response.status_code == 429 and f'{limit}/{limit}' in response.text, response.text
            assert len(env.queued) == 1
    asyncio.run(run())


def test_daily_count_is_per_advisor_customer_and_shanghai_day(tmp_path, monkeypatch, backend):
    async def run():
        from app.geo.content.time_windows import shanghai_day_bounds_utc_naive
        from app.geo.content.patrol import count_patrol_runs_today
        from zoneinfo import ZoneInfo
        start, end = shanghai_day_bounds_utc_naive(datetime.now(ZoneInfo('Asia/Shanghai')).date())
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            async with env.factory() as session:
                for tid, uid, created in [(10, 1, start - timedelta(microseconds=1)), (10, 1, start),
                    (10, 1, end), (10, 2, start), (20, 1, start)]:
                    session.add(GeoVisibilityPatrolRun(tenant_id=tid, created_by=uid, status='failed', created_at=created))
                await session.commit()
                assert await count_patrol_runs_today(session, 10, created_by=1) == 1
                assert await count_patrol_runs_today(session, 10) == 2
    asyncio.run(run())


@pytest.mark.parametrize('status', ['pending', 'running'])
def test_customer_inflight_rejects_even_other_creator_and_old_day(tmp_path, monkeypatch, backend, status):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            async with env.factory() as session:
                session.add(GeoVisibilityPatrolRun(tenant_id=10, created_by=2, status=status,
                    trigger='schedule', created_at=datetime.utcnow() - timedelta(days=1)))
                await session.commit()
            response = await env.request('POST', PATH, body={'tenant_id': 10})
            assert response.status_code == 409 and '排队或运行' in response.text, response.text
            assert not env.queued
    asyncio.run(run())


def test_entitlement_and_tenant_quota_are_not_bypassed(tmp_path, monkeypatch):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch) as env:
            env.entitlement.side_effect = HTTPException(403, 'GEO 权益已失效')
            assert (await env.request('POST', PATH, body={'tenant_id': 10})).status_code == 403
            env.entitlement.side_effect = None
            monkeypatch.setattr(get_settings(), 'geo_patrol_max_runs_per_day', 1)
            async with env.factory() as session:
                session.add(GeoVisibilityPatrolRun(tenant_id=10, created_by=2, status='completed'))
                await session.commit()
            response = await env.request('POST', PATH, body={'tenant_id': 10})
            assert response.status_code == 429 and not env.queued
    asyncio.run(run())


@pytest.mark.parametrize('missing', ['prompts', 'engines'])
def test_empty_assigned_scope_never_falls_back_to_other_data(tmp_path, monkeypatch, missing):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch) as env:
            async with env.factory() as session:
                if missing == 'prompts':
                    await session.execute(update(GeoPrompt).where(GeoPrompt.id == 10).values(status='paused'))
                else:
                    await session.execute(update(GeoTrackingEngine).values(enabled=False))
                await session.commit()
            response = await env.request('POST', PATH, body={'tenant_id': 10})
            assert response.status_code == 409, response.text
            assert not env.queued
    asyncio.run(run())


def test_real_worker_uses_frozen_questions_and_existing_entitlement_checks(tmp_path, monkeypatch, backend):
    async def run():
        from app.geo.content import ai_settings, daily_metrics, patrol
        from app.models import GeoAnswerSnapshot
        from types import SimpleNamespace
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            response = await env.request('POST', PATH, body={'tenant_id': 10})
            assert response.status_code == 200, response.text
            run_id = response.json()['run']['id']
            monkeypatch.setattr(ai_settings, 'resolve_llm_credentials', AsyncMock(return_value={}))
            monkeypatch.setattr(ai_settings, 'ensure_ai_setting', AsyncMock(return_value=SimpleNamespace(monitoring_stance='hybrid')))
            monkeypatch.setattr(patrol, 'resolve_engine_llm', lambda **kw: (
                {'api_key': 'fixture-only', 'model': 'fixture-model', 'provider': 'fixture'}, 'openai_compat', None))
            probe = AsyncMock(return_value={'raw_text': 'synthetic fixture answer', 'simulated': False,
                'sample_mode': 'openai_compat', 'suggested_mentions_brand': False, 'analysis_status': 'completed'})
            entitlement = AsyncMock()
            monkeypatch.setattr(patrol, 'run_probe_draft', probe)
            monkeypatch.setattr(patrol, 'ensure_geo_entitlement', entitlement)
            monkeypatch.setattr(daily_metrics, 'safe_rebuild_day', AsyncMock())
            async with env.factory() as session:
                row = await patrol.execute_patrol_run(session, run_id, tenant_id=10)
                assert row.status == 'completed', row.error
                assert row.summary['advisor_visibility_prompt_ids'] == [10]
                assert row.summary['snapshots_created'] == 1
                assert list(await session.scalars(select(GeoAnswerSnapshot.prompt_id))) == [10]
            probe.assert_awaited_once()
            assert probe.await_args.kwargs['question'] == 'fixture question 10?'
            assert entitlement.await_count >= 4
    asyncio.run(run())


@pytest.mark.parametrize('change', ['grant', 'assignment', 'flag'])
def test_actual_commit_hook_rejects_last_moment_changes(tmp_path, monkeypatch, backend, change):
    async def run():
        import app.security.advisor_write_commit as policy
        original = policy.recheck_advisor_before_commit
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            async def race(session, ctx):
                if change == 'grant':
                    await session.execute(update(Grant).where(Grant.id == 101).values(
                        revoked_at=datetime.utcnow(), revoked_by=2, revoke_reason='admin_uncheck'))
                elif change == 'assignment':
                    await session.execute(update(GeoProject).where(GeoProject.id == 10).values(project_settings={}))
                else:
                    monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', False)
                await original(session, ctx)
            monkeypatch.setattr(policy, 'recheck_advisor_before_commit', race)
            response = await env.request('POST', PATH, body={'tenant_id': 10})
            assert response.status_code in {401, 403}, response.text
            assert not env.queued
            async with env.factory() as session:
                assert not list(await session.scalars(select(GeoVisibilityPatrolRun)))
    asyncio.run(run())


def test_postgres_two_simultaneous_requests_only_enqueue_one(tmp_path, monkeypatch, backend):
    if backend != 'postgres':
        pytest.skip('real row-lock race is PostgreSQL only')
    async def run():
        monkeypatch.setattr(get_settings(), 'advisor_visibility_max_runs_per_day', 2)
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            responses = await asyncio.gather(*[
                env.request('POST', PATH, body={'tenant_id': 10}) for _ in range(2)])
            assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
            assert len(env.queued) == 1
    asyncio.run(run())


def test_retest_cannot_start_alongside_existing_manual_detection(tmp_path, monkeypatch, backend):
    async def run():
        from types import SimpleNamespace
        from app.geo import integration, retest
        from app.security.auth import AuthContext
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            async with env.factory() as session:
                session.add(GeoVisibilityPatrolRun(tenant_id=10, created_by=1, status='pending', trigger='manual'))
                await session.commit()
                monkeypatch.setattr(integration, 'ticket', AsyncMock(return_value=SimpleNamespace(progress={})))
                monkeypatch.setattr(retest, 'prepare_retest', AsyncMock(return_value={}))
                ctx = AuthContext(user_id=2, username='fixture', role_name='admin', tenant_id=None, is_superadmin=True)
                with pytest.raises(HTTPException) as denied:
                    await integration.start_retest(10, BackgroundTasks(), 10, ctx, session)
                assert denied.value.status_code == 409
            assert not env.queued
    asyncio.run(run())
