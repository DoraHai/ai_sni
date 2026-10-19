"""Retest access decisions with mocked storage only; no connections or tokens."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.security.auth import AuthContext
from app.security.advisor_scope import AdvisorScope


def advisor(tid=17):
    return AuthContext(1, 'synthetic', '顾问', tid,
        {'geo.assets': 'edit', 'geo.content': 'edit'},
        advisor_scope=AdvisorScope(frozenset({15, 17}), tid, 102))


@pytest.mark.parametrize('tid', [15, 17])
@pytest.mark.parametrize('enabled,assigned', [(True, True), (True, False), (False, False)])
def test_selected_customer_switcher_explains_missing_entitlement_or_project(monkeypatch, tid, enabled, assigned):
    from app.geo import routes, tenant_scope
    from app.security import advisor_write_reads
    tenants = AsyncMock(return_value=[NS(id=tid, name='synthetic')] if enabled else [])
    monkeypatch.setattr(routes, 'list_geo_tenants_for_auth', tenants)
    monkeypatch.setattr(advisor_write_reads, 'assigned_scope',
        AsyncMock(return_value=({10}, {10}) if assigned else (set(), set())))
    monkeypatch.setattr(tenant_scope, 'ensure_geo_entitlement', AsyncMock(return_value=NS(
        is_demo=False, read_only=False, fixture_namespace=None, dataset_version=None)))
    session = object()
    result = asyncio.run(routes.get_geo_tenants(ctx=advisor(tid), session=session))
    tenants.assert_awaited_once_with(session, bound_tenant_id=tid)
    assert [r['id'] for r in result['tenants']] == ([tid] if enabled and assigned else [])
    if enabled and assigned:
        assert 'unavailable_reason' not in result
    else:
        assert ('项目顾问' if enabled else 'GEO 模块和有效期') in result['unavailable_reason']


def test_admin_switcher_does_not_require_advisor_assignment(monkeypatch):
    from app.geo import routes, tenant_scope
    from app.security import advisor_write_reads
    monkeypatch.setattr(routes, 'list_geo_tenants_for_auth', AsyncMock(return_value=[NS(id=17, name='second')]))
    assignment = AsyncMock(side_effect=AssertionError('admin must not use advisor assignment'))
    monkeypatch.setattr(advisor_write_reads, 'assigned_scope', assignment)
    monkeypatch.setattr(tenant_scope, 'ensure_geo_entitlement', AsyncMock(return_value=NS(
        is_demo=False, read_only=False, fixture_namespace=None, dataset_version=None)))
    result = asyncio.run(routes.get_geo_tenants(ctx=AuthContext(None, '', '', None, is_superadmin=True), session=object()))
    assert result['tenants'][0]['id'] == 17
    assignment.assert_not_awaited()


@pytest.mark.parametrize('suffix', ['variants', 'publications', 'import-receipts'])
def test_content_actions_do_not_require_ownership_of_every_customer_project(suffix):
    from app.security.advisor_write_routes import match_write_rule
    from app.security.advisor_operations import guard_shared_destinations
    rule = match_write_rule(NS(method='POST', scope={'route': NS(path=f'/api/v1/geo/content-tasks/{{task_id}}/{suffix}')}))
    assert rule is not None
    # This object deliberately cannot query any project: these are task writes.
    asyncio.run(guard_shared_destinations(object(), advisor(), NS(path_params={}), {}, rule, {10}))


def test_shared_partial_assignment_denial_explains_where_to_fix_it():
    from app.security.advisor_operations import rules, guard_shared_destinations
    session = NS(scalars=AsyncMock(return_value=[10, 11]))
    rule = rules()[('PUT', '/api/v1/geo/competitor-aliases')]
    with pytest.raises(HTTPException) as denied:
        asyncio.run(guard_shared_destinations(session, advisor(), NS(path_params={}), {}, rule, {10}))
    assert denied.value.status_code == 403
    assert '全部有效项目' in denied.value.detail['message']
    assert '项目顾问' in denied.value.detail['message']


@pytest.mark.parametrize('status,owner', [('active', 1), ('active', 2), ('paused', 1)])
def test_assignment_filters_selected_customer_and_active_project(status, owner):
    from app.security.advisor_write_reads import assigned_scope
    project = NS(id=42, status=status, project_settings={
        'geo_business_scope': {'business_ids': [5]}, 'geo_service_plan': {'advisor_user_id': owner}})
    session = NS(scalars=AsyncMock(return_value=[project]))
    owned, businesses = asyncio.run(assigned_scope(session, advisor()))
    assert owned == ({42} if status == 'active' and owner == 1 else set())
    assert businesses == ({5} if owned else set())
    statement = session.scalars.await_args.args[0]
    assert statement.compile().params['tenant_id_1'] == 17
