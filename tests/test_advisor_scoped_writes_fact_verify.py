"""Mounted fact verification with synthetic auth and disposable local fixtures."""
import asyncio
import copy
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import update

from app.models import GeoFact, GeoOptimizationPeriod, GeoProject, GeoVisibilityPatrolSettings, Role, User
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from test_advisor_scoped_writes import (
    assert_denied, backend, fixture_token, mutate,
    no_external_http_or_background_dispatch, write_sandbox,
)


BODY = {
    'excerpt': 'synthetic evidence statement',
    'excerpt_locator': 'fixture source paragraph',
    'source_url': 'https://source.example.test/evidence',
    'expected_source_name': 'fixture source',
    'expected_source_statement': 'synthetic evidence statement',
}
PATH = '/facts/10/verify'


def test_advisor_verification_records_real_reviewer_and_preserves_other_decisions(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            meta = {'public_use': {'allowed': True, 'authorized_by': 2},
                    'verified_translations': [{'text': 'existing human translation', 'verified_by': 2}],
                    'unrelated': 'keep'}
            await mutate(env, GeoFact, 10, meta=meta, source_url=BODY['source_url'])
            before = await env.snapshot()
            response = await env.request('POST', PATH, body=BODY)
            assert response.status_code == 200, response.text
            after = await env.snapshot()
            fact = next(r for r in after['geo_facts'] if r['id'] == 10)
            assert fact['trust_level'] == 'verified'
            record = fact['meta']['verification']
            assert record['verified_by'] == fact['meta']['verified_by'] == 1
            assert datetime.fromisoformat(record['verified_at'])
            assert record['source_url'] == BODY['source_url']
            assert record['excerpt'] == BODY['excerpt']
            for key, value in meta.items():
                assert fact['meta'][key] == value
            old = next(r for r in before['geo_facts'] if r['id'] == 10)
            for key in old.keys() - {'trust_level', 'meta', 'updated_at'}:
                assert fact[key] == old[key]
            for table in before.keys() - {'geo_facts'}:
                assert after[table] == before[table], table
    asyncio.run(run())


@pytest.mark.parametrize('change', [
    {'public_use_allowed': True}, {'public_use_allowed': False}, {'public_use_allowed': None},
    {'verified_translation': None}, {'verified_translation': 'some translation'},
    {'verified_translations': []}, {'verification': {}}, {'meta': {}},
    {'trust_level': 'verified'}, {'trust_level': 'draft'}, {'status': 'active'},
    {'verified': True}, {'business_id': 10}, {'project_id': 10},
    {'verified_by': 2}, {'verified_at': '2026-01-01'}, {'use_llm': False}, {'other': None},
])
def test_extra_verification_fields_are_rejected_even_false_or_null(tmp_path, monkeypatch, backend, change):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            assert_denied(await env.request('POST', PATH, body={**BODY, **change}),
                          code='ADVISOR_WRITE_FIELD_FORBIDDEN')
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('key', ['source_url', 'expected_source_name'])
@pytest.mark.parametrize('value', ['missing', None, '', '   ', [], {}])
def test_explicit_nonempty_source_is_required(tmp_path, monkeypatch, backend, key, value):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            # Stored sources do not make an empty submission acceptable.
            await mutate(env, GeoFact, 10, source_url=BODY['source_url'])
            body = {**BODY, key: value}
            if value == 'missing':
                body.pop(key)
            before = await env.snapshot()
            assert_denied(await env.request('POST', PATH, body=body), code='ADVISOR_WRITE_FIELD_FORBIDDEN')
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('case,status', [
    ('disabled', 403), ('identity-only', 409), ('ungranted', 403), ('other-selected', 403),
    ('no-query', 403), ('other-fact', 403), ('unscoped', 403), ('other-advisor', 403),
    ('inactive-project', 403), ('patrol', 403), ('plan', 403), ('period', 403),
    ('stale-source', 409), ('empty-stored-source', 400),
])
def test_scope_assignment_sources_and_execution_chain_fail_closed(tmp_path, monkeypatch, backend, case, status):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend, enabled=case != 'disabled') as env:
            body, params, auth, path = dict(BODY), {}, None, PATH
            if case == 'identity-only':
                auth = fixture_token(scope_kind='advisor_identity', aud='advisor-session')
            elif case == 'ungranted':
                params = {'tenant_id': 30}
            elif case == 'other-selected':
                params = {'tenant_id': 20}
            elif case == 'other-fact':
                path = '/facts/20/verify'
            elif case == 'unscoped':
                await mutate(env, GeoFact, 10, business_id=None)
            elif case == 'empty-stored-source':
                await mutate(env, GeoFact, 10, source_name='')
            elif case in {'other-advisor', 'inactive-project', 'plan'}:
                async with env.factory() as session:
                    project = await session.get(GeoProject, 10)
                    settings = copy.deepcopy(project.project_settings)
                if case == 'other-advisor':
                    settings['geo_service_plan']['advisor_user_id'] = 2
                if case == 'plan':
                    settings['geo_service_plan']['enabled'] = True
                await mutate(env, GeoProject, 10, project_settings=settings,
                             status='paused' if case == 'inactive-project' else 'active')
            elif case == 'patrol':
                await mutate(env, GeoVisibilityPatrolSettings, 10, enabled=True)
            elif case == 'period':
                async with env.factory() as session:
                    session.add(GeoOptimizationPeriod(tenant_id=10, name='fixture period', status='active',
                        starts_at=datetime(2026, 1, 1), ends_at=datetime(2027, 1, 1)))
                    await session.commit()
            elif case == 'stale-source':
                body['expected_source_name'] = 'old source name'
            before = await env.snapshot()
            if case == 'no-query':
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url='http://fixture') as client:
                    response = await client.post('/api/v1/geo' + PATH, json=body,
                        headers={'Authorization': 'Bearer ' + fixture_token()})
            else:
                response = await env.request('POST', path, body=body, params=params, auth=auth)
            assert_denied(response, status=status)
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('change', ['assignment', 'inactive-project', 'business', 'grant', 'permissions', 'user', 'switch'])
def test_actual_verify_commit_rechecks_and_rolls_back(tmp_path, monkeypatch, backend, change):
    import app.security.advisor_write_commit as commit
    from app.config import get_settings

    original = commit.recheck_advisor_before_commit

    async def changed_before_commit(session, ctx):
        if change == 'assignment':
            project = await session.get(GeoProject, 10)
            settings = copy.deepcopy(project.project_settings)
            settings['geo_service_plan']['advisor_user_id'] = 2
            await session.execute(update(GeoProject).where(GeoProject.id == 10).values(project_settings=settings))
        elif change == 'inactive-project':
            await session.execute(update(GeoProject).where(GeoProject.id == 10).values(status='paused'))
        elif change == 'business':
            await session.execute(update(GeoFact).where(GeoFact.id == 10).values(business_id=None))
        elif change == 'grant':
            await session.execute(update(Grant).where(Grant.id == 101).values(
                revoked_at=datetime.now(timezone.utc), revoked_by=2, revoke_reason='fixture revoke'))
        elif change == 'permissions':
            await session.execute(update(Role).where(Role.id == 1).values(permissions={'geo.content': 'view'}))
        elif change == 'user':
            await session.execute(update(User).where(User.id == 1).values(is_active=False))
        else:
            monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', False)
        await original(session, ctx)

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            monkeypatch.setattr(commit, 'recheck_advisor_before_commit', changed_before_commit)
            before = await env.snapshot()
            response = await env.request('POST', PATH, body=BODY)
            assert response.status_code in {401, 403}, response.text
            assert await env.snapshot() == before
    asyncio.run(run())
