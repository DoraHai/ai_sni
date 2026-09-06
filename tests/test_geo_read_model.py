import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from app.geo.integration_metrics import build_weekly_snapshot, verified_patrol_rows, MENTIONS
from app.geo.read_model import answer_payload, period_context
from app.geo.read_routes import decode_cursor, encode_cursor, progress_payload, get_capabilities, router, read_session, get_answer, get_answers


def fixture(count=7):
    rows = [NS(id=i+1, tenant_id=1, prompt_id=i%3+1, engine=str(i%2), captured_at=datetime(2026,8,27),
               sample_mode='openai_compat', simulated=False, note='method=unprimed_json_v2 analysis=completed',
               citation_accuracy='unknown', raw_text='sample answer', mentions_brand=True, cited_urls=[], competitors=[],
               patrol_run_id=31) for i in range(count)]
    run = NS(id=31, tenant_id=1, status='completed', started_at=datetime(2026,8,26), finished_at=datetime(2026,8,28),
             items=[dict(snapshot_id=r.id, prompt_id=r.prompt_id, engine=r.engine, ok=True,
                         sample_mode=r.sample_mode, simulated=False, sampling_method='unprimed_json_v2', analysis_status='completed',
                         raw_text=r.raw_text, suggested_mentions_brand=r.mentions_brand, competitors=[],
                         provider='historical-provider', model='historical-model', prompt_question='Historical question') for r in rows])
    verified_patrol_rows(rows, [run])
    current = build_weekly_snapshot(rows, ['example.com'], date(2026,8,31))
    previous = build_weekly_snapshot([], ['example.com'], date(2026,8,24))
    context = period_context(1, date(2026,8,31), current, previous)
    return rows, run, context


def test_eligible_row_remains_eligible_when_week_insufficient():
    rows, run, context = fixture()
    result = answer_payload(rows[0], NS(question='Edited question', is_brand_probe=False), run, context)
    assert result['sample_eligibility']['eligible']
    assert result['week_membership']['included_in_cohort']
    assert result['metric_adoption'][0]['status'] == 'unavailable'
    assert result['metric_adoption'][0]['reasons'][0]['scope'] == 'week'
    assert result['question']['historical_text'] == 'Historical question'
    assert result['question']['current_text'] == 'Edited question'
    assert result['engine']['model'] == 'historical-model'
    assert result['captured_at'].endswith('Z')
    assert result['captured_at_local'].endswith('+08:00')


@pytest.mark.parametrize('mutation', ['simulated', 'manual', 'wrong_tenant', 'tampered_text', 'brand_probe'])
def test_bad_samples_never_adopted(mutation):
    rows, run, context = fixture(8)
    prompt = NS(question='q', is_brand_probe=False)
    if mutation == 'simulated': rows[0].simulated = True
    if mutation == 'manual': rows[0].sample_mode = 'manual'
    if mutation == 'wrong_tenant': run.tenant_id = 2
    if mutation == 'tampered_text': rows[0].raw_text = 'modified answer'
    if mutation == 'brand_probe': prompt.is_brand_probe = True
    result = answer_payload(rows[0], prompt, run, context)
    assert not result['sample_eligibility']['eligible']
    assert all(r['status'] == 'excluded' for r in result['metric_adoption'])


def test_outside_week_is_not_intrinsically_invalid_and_missing_model_is_not_row_rejection():
    rows, run, context = fixture(8)
    rows[0].captured_at = datetime(2026,8,31)
    run.finished_at = datetime(2026,9,1)
    run.items[0]['model'] = None
    result = answer_payload(rows[0], NS(question='q', is_brand_probe=False), run, context)
    assert result['sample_eligibility']['eligible']
    assert not result['week_membership']['within_window']
    assert not result['comparison_metadata']['complete']
    assert result['metric_adoption'][0]['reasons'][0]['code'] == 'outside_selected_week'


def test_signed_cursor_rejects_tampering():
    cursor = encode_cursor({'v': 1, 'max_id': 30, 'last_id': 10})
    assert decode_cursor(cursor)['max_id'] == 30
    with pytest.raises(HTTPException) as err:
        decode_cursor(cursor[:-1] + ('0' if cursor[-1] != '0' else '1'))
    assert err.value.status_code == 400


def test_expired_job_reads_do_not_reconcile_or_expose_secrets():
    row = NS(id=9, tenant_id=1, status='running', started_at=datetime(2020,1,1), created_at=datetime(2020,1,1),
             finished_at=None, error='401 authorization failed token=do-not-expose', request_meta={'api_key':'do-not-expose', 'progress': {'pct':45}},
             result_meta={}, ref_type=None, ref_id=None)
    before = deepcopy(vars(row))
    with patch('app.geo.content.async_jobs.reconcile_stale_job', side_effect=AssertionError('write forbidden')):
        result = asyncio.run(progress_payload(Mock(), row, 1, 'async_job'))
    assert result['stale'] and result['stored_status'] == 'running'
    assert vars(row) == before
    assert 'do-not-expose' not in str(result)
    assert result['result_refs'] == []


