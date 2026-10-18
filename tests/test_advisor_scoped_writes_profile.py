"""Brand profile bounds, preservation and real scoped-write rejection paths."""
import asyncio
import copy

import httpx
import pytest
from fastapi import HTTPException

from app.models import GeoOptimizationBusiness, GeoOptimizationPeriod, GeoProject, GeoVisibilityPatrolSettings
from app.security.advisor_write_routes import (
    PROFILE_LIST_FIELDS, PROFILE_STRING_FIELDS, WRITE_ROUTES, check_write_fields,
)
from test_advisor_scoped_writes import (
    BRAND_PROFILE, assert_denied, backend, fixture_token, mutate,
    no_external_http_or_background_dispatch, write_sandbox,
)

RULE = WRITE_ROUTES[('PATCH', '/api/v1/geo/optimization-businesses/{business_id}')]


@pytest.mark.parametrize('key', sorted(PROFILE_STRING_FIELDS | PROFILE_LIST_FIELDS))
def test_profile_bounds_and_types(key):
    valid = ['x' * 500, '']
    invalid = [None, 1, True, {}, {'tenant_id': 20}, [['nested']], [{'id': 10}]]
    if key in PROFILE_LIST_FIELDS:
        valid += [[], ['x' * 500] * 20, ','.join(['x' * 500] * 20)]
        invalid += [['x'] * 21, ['x' * 501], [None], [1], [True], ','.join(['x'] * 21)]
    else:
        invalid += [[], ['x']]
    invalid += ['x' * 501]
    for value in valid:
        check_write_fields(RULE, {'profile': {key: value}})
    for value in invalid:
        with pytest.raises(HTTPException) as denied:
            check_write_fields(RULE, {'profile': {key: value}})
        assert denied.value.status_code == 403
        assert denied.value.detail['code'] == 'ADVISOR_WRITE_FIELD_FORBIDDEN'


@pytest.mark.parametrize('profile', [None, [], '', 1, True,
    {'unknown': ''}, {'geo_scope': ''}, {'website_url': ''}, {'official_url': ''},
    {'id': 10}, {'tenant_id': 20}, {'business_id': 20}, {'project_id': 20},
    {'owner_user_id': 2}, {'advisor_user_id': 2}, {'status': 'active'},
    {'permissions': {'geo.assets': 'edit'}}, {'review_status': 'approved'},
    {'published_url': 'https://example.test'}, {'deleted_at': None},
    {'qualifications': [{'text': 'nested'}]}, {'summary': {'value': 'nested'}},
    {'competitors': ['x'] * 21}, {'summary': '字' * 501},
])
def test_raw_profile_rejected_atomically(tmp_path, monkeypatch, backend, profile):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            response = await env.request('PATCH', '/optimization-businesses/10',
                body={'name': 'must not persist', 'profile': profile})
            assert_denied(response, code='ADVISOR_WRITE_FIELD_FORBIDDEN')
            assert response.json()['detail']['message'].startswith('品牌资料')
            assert await env.snapshot() == before
    asyncio.run(run())


