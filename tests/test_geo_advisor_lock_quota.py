"""Pure mock/SQL compilation checks: no database or external transport."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import dialect

from app.security import advisor_operation_call as calls
from app.security import advisor_quota as quota


@pytest.mark.parametrize('change', ('grant', 'role', 'assignment'))
def test_revocation_during_supplier_discards_result_and_blocks_next_step(monkeypatch, change):
    from app.security import advisor_write_commit as commits
    from app.security import advisor_read_scope as reads
    session = SimpleNamespace(info={}, commit=AsyncMock(), rollback=AsyncMock())
    revoked = False
    async def recheck(*_args):
        if revoked:
            raise HTTPException(403, change)
    monkeypatch.setattr(commits, 'recheck_advisor_before_commit', recheck)
    monkeypatch.setattr(reads, 'recheck_initial_scope', AsyncMock())
    steps = []
    @calls.checked_call
    async def supplier():
        nonlocal revoked
        steps.append('supplier')
        revoked = True
        return {'result': 'must never escape'}
    @calls.checked_call
    async def next_step():
        steps.append('next')
    async def run():
        token = calls.current_operation.set((session, object()))
        try:
            with pytest.raises(HTTPException):
                await supplier()
            # Even if the handler catches the denial, no later dispatch works.
            with pytest.raises(HTTPException):
                await next_step()
        finally:
            calls.current_operation.reset(token)
    asyncio.run(run())
    assert steps == ['supplier']
    assert session.commit.await_count == 1  # only pre-call release
    session.rollback.assert_awaited_once()
    assert session.info['advisor_operation_denied'] is True


def test_post_call_retains_authority_until_business_commit(monkeypatch):
    from app.security import advisor_write_commit as commits
    from app.security import advisor_read_scope as reads
    session = SimpleNamespace(info={}, commit=AsyncMock(), rollback=AsyncMock())
    recheck = AsyncMock()
    monkeypatch.setattr(commits, 'recheck_advisor_before_commit', recheck)
    monkeypatch.setattr(reads, 'recheck_initial_scope', AsyncMock())
    async def supplier():
        assert session.commit.await_count == 1
        return 'ok'
    async def run():
        token = calls.current_operation.set((session, object()))
        try:
            assert await calls.checked_call(supplier)() == 'ok'
        finally:
            calls.current_operation.reset(token)
    asyncio.run(run())
    assert recheck.await_count == 2
    assert session.commit.await_count == 1


def test_caught_denial_cannot_commit_results():
    from app.security.advisor_write_commit import recheck_advisor_before_commit
    async def run():
        session = SimpleNamespace(info={'advisor_operation_denied': True})
        with pytest.raises(HTTPException):
            await recheck_advisor_before_commit(session, SimpleNamespace(advisor_scope=object()))
    asyncio.run(run())


def test_atomic_refund_is_bound_to_one_actor_tenant_and_reserved_state():
    statement = quota.transition((7, 10, 1), 'reserved', 'refunded')
    compiled = statement.compile(dialect=dialect())
    sql = str(compiled)
    assert 'UPDATE geo_visibility_patrol_runs SET summary=' in sql
    assert all(f'geo_visibility_patrol_runs.{name} =' in sql for name in ('id', 'tenant_id', 'created_by'))
    assert 'reservation_only' in compiled.params.values()
    assert 'reserved' in compiled.params.values()
    assert {'reservation_only': True, quota.STATE: 'refunded'} in compiled.params.values()


@pytest.mark.parametrize('initial,expected', [('reserved', 'refunded'), ('consumed', 'consumed'), ('queued', 'queued'), ('refunded', 'refunded')])
def test_duplicate_and_concurrent_refund_updates_at_most_one_row(monkeypatch, initial, expected):
    # Model the single SQL compare-and-set, not a read/modify/write counter.
    async def run():
        state, affected = initial, 0
        lock = asyncio.Lock()
        class Cleanup:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                pass
            async def execute(self, statement):
                nonlocal state, affected
                compiled = statement.compile(dialect=dialect())
                assert 'reserved' in compiled.params.values()
                async with lock:
                    if state == 'reserved':
                        state, affected = 'refunded', affected + 1
            async def commit(self):
                pass
        monkeypatch.setattr(quota, 'async_sessionmaker', lambda **_kw: Cleanup)
        session = SimpleNamespace(info={quota.KEY: (7, 10, 1)}, bind=object(), rollback=AsyncMock())
        await asyncio.gather(*(quota.refund_unused_reservation(session) for _ in range(20)))
        await quota.refund_unused_reservation(session)
        assert state == expected
        assert affected == int(initial == 'reserved')
    asyncio.run(run())


@pytest.mark.parametrize('items,has_result', [([], False), ([{'error': 'failed'}], False),
    ([{'source': 'skipped'}], False), ([{'results': [], 'error': None}], True),
    ([{'error': 'failed'}, {'results': [{'url': 'fixture'}], 'error': None}], True)])
def test_search_partial_results_and_error_only(items, has_result):
    assert quota.search_has_results({'items': items}) is has_result


@pytest.mark.parametrize('status,items,expected', [('failed', [], 'refunded'),
    ('cancelled', [], 'refunded'), ('succeeded', [], 'consumed'),
    ('failed', [{'results': [], 'error': None}], 'consumed'), ('running', [], None)])
def test_async_search_terminal_settlement(status, items, expected):
    session = SimpleNamespace(execute=AsyncMock())
    job = SimpleNamespace(kind='search_visibility', tenant_id=10, created_by=1, status=status,
        request_meta={quota.KEY: [7, 10, 1]}, result_meta={'items': items})
    asyncio.run(quota.settle_search_reservation(session, job))
    if expected is None:
        session.execute.assert_not_awaited()
    else:
        params = session.execute.call_args.args[0].compile(dialect=dialect()).params
        assert {'reservation_only': True, quota.STATE: expected} in params.values()
        assert 'queued' in params.values()


@pytest.mark.parametrize('status,items,snapshots,expected', [
    ('failed', [], 0, 'refunded'), ('completed', [{'ok': False}], 0, 'refunded'),
    ('cancelled', [], 0, 'refunded'), ('failed', [{'ok': True}], 0, 'consumed'),
    ('failed', [], 1, 'consumed'), ('pending', [], 0, None)])
def test_patrol_terminal_failure_partial_and_retry(status, items, snapshots, expected):
    row = SimpleNamespace(status=status, items=items,
        summary={'advisor_visibility_auth': {'user_id': 1}, 'snapshots_created': snapshots})
    quota.settle_patrol_quota(row)
    quota.settle_patrol_quota(row)
    assert row.summary.get(quota.STATE) == expected


def test_refunded_attempt_is_excluded_but_legacy_and_other_actors_are_counted():
    from app.geo.content.patrol import count_patrol_runs_today
    session = SimpleNamespace(scalar=AsyncMock(return_value=2))
    assert asyncio.run(count_patrol_runs_today(session, 10, created_by=1)) == 2
    compiled = session.scalar.call_args.args[0].compile(dialect=dialect())
    assert 'coalesce' in str(compiled) and 'created_by =' in str(compiled)
    assert 'refunded' in compiled.params.values() and quota.STATE in compiled.params.values()


def test_stale_pending_cancel_reloads_running_job_before_refunding():
    from app.geo.content.async_jobs import request_cancel
    stale = SimpleNamespace(id=7, kind='search_visibility', status='pending')
    live = SimpleNamespace(kind='search_visibility', status='running', tenant_id=10, created_by=1,
        request_meta={quota.KEY: [9, 10, 1]})
    session = SimpleNamespace(scalar=AsyncMock(return_value=live), execute=AsyncMock(),
        commit=AsyncMock(), refresh=AsyncMock())
    assert asyncio.run(request_cancel(session, stale)) is live
    assert live.status == 'running' and live.request_meta['cancel_requested'] is True
    session.execute.assert_not_awaited()
    sql = str(session.scalar.call_args.args[0].compile(dialect=dialect()))
    assert 'FOR UPDATE' in sql
