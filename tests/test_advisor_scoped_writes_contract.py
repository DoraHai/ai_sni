"""Pure route/field contract and real-SQL body/assignment contract tests.

All implementation modules are imported unconditionally; missing modules fail.
HTTP acceptance tests and contract tests both execute the integrated policy.
"""
import asyncio
import copy
import json
import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.security.advisor_scope import AdvisorScope
from app.security.auth import AuthContext
from test_advisor_scoped_writes import (CASES, CASE_IDS, EDIT, PREFIX, backend,
    mutate, no_external_http_or_background_dispatch, write_sandbox)


def context():
    return AuthContext(user_id=1, username='fixture-1', role_name='顾问', tenant_id=10,
        permissions=EDIT.copy(), advisor_scope=AdvisorScope(frozenset({10, 20}), 10, 101))


def request_for(method, template, *, path_params=None, query='tenant_id=10', body=None):
    raw = json.dumps(body or {}).encode()
    path = template
    for key, value in {'fact_id': 10, 'prompt_id': 10, 'business_id': 10, 'unit_id': 10,
                       'task_id': 10, 'channel': 'website', **(path_params or {})}.items():
        path = path.replace('{' + key + '}', str(value))

    async def receive():
        return {'type': 'http.request', 'body': raw, 'more_body': False}

    return Request({'type': 'http', 'method': method, 'scheme': 'http',
        'server': ('fixture', 80), 'client': ('127.0.0.1', 1),
        'path': PREFIX + path, 'root_path': '', 'headers': [],
        'query_string': query.encode(), 'path_params': path_params or {},
        'route': SimpleNamespace(path=PREFIX + template)}, receive)


@pytest.fixture
def rules():
    return importlib.import_module('app.security.advisor_write_routes')


@pytest.fixture
def objects():
    return importlib.import_module('app.security.advisor_write_objects')


def test_settings_scoped_flag_exists_and_defaults_false():
    from app.config import Settings
    field = Settings.model_fields.get('advisor_scoped_content_writes_enabled')
    assert field is not None, 'A must add the scoped-content flag to Settings'
    assert field.annotation is bool
    assert field.default is False


def test_write_surface_is_bounded_to_this_task(rules):
    mandatory = {(case[0], PREFIX + case[1]) for case in CASES}
    optional = {('POST', PREFIX + path) for path in ('/facts/import', '/prompts/import', '/prompts/import-csv')}
    optional |= {('POST', PREFIX + '/content-tasks/{task_id}/' + action) for action in ('generate', 'suggest-brief')}
    assert mandatory <= rules.WRITE_ROUTES.keys()
    assert rules.WRITE_ROUTES.keys() <= mandatory | optional


@pytest.mark.parametrize('case', CASES, ids=CASE_IDS)
def test_mandatory_rule_matches_exact_method_and_mounted_template(rules, case):
    method, template, body, *_ = case
    request = request_for(method, template)
    rule = rules.match_write_rule(request)
    assert rule is rules.WRITE_ROUTES[(method, PREFIX + template)]
    assert rule.method == method and rule.template == PREFIX + template
    assert rule.assignment == 'project'
    assert rule.edit_all and set(rule.edit_all).issubset({'geo.assets', 'geo.content'})
    assert isinstance(rule.fields, frozenset) and isinstance(rule.forbidden, frozenset)
    rules.check_write_fields(rule, copy.deepcopy(body))


@pytest.mark.parametrize('method,template', [
    ('DELETE', '/facts/{fact_id}'),
    ('POST', '/content-tasks/{task_id}/ai-review'),
     ('POST', '/facts-extra'),
    ('PATCH', '/content-tasks/{task_id}/variants/{channel}/publish'),
])
def test_unknown_methods_or_adjacent_templates_do_not_match(rules, method, template):
    assert rules.match_write_rule(request_for(method, template)) is None


@pytest.mark.parametrize('case', CASES, ids=CASE_IDS)
@pytest.mark.parametrize('extra', [{'unknown_field': 1}, {'owner_user_id': None},
                                  {'advisor_user_id': 1}, {'published_at': None}])
