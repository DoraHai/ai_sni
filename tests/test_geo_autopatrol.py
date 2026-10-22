"""Mounted synthetic API policy and durable self-service state transitions."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func

from app.geo.content import autopatrol as service, autopatrol_queue as queue
from app.geo.content.autopatrol_routes import router
from app.models import GeoPrompt, GeoProject, GeoVisibilityPatrolRun as Run, GeoVisibilityPatrolSettings as Settings, User
from app.models.geo_visibility_patrol import GeoVisibilityPatrolSettingEvent as Event
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from test_geo_advisor_visibility import visibility_sandbox
from test_advisor_scoped_writes import fixture_token, mutate, backend

PATH = '/visibility-patrol/self-service'


@asynccontextmanager
async def sandbox(tmp_path, monkeypatch, backend='sqlite'):
    from app.geo.content import engine_providers
    def credentials(key, **kwargs):
        return {'api_key': 'synthetic-only', 'base_url': 'https://supplier.invalid',
                'provider': key, 'model': {'wenxin': 'ernie-test', 'doubao': 'doubao-test', 'hunyuan': 'hunyuan-test'}.get(key, key + '-test')}
    monkeypatch.setattr(engine_providers, 'resolve_platform_engine_credentials', credentials)
    async with visibility_sandbox(tmp_path, monkeypatch, backend, extra_tables=(Event.__tablename__, 'geo_visibility_patrol_daily_budget')) as env:
        env.app.include_router(router, prefix='/api/v1/geo')
        import app.database as database
        monkeypatch.setattr(database, 'engine', env.engine)
        yield env


async def toggle(env, enabled, revision=0, **kwargs):
    return await env.request('PUT', PATH, body={'tenant_id': 10, 'enabled': enabled, 'expected_revision': revision}, **kwargs)


def test_advisor_enables_only_own_scope_and_admin_can_only_stop_unlock(tmp_path, monkeypatch, backend):
    async def run():
        async with sandbox(tmp_path, monkeypatch, backend) as env:
            opened = await toggle(env, True)
            assert opened.status_code == 200, opened.text
            body = opened.json()
            assert body['enabled'] and body['owner']['user_id'] == 1
            assert body['schedule_mode'] == service.MODE and len(body['platforms']) == 6
            revision = body['revision']
            assert not env.queued
            assert (await toggle(env, True, revision)).json()['revision'] == revision
            assert (await toggle(env, False, 0)).status_code == 409
            admin = fixture_token(uid=2, native=True)
            assert (await toggle(env, True, revision, auth=admin)).status_code == 403
            assert (await env.request('POST', PATH + '/admin-action', body={'tenant_id': 10, 'action': 'enable', 'reason': 'x', 'expected_revision': revision}, auth=admin)).status_code == 422
            forced = await env.request('POST', PATH + '/admin-action', body={'tenant_id': 10, 'action': 'force_disable', 'reason': 'manual review', 'expected_revision': revision}, auth=admin)
            assert forced.status_code == 200, forced.text
            assert forced.json()['admin_locked'] and not forced.json()['enabled']
            assert (await toggle(env, True, forced.json()['revision'])).status_code == 423
            unlocked = await env.request('POST', PATH + '/admin-action', body={'tenant_id': 10, 'action': 'unlock', 'reason': 'reviewed', 'expected_revision': forced.json()['revision']}, auth=admin)
            assert unlocked.status_code == 200, unlocked.text
            assert not unlocked.json()['enabled'] and not unlocked.json()['admin_locked']
            legacy = await env.request('PUT', '/visibility-patrol/settings', body={'tenant_id': 10, 'enabled': True}, auth=admin)
            assert legacy.status_code == 409
            history = await env.request('GET', PATH + '/history')
            assert history.status_code == 200, history.text
            assert [r['action'] for r in history.json()['items']] == ['unlock', 'force_disable', 'enable', 'migrate']
    asyncio.run(run())


@pytest.mark.parametrize('case', ['extra', 'wrong-tenant', 'no-assignment', 'customer', 'no-prompts', 'no-platforms'])
def test_admission_is_fail_closed(tmp_path, monkeypatch, case):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as env:
            body = {'tenant_id': 10, 'enabled': True, 'expected_revision': 0}
            kwargs = {}
            if case == 'extra':
                body['owner_user_id'] = 2
            if case == 'wrong-tenant':
                body['tenant_id'] = 20
            if case == 'no-assignment':
                await mutate(env, GeoProject, 10, project_settings={})
            if case == 'no-prompts':
                await mutate(env, GeoPrompt, 10, status='archived')
            if case == 'no-platforms':
                from app.geo.content import engine_providers
                monkeypatch.setattr(engine_providers, 'resolve_platform_engine_credentials', lambda *a, **kw: None)
            if case == 'customer':
                kwargs['auth'] = fixture_token(uid=3, native=True)
            result = await env.request('PUT', PATH, body=body, **kwargs)
            assert result.status_code in {403, 409, 422}, result.text
            async with env.factory() as session:
                assert not (await session.get(Settings, 10)).self_service_enabled
                assert await session.scalar(select(func.count()).select_from(Event)) == 0
    asyncio.run(run())


def test_close_succeeds_without_questions_and_quota_has_independent_revision(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as env:
            opened = await toggle(env, True)
            assert opened.status_code == 200, opened.text
            admin = fixture_token(uid=2, native=True)
            changed = await env.request('PUT', '/visibility-patrol/manual-limit', body={'tenant_id': 10, 'manual_daily_limit': 0, 'expected_revision': 0, 'reason': 'pause manual'}, auth=admin)
            assert changed.status_code == 200, changed.text
            assert changed.json()['manual_quota'] == {'used': 0, 'limit': 0}
            assert (await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 10})).status_code == 429
            await mutate(env, GeoPrompt, 10, status='archived')
            closed = await toggle(env, False, opened.json()['revision'])
            assert closed.status_code == 200, closed.text
            assert not closed.json()['enabled'] and closed.json()['schedule_mode'] == service.MODE
            history = await env.request('GET', '/visibility-patrol/manual-limit/history', auth=admin)
            assert history.status_code == 200 and history.json()['items'][0]['before']['manual_daily_limit'] == 10
    asyncio.run(run())


def test_daily_claim_persistent_auth_and_no_manual_quota(tmp_path, monkeypatch, backend):
    async def run():
        async with sandbox(tmp_path, monkeypatch, backend) as env:
            assert (await toggle(env, True)).status_code == 200
            now = datetime.now(service.BJ).replace(hour=11, minute=5, second=0)
            async with env.factory() as session:
                row = await queue.enqueue_day(session, 10, now=now)
                assert row is not None
                ident = row.id
                assert 'auth_exp' not in row.summary['advisor_visibility_auth']
                assert row.summary['advisor_visibility_prompt_ids'] == [10]
                await session.commit()
                assert await service.manual_quota(session, 10) == {'used': 0, 'limit': 10}
            async with env.factory() as session:
                assert await queue.enqueue_day(session, 10, now=now) is None
            async with env.factory() as session:
                row = await session.get(Run, ident)
                from app.security.advisor_visibility import check_visibility_execution, AdvisorVisibilityUnavailable
                await check_visibility_execution(session, row, [10])
                grant = await session.get(Grant, 101)
                grant.revoked_at = datetime.utcnow()
                grant.revoked_by, grant.revoke_reason = 2, 'admin_uncheck'
                await session.commit()
            async with env.factory() as session:
                row = await session.get(Run, ident)
                with pytest.raises(AdvisorVisibilityUnavailable):
                    await check_visibility_execution(session, row, [10])
    asyncio.run(run())


def test_auto_day_cannot_be_deleted_and_queue_wait_is_not_stale(tmp_path, monkeypatch):
    async def run():
        from app.geo.content.patrol import patrol_stale_view
        async with sandbox(tmp_path, monkeypatch) as env:
            async with env.factory() as session:
                row = Run(tenant_id=10, trigger='self_service', auto_day=datetime.now(service.BJ).date(), status='pending',
                    summary={'self_service': {'mode': service.MODE}, 'advisor_visibility_prompt_ids': [10]},
                    created_at=datetime.utcnow() - timedelta(hours=3))
                session.add(row)
                await session.commit()
                assert patrol_stale_view(row) == (False, None)
                row.status = 'failed'
                await session.commit()
            response = await env.request('DELETE', '/visibility-patrol/runs/' + str(row.id), auth=fixture_token(uid=2, native=True))
            assert response.status_code == 409, response.text
    asyncio.run(run())


def test_bj_estimate_and_classification_projection():
    now = datetime(2026, 10, 22, 7, 0, tzinfo=service.BJ)
    assert service.next_run(10, now=now) == '2026-10-22T10:05:00+08:00'
    assert service.next_run(10, now=now, claimed=True) == '2026-10-23T10:05:00+08:00'
    row = SimpleNamespace(id=1, status='completed', items=[{'engine': 'deepseek', 'ok': True},
        {'engine': 'wenxin', 'ok': False}, {'engine': 'kimi', 'skipped_reason': 'not_configured'}],
        created_at=now, started_at=None, finished_at=None)
    payload = service.last_run_payload(row)
    assert payload['status'] == 'partial_success'
    assert (payload['success'], payload['failed'], payload['skipped']) == (1, 1, 1)


@pytest.mark.parametrize('revoke', [False, True])
def test_auto_executor_uses_frozen_questions_real_six_and_rechecks_response(tmp_path, monkeypatch, revoke):
    async def run():
        import app.ai.deepseek as provider
        from app.geo.content import patrol, daily_metrics, visibility_budget
        from app.models import GeoAnswerSnapshot
        async with sandbox(tmp_path, monkeypatch) as env:
            opened = await toggle(env, True)
            assert opened.status_code == 200, opened.text
            async with env.factory() as session:
                row = await queue.enqueue_day(session, 10, now=datetime.now(service.BJ).replace(hour=11, minute=5, second=0))
                assert row is not None
                ident = row.id
                await session.commit()
            monkeypatch.setattr(patrol, 'ensure_geo_entitlement', AsyncMock())
            monkeypatch.setattr(daily_metrics, 'safe_rebuild_day', AsyncMock())
            attempts = AsyncMock(return_value=1)
            monkeypatch.setattr(visibility_budget, 'claim_visibility_attempt', attempts)
            calls = []
            worker = None
            async def fake_provider(system, user, **kwargs):
                calls.append(kwargs)
                assert kwargs['model'] == 'deepseek-test' and kwargs['max_tokens'] == 4096
                if revoke:
                    grant = await worker.get(Grant, 101)
                    grant.revoked_at, grant.revoked_by, grant.revoke_reason = datetime.utcnow(), 2, 'admin_uncheck'
                    await worker.flush()
                return {'raw_text': 'synthetic safe answer'} if len(calls) == 1 else {'suggested_mentions_brand': False}
            monkeypatch.setattr(provider, 'chat_json', fake_provider)
            async with env.factory() as session:
                worker = session
                row = await patrol.execute_patrol_run(session, ident, tenant_id=10, execution_protocol=patrol.PATROL_EXECUTION_PROTOCOL)
                if revoke:
                    assert row.status == 'failed' and row.error == 'authorization_changed'
                    assert len(calls) == 1
                    assert not list(await session.scalars(select(GeoAnswerSnapshot)))
                else:
                    assert row.status == 'completed', row.error
                    assert row.summary['self_service']['mode'] == service.MODE
                    assert len(calls) == 2 and attempts.await_count == 2
                    assert len(row.items) == 6 and sum(bool(i.get('skipped_reason')) for i in row.items) == 5
                    assert {i['engine'] for i in row.items} == set(service.ENGINES)
                    assert row.summary['advisor_visibility_prompt_ids'] == [10]
                    assert await service.manual_quota(session, 10) == {'used': 0, 'limit': 10}
    asyncio.run(run())


def test_another_assigned_advisor_can_close_without_replacing_owner(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as env:
            opened = await toggle(env, True)
            async with env.factory() as session:
                session.add(User(id=4, username='second-advisor', role_id=1, tenant_id=10, is_active=True, password_hash='unused'))
                session.add(Grant(id=104, user_id=4, tenant_id=10, grant_source='backfill'))
                session.add(GeoProject(id=11, tenant_id=10, tenant_module_id=10, name='empty assigned project',
                    primary_domain='second.example.test', canonical_domain='second.example.test', status='active',
                    project_settings={'geo_service_plan': {'advisor_user_id': 4}}))
                await session.commit()
            closed = await toggle(env, False, opened.json()['revision'], auth=fixture_token(uid=4, gid=104))
            assert closed.status_code == 200, closed.text
            assert closed.json()['owner']['user_id'] == 1
            assert closed.json()['last_changed_by']['user_id'] == 4
    asyncio.run(run())


def test_shared_manual_count_excludes_automatic_and_other_operation_reservations(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as env:
            async with env.factory() as session:
                (await session.get(Settings, 10)).manual_daily_limit = 4
                session.add_all([
                    Run(tenant_id=10, created_by=1, trigger='manual', status='completed', summary={'advisor_quota_state': 'consumed'}),
                    Run(tenant_id=10, created_by=2, trigger='manual', status='failed', summary={'advisor_quota_state': 'refunded'}),
                    Run(tenant_id=10, trigger='contract_retest', status='completed'),
                    Run(tenant_id=10, trigger='quota_history', status='completed', summary={'reservation_only': True, 'manual_visibility': True}),
                    Run(tenant_id=10, trigger='manual', status='completed', summary={'reservation_only': True}),
                    Run(tenant_id=10, trigger='self_service', status='failed', auto_day=date(2026, 10, 22)),
                ])
                await session.commit()
                assert await service.manual_quota(session, 10) == {'used': 3, 'limit': 4}
    asyncio.run(run())


def test_request_budget_covers_answer_retry_and_judge_and_fails_closed(monkeypatch):
    async def run():
        import httpx
        from app.ai.deepseek import DeepSeekError
        from app.geo.content.probe import run_probe_draft
        from app.geo.content import visibility_budget as budget
        claims = AsyncMock(return_value=1)
        monkeypatch.setattr(budget, 'claim_visibility_attempt', claims)
        calls = 0
        async def supplier(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise DeepSeekError('timeout') from httpx.ReadTimeout('synthetic')
            return {'raw_text': 'synthetic raw answer'} if calls == 2 else {'suggested_mentions_brand': False}
        result = await run_probe_draft(question='q', brand='b', brand_names=['b'], engine='deepseek',
            llm={'api_key': 'dummy', 'model': 'deepseek-test', 'base_url': 'https://supplier.invalid'},
            chat_json=budget.budgeted_chat(supplier), sample_mode='openai_compat')
        assert result['raw_text'] == 'synthetic raw answer'
        assert calls == claims.await_count == 3
        claims.side_effect = budget.VisibilityBudgetUnavailable('safe unavailable')
        with pytest.raises(budget.VisibilityBudgetUnavailable):
            await budget.budgeted_chat(supplier)('system', 'user')
        assert calls == 3
    asyncio.run(run())


def test_hy4_identity_fix_is_narrow():
    from app.geo.content.engine_identity import trusted_engine_source
    assert trusted_engine_source('hunyuan', 'hunyuan', 'hy4-preview')
    assert not trusted_engine_source('hunyuan', 'dashscope', 'hy4-preview')
    assert not trusted_engine_source('hunyuan', 'hunyuan', 'hy4evil')
    assert not trusted_engine_source('wenxin', 'hunyuan', 'hy4-preview')
