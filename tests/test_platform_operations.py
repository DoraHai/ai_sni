"""Native ledger pagination, atomic account audit and incident concurrency."""
import asyncio
import csv
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import QueryParams

from app import platform_history as history, platform_operations as ops
from app.api import platform_console as console, users, roles
from app.api_controls import ControlConflict
from app.models import Role, User, Tenant
from app.security.auth import AuthContext, require_auth

ADMIN = AuthContext(7, 'test-admin', '管理员', None, {'settings.accounts': 'edit', 'settings.customers': 'edit'})


def native(monkeypatch, scenario):
    raw = os.getenv('PLATFORM_CONSOLE_TEST_DATABASE_URL') or os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL')
    if not raw:
        pytest.skip('Explicit local PostgreSQL test URL required')
    url = make_url(raw)
    assert url.host in {'localhost', '127.0.0.1'} and 'test' in url.database.lower()
    schema = 'platform_ops_' + uuid4().hex
    async def run():
        setup = create_async_engine(raw)
        db = create_async_engine(raw, connect_args={'server_settings': {'search_path': schema}})
        factory = async_sessionmaker(db, expire_on_commit=False)
        try:
            async with setup.begin() as c:
                await c.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with db.connect() as c:
                raw_c = await c.get_raw_connection()
                root = Path(__file__).parents[1]
                for script in ('api_metering_schema.sql', 'api_controls_schema.sql'):
                    await raw_c.driver_connection.execute((root / 'scripts' / script).read_text(encoding='utf-8'))
                await c.commit()
            async with db.begin() as c:
                for model in (Tenant, Role, User):
                    await c.run_sync(model.__table__.create)
            monkeypatch.setattr(console, 'async_session_factory', factory)
            await scenario(factory)
        finally:
            await db.dispose()
            async with setup.begin() as c:
                await c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await setup.dispose()
    asyncio.run(run())


def test_native_history_filters_stable_pagination_and_complete_csv(monkeypatch):
    async def scenario(factory):
        now = datetime.now(timezone.utc) - timedelta(minutes=1)
        async with factory() as session:
            for i in range(7):
                await session.execute(text('''INSERT INTO api_usage_events
                    (id,tenant_id,user_id,origin,module,operation,provider,model,endpoint,state,estimated_amount,currency,started_at)
                    VALUES(CAST(:id AS uuid),:tenant,:user,'background','seo','fixture','chinaz',:model,:endpoint,'succeeded',:amount,'CNY',:time)'''),
                    {'id': str(uuid4()), 'tenant': 1 if i < 6 else 2, 'user': None,
                     'model': '=DANGEROUS_FORMULA' if i == 0 else None,
                     'endpoint': 'https://user:NEVER_EXPORT@openapi.chinaz.net/v1/index?key=NEVER_EXPORT',
                     'amount': None if i == 0 else '0.01', 'time': now})
            await session.commit()
        query = QueryParams('tenant_id=1&user_id=0&module=seo&page_size=2')
        seen = []
        async with factory() as session:
            first = await history.read_history(session, history.parse_query(query))
            assert first['total'] == 6 and first['unpriced'] == 1
            assert first['estimated_amount'] is None and first['known_amount'] == '0.050000000000'
            seen += [r['id'] for r in first['rows']]
            cursor = first['next_cursor']
        # A new insertion after page one must not enter its continuation.
        async with factory() as session:
            await session.execute(text("INSERT INTO api_usage_events(id,tenant_id,origin,module,operation,provider,endpoint,state,started_at) VALUES(CAST(:id AS uuid),1,'background','seo','fixture','chinaz','openapi.chinaz.net/v1/index','requested',:started)"),
                {'id': str(uuid4()), 'started': datetime.fromisoformat(first['as_of']) + timedelta(microseconds=1)})
            await session.commit()
        while cursor:
            async with factory() as session:
                page = await history.read_history(session, history.parse_query(QueryParams(str(query) + '&cursor=' + cursor)))
            assert page['total'] == 6
            seen += [r['id'] for r in page['rows']]
            cursor = page['next_cursor']
        assert len(seen) == len(set(seen)) == 6
        with pytest.raises(ValueError):
            history.parse_query(QueryParams('tenant_id=2&cursor=' + first['next_cursor']))
        async with factory() as session:
            result = await history.read_history(session, history.parse_query(QueryParams('tenant_id=1&unpriced=false')), export=True)
            assert result['total'] == len(result['rows']) == 5
            all_rows = await history.read_history(session, history.parse_query(QueryParams('tenant_id=1')), export=True)
            output = history.export_csv(all_rows['rows']).decode('utf-8-sig')
            assert 'NEVER_EXPORT' not in output
            csv_rows = list(csv.DictReader(io.StringIO(output)))
            assert len(csv_rows) == 7
            formula = next(r for r in csv_rows if 'DANGEROUS_FORMULA' in r['model'])
            assert formula['model'] == "'=DANGEROUS_FORMULA" and formula['estimated_amount'] == ''
        # Exercise the actual HTTP transaction and download boundary as well.
        from httpx import ASGITransport, AsyncClient
        app = FastAPI()
        app.include_router(console.router)
        app.dependency_overrides[require_auth] = lambda: ADMIN
        original = console.read_history
        async def readonly(session, spec, **kwargs):
            assert await session.scalar(text('SHOW transaction_read_only')) == 'on'
            return await original(session, spec, **kwargs)
        monkeypatch.setattr(console, 'read_history', readonly)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/api/v1/admin/console/usage?tenant_id=1&page_size=2')
            assert response.status_code == 200 and len(response.json()['rows']) == 2
            assert response.headers['cache-control'] == 'no-store, private'
            response = await client.get('/api/v1/admin/console/usage/export?tenant_id=1')
            assert response.status_code == 200 and 'text/csv' in response.headers['content-type']
            assert response.headers['content-disposition'].startswith('attachment;')
            assert 'NEVER_EXPORT' not in response.text
        async with factory() as session:
            monkeypatch.setattr(history, 'EXPORT_LIMIT', 2)
            with pytest.raises(ValueError, match='不会截断'):
                await history.read_history(session, history.parse_query(QueryParams('tenant_id=1')), export=True)
    native(monkeypatch, scenario)