def test_unset_null_is_still_a_forbidden_field(rules, case, extra):
    rule = rules.WRITE_ROUTES[(case[0], PREFIX + case[1])]
    with pytest.raises(HTTPException) as denied:
        rules.check_write_fields(rule, {**case[2], **extra})
    assert denied.value.status_code == 403
    assert denied.value.detail['code'] == 'ADVISOR_WRITE_FIELD_FORBIDDEN'


@pytest.mark.parametrize('body', [
    {'brief': {'prompt_id': 20}},
    {'brief': {'nested': [{'fact_ids': [10, 20]}]}},
    [{'prompt_id': 10}, {'prompt_id': 20}],
    {'brief': {'nested': {'business_id': 20}}},
    {'brief': {'tenant_ids': [10, 20]}},
])
def test_object_walker_checks_every_nested_or_array_id(tmp_path, monkeypatch, backend, rules, objects, body):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            rule = rules.WRITE_ROUTES[('PATCH', PREFIX + '/content-tasks/{task_id}')]
            request = request_for('PATCH', '/content-tasks/{task_id}', path_params={'task_id': 10})
            before = await env.snapshot()
            async with env.factory() as session:
                with pytest.raises(HTTPException) as denied:
                    await objects.check_write_objects(session, context(), request, body, rule)
                assert denied.value.status_code == 403
                assert denied.value.detail['code'] == 'ADVISOR_TENANT_NOT_GRANTED'
                await session.rollback()
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('body', [{'brief': {'future_object_id': 10}},
                                  {'brief': [{'unknown_ids': [10]}]}])
def test_unknown_id_fields_fail_closed(tmp_path, monkeypatch, backend, rules, objects, body):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            rule = rules.WRITE_ROUTES[('PATCH', PREFIX + '/content-tasks/{task_id}')]
            request = request_for('PATCH', '/content-tasks/{task_id}', path_params={'task_id': 10})
            async with env.factory() as session:
                with pytest.raises(HTTPException) as denied:
                    await objects.check_write_objects(session, context(), request, body, rule)
                assert denied.value.status_code == 403
                assert denied.value.detail['code'] == 'ADVISOR_OBJECT_UNAVAILABLE'
    asyncio.run(run())


@pytest.mark.parametrize('location', ['path', 'query', 'body'])
def test_nonexistent_objects_are_404(tmp_path, monkeypatch, backend, rules, objects, location):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            rule = rules.WRITE_ROUTES[('PATCH', PREFIX + '/content-tasks/{task_id}')]
            request = request_for('PATCH', '/content-tasks/{task_id}',
                path_params={'task_id': 999 if location == 'path' else 10},
                query='tenant_id=10' + ('&prompt_id=999' if location == 'query' else ''))
            async with env.factory() as session:
                with pytest.raises(HTTPException) as denied:
                    await objects.check_write_objects(session, context(), request,
                        {'brief': {'fact_ids': [999]}} if location == 'body' else {}, rule)
                assert denied.value.status_code == 404
    asyncio.run(run())


def test_content_task_id_uses_content_table_even_when_ticket_id_collides(tmp_path, monkeypatch, backend, rules, objects):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            rule = rules.WRITE_ROUTES[('PATCH', PREFIX + '/content-tasks/{task_id}')]
            request = request_for('PATCH', '/content-tasks/{task_id}', path_params={'task_id': 10})
            async with env.factory() as session:
                await objects.check_write_objects(session, context(), request, {'title': 'safe'}, rule)
                await objects.ensure_advisor_assignment(session, context(), request, {'title': 'safe'}, rule)
    asyncio.run(run())


