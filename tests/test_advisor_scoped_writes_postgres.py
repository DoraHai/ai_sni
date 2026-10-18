"""PostgreSQL commit-time revocation, not merely response-delivery rejection.

Uses the same validated GEO_TEST_POSTGRES_URL/disposable-schema fixture as the
HTTP matrix. The writer and revoker always use different actual connections.
All waits are bounded; no production schema or existing test service is used.
"""
import asyncio
import importlib
import copy
import os
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, update

from app.models import GeoFact, GeoProject, Role, User
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from test_advisor_scoped_writes import (CASES, EDIT, assert_denied, fixture_token,
    concrete, mutate, no_external_http_or_background_dispatch, write_sandbox)
from test_advisor_scoped_writes_contract import context, request_for

pytestmark = pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'),
                                reason='requires explicitly configured isolated PostgreSQL')


def bind_writer(commit, writer):
    from app.security.advisor_write_routes import WRITE_ROUTES
    ctx = context()
    rule = WRITE_ROUTES[('PATCH', '/api/v1/geo/facts/{fact_id}')]
    request = request_for('PATCH', '/facts/{fact_id}', path_params={'fact_id': 10})
    commit.bind_advisor_write_commit(writer, ctx, request, {'title': 'manual change'}, rule,
        {'exp': int(datetime.now(timezone.utc).timestamp()) + 600})
    return ctx


async def revoke(env, kind):
    if kind == 'grant':
        await mutate(env, Grant, 101, revoked_at=datetime.now(timezone.utc), revoked_by=2,
                     revoke_reason='fixture_revocation')
    elif kind == 'permissions':
        await mutate(env, Role, 1, permissions={'geo.assets': 'edit', 'geo.content': 'view'})
    elif kind == 'user':
        await mutate(env, User, 1, is_active=False)
    elif kind == 'assignment':
        async with env.factory() as session:
            project = await session.get(GeoProject, 10)
            settings = copy.deepcopy(project.project_settings)
        settings['geo_service_plan']['advisor_user_id'] = 2
        await mutate(env, GeoProject, 10, project_settings=settings)


@pytest.mark.parametrize('kind', ['grant', 'permissions', 'user'])
def test_commit_recheck_reloads_stale_identity_and_rolls_back_pending_business_change(tmp_path, monkeypatch, kind):
    commit = importlib.import_module('app.security.advisor_write_commit')

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend='postgres') as env:
            before = await env.snapshot()
            async with env.factory() as writer:
                # Warm the actual identity map before revocation. A cached get()
                # must not turn a revoked grant or edit downgrade into success.
                stale_identity = [await writer.get(model, ident)
                    for model, ident in ((Grant, 101), (Role, 1), (User, 1))]
                assert all(row is not None for row in stale_identity)
                fact = await writer.get(GeoFact, 10)
                fact.title = 'must roll back before commit'
                await writer.flush()
                writer_pid = await writer.scalar(text('SELECT pg_backend_pid()'))
                async with env.factory() as independent:
                    assert await independent.scalar(text('SELECT pg_backend_pid()')) != writer_pid
                await asyncio.wait_for(revoke(env, kind), 5)
                with pytest.raises(HTTPException) as denied:
                    await commit.recheck_advisor_before_commit(writer, bind_writer(commit, writer))
                    await writer.commit()
                assert denied.value.status_code in {401, 403}
                if kind == 'grant':
                    assert denied.value.detail['code'] == 'ADVISOR_GRANT_REVOKED'
                await writer.rollback()
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['grant', 'permissions', 'user', 'assignment'])
@pytest.mark.parametrize('production_dependency', [False, True], ids=['fixture-cleanup', 'production-session-cleanup'])
@pytest.mark.parametrize('case', [CASES[0], CASES[-1]], ids=['fact', 'brand-profile'])
def test_real_http_revoke_after_guard_before_handler_commit_never_persists(tmp_path, monkeypatch, kind, production_dependency, case):
    importlib.import_module('app.security.advisor_write_commit')
    from app.security import geo_advisor

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend='postgres') as env:
            if production_dependency:
                from app.database import get_session
                del env.app.dependency_overrides[get_session]
            checked, release = asyncio.Event(), asyncio.Event()
            writer_pid = None
            original = geo_advisor.guard_request

            async def gate(session, ctx, request, claims):
                nonlocal writer_pid
                await original(session, ctx, request, claims)
                # The real guard must have admitted the scoped write first.
                assert getattr(request.state, 'advisor_scoped_write', None) is not None
                writer_pid = await session.scalar(text('SELECT pg_backend_pid()'))
                checked.set()
                await asyncio.wait_for(release.wait(), 10)

            monkeypatch.setattr(geo_advisor, 'guard_request', gate)
            before = await env.snapshot()
            method, template, body, table, column, value = case
            writer = asyncio.create_task(env.request(method, concrete(template), body=body))
            waiter = asyncio.create_task(checked.wait())
            revoker = None
            try:
                finished, _ = await asyncio.wait({writer, waiter}, timeout=10,
                                                 return_when=asyncio.FIRST_COMPLETED)
                if writer in finished:
                    response = await writer
                    pytest.fail('write did not reach the admitted guard: ' + response.text)
                assert waiter in finished, 'guard barrier not reached'
                # Revocation COMMIT must precede handler execution, not just the
                # response middleware's final view check.
                revoker = asyncio.create_task(revoke(env, kind))
                # A secure implementation may already hold authorization locks
                # in the guard. Accept that valid ordering only after PostgreSQL
                # proves the revoker is blocked by this exact writer connection.
                blocked = False
                async with env.factory() as observer:
                    for _ in range(100):
                        if revoker.done():
                            await revoker
                            break
                        blocked = bool(await observer.scalar(text(
                            'SELECT EXISTS (SELECT 1 FROM pg_stat_activity '
                            'WHERE :writer = ANY(pg_blocking_pids(pid)))'), {'writer': writer_pid}))
                        if blocked:
                            break
                        await asyncio.sleep(0.02)
                if blocked:
                    release.set()
                    response = await asyncio.wait_for(writer, 10)
                    # Delivery recheck can reject a legitimately committed write
                    # if revocation wins immediately after that business commit.
                    assert response.status_code in {200, 201, 401, 403}, response.text
                    await asyncio.wait_for(revoker, 5)
                    assert any(row[column] == value for row in (await env.snapshot())[table])
                    after_revoke = await env.snapshot()
                    rejected = await env.request(method, concrete(template), body=body)
                    assert rejected.status_code in {401, 403}, rejected.text
                    assert await env.snapshot() == after_revoke
                else:
                    await asyncio.wait_for(revoker, 5)
                    after_revoke = await env.snapshot()
                    release.set()
                    response = await asyncio.wait_for(writer, 10)
                    assert response.status_code in {401, 403}, response.text
                    if kind == 'grant':
                        assert_denied(response, status=401, code='ADVISOR_GRANT_REVOKED')
                    assert await env.snapshot() == after_revoke
                    assert (await env.snapshot())['geo_facts'] == before['geo_facts']
                    assert (await env.snapshot())['geo_optimization_businesses'] == before['geo_optimization_businesses']
            finally:
                release.set()
                tasks = [writer, waiter, *([revoker] if revoker is not None else [])]
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(run())