def test_empty_capabilities_do_not_seed_configuration():
    session = Mock(scalars=AsyncMock(return_value=[]), scalar=AsyncMock(return_value=None))
    result = asyncio.run(get_capabilities(1, Mock(), session))
    assert result['configuration_status'] == 'unconfigured'
    assert result['engines'] == result['channels'] == []
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize('stance,configured,mode', [('simulation', True, 'mock_persona'), ('real_only', False, 'unavailable'), ('hybrid', False, 'mock_persona')])
def test_capabilities_do_not_claim_live_mode_from_a_key(stance, configured, mode):
    engine = NS(engine_key='deepseek', display_name='DeepSeek', enabled=True, sample_mode='mock_persona')
    session = Mock(scalars=AsyncMock(side_effect=[[engine], [], []]), scalar=AsyncMock(return_value=NS(monitoring_stance=stance)))
    with patch('app.geo.content.engine_providers.platform_engine_public_status', return_value={'configured': configured}):
        result = asyncio.run(get_capabilities(1, Mock(), session))
    item = result['engines'][0]
    assert item['configured_mode'] == mode
    assert item['effective_mode'] is None and not item['connection_verified']


def test_routes_only_allow_get_and_use_read_session():
    assert {route.path.removeprefix('/integration/read') for route in router.routes} == {
        '/answers', '/answers/{snapshot_id}', '/period-context', '/capabilities', '/content-tasks/{content_task_id}',
        '/async-jobs', '/async-jobs/{async_job_id}', '/patrol-runs', '/patrol-runs/{patrol_run_id}'}
    for route in router.routes:
        assert route.methods == {'GET'}
        assert any(d.call == read_session for d in route.dependant.dependencies)


def test_missing_or_other_tenant_object_returns_404_without_context_loading():
    session = Mock(scalar=AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as err:
        asyncio.run(get_answer(42, 1, None, Mock(), session))
    assert err.value.status_code == 404
    compiled = str(session.scalar.call_args.args[0].compile(compile_kwargs={'literal_binds': True}))
    assert 'tenant_id = 1' in compiled


def test_page_cursor_is_bound_to_tenant_filters_and_has_stable_tie_breaker():
    rows, run, context = fixture(8)
    prompt = NS(question='q', is_brand_probe=False)
    pairs = [(r, prompt) for r in reversed(rows[-3:])]
    session = Mock(scalar=AsyncMock(side_effect=[0, 8]), execute=AsyncMock(return_value=NS(all=lambda: pairs)),
                   scalars=AsyncMock(return_value=[run]))
    with patch('app.geo.read_routes.context_for', AsyncMock(return_value=context)):
        result = asyncio.run(get_answers(tenant_id=1, week_end=date(2026,8,31), limit=2, ctx=Mock(), session=session))
    assert result['pagination']['has_more']
    cursor = result['pagination']['next_cursor']
    assert decode_cursor(cursor)['last_id'] == pairs[1][0].id
    sql = str(session.execute.call_args.args[0].compile(compile_kwargs={'literal_binds': True}))
    assert 'captured_at DESC NULLS LAST' in sql and 'id DESC' in sql
    assert 'tenant_id = 1' in sql and 'id <= 8' in sql
    with pytest.raises(HTTPException) as err:
        asyncio.run(get_answers(tenant_id=2, week_end=date(2026,8,31), limit=2, cursor=cursor, ctx=Mock(), session=Mock()))
    assert err.value.status_code == 400
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_read_session_sets_database_read_only_before_any_query():
    class Context:
        def __init__(self, value): self.value = value
        async def __aenter__(self): return self.value
        async def __aexit__(self, *args): pass
    session = Mock(execute=AsyncMock(), begin=Mock(return_value=Context(None)))
    async def consume():
        async for value in read_session():
            assert value is session
            assert session.execute.await_count == 1
    with patch('app.geo.read_routes.async_session_factory', return_value=Context(session)) as factory:
        asyncio.run(consume())
    factory.assert_called_once_with(autoflush=False)
    assert str(session.execute.call_args.args[0]) == 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_observation_dates_require_timezone_before_data_access():
    with pytest.raises(HTTPException) as err:
        asyncio.run(get_answers(tenant_id=1, captured_from=datetime(2026,8,24), limit=2, ctx=Mock(), session=Mock()))
    assert err.value.status_code == 400
