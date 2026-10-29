"""Executed only inside the isolated real-session fixture (no global DB/config)."""
import importlib.util
from types import SimpleNamespace
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.sem_phase0.store import ScopeDenied
from app.sem_phase1a.errors import ShadowError
from app.sem_phase1a.grant_management import AccountGrantService
from app.sem_phase1a.grant_router import create_grant_router
from app.sem_phase1a.production_principals import ProductionPrincipalAdapter


async def run_checks(factory, token):
    from app.database import get_session
    from app.models.role import Role
    from app.models.user import User
    from app.permissions import ALL_EDIT, CLIENT_PERMS
    from app.security.auth import AuthContext, require_admin
    spec = importlib.util.spec_from_file_location('slice4', 'migrations/versions/0078_sem_phase1a_grants.py')
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    async with factory() as session, session.begin():
        connection = await session.connection()
        def upgrade(db):
            with Operations.context(MigrationContext.configure(db)):
                migration.upgrade()
        await connection.run_sync(upgrade)
        session.add_all([Role(id=3, name='管理员', is_system=True, permissions=ALL_EDIT),
                         Role(id=4, name='合成平台管理员', is_system=False,
                              permissions={'settings.accounts':'edit','settings.customers':'edit'}),
                         User(id=9, username='synthetic-admin', password_hash='unused', role_id=3),
                         User(id=8, username='synthetic-platform-admin', password_hash='unused', role_id=4),
                         User(id=7, username='synthetic-other-customer', password_hash='unused', role_id=2, tenant_id=102)])
    service = AccountGrantService(factory.begin)
    app = FastAPI()
    app.include_router(create_grant_router(service))
    async def sessions():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    # Missing-login branch reads settings before returning 401. Supply only
    # in-memory fixture values; real configuration/.env remains forbidden.
    from app.security import auth
    auth.get_settings = lambda: SimpleNamespace(admin_api_key_query_enabled=False, admin_api_key='')
    from app.security import api_key
    api_key.get_settings = auth.get_settings
    route = next(r for r in app.routes if getattr(r, 'path', '').endswith('/accounts/{account_id}'))
    assert route.dependant.dependencies[0].call is require_admin
    root = '/api/v1/sem/phase1a/account-grants/accounts/204'
    admin = {'Authorization': 'Bearer ' + token(9, False)}
    platform = {'Authorization': 'Bearer ' + token(8, False)}
    body = {'tenant_id':101, 'user_id':1, 'advisor_grant_id':10}
    async def count():
        async with factory() as session:
            return (await session.execute(text('SELECT count(*) FROM sem_phase1a_grant_audit'))).scalar_one()
    async def sql(statement):
        async with factory() as session, session.begin():
            await session.execute(text(statement))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='https://testserver') as api:
        for path, method, data in ((root+'?tenant_id=101', 'GET', None), (root,'POST',body),
                                    (root+'/revoke','POST',body)):
            response = await api.request(method, path, json=data)
            assert response.status_code == 401
            for uid, advisor in ((1,True),(2,False),(7,False)):
                response = await api.request(method, path, json=data,
                    headers={'Authorization':'Bearer '+token(uid,advisor)})
                assert response.status_code == 403
        assert await count() == 0
        # The real API-key fallback passes require_admin, but cannot attribute
        # a grant audit to a user. Every management endpoint must still deny it.
        key_settings = SimpleNamespace(admin_api_key_query_enabled=False,
            admin_api_key='synthetic-management-api-key', admin_api_key_tenant_id=None)
        async with factory() as session:
            bindings_before = (await session.execute(text(
                'SELECT * FROM sem_phase1a_account_grants ORDER BY user_id,account_id'))).all()
        with patch.object(auth, 'get_settings', return_value=key_settings), \
             patch.object(api_key, 'get_settings', return_value=key_settings), \
             patch.object(service, '_admin', wraps=service._admin) as admin_check:
            for path, method, data in ((root+'?tenant_id=101', 'GET', None), (root, 'POST', body),
                                      (root+'/revoke', 'POST', {'tenant_id':101, 'user_id':1})):
                response = await api.request(method, path, json=data,
                    headers={'X-API-Key':key_settings.admin_api_key})
                assert response.status_code == 403
                assert response.json()['detail']['code'] == 'GRANT_ADMIN_REQUIRED'
                assert key_settings.admin_api_key not in response.text
            assert admin_check.await_count == 3
            for call in admin_check.await_args_list:
                key_ctx = call.args[1]
                assert key_ctx.is_superadmin and key_ctx.user_id is None
        assert await count() == 0
        async with factory() as session:
            assert (await session.execute(text(
                'SELECT * FROM sem_phase1a_account_grants ORDER BY user_id,account_id'))).all() == bindings_before
        response = await api.post(root, json=body, headers=admin)
        assert response.status_code == 200 and response.json()['changed']
        assert response.json()['grant']['generation'] == 1
        response = await api.post(root, json=body, headers=platform)
        assert response.status_code == 200 and not response.json()['changed'] and await count() == 1
        response = await api.get(root+'?tenant_id=101', headers=admin)
        assert len(response.json()) == 1 and response.json()[0]['advisor_grant_id'] == 10
        ctx = AuthContext(1, '', '合成顾问', 101, advisor_scope=__import__(
            'app.security.advisor_scope', fromlist=['AdvisorScope']).AdvisorScope(frozenset({101}),101,10),
            auth_exp=4102444800)
        async with factory() as session:
            assert (101,204) in (await ProductionPrincipalAdapter().resolve(ctx, session)).writable_accounts
        response = await api.post(root+'/revoke', json={'tenant_id':101,'user_id':1}, headers=platform)
        assert response.status_code == 200 and response.json()['changed']
        assert response.json()['grant']['generation'] == 1
        response = await api.post(root+'/revoke', json={'tenant_id':101,'user_id':1}, headers=admin)
        assert not response.json()['changed'] and await count() == 2
        async with factory() as session:
            assert (101,204) not in (await ProductionPrincipalAdapter().resolve(ctx, session)).readable_accounts
        response = await api.post(root, json=body, headers=admin)
        assert response.json()['grant']['generation'] == 2 and await count() == 3
        # Customer grants are read-only through the production adapter.
        response = await api.post(root, json={'tenant_id':101,'user_id':2}, headers=admin)
        assert response.status_code == 200
        customer = AuthContext(2,'','品牌方客户',101,permissions=CLIENT_PERMS,auth_exp=4102444800)
        async with factory() as session:
            who = await ProductionPrincipalAdapter().resolve(customer,session)
            assert (101,204) in who.readable_accounts and not who.writable_accounts
        for bad, code in (({'tenant_id':102,'user_id':1,'advisor_grant_id':10},'GRANT_ACCOUNT_SCOPE_INVALID'),
                          ({'tenant_id':101,'user_id':7},'GRANT_TARGET_TENANT_INVALID'),
                          ({'tenant_id':101,'user_id':9},'GRANT_TARGET_ROLE_INVALID'),
                          ({'tenant_id':101,'user_id':1,'advisor_grant_id':999},'GRANT_ADVISOR_GENERATION_INVALID')):
            response = await api.post(root,json=bad,headers=admin)
            assert response.status_code in (409,422) and response.json()['detail']['code'] == code
        for bad in ({**body,'user_id':'never-echo-untrusted'}, {**body,'extra':'never-echo-untrusted'}):
            response = await api.post(root,json=bad,headers=admin)
            assert response.status_code == 422 and 'never-echo' not in response.text
        response = await api.get(root+'?tenant_id=never-echo-untrusted',headers=admin)
        assert response.status_code == 422 and 'never-echo' not in response.text
        await sql("UPDATE roles SET permissions='{}' WHERE id=4")
        response = await api.post(root,json=body,headers=platform)
        assert response.status_code == 403
        # Direct service cannot trust a stale admin context either.
        stale = AuthContext(8,'','合成平台管理员',None,permissions=ALL_EDIT)
        try:
            await service.change(stale,101,204,1,10)
            raise AssertionError('stale administrator accepted')
        except ShadowError as exc:
            assert exc.code == 'GRANT_ADMIN_REQUIRED'
        await sql("UPDATE roles SET permissions='{}' WHERE id=1")
        response = await api.post(root,json=body,headers=admin)
        assert response.status_code == 422 and response.json()['detail']['code'] == 'GRANT_TARGET_ROLE_INVALID'
        await sql('UPDATE roles SET permissions=\'{"seo.site":"edit","seo.content":"edit"}\' WHERE id=1')
        await sql("UPDATE baidu_accounts SET status='archived' WHERE id=204")
        response = await api.post(root,json=body,headers=admin)
        assert response.json()['detail']['code'] == 'GRANT_ACCOUNT_INACTIVE'
        # Revocation remains possible for archived accounts or changed targets.
        assert (await api.post(root+'/revoke',json={'tenant_id':101,'user_id':1},headers=admin)).status_code == 200
        await sql("UPDATE baidu_accounts SET status='active' WHERE id=204")
        before = await count()
        # Fail the audit INSERT after binding UPDATE: the entire transaction rolls back.
        from sqlalchemy.ext.asyncio import AsyncSession
        original = AsyncSession.execute
        async def fail_audit(self, statement, *args, **kwargs):
            if str(statement).startswith('INSERT INTO sem_phase1a_grant_audit'):
                from sqlalchemy.exc import SQLAlchemyError
                raise SQLAlchemyError('never-echo-untrusted')
            return await original(self, statement, *args, **kwargs)
        with patch.object(AsyncSession,'execute',fail_audit):
            response = await api.post(root,json=body,headers=admin)
        assert response.status_code == 503 and 'never-echo' not in response.text
        assert await count() == before
        async with factory() as session:
            row = (await session.execute(text('SELECT generation,revoked_at FROM sem_phase1a_account_grants WHERE user_id=1 AND account_id=204'))).first()
            assert row[0] == 2 and row[1] is not None
            audits = (await session.execute(text('SELECT actor_id,user_id,tenant_id,account_id,advisor_grant_id,generation,action,occurred_at FROM sem_phase1a_grant_audit ORDER BY occurred_at'))).all()
            assert audits[0][:7] == (9,1,101,204,10,1,'grant')
            assert audits[1][:7] == (8,1,101,204,10,1,'revoke')
            assert all(a[-1] for a in audits)
        for path in app.openapi()['paths']:
            assert not any(part in path for part in ('execute','upload','enable','customer-confirm'))
    print('management real-session HTTP, idempotency, revocation and audit rollback checks passed')