def test_regrant_does_not_revive_old_generation_write(tmp_path, monkeypatch):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend='postgres') as env:
            await revoke(env, 'grant')
            async with env.factory() as session:
                session.add(Grant(id=103, user_id=1, tenant_id=10, grant_source='admin', granted_by=2))
                await session.commit()
            before = await env.snapshot()
            assert_denied(await env.request('POST', '/facts', body=CASES[0][2]),
                          status=401, code='ADVISOR_GRANT_REVOKED')
            assert await env.snapshot() == before
            accepted = await env.request('POST', '/facts', body=CASES[0][2], auth=fixture_token(gid=103))
            assert accepted.status_code in {200, 201}, accepted.text
            assert len((await env.snapshot())['geo_facts']) == len(before['geo_facts']) + 1
    asyncio.run(run())


@pytest.mark.parametrize('model,ident,values', [
    (Grant, 101, {'revoked_at': None}),  # Values filled with a fresh timestamp below.
    (Role, 1, {'permissions': {'geo.assets': 'edit', 'geo.content': 'view'}}),
    (User, 1, {'is_active': False}),
], ids=['grant-lock', 'role-lock', 'user-lock'])
def test_recheck_holds_identity_locks_through_business_commit(tmp_path, monkeypatch, model, ident, values):
    commit = importlib.import_module('app.security.advisor_write_commit')

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend='postgres') as env:
            started = asyncio.Event()
            pids = {}
            changes = copy.deepcopy(values)
            if model is Grant:
                changes.update(revoked_at=datetime.now(timezone.utc), revoked_by=2,
                               revoke_reason='fixture_revocation')

            async def competing_revocation():
                async with env.factory() as session:
                    pids['revoker'] = await session.scalar(text('SELECT pg_backend_pid()'))
                    started.set()
                    await session.execute(update(model).where(model.id == ident).values(**changes))
                    await session.commit()

            async with env.factory() as writer:
                fact = await writer.get(GeoFact, 10)
                fact.title = 'authorized before revocation'
                await writer.flush()
                pids['writer'] = await writer.scalar(text('SELECT pg_backend_pid()'))
                await commit.recheck_advisor_before_commit(writer, bind_writer(commit, writer))
                revoker = asyncio.create_task(competing_revocation())
                try:
                    await asyncio.wait_for(started.wait(), 5)
                    blocked = False
                    async with env.factory() as observer:
                        for _ in range(100):
                            blockers = await observer.scalar(text('SELECT pg_blocking_pids(:pid)'),
                                                             {'pid': pids['revoker']})
                            if pids['writer'] in blockers:
                                blocked = True
                                break
                            if revoker.done():
                                await revoker
                                break
                            await asyncio.sleep(0.02)
                    assert blocked, 'recheck must lock this identity row until the business commit'
                    await writer.commit()
                    await asyncio.wait_for(revoker, 5)
                finally:
                    await writer.rollback()
                    if not revoker.done():
                        revoker.cancel()
                    await asyncio.gather(revoker, return_exceptions=True)
            async with env.factory() as session:
                assert (await session.get(GeoFact, 10)).title == 'authorized before revocation'
            before = await env.snapshot()
            response = await env.request('POST', '/facts', body=CASES[0][2])
            assert response.status_code in {401, 403}, response.text
            assert await env.snapshot() == before
    asyncio.run(run())
