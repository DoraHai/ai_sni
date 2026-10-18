import asyncio
import copy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from app.config import get_settings
from app.models import GeoAnswerSnapshot, GeoProject, GeoPrompt, Role, User
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from test_advisor_scoped_writes import backend
from test_geo_advisor_visibility import visibility_sandbox


def worker_stubs(monkeypatch):
    from app.geo.content import ai_settings, daily_metrics, patrol
    monkeypatch.setattr(ai_settings, 'resolve_llm_credentials', AsyncMock(return_value={}))
    monkeypatch.setattr(ai_settings, 'ensure_ai_setting', AsyncMock(side_effect=AssertionError('advisor worker must not create model settings')))
    monkeypatch.setattr(ai_settings, 'get_ai_setting_row', AsyncMock(return_value=SimpleNamespace(monitoring_stance='hybrid')))
    monkeypatch.setattr(patrol, 'resolve_engine_llm', lambda **kw: (
        {'api_key': 'fixture-only', 'model': 'fixture-model', 'provider': 'fixture'}, 'openai_compat', None))
    monkeypatch.setattr(patrol, 'ensure_geo_entitlement', AsyncMock())
    monkeypatch.setattr(daily_metrics, 'safe_rebuild_day', AsyncMock())
    return patrol


@pytest.mark.parametrize('change', ['grant', 'regrant', 'assignment', 'prompt', 'account', 'role', 'expired', 'flag', 'legacy', 'engine-disabled', 'engine-deleted'])
def test_queued_detection_rechecks_before_any_provider(tmp_path, monkeypatch, backend, change):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 10})
            assert response.status_code == 200, response.text
            run_id = response.json()['run']['id']
            from app.models import GeoVisibilityPatrolRun
            async with env.factory() as session:
                if change in {'grant', 'regrant'}:
                    await session.execute(update(Grant).where(Grant.id == 101).values(
                        revoked_at=datetime.utcnow(), revoked_by=2, revoke_reason='admin_uncheck'))
                    if change == 'regrant':
                        await session.flush()
                        session.add(Grant(id=901, user_id=1, tenant_id=10, grant_source='backfill'))
                elif change == 'assignment':
                    project = await session.get(GeoProject, 10)
                    settings = copy.deepcopy(project.project_settings)
                    settings['geo_service_plan']['advisor_user_id'] = 2
                    project.project_settings = settings
                elif change == 'prompt':
                    await session.execute(update(GeoPrompt).where(GeoPrompt.id == 10).values(unit_id=None))
                elif change == 'account':
                    await session.execute(update(User).where(User.id == 1).values(is_active=False))
                elif change == 'role':
                    await session.execute(update(Role).where(Role.id == 1).values(
                        permissions={'geo.assets': 'edit', 'geo.content': 'view'}))
                elif change in {'engine-disabled', 'engine-deleted'}:
                    from app.models import GeoTrackingEngine
                    from sqlalchemy import delete
                    statement = (delete(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == 10)
                        if change == 'engine-deleted' else update(GeoTrackingEngine).where(
                            GeoTrackingEngine.tenant_id == 10).values(enabled=False))
                    await session.execute(statement)
                elif change == 'expired':
                    row = await session.get(GeoVisibilityPatrolRun, run_id)
                    summary = copy.deepcopy(row.summary)
                    summary['advisor_visibility_auth']['auth_exp'] = 0
                    row.summary = summary
                elif change == 'legacy':
                    row = await session.get(GeoVisibilityPatrolRun, run_id)
                    row.summary = {'advisor_visibility_prompt_ids': [10]}
                else:
                    monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', False)
                await session.commit()
            patrol = worker_stubs(monkeypatch)
            probe = AsyncMock(side_effect=AssertionError('revoked job must never call a provider'))
            monkeypatch.setattr(patrol, 'run_probe_draft', probe)
            async with env.factory() as session:
                row = await patrol.execute_patrol_run(session, run_id, tenant_id=10)
                assert row.status == 'failed' and '重新发起' in row.error
                assert not list(await session.scalars(select(GeoAnswerSnapshot)))
            probe.assert_not_awaited()
    asyncio.run(run())


def test_revocation_during_provider_discards_response_and_stops_followup(tmp_path, monkeypatch, backend):
    async def run():
        import app.ai.deepseek as deepseek
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 10})
            run_id = response.json()['run']['id']
            patrol = worker_stubs(monkeypatch)
            worker_session = None
            async def provider(*args, **kwargs):
                # A deterministic boundary change, using the worker's fixture
                # transaction so SQLite needs no concurrent database service.
                await worker_session.execute(update(Grant).where(Grant.id == 101).values(
                    revoked_at=datetime.utcnow(), revoked_by=2, revoke_reason='admin_uncheck'))
                return {'answer': 'private fixture provider response'}
            real_call = AsyncMock(side_effect=provider)
            monkeypatch.setattr(deepseek, 'chat_json', real_call)
            async def probe(**kwargs):
                await kwargs['chat_json']('fixture system', 'fixture question')
                pytest.fail('revoked answer must not reach follow-up analysis')
            monkeypatch.setattr(patrol, 'run_probe_draft', probe)
            async with env.factory() as session:
                worker_session = session
                row = await patrol.execute_patrol_run(session, run_id, tenant_id=10)
                assert row.status == 'failed' and '重新发起' in row.error
                assert not list(await session.scalars(select(GeoAnswerSnapshot)))
                assert 'private fixture provider response' not in str(row.items)
            real_call.assert_awaited_once()
    asyncio.run(run())


