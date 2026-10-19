"""CI-owned isolated schemas only; all suppliers are mocked."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app import models as m
from app.security import advisor_quota as quota
from app.security.advisor_operation_call import checked_call
from test_advisor_scoped_writes import backend, mutate, write_sandbox


async def configure_probes(env, monkeypatch):
    from app.geo.content import routes
    async with env.factory() as session:
        session.add_all([m.GeoTrackingEngine(tenant_id=10, engine_key=key,
            display_name=key, enabled=True) for key in ('deepseek', 'kimi')])
        await session.commit()
    monkeypatch.setattr(routes, 'resolve_llm_credentials', AsyncMock(return_value={'api_key': 'fixture-only'}))
    monkeypatch.setattr(routes, 'resolve_engine_llm', lambda **_kw: ({'api_key': 'fixture-only'}, 'openai_compat', None))
    monkeypatch.setattr(routes, '_brand_context_for_prompt', AsyncMock(return_value=('fixture', ['fixture'])))
    return routes


@pytest.mark.parametrize('outcome,expected', [('failure', 0), ('success', 1), ('partial', 1), ('all-failed', 0)])
def test_probe_daily_quota_failure_success_partial(tmp_path, monkeypatch, backend, outcome, expected):
    from app.geo.content.patrol import count_patrol_runs_today
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            routes = await configure_probes(env, monkeypatch)
            draft = {'raw_text': 'synthetic answer', 'engine': 'deepseek'}
            results = [draft, ValueError('fixture failure')] if outcome == 'partial' else (
                [ValueError('fixture failure')] * 2 if outcome in {'failure', 'all-failed'} else [draft])
            monkeypatch.setattr(routes, 'run_probe_draft', AsyncMock(side_effect=results))
            batch = outcome in {'partial', 'all-failed'}
            response = await env.request('POST', '/answer-snapshots/probe' + ('-batch' if batch else ''),
                body={'tenant_id': 10, 'prompt_id': 10, **({'engines': ['deepseek', 'kimi']} if batch else {'engine': 'deepseek'})})
            assert response.status_code == (502 if outcome == 'failure' else 200), response.text
            async with env.factory() as session:
                assert await count_patrol_runs_today(session, 10, created_by=1) == expected
                rows = list(await session.scalars(select(m.GeoVisibilityPatrolRun)))
                assert len(rows) == 1
                assert rows[0].summary[quota.STATE] == ('consumed' if expected else 'refunded')
    asyncio.run(run())


@pytest.mark.parametrize('change', ('grant', 'role', 'assignment'))
def test_real_revocation_during_probe_rejects_result_and_refunds(tmp_path, monkeypatch, backend, change):
    from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
    from app.geo.content.patrol import count_patrol_runs_today
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            routes = await configure_probes(env, monkeypatch)
            @checked_call
            async def supplier(**_kw):
                if change == 'grant':
                    await mutate(env, Grant, 101, revoked_at=datetime.utcnow(), revoked_by=2,
                                 revoke_reason='admin_uncheck')
                elif change == 'role':
                    await mutate(env, m.Role, 1, permissions={'geo.assets': 'view', 'geo.content': 'view'})
                else:
                    await mutate(env, m.GeoProject, 10, project_settings={
                        'geo_business_scope': {'business_ids': [10]}, 'geo_service_plan': {'advisor_user_id': 3}})
                return {'raw_text': 'must be discarded'}
            monkeypatch.setattr(routes, 'run_probe_draft', supplier)
            response = await env.request('POST', '/answer-snapshots/probe',
                body={'tenant_id': 10, 'prompt_id': 10, 'engine': 'deepseek'})
            assert response.status_code in {401, 403}, response.text
            assert 'must be discarded' not in response.text
            async with env.factory() as session:
                assert await count_patrol_runs_today(session, 10, created_by=1) == 0
                assert await session.scalar(select(m.GeoAnswerSnapshot.id)) is None
    asyncio.run(run())


def test_native_concurrent_refund_retains_other_attempts(tmp_path, monkeypatch, backend):
    from app.geo.content.patrol import count_patrol_runs_today
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            async with env.factory() as session:
                row = m.GeoVisibilityPatrolRun(tenant_id=10, created_by=1, status='completed',
                    summary={'reservation_only': True, quota.STATE: 'reserved'})
                session.add_all([row, m.GeoVisibilityPatrolRun(tenant_id=10, created_by=1, status='completed'),
                    m.GeoVisibilityPatrolRun(tenant_id=10, created_by=3, status='completed')])
                await session.commit()
                reservation = (row.id, 10, 1)
            # Separate sessions/connections race on the same PostgreSQL UPDATE.
            async def refund():
                await quota.refund_unused_reservation(SimpleNamespace(
                    info={quota.KEY: reservation}, bind=env.engine, rollback=AsyncMock()))
            await asyncio.wait_for(asyncio.gather(*(refund() for _ in range(4))), timeout=20)
            await refund()
            async with env.factory() as session:
                assert await count_patrol_runs_today(session, 10, created_by=1) == 1
                assert await count_patrol_runs_today(session, 10, created_by=3) == 1
                assert (await session.get(m.GeoVisibilityPatrolRun, reservation[0])).summary[quota.STATE] == 'refunded'
    asyncio.run(run())


@pytest.mark.parametrize('status,items,expected', [('failed', [], 0), ('cancelled', [], 0),
    ('succeeded', [], 1), ('failed', [{'results': [], 'error': None}], 1)])
def test_async_terminal_settlement_is_durable_and_idempotent(tmp_path, monkeypatch, backend, status, items, expected):
    from app.geo.content.patrol import count_patrol_runs_today
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            async with env.factory() as session:
                row = m.GeoVisibilityPatrolRun(tenant_id=10, created_by=1, status='completed',
                    summary={'reservation_only': True, quota.STATE: 'queued'})
                session.add(row)
                await session.flush()
                job = m.GeoAsyncJob(tenant_id=10, created_by=1, kind='search_visibility', status=status,
                    request_meta={quota.KEY: [row.id, 10, 1]}, result_meta={'items': items})
                session.add(job)
                await session.commit()
                await quota.settle_search_reservation(session, job)
                await quota.settle_search_reservation(session, job)
                await session.commit()
            async with env.factory() as session:
                assert await count_patrol_runs_today(session, 10, created_by=1) == expected
    asyncio.run(run())