def test_same_customer_other_project_ids_are_not_an_assignment(tmp_path, monkeypatch, backend, rules, objects):
    async def run():
        from app.models import GeoFact, GeoOptimizationBusiness
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            async with env.factory() as session:
                session.add(GeoOptimizationBusiness(id=40, tenant_id=10, name='unassigned business'))
                await session.flush()
                session.add(GeoFact(id=40, tenant_id=10, business_id=40, title='unassigned fact',
                    statement='synthetic fixture statement', source_name='fixture', trust_level='draft'))
                await session.commit()
            rule = rules.WRITE_ROUTES[('PUT', PREFIX + '/content-tasks/{task_id}/facts')]
            request = request_for('PUT', '/content-tasks/{task_id}/facts', path_params={'task_id': 10})
            before = await env.snapshot()
            async with env.factory() as session:
                with pytest.raises(HTTPException) as denied:
                    await objects.check_write_objects(session, context(), request, {'fact_ids': [10, 40]}, rule)
                    await objects.ensure_advisor_assignment(session, context(), request, {'fact_ids': [10, 40]}, rule)
                assert denied.value.status_code == 403
                await session.rollback()
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('missing', [None, 'geo.content', 'geo.assets'])
def test_guard_requires_all_edit_keys_and_preserves_handler_json(tmp_path, monkeypatch, backend, rules, objects, missing):
    async def run():
        from dataclasses import replace
        from app.security.geo_advisor import guard_request
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            key = ('PATCH', PREFIX + '/content-tasks/{task_id}')
            # Exercise the AND contract even if this particular product route
            # ultimately needs only one permission. AuthContext.can_edit(*keys)
            # implements OR, so passing both keys at once is a regression.
            monkeypatch.setitem(rules.WRITE_ROUTES, key,
                                replace(rules.WRITE_ROUTES[key], edit_all=('geo.assets', 'geo.content')))
            body = {'title': 'manual title'}
            request = request_for('PATCH', '/content-tasks/{task_id}',
                                  path_params={'task_id': 10}, body=body)
            ctx = context()
            if missing:
                ctx.permissions[missing] = 'view'
            async with env.factory() as session:
                if missing:
                    with pytest.raises(HTTPException) as denied:
                        await guard_request(session, ctx, request, {'scope_kind': 'advisor_tenant', 'tid': 10, 'gid': 101, 'exp': int(datetime.now(timezone.utc).timestamp()) + 600})
                    assert denied.value.status_code == 403
                else:
                    await guard_request(session, ctx, request, {'scope_kind': 'advisor_tenant', 'tid': 10, 'gid': 101, 'exp': int(datetime.now(timezone.utc).timestamp()) + 600})
                    assert request.state.advisor_scoped_write == rules.WRITE_ROUTES[key]
                    assert await request.json() == body
                    assert json.loads(await request.body()) == body
    asyncio.run(run())


@pytest.mark.parametrize('path,upload', [('/facts/import', True),
                                       ('/prompts/import', False), ('/prompts/import-csv', True)])
@pytest.mark.parametrize('foreign', [False, True], ids=['all-safe-success-or-excluded', 'foreign-row-atomic-rejection'])
def test_optional_imports_are_closed_or_validate_every_row_before_writing(tmp_path, monkeypatch, backend, rules, path, upload, foreign):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            tid = 20 if foreign else 10
            before = await env.snapshot()
            params = {'project_id': 10, 'business_id': 10, 'unit_id': 10}
            if upload:
                if path.startswith('/facts'):
                    raw = ('tenant_id,business_id,title,statement,source_name,trust_level\n'
                           '10,10,safe first row,synthetic statement,fixture source,draft\n'
                           f'{tid},{tid},second row,synthetic statement,fixture source,draft\n')
                else:
                    raw = ('tenant_id,unit_id,question\n10,10,safe first question?\n'
                           f'{tid},{tid},second fixture question?\n')
                response = await env.request('POST', path, params=params,
                    files={'file': ('fixture.csv', raw.encode('utf-8'), 'text/csv')})
            else:
                response = await env.request('POST', path, params=params, body={
                    'tenant_id': 10, 'items': [
                        {'question': 'safe first question?', 'unit_id': 10},
                        {'question': 'second fixture question?', 'unit_id': tid, 'tenant_id': tid}]})
            permitted = ('POST', PREFIX + path) in rules.WRITE_ROUTES
            if not permitted or foreign:
                assert response.status_code == 403, response.text
                assert await env.snapshot() == before
            else:
                assert response.status_code in {200, 201}, response.text
                table = 'geo_facts' if path.startswith('/facts') else 'geo_prompts'
                assert len((await env.snapshot())[table]) == len(before[table]) + 2
    asyncio.run(run())
