"""SEM-only request bounds; all model and database operations are mocked."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests import test_sem_expansion_acceptance as acceptance
from tests.test_sem_expansion_business_profile import tenant, basis
from tests.test_sem_expansion_small_batch import api_client, candidate, rows_result
from app.ai import expansion_eval as ev


@pytest.fixture
def deny_network():
    yield from acceptance.deny_network.__wrapped__()


def response(words):
    return {'items': [dict(word=w['word'], relevance='relevant', recommend='watch',
                           reason='相关', basis=basis(), suggested_bid=None, bid_reason=None)
                      for w in words]}


def session_for(rows):
    return SimpleNamespace(get=AsyncMock(return_value=tenant()),
                           scalars=AsyncMock(return_value=rows_result(rows)), commit=AsyncMock())


@pytest.mark.parametrize('limit', [None, 1, 5, 6, 20])
def test_http_one_model_request_and_real_cursor_progress(monkeypatch, limit):
    monkeypatch.setattr(ev, 'is_enabled', lambda: True)
    rows = [candidate(i) for i in range(1, 13)] + [candidate(13, '粉末涂料1')]
    size = min(limit or 5, 5)
    chat = AsyncMock(return_value=response([{'word': r.word} for r in rows[:size]]))
    monkeypatch.setattr(ev, 'chat_json', chat)
    session = session_for(rows)
    params = {'tenant_id': 3, 'force': True}
    if limit is not None:
        params['limit'] = limit
    result = api_client(session).post('/api/v1/expansion/evaluate', params=params)
    assert result.status_code == 200
    body = result.json()
    assert body['batches'] == 1 and body['successful_words'] == size
    assert body['evaluated'] == size + 1  # same word, two source rows
    assert body['next_after_id'] == size and body['deferred'] == 12 - size
    assert body['failed_candidate_ids'] == []
    chat.assert_awaited_once()
    assert chat.await_args.kwargs == {'timeout': 30.0}
    sent = chat.await_args.args[1].splitlines()[3:]
    assert len(sent) == size
    assert all(r.ai_evaluated_at is None for r in rows[size:12])
    assert all(r.status == 'pending' and r.preset_price == 2 for r in rows)
    session.commit.assert_awaited_once()


def test_timeout_keeps_old_values_and_all_retry_ids_without_continuing(monkeypatch):
    monkeypatch.setattr(ev, 'is_enabled', lambda: True)
    monkeypatch.setattr(ev, 'MODEL_TIMEOUT_SECONDS', 0.02)
    cancelled = []
    async def slow(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    chat = AsyncMock(side_effect=slow)
    monkeypatch.setattr(ev, 'chat_json', chat)
    rows = [candidate(i) for i in range(1, 13)]
    for row in rows:
        row.ai_reason = '旧结果'
        row.ai_suggested_bid = 3
        row.raw = {'source': 'keep'}
    session = session_for(rows)
    client = api_client(session)
    result = client.post('/api/v1/expansion/evaluate?tenant_id=3&force=true&limit=20').json()
    assert result['failed_batches'] == 1 and result['failed_words'] == 5
    assert result['successful_words'] == 0 and result['evaluated'] == 0
    assert result['failed_candidate_ids'] == [1, 2, 3, 4, 5]
    assert result['next_after_id'] == 5 and result['deferred'] == 7
    assert result['remaining'] == 12 and cancelled == [True]
    chat.assert_awaited_once()
    session.commit.assert_not_awaited()
    for row in rows:
        assert row.ai_reason == '旧结果' and row.ai_suggested_bid == 3
        assert row.raw == {'source': 'keep'} and row.ai_evaluated_at is None
        assert row.status == 'pending' and row.preset_price == 2
    # A subsequent explicit click may proceed past failures; no hidden retry.
    chat.side_effect = None
    chat.return_value = response([{'word': r.word} for r in rows[5:10]])
    next_result = client.post('/api/v1/expansion/evaluate?tenant_id=3&force=true&after_id=5').json()
    assert next_result['successful_words'] == 5 and next_result['next_after_id'] == 10
    assert chat.await_count == 2
    assert all(r.ai_evaluated_at is None for r in rows[:5])


def test_oversized_legacy_retry_is_rejected_without_losing_or_attempting_ids(monkeypatch):
    chat = AsyncMock()
    monkeypatch.setattr(ev, 'chat_json', chat)
    session = session_for([])
    result = api_client(session).post('/api/v1/expansion/evaluate?tenant_id=3&limit=20',
                                      json={'retry_ids': list(range(1, 21))})
    assert result.status_code == 422 and '5' in result.json()['detail']
    chat.assert_not_awaited()
    session.get.assert_not_awaited()
    session.scalars.assert_not_awaited()


def test_wall_clock_budget_cancels_continuously_active_model(deny_network):
    runner, guard = deny_network
    guard.setattr(ev, 'MODEL_TIMEOUT_SECONDS', 0.02)
    async def active(*args, **kwargs):
        while True:
            await asyncio.sleep(0)  # activity never finishes: HTTP inactivity != total time
    chat = AsyncMock(side_effect=active)
    guard.setattr(ev, 'chat_json', chat)
    with pytest.raises(ev.DeepSeekError, match='超过时限'):
        runner.run(ev._evaluate_batch(tenant(), [{'word': '涂料'}]))
    chat.assert_awaited_once()


def test_external_cancellation_is_not_misreported_as_model_timeout(deny_network):
    runner, guard = deny_network
    async def run():
        entered = asyncio.Event()
        async def wait(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        chat = AsyncMock(side_effect=wait)
        guard.setattr(ev, 'chat_json', chat)
        task = asyncio.create_task(ev._evaluate_batch(tenant(), [{'word': '涂料'}]))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        chat.assert_awaited_once()
    runner.run(run())


def test_transport_failure_is_not_retried(deny_network):
    runner, guard = deny_network
    chat = AsyncMock(side_effect=ev.DeepSeekError('offline transport failure'))
    guard.setattr(ev, 'chat_json', chat)
    with pytest.raises(ev.DeepSeekError, match='offline transport'):
        runner.run(ev._evaluate_batch(tenant(), [{'word': '涂料'}]))
    chat.assert_awaited_once()


def test_budget_change_does_not_modify_profile_or_verdict_policy(deny_network):
    runner, guard = deny_network
    customer = tenant()
    before = ev.context_fingerprint(customer)
    item = response([{'word': '涂料'}])
    original = deepcopy(item)
    guard.setattr(ev, 'chat_json', AsyncMock(return_value=item))
    result = runner.run(ev._evaluate_batch(customer, [{'word': '涂料'}]))
    assert result['涂料']['recommend'] == 'watch'
    assert ev.context_fingerprint(customer) == before and item == original
    assert ev.MODEL_TIMEOUT_SECONDS == 30 and ev.INTERACTIVE_WORD_LIMIT == 5