def test_profile_patch_preserves_omitted_and_unwritable_fields(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            original = {'geo_scope': '原服务区域', 'internal_note': {'kept': True}, 'summary': '保留简介'}
            await mutate(env, GeoOptimizationBusiness, 10, profile=original)
            before = await env.snapshot()
            for patch in [BRAND_PROFILE, {'product_name': '再次保存', 'honors': '口号一；口号二\n口号三'}, {},
                          {'qualifications': [], 'cta': ''}]:
                response = await env.request('PATCH', '/optimization-businesses/10', body={'profile': patch})
                assert response.status_code == 200, response.text
            after = await env.snapshot()
            row = next(r for r in after['geo_optimization_businesses'] if r['id'] == 10)
            assert row['profile'] == {**original, **BRAND_PROFILE, 'product_name': '再次保存',
                'honors': ['口号一', '口号二', '口号三'], 'qualifications': [], 'cta': ''}
            for table in before:
                expected = copy.deepcopy(before[table])
                if table == 'geo_optimization_businesses':
                    expected_row = next(r for r in expected if r['id'] == 10)
                    expected_row.update(profile=row['profile'], updated_at=row['updated_at'])
                assert after[table] == expected, table
    asyncio.run(run())


@pytest.mark.parametrize('which', ['missing-query', 'identity-only', 'inactive-project',
    'unassigned', 'outside-project', 'patrol', 'period', 'service-plan', 'post-profile'])
def test_profile_keeps_scope_while_allowing_running_plans(tmp_path, monkeypatch, backend, which):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            if which == 'inactive-project':
                await mutate(env, GeoProject, 10, status='archived')
            elif which in {'unassigned', 'outside-project', 'service-plan'}:
                async with env.factory() as session:
                    settings = copy.deepcopy((await session.get(GeoProject, 10)).project_settings)
                if which == 'unassigned':
                    settings['geo_service_plan']['advisor_user_id'] = 2
                elif which == 'outside-project':
                    settings['geo_business_scope']['business_ids'] = []
                else:
                    settings['geo_service_plan']['enabled'] = True
                await mutate(env, GeoProject, 10, project_settings=settings)
            elif which == 'patrol':
                await mutate(env, GeoVisibilityPatrolSettings, 10, enabled=True)
            elif which == 'period':
                from datetime import datetime
                async with env.factory() as session:
                    session.add(GeoOptimizationPeriod(tenant_id=10, name='fixture period',
                        starts_at=datetime(2026, 1, 1), ends_at=datetime(2026, 12, 31), status='active'))
                    await session.commit()
            before = await env.snapshot()
            if which == 'missing-query':
                # Exercise an actually absent query, not tenant_id=null/empty.
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url='http://fixture') as client:
                    response = await client.patch('/api/v1/geo/optimization-businesses/10',
                        json={'profile': BRAND_PROFILE}, headers={'Authorization': 'Bearer ' + fixture_token()})
            else:
                response = await env.request(
                    'POST' if which == 'post-profile' else 'PATCH',
                    '/optimization-businesses' if which == 'post-profile' else '/optimization-businesses/10',
                    body={'tenant_id': 10, 'name': 'fixture new', 'profile': {}} if which == 'post-profile'
                         else {'profile': BRAND_PROFILE},
                    params={'project_id': 10} if which == 'post-profile' else {},
                    auth=fixture_token(native=True) if which == 'identity-only' else None)
            if which in {"patrol", "period", "service-plan"}:
                assert response.status_code == 200, response.text
                assert await env.snapshot() != before
            else:
                assert response.status_code in {403, 409}, response.text
                assert await env.snapshot() == before
    asyncio.run(run())


def test_profile_commit_rechecks_and_rolls_back(tmp_path, monkeypatch, backend):
    async def run():
        from app.security import advisor_write_commit as commit
        from app.security.advisor_scope import deny
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            checked = []
            original = commit.recheck_advisor_before_commit

            async def revoke_before_commit(session, ctx):
                await original(session, ctx)
                checked.append(True)
                deny(403, 'ADVISOR_ROLE_CHANGED', '顾问权限已变化')

            monkeypatch.setattr(commit, 'recheck_advisor_before_commit', revoke_before_commit)
            response = await env.request('PATCH', '/optimization-businesses/10', body={'profile': BRAND_PROFILE})
            assert_denied(response, code='ADVISOR_ROLE_CHANGED')
            assert checked == [True]
            assert await env.snapshot() == before
    asyncio.run(run())


def test_brand_editor_still_cannot_change_role_permissions(tmp_path, monkeypatch, backend):
    async def run():
        # Load the real roles router without app.api.__init__, which imports
        # the unrelated scheduler and its Unix-only fcntl dependency.
        import runpy
        from pathlib import Path
        router = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'app/api/roles.py'))['router']
        from app.models import Role
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            env.app.include_router(router)
            before = await env.snapshot()
            async with env.factory() as session:
                permissions = copy.deepcopy((await session.get(Role, 1)).permissions)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url='http://fixture') as client:
                response = await client.patch('/api/v1/roles/1', params={'tenant_id': 10},
                    json={'permissions': {'settings.accounts': 'edit'}},
                    headers={'Authorization': 'Bearer ' + fixture_token()})
            assert_denied(response, code='ADVISOR_HIGH_RISK_WRITES_DISABLED')
            async with env.factory() as session:
                assert (await session.get(Role, 1)).permissions == permissions
            assert await env.snapshot() == before
    asyncio.run(run())