def test_revocation_discards_uncommitted_prior_cells(tmp_path, monkeypatch, backend):
    async def run():
        from app.models import GeoTrackingEngine
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            async with env.factory() as session:
                session.add(GeoTrackingEngine(tenant_id=10, engine_key='qwen', display_name='fixture second engine', enabled=True))
                await session.commit()
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 10})
            run_id = response.json()['run']['id']
            patrol = worker_stubs(monkeypatch)
            worker_session, calls = None, []
            async def probe(**kwargs):
                calls.append(1)
                if len(calls) == 2:
                    await worker_session.execute(update(Grant).where(Grant.id == 101).values(
                        revoked_at=datetime.utcnow(), revoked_by=2, revoke_reason='admin_uncheck'))
                return {'raw_text': 'uncommitted fixture response', 'simulated': False,
                    'sample_mode': 'openai_compat', 'suggested_mentions_brand': False,
                    'analysis_status': 'completed'}
            monkeypatch.setattr(patrol, 'run_probe_draft', probe)
            async with env.factory() as session:
                worker_session = session
                row = await patrol.execute_patrol_run(session, run_id, tenant_id=10)
                assert row.status == 'failed' and len(calls) == 2
                assert not list(await session.scalars(select(GeoAnswerSnapshot)))
                assert row.summary.get('snapshots_created', 0) == 0
                assert not row.items
    asyncio.run(run())


def test_visibility_job_keeps_selected_token_expiry(tmp_path, monkeypatch, backend):
    from datetime import timezone
    from test_advisor_scoped_writes import fixture_token
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            expiry = int(datetime.now(timezone.utc).timestamp()) + 120
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 10},
                auth=fixture_token(exp=expiry))
            assert response.status_code == 200, response.text
            assert response.json()['run']['summary']['advisor_visibility_auth']['auth_exp'] == expiry
    asyncio.run(run())


@pytest.mark.parametrize('tid', [10, 20])
def test_worker_current_authority_persists_and_audits(tmp_path, monkeypatch, backend, caplog, tid):
    import json
    import logging
    from app.models import GeoTrackingEngine
    from test_advisor_scoped_writes import fixture_token
    caplog.set_level(logging.INFO, logger='geo.advisor.operations')
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            if tid == 20:
                async with env.factory() as session:
                    session.add(GeoTrackingEngine(tenant_id=20, engine_key='deepseek', display_name='fixture', enabled=True))
                    await session.commit()
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': tid},
                params={'tenant_id': tid}, auth=fixture_token(tid=tid, gid=101 if tid == 10 else 102))
            assert response.status_code == 200, response.text
            run_id = response.json()['run']['id']
            patrol = worker_stubs(monkeypatch)
            probe = AsyncMock(return_value={'raw_text': 'synthetic answer', 'sample_mode': 'openai_compat',
                'simulated': False, 'suggested_mentions_brand': False})
            monkeypatch.setattr(patrol, 'run_probe_draft', probe)
            async with env.factory() as session:
                row = await patrol.execute_patrol_run(session, run_id, tenant_id=tid)
                assert row.status == 'completed', row.error
                snapshots = list(await session.scalars(select(GeoAnswerSnapshot)))
                assert snapshots and all(s.tenant_id == tid for s in snapshots)
            return run_id
    ident = asyncio.run(run())
    events = [json.loads(r.message) for r in caplog.records if r.name == 'geo.advisor.operations']
    assert any(e['result'] == 'job_succeeded' and e['tenant_id'] == tid and e['advisor_user_id'] == 1
        and e['object_ids'] == {'run_id': ident} for e in events)


def test_project_reassignment_can_commit_during_provider_and_discards_reply(tmp_path, monkeypatch, backend):
    if backend != 'postgres':
        pytest.skip('requires real concurrent PostgreSQL transactions')
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 10})
            run_id = response.json()['run']['id']
            patrol = worker_stubs(monkeypatch)
            async def provider(**kwargs):
                async def reassign():
                    async with env.factory() as admin:
                        project = await admin.get(GeoProject, 10, with_for_update=True)
                        settings = copy.deepcopy(project.project_settings)
                        settings['geo_service_plan']['advisor_user_id'] = 2
                        project.project_settings = settings
                        await admin.commit()
                # A provider call must not retain the project lock and block
                # the administrator's reassignment until the sample is stored.
                await asyncio.wait_for(reassign(), timeout=5)
                return {'raw_text': 'stale provider response', 'sample_mode': 'openai_compat', 'simulated': False}
            probe = AsyncMock(side_effect=provider)
            monkeypatch.setattr(patrol, 'run_probe_draft', probe)
            async with env.factory() as session:
                row = await patrol.execute_patrol_run(session, run_id, tenant_id=10)
                assert row.status == 'failed' and '重新发起' in row.error
                assert not list(await session.scalars(select(GeoAnswerSnapshot)))
                assert 'stale provider response' not in str(row.items)
            probe.assert_awaited_once()
    asyncio.run(run())


