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
    monkeypatch.setattr(ai_settings, 'ensure_ai_setting', AsyncMock(return_value=SimpleNamespace(monitoring_stance='hybrid')))
    monkeypatch.setattr(patrol, 'resolve_engine_llm', lambda **kw: (
        {'api_key': 'fixture-only', 'model': 'fixture-model', 'provider': 'fixture'}, 'openai_compat', None))
    monkeypatch.setattr(patrol, 'ensure_geo_entitlement', AsyncMock())
    monkeypatch.setattr(daily_metrics, 'safe_rebuild_day', AsyncMock())
    return patrol


@pytest.mark.parametrize('change', ['grant', 'regrant', 'assignment', 'prompt', 'account', 'role', 'expired', 'flag', 'legacy'])
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
