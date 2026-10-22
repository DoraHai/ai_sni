"""Native PostgreSQL races; only explicitly allowed loopback CI schemas."""
import asyncio
from datetime import datetime, timedelta, timezone
import os
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.geo.content import autopatrol as service, autopatrol_queue as queue, patrol, visibility_budget as budget
from app.models import GeoVisibilityPatrolRun as Run, GeoVisibilityPatrolSettings as Settings
from app.models.geo_visibility_patrol import GeoVisibilityPatrolDailyBudget as Budget
from test_geo_autopatrol import sandbox, toggle
from test_advisor_scoped_writes import fixture_token

pytestmark = pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires dedicated loopback PostgreSQL')


def test_manual_outer_limit_does_not_block_daily_automatic_claim(tmp_path, monkeypatch):
    async def run():
        from app.config import get_settings
        async with sandbox(tmp_path, monkeypatch, 'postgres') as env:
            monkeypatch.setattr(get_settings(), 'geo_patrol_max_runs_per_day', 1)
            assert (await toggle(env, True)).status_code == 200
            async with env.factory() as session:
                (await session.get(Settings, 10)).manual_daily_limit = 100
                session.add(Run(tenant_id=10, trigger='manual', status='completed',
                    summary={'advisor_quota_state': 'consumed'}))
                await session.commit()
                assert (await service.manual_quota(session, 10)) == {'used': 1, 'limit': 100}
            # The same persisted manual count fills the manual path's outer guard.
            response = await env.request('POST', '/visibility-patrol/runs', body={'tenant_id': 10})
            assert response.status_code == 429, response.text
            assert response.json()['detail']['code'] == 'TENANT_MANUAL_SAFETY_LIMIT'
            now = datetime.now(service.BJ).replace(hour=11, minute=5, second=0)
            async with env.factory() as session:
                row = await queue.enqueue_day(session, 10, now=now)
                assert row is not None and row.auto_day == now.date() and row.trigger == 'self_service'
                await session.commit()
            async with env.factory() as session:
                assert (await session.get(Settings, 10)).blocked_reason is None
                assert (await service.manual_quota(session, 10)) == {'used': 1, 'limit': 100}
                assert await queue.enqueue_day(session, 10, now=now) is None
                assert await session.scalar(select(func.count()).select_from(Run).where(
                    Run.tenant_id == 10, Run.auto_day == now.date())) == 1
    asyncio.run(run())


def test_two_producers_claim_once_and_disable_reenable_does_not_reset(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch, 'postgres') as env:
            opened = await toggle(env, True)
            assert opened.status_code == 200, opened.text
            now = datetime.now(service.BJ).replace(hour=11, minute=5, second=0)
            async def produce():
                async with env.factory() as session:
                    row = await queue.enqueue_day(session, 10, now=now)
                    await session.commit()
                    return row.id if row else None
            results = await asyncio.gather(produce(), produce())
            assert sum(result is not None for result in results) == 1
            async with env.factory() as session:
                row = await session.scalar(select(Run))
                row.status = 'failed'
                await session.commit()
            closed = await toggle(env, False, opened.json()['revision'])
            reopened = await toggle(env, True, closed.json()['revision'])
            assert reopened.status_code == 200, reopened.text
            assert await produce() is None
            async with env.factory() as session:
                assert await session.scalar(select(func.count()).select_from(Run)) == 1
    asyncio.run(run())


def test_budget_atomic_limit_and_midnight_follow_request_day(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch, 'postgres') as env:
            before = datetime(2026, 10, 22, 15, 59, 59, tzinfo=timezone.utc)
            after = before + timedelta(seconds=2)
            async with env.factory() as session:
                session.add(Budget(budget_day=before.astimezone(service.BJ).date(), attempts=35995))
                await session.commit()
            async def claim():
                try:
                    return await budget.claim_visibility_attempt(now=before, sessions=env.factory)
                except budget.VisibilityBudgetExhausted:
                    return None
            results = await asyncio.gather(*(claim() for _ in range(12)))
            assert sum(n is not None for n in results) == 5
            assert max(n for n in results if n) == budget.MAX_VISIBILITY_ATTEMPTS_PER_BJ_DAY == 36000
            assert await budget.claim_visibility_attempt(now=after, sessions=env.factory) == 1
            async with env.factory() as session:
                assert await session.scalar(select(func.sum(Budget.attempts))) == 36001
    asyncio.run(run())