@pytest.mark.parametrize('raw', ['from=2026-02-30', 'tenant_id=-1', 'tenant_id=1&tenant_id=2', 'page_size=201',
                               'state=wrong', 'module=platform', 'unpriced=maybe', 'cursor=invalid', 'api_key=PRIVATE'])
def test_bad_history_queries_are_rejected(raw):
    with pytest.raises(Exception):
        history.parse_query(QueryParams(raw))


def test_history_export_and_operations_share_strict_console_auth(monkeypatch):
    app = FastAPI()
    app.include_router(console.router)
    with TestClient(app) as client:
        for path in ('/usage', '/usage/export'):
            assert client.get('/api/v1/admin/console' + path).status_code == 401
        assert client.post('/api/v1/admin/console/operations', json={}).status_code == 401
        app.dependency_overrides[require_auth] = lambda: AuthContext(8, 'customer', '客户', 1, ADMIN.permissions)
        for path in ('/usage', '/usage/export'):
            assert client.get('/api/v1/admin/console' + path).status_code == 403
        assert client.post('/api/v1/admin/console/operations', json={}).status_code == 403
        app.dependency_overrides[require_auth] = lambda: ADMIN
        monkeypatch.delenv('API_CONTROLS_ENABLED', raising=False)
        assert client.post('/api/v1/admin/console/operations', json={}).status_code == 503
        response = client.get('/api/v1/admin/console/usage?cursor=PRIVATE-INVALID')
        assert response.status_code == 422 and 'PRIVATE-INVALID' not in response.text


def test_native_incident_replay_conflicts_recurrence_and_supplier_unknowns(monkeypatch):
    monkeypatch.setenv('API_CONTROLS_ENABLED', 'true')
    async def scenario(factory):
        alert = ops.alert_identity({'kind': 'test'}, 'test-source', 'first-failure')
        def request(action, revision, signal=None):
            return {'request_id': str(uuid4()), 'kind': 'alert', 'key': alert['id'], 'expected_revision': revision,
                    'value': {'action': action, 'note': 'checked' if action == 'resolve' else '', 'signal': signal or alert['signal']}}
        first = request('claim', 0)
        async with factory() as session:
            assert (await ops.mutate_operation(session, 7, first, [alert]))['revision'] == 1
            assert (await ops.mutate_operation(session, 7, first, [alert]))['replayed']
        async with factory() as session:
            with pytest.raises(ControlConflict):
                await ops.mutate_operation(session, 8, first, [alert])
        async def write(data):
            async with factory() as session:
                return await ops.mutate_operation(session, 7, data, [alert])
        results = await asyncio.gather(write(request('resolve', 1)), write(request('resolve', 1)), return_exceptions=True)
        assert sum(isinstance(r, ControlConflict) for r in results) == 1
        async with factory() as session:
            # Ordering uses the record version even if timestamps go backwards.
            await session.execute(text("UPDATE api_control_audit SET created_at=created_at - INTERVAL '1 hour' WHERE after_value->>'revision'='2'"))
            await session.commit()
            await ops.attach_alert_states(session, [alert])
            assert alert['handling']['status'] == 'resolved'
            new_alert = ops.alert_identity({'kind': 'test'}, 'test-source', 'new-failure')
            await ops.attach_alert_states(session, [new_alert])
            assert new_alert['handling']['status'] == 'open' and new_alert['handling']['revision'] == 2
            with pytest.raises(ControlConflict):
                await ops.mutate_operation(session, 7, request('resolve', 2), [new_alert])
        async with factory() as session:
            await session.execute(text("INSERT INTO api_control_bindings(id,module,label,host,configured,can_rotate) VALUES('fixture','seo','fixture','provider.test',false,false)"))
            await session.commit()
            value = {'balance': None, 'currency': 'USD', 'remaining_calls': 0, 'expires_on': None,
                     'warning_balance': None, 'warning_calls': 10}
            payload = {'request_id': str(uuid4()), 'kind': 'supplier', 'key': 'provider.test', 'expected_revision': 0, 'value': value}
            await ops.mutate_operation(session, 7, payload, [])
            supplier = (await ops.read_suppliers(session))[0]
            assert supplier['balance'] is None and supplier['remaining_calls'] == 0 and supplier['source'] == 'manual'
            assert supplier['currency'] == 'USD'
    native(monkeypatch, scenario)