def test_advisor_detection_reads_config_without_creating_defaults(tmp_path, monkeypatch, backend):
    from app.geo.content import ai_settings
    from unittest.mock import Mock
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 10})
            run_id = response.json()['run']['id']
            patrol = worker_stubs(monkeypatch)
            read_config = AsyncMock(return_value=None)
            create_config = AsyncMock(side_effect=AssertionError('configuration creation forbidden'))
            defaults = Mock(side_effect=AssertionError('engine creation forbidden'))
            monkeypatch.setattr(ai_settings, 'get_ai_setting_row', read_config)
            monkeypatch.setattr(ai_settings, 'ensure_ai_setting', create_config)
            monkeypatch.setattr('app.geo.content.engines.default_engine_rows', defaults)
            monkeypatch.setattr(patrol, 'run_probe_draft', AsyncMock(return_value={
                'raw_text': 'synthetic answer', 'sample_mode': 'openai_compat', 'simulated': False}))
            async with env.factory() as session:
                row = await patrol.execute_patrol_run(session, run_id, tenant_id=10)
                assert row.status == 'completed', row.error
            read_config.assert_awaited()
            create_config.assert_not_awaited()
            defaults.assert_not_called()
    asyncio.run(run())


def test_reassignment_during_second_provider_commits_and_discards_batch(tmp_path, monkeypatch, backend):
    async def run():
        from app.models import GeoTrackingEngine, Tenant
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            async with env.factory() as session:
                session.add(GeoTrackingEngine(tenant_id=10, engine_key='qwen',
                    display_name='second fixture engine', enabled=True))
                await session.commit()
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 10})
            assert response.status_code == 200, response.text
            run_id = response.json()['run']['id']
            patrol = worker_stubs(monkeypatch)
            calls, reassigned = [], []

            async def reassign():
                async with env.factory() as admin:
                    # Same tenant/project lock order used by project writers.
                    await admin.scalar(select(Tenant.id).where(Tenant.id == 10).with_for_update())
                    project = await admin.get(GeoProject, 10, with_for_update=True)
                    settings = copy.deepcopy(project.project_settings)
                    settings['geo_service_plan']['advisor_user_id'] = 2
                    project.project_settings = settings
                    await admin.commit()
                    reassigned.append(True)

            async def probe(**kwargs):
                calls.append(1)
                if len(calls) == 2:
                    await asyncio.wait_for(reassign(), timeout=3)
                return {'raw_text': 'uncommitted fixture response', 'simulated': False,
                    'sample_mode': 'openai_compat', 'suggested_mentions_brand': False,
                    'analysis_status': 'completed'}

            monkeypatch.setattr(patrol, 'run_probe_draft', probe)
            async with env.factory() as session:
                row = await patrol.execute_patrol_run(session, run_id, tenant_id=10)
                assert reassigned == [True], 'provider must not hold locks blocking project reassignment'
                assert row.status == 'failed' and '重新发起' in row.error
                assert not list(await session.scalars(select(GeoAnswerSnapshot)))
                assert row.summary.get('snapshots_created', 0) == 0
                assert not row.items
    asyncio.run(run())



def test_unchanged_detection_persists_periodic_and_final_advisor_batches(tmp_path, monkeypatch, backend):
    async def run():
        async with visibility_sandbox(tmp_path, monkeypatch, backend) as env:
            async with env.factory() as session:
                session.add_all([GeoPrompt(id=100+i, tenant_id=10, unit_id=10,
                    question=f'fixture question {i}', status='active') for i in range(5)])
                await session.commit()
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 10})
            assert response.status_code == 200, response.text
            run_id = response.json()['run']['id']
            patrol = worker_stubs(monkeypatch)
            probe = AsyncMock(return_value={'raw_text': 'authorized fixture response', 'simulated': False,
                'sample_mode': 'openai_compat', 'suggested_mentions_brand': False,
                'analysis_status': 'completed'})
            monkeypatch.setattr(patrol, 'run_probe_draft', probe)
            async with env.factory() as session:
                row = await patrol.execute_patrol_run(session, run_id, tenant_id=10)
                assert row.status == 'completed', row.error
                snapshots = list(await session.scalars(select(GeoAnswerSnapshot)))
                assert len(snapshots) == 6 and probe.await_count == 6
                assert row.summary['snapshots_created'] == 6
                assert {cell['snapshot_id'] for cell in row.items} == {s.id for s in snapshots}
    asyncio.run(run())
