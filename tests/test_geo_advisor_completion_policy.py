"""No database or provider calls: exact contracts and compiled scope boundaries."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.orm import aliased, with_loader_criteria
from starlette.requests import Request

from app import models as m
from app.security.advisor_operations import LOOKUP, check_fields, read_contract, rules
from app.security.advisor_read_scope import patrol_in_scope, predicates


def compile_scoped(statement, projects=(10,), businesses=(10,)):
    conditions = predicates(SimpleNamespace(tenant_id=10, user_id=1), projects, businesses, ('own.test',))
    return str(statement.options(*(with_loader_criteria(model, c, include_aliases=True)
        for model, c in conditions.items())).compile(dialect=dialect(), compile_kwargs={'literal_binds': True}))


@pytest.mark.parametrize('model', (m.GeoProject, m.GeoFact, m.GeoPrompt, m.GeoContentTask,
    m.GeoArticleVersion, m.GeoChannelVariant, m.GeoPublication, m.GeoAnswerSnapshot,
    m.GeoAsyncJob, m.GeoOptimizationPeriod, m.GeoCompetitorReport, m.GeoDailyMetric))
def test_all_content_queries_have_project_predicates(model):
    sql = compile_scoped(select(model))
    assert 'WHERE' in sql
    assert '10' in sql and '50' not in sql
    if hasattr(model, 'tenant_id'):
        assert 'tenant_id = 10' in sql


def test_aggregate_alias_subquery_and_bulk_delete_are_scoped():
    assert 'business_id IN (10)' in compile_scoped(select(func.count(m.GeoFact.id)))
    assert 'business_id IN (10)' in compile_scoped(select(aliased(m.GeoFact)))
    sql = compile_scoped(select(m.GeoContentTask.id).subquery().select())
    assert 'geo_prompts.unit_id IN' in sql and 'business_id IN (10)' in sql
    assert 'business_id IN (10)' in compile_scoped(delete(m.GeoDailyMetric))


def test_empty_assignment_returns_no_project_content():
    sql = compile_scoped(select(m.GeoFact), (), ())
    assert '1 != 1' in sql


@pytest.mark.parametrize('method,path', LOOKUP)
def test_operational_routes_remain_exact(method, path):
    from app.security.advisor_write_routes import match_write_rule
    request = SimpleNamespace(method=method, scope={'route': SimpleNamespace(path=path)})
    assert match_write_rule(request).assignment == 'operations'
    request.scope['route'].path += '/extra'
    assert match_write_rule(request) is None


@pytest.mark.parametrize('path', ('/tracking-engines', '/visibility-patrol/settings',
    '/projects/{project_id}/service-plan', '/projects/{project_id}/business-scope',
    '/oauth/social/start', '/ai-settings', '/monitoring-stance'))
def test_system_settings_are_not_operational_grants(path):
    assert not any(template == '/api/v1/geo' + path for _, template in LOOKUP)


@pytest.mark.parametrize('value', ({'api_key': 'fixture'}, {'role_id': 2},
    {'advisor_user_id': 2}, {'interval_hours': 1}, {'model': 'fixture'}))
def test_nested_configuration_fields_are_rejected(value):
    rule = rules()[('POST', '/api/v1/geo/publishing-channels')]
    with pytest.raises(HTTPException):
        check_fields(rule, {'content_rules': {'nested': [value]}})


def test_operation_query_and_duplicate_json_fields_are_rejected():
    rule = rules()[('POST', '/api/v1/geo/answer-snapshots/probe')]
    async def run(query, raw):
        async def receive():
            return {'type': 'http.request', 'body': raw}
        req = Request({'type': 'http', 'method': 'POST', 'path': rule.template, 'headers': [],
                       'query_string': query.encode()}, receive)
        with pytest.raises(HTTPException):
            await read_contract(req, rule)
    asyncio.run(run('tenant_id=10&engine_keys=x', b'{}'))
    asyncio.run(run('tenant_id=10', b'{"prompt_id":10,"prompt_id":50}'))


@pytest.mark.parametrize('items,frozen,declared,visible', [
    ([{'prompt_id': 10}], [10], 1, True),
    ([], [10], 1, True),
    ([{'prompt_id': 50}], [10], 2, False),
    ([{'prompt_id': 10}], [50], 1, False),
    ([{'prompt_id': 10}], None, 2, False),
    ([], None, 0, False),
])
def test_patrol_cached_payload_cannot_mix_other_project_samples(items, frozen, declared, visible):
    summary = {'prompts': declared}
    if frozen is not None:
        summary['advisor_visibility_prompt_ids'] = frozen
    row = SimpleNamespace(items=items, summary=summary)
    assert patrol_in_scope(row, {10}) is visible


def test_supplier_is_not_called_after_revocation(monkeypatch):
    from app.security import advisor_operation_call as calls
    from app.security import advisor_write_commit as commits
    provider = AsyncMock(return_value={'candidate': 'fixture'})
    session = SimpleNamespace(commit=AsyncMock())
    async def revoked(*args):
        raise HTTPException(403, 'fixture revoked')
    monkeypatch.setattr(commits, 'recheck_advisor_before_commit', revoked)
    async def run():
        token = calls.current_operation.set((session, object()))
        try:
            with pytest.raises(HTTPException):
                await calls.checked_call(provider)()
        finally:
            calls.current_operation.reset(token)
    asyncio.run(run())
    provider.assert_not_awaited()


@pytest.mark.parametrize('body', ({'auth_type': 'webhook'}, {'credentials': {}}, {'auth_type': 'oauth2'}))
def test_manual_account_operations_cannot_configure_credentials(body):
    rule = rules()[('POST', '/api/v1/geo/channel-accounts')]
    with pytest.raises(HTTPException):
        check_fields(rule, body)


def test_dispatched_patrol_does_not_reuse_request_session(monkeypatch):
    from contextlib import asynccontextmanager
    from app.geo.content import patrol
    from app.geo import tenant_scope
    from app.security import advisor_operation_call as calls

    visited = []
    @asynccontextmanager
    async def not_acquired(run_id):
        assert run_id == 10
        visited.append(calls.current_operation.get())
        yield False  # No database or real worker is started.
    monkeypatch.setattr(patrol, 'patrol_execution_lock', not_acquired)
    monkeypatch.setattr(tenant_scope, 'ensure_geo_background_execution_allowed', lambda _: None)
    async def run():
        binding = (object(), object())
        token = calls.current_operation.set(binding)
        try:
            await patrol.run_patrol_in_background(10, 10)
            assert calls.current_operation.get() is binding
        finally:
            calls.current_operation.reset(token)
    asyncio.run(run())
    assert visited == [None]


def test_operation_log_does_not_claim_savepoint_is_durable(monkeypatch):
    from unittest.mock import Mock
    from app.security import advisor_write_audit as audit
    from app.security import advisor_write_commit as commits
    callbacks = {}
    monkeypatch.setattr(commits.event, 'listen',
        lambda _session, name, function: callbacks.setdefault(name, function))
    logged = Mock()
    monkeypatch.setattr(audit, 'record', logged)
    request = SimpleNamespace(scope={})
    session = SimpleNamespace(info={}, sync_session=object())
    commits.bind_advisor_write_commit(session, object(), request, {}, object(), {'exp': 999})
    callbacks['after_commit'](SimpleNamespace(in_nested_transaction=lambda: True))
    logged.assert_not_called()
    callbacks['after_commit'](SimpleNamespace(in_nested_transaction=lambda: False))
    logged.assert_called_once_with(request.scope, 'committed')


def test_patrol_history_delete_retains_answers_and_does_not_replay_deleted_run():
    from app.security.advisor_patrol_delete import detach_run_evidence
    snapshot = SimpleNamespace(patrol_run_id=10, raw_text='fixture evidence',
        sample_mode='openai_compat', simulated=False, note='original note')
    ticket = SimpleNamespace(progress={'retest_runs': {'old-week': 99, 'this-week': 10}})
    from unittest.mock import Mock
    from datetime import datetime
    session = SimpleNamespace(scalars=AsyncMock(side_effect=[[snapshot], [ticket]]), add=Mock())
    ctx = SimpleNamespace(advisor_scope=object(), tenant_id=10, user_id=1)
    created = datetime(2026, 10, 18, 18)
    asyncio.run(detach_run_evidence(session, ctx, SimpleNamespace(id=10, status='completed',
        created_by=1, created_at=created)))
    assert snapshot.patrol_run_id is None and '#10' in snapshot.note and 'original note' in snapshot.note
    assert (snapshot.raw_text, snapshot.sample_mode, snapshot.simulated) == ('fixture evidence', 'openai_compat', False)
    assert ticket.progress['retest_runs'] == {'old-week': 99}
    assert ticket.progress['deleted_retest_runs']['10']['window_starts'] == ['this-week']
    counter = session.add.call_args.args[0]
    assert counter.created_at == created and counter.created_by == 1
    assert counter.summary == {'reservation_only': True, 'deleted_run_id': 10}