def test_native_account_and_role_mutations_are_atomic_and_never_audit_passwords(monkeypatch):
    monkeypatch.setenv('API_CONTROLS_ENABLED', 'true')
    async def scenario(factory):
        async with factory() as session:
            created_role = await roles.create_role(roles.RoleRequest(name='fixture-role', permissions={'seo.content': 'view'}), session, ADMIN)
            created_user = await users.create_user(users.CreateUserRequest(username='fixture-user', password='PRIVATE-PASSWORD', role_id=created_role['id']), session, ADMIN)
            await users.update_user(created_user['id'], users.UpdateUserRequest(is_active=False, new_password='OTHER-PRIVATE-PASSWORD'), session, ADMIN)
            await users.reset_user_password(created_user['id'], users.ResetPasswordRequest(new_password='RESET-PRIVATE-PASSWORD'), session, ADMIN)
            await roles.update_role(created_role['id'], roles.UpdateRoleRequest(permissions={'seo.content': 'edit'}), session, ADMIN)
            audits = (await session.execute(text('SELECT action,before_value,after_value FROM api_control_audit'))).mappings().all()
            assert {r['action'] for r in audits} == {'role.create', 'user.create', 'user.update', 'user.password', 'role.update'}
            assert 'PRIVATE-PASSWORD' not in str(audits) and 'password_hash' not in str(audits)
            changed = next(r for r in audits if r['action'] == 'user.update')
            assert changed['before_value']['is_active'] and not changed['after_value']['is_active']
            assert changed['after_value']['password_changed'] is True
            changed_role = next(r for r in audits if r['action'] == 'role.update')
            assert changed_role['before_value']['permissions']['seo.content'] == 'view'
            assert changed_role['after_value']['permissions']['seo.content'] == 'edit'
            await session.execute(text('DROP TABLE api_control_audit'))
            await session.commit()
            with pytest.raises(HTTPException) as error:
                await users.update_user(created_user['id'], users.UpdateUserRequest(is_active=True), session, ADMIN)
            assert error.value.status_code == 503
            session.expire_all()
            assert (await session.get(User, created_user['id'])).is_active is False
            assert (await session.get(Role, created_role['id'])).permissions['seo.content'] == 'edit'
    native(monkeypatch, scenario)


def test_backup_metadata_does_not_claim_restore_and_rejects_private_projection(tmp_path):
    report = tmp_path / 'status.json'
    assert ops.read_backup_status(report)['state'] == 'unavailable'
    record = {'id': str(uuid4()), 'completed_at': datetime.now(timezone.utc).isoformat(), 'scope': 'public_schema',
              'state': 'succeeded', 'bytes': 100, 'archive_verified': True, 'restore_verified': False}
    report.write_text(json.dumps({'schema': 1, 'records': [record]}), encoding='utf-8')
    result = ops.read_backup_status(report)
    assert result['state'] == 'available' and not result['records'][0]['restore_verified']
    record['path'] = '/private/archive'
    report.write_text(json.dumps({'schema': 1, 'records': [record]}), encoding='utf-8')
    result = ops.read_backup_status(report)
    assert result['state'] == 'invalid' and '/private' not in str(result)


def test_backup_operator_captures_failure_without_credentials_or_false_success(monkeypatch, tmp_path, capsys):
    from scripts import platform_database_backup as operator
    import subprocess
    env = tmp_path / 'private.env'
    env.write_text('DATABASE_URL=postgresql://test:PRIVATE-DATABASE-PASSWORD@127.0.0.1/test\n', encoding='utf-8')
    def fail(command, **kwargs):
        assert 'PRIVATE-DATABASE-PASSWORD' not in ' '.join(command)
        assert kwargs['env']['PGPASSWORD'] == 'PRIVATE-DATABASE-PASSWORD'
        raise subprocess.CalledProcessError(1, command, stderr=b'PRIVATE-DATABASE-PASSWORD internal failure')
    monkeypatch.setattr(operator.subprocess, 'run', fail)
    report = tmp_path / 'status.json'
    assert operator.backup(env, tmp_path / 'archives', report) == 1
    captured = capsys.readouterr()
    assert 'PRIVATE-DATABASE-PASSWORD' not in captured.out + captured.err
    record = ops.read_backup_status(report)['records'][0]
    assert record['state'] == 'failed' and not record['archive_verified'] and not record['restore_verified']