def test_global_slot_locks_bound_all_consumers_to_two(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch, 'postgres') as env:
            async with env.factory() as session:
                for tid in (10, 20, 30):
                    session.add(Run(tenant_id=tid, status='pending', trigger='self_service', auto_day=datetime.now(service.BJ).date(),
                        summary={'self_service': {'mode': service.MODE}}))
                await session.commit()
            active, maximum, calls = 0, 0, []
            async def execute(session, ident, **kwargs):
                nonlocal active, maximum
                row = await session.get(Run, ident)
                assert row.status == 'pending'
                row.status = 'running'
                await session.commit()
                active += 1
                maximum = max(maximum, active)
                calls.append(ident)
                await asyncio.sleep(0.1)
                active -= 1
                row.status = 'completed'
                await session.commit()
            monkeypatch.setattr(patrol, 'execute_patrol_run', execute)
            await asyncio.gather(*(queue.consume_slot(i % 2) for i in range(6)))
            assert maximum == 2 and len(calls) == len(set(calls)) == 2
            await queue.consume_queue()
            assert len(calls) == len(set(calls)) == 3
    asyncio.run(run())


def test_restart_never_replays_started_run_and_preserves_today_pending(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch, 'postgres') as env:
            today = datetime.now(service.BJ).date()
            async with env.factory() as session:
                rows = [Run(tenant_id=10, trigger='self_service', auto_day=day, status=status,
                    summary={'self_service': {'mode': service.MODE}, 'execution_protocol': patrol.PATROL_EXECUTION_PROTOCOL},
                    created_at=datetime.utcnow() - timedelta(hours=3)) for day, status in
                    [(today - timedelta(days=2), 'running'), (today - timedelta(days=1), 'pending'), (today, 'pending')]]
                session.add_all(rows)
                await session.commit()
                ids = [r.id for r in rows]
            await patrol.recover_patrol_runs_on_startup()
            async with env.factory() as session:
                stored = [await session.get(Run, ident) for ident in ids]
                assert [r.status for r in stored] == ['failed', 'cancelled', 'pending']
                assert all(r.auto_day for r in stored)
            seen = []
            async def execute(session, ident, **kwargs):
                seen.append(ident)
                row = await session.get(Run, ident)
                row.status = 'completed'
                await session.commit()
            monkeypatch.setattr(patrol, 'execute_patrol_run', execute)
            await queue.consume_queue()
            assert seen == [ids[-1]]
    asyncio.run(run())


def test_periodic_recovery_cancels_expired_pending_without_releasing_claim(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch, 'postgres') as env:
            yesterday = datetime.now(service.BJ).date() - timedelta(days=1)
            async with env.factory() as session:
                row = Run(tenant_id=10, trigger='self_service', auto_day=yesterday, status='pending',
                    created_at=datetime.utcnow() - timedelta(hours=3), summary={'self_service': {'mode': service.MODE}})
                session.add(row)
                await session.commit()
                row = await patrol.reconcile_stale_patrol_run(session, row)
                assert row.status == 'cancelled' and row.error == 'expired_queue_day'
                assert row.auto_day == yesterday
                assert await session.scalar(select(func.count()).select_from(Run).where(Run.auto_day == yesterday)) == 1
    asyncio.run(run())


def test_admin_list_uses_native_distinct_on_for_each_customer_latest_run(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch, 'postgres') as env:
            today = datetime.now(service.BJ).date()
            async with env.factory() as session:
                first = Run(tenant_id=10, trigger='self_service', auto_day=today, status='completed', items=[{'engine': 'deepseek', 'ok': True}])
                older = Run(tenant_id=20, trigger='self_service', auto_day=today - timedelta(days=1), status='completed', items=[{'engine': 'deepseek', 'ok': True}])
                latest = Run(tenant_id=20, trigger='self_service', auto_day=today, status='completed', items=[{'engine': 'wenxin', 'ok': False}])
                session.add_all([first, older, latest])
                await session.commit()
                expected = {10: first.id, 20: latest.id}
            response = await env.request('GET', '/visibility-patrol/admin-settings', auth=fixture_token(uid=2, native=True))
            assert response.status_code == 200, response.text
            items = {item['tenant_id']: item for item in response.json()['items']}
            assert response.json()['total'] == 3
            assert {tid: items[tid]['last_run']['id'] for tid in expected} == expected
            assert items[10]['last_run']['success'] == 1 and items[20]['last_run']['failed'] == 1
            assert items[30]['last_run'] is None
            filtered = await env.request('GET', '/visibility-patrol/admin-settings', params={'search': 'tenant 20', 'page_size': 1}, auth=fixture_token(uid=2, native=True))
            assert filtered.status_code == 200 and filtered.json()['total'] == 1
            assert filtered.json()['items'][0]['tenant_id'] == 20
    asyncio.run(run())
