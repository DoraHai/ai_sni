"""Standalone local synthetic session verification; never imported by application."""
import asyncio
import builtins
import importlib.util
import json
import socket
import sys
import tempfile
import time
import types
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData, Table, Column, BigInteger, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB


def no_connection(*args, **kwargs):
    raise AssertionError('network forbidden')
socket.create_connection = no_connection
original_open = builtins.open
def checked_open(file, *args, **kwargs):
    if isinstance(file, (str, Path)) and Path(file).name == '.env':
        raise AssertionError('.env forbidden')
    return original_open(file, *args, **kwargs)
builtins.open = checked_open

class Base(DeclarativeBase):
    pass
async def unused_session():
    raise AssertionError('global DB forbidden')
    yield
stub = types.ModuleType('app.database')
stub.Base = Base
stub.get_session = unused_session
stub.async_session_factory = unused_session
sys.modules['app.database'] = stub
# Real config module may be imported for functions; constructing settings is forbidden.
import app.config
app.config.get_settings = lambda: (_ for _ in ()).throw(AssertionError('config forbidden'))
from app.security import auth
from app.security.auth import AuthContext, require_auth
from app.security.advisor_scope import AdvisorScope
from app.models import Tenant, BaiduAccount, TenantModule
from app.models.user import User
from app.models.role import Role
from app.models.advisor_tenant_grant import AdvisorTenantGrant
from app.sem_phase1a.production_principals import ProductionPrincipalAdapter, production_principal_dependency
from app.sem_phase0.store import ScopeDenied
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request
import jwt

@compiles(JSONB, 'sqlite')
def jsonb(type_, compiler, **kw):
    return 'JSON'

async def run(directory):
    engine = create_async_engine('sqlite+aiosqlite:///' + str(directory / 'auth.sqlite'))
    metadata = MetaData()
    Table('baidu_oauth_grants', metadata, Column('id', BigInteger, primary_key=True))
    models = (Role, Tenant, User, AdvisorTenantGrant, TenantModule, BaiduAccount)
    tables = [model.__table__.to_metadata(metadata) for model in models]
    async with engine.begin() as db:
        await db.run_sync(metadata.create_all)
        # Add only new migration to the disposable schema; never migrations/env.py.
        spec = importlib.util.spec_from_file_location('slice3', 'migrations/versions/0077_sem_phase1a_shadow.py')
        migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        def upgrade(connection):
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        await db.run_sync(upgrade)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add_all([Role(id=1, name='合成顾问', is_system=False,
                             permissions={'seo.site': 'edit', 'seo.content': 'edit'}),
                         Role(id=2, name='品牌方客户', is_system=True, permissions=__import__('app.permissions', fromlist=['CLIENT_PERMS']).CLIENT_PERMS),
                         Tenant(id=101, name='合成客户'), Tenant(id=102, name='合成其他客户'),
                         User(id=1, username='synthetic-advisor', password_hash='synthetic-unused', role_id=1, tenant_id=101),
                         User(id=2, username='synthetic-customer', password_hash='synthetic-unused', role_id=2, tenant_id=101),
                         TenantModule(id=1, tenant_id=101, module_code='sem', status='active'),
                         AdvisorTenantGrant(id=10, user_id=1, tenant_id=101, grant_source='admin', granted_by=1),
                         BaiduAccount(id=201, tenant_id=101, baidu_username='synthetic-a', baidu_ucid=201,
                             access_token_encrypted='synthetic-unused', expires_at=datetime(2099,1,1)),
                         BaiduAccount(id=204, tenant_id=101, baidu_username='synthetic-b', baidu_ucid=204,
                             access_token_encrypted='synthetic-unused', expires_at=datetime(2099,1,1))])
        await session.flush()
        await session.execute(text('INSERT INTO sem_phase1a_account_grants(user_id,tenant_id,account_id,advisor_grant_id) '
                                   'VALUES(1,101,201,10),(2,101,201,NULL)'))
    # Synthetic signing material is kept in memory and never logged.
    import secrets
    signing = secrets.token_hex(32)
    auth._jwt_secret = lambda: signing
    now = int(time.time())
    def token(uid, advisor=True, **changes):
        claims = {'sub': str(uid), 'exp': now+3600, 'iat': now}
        if advisor:
            claims.update(scope_kind='advisor_tenant', aud='advisor-business', tid=101, gid=10, auth_exp=now+3600)
        claims.update(changes)
        return jwt.encode(claims, signing, algorithm='HS256')
    async def context(session, encoded):
        # Real session route is explicitly allowed by the existing guard.
        request = Request({'type':'http','method':'GET','scheme':'https','server':('testserver',443),
                           'path':'/api/v1/auth/me','query_string':b'','headers':[]})
        return await require_auth(HTTPAuthorizationCredentials(scheme='Bearer', credentials=encoded),
                                  None, None, session, request)
    adapter = ProductionPrincipalAdapter()
    async with factory() as session:
        ctx = await context(session, token(1))
        who = await adapter.resolve(ctx, session)
        assert who.role == 'advisor' and who.writable_accounts == frozenset({(101,201)})
        customer_ctx = await context(session, token(2, False))
        who = await adapter.resolve(customer_ctx, session)
        assert who.role == 'customer' and not who.writable_accounts and who.readable_accounts == frozenset({(101,201)})
        ctx.role_name = 'forged'
        try:
            await adapter.resolve(ctx, session)
            raise AssertionError('DB/session role mismatch accepted')
        except ScopeDenied:
            pass
    async with factory() as session:
        ctx = await context(session, token(1))
        # Independently re-read live DB flags/permissions for each resolution.
        for sql in ["UPDATE users SET is_active=0 WHERE id=1",
                    "UPDATE roles SET permissions='{}' WHERE id=1",
                    "UPDATE tenant_modules SET status='suspended' WHERE tenant_id=101",
                    "UPDATE sem_phase1a_account_grants SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=1"]:
            await session.execute(text(sql))
            try:
                who = await adapter.resolve(ctx, session)
                assert not who.readable_accounts
            except (ScopeDenied, __import__('fastapi').HTTPException):
                pass
            await session.rollback()
        # Real require_auth still denies phase1a routes, including writes.
        from fastapi import HTTPException
        for method in ('GET', 'POST'):
            request = Request({'type':'http','method':method,'scheme':'https','server':('testserver',443),
                'path':'/api/v1/sem/phase1a/shadow/plans','query_string':b'','headers':[]})
            if method == 'POST':
                async def receive():
                    return {'type':'http.request','body':b'{}','more_body':False}
                request = Request(request.scope, receive)
            try:
                await require_auth(HTTPAuthorizationCredentials(scheme='Bearer', credentials=token(1)),
                    None, None, session, request)
                raise AssertionError('unmounted guard bypassed')
            except HTTPException as exc:
                assert exc.status_code == 403
        for encoded in (token(1, exp=now-1), jwt.encode({'sub':'1','exp':now+3600}, 'invalid-synthetic-key', algorithm='HS256')):
            try:
                await context(session, encoded)
                raise AssertionError('invalid JWT accepted')
            except HTTPException as exc:
                assert exc.status_code == 401
    async with factory() as session, session.begin():
        await session.execute(text("UPDATE advisor_tenant_grants SET revoked_at=CURRENT_TIMESTAMP,revoked_by=1,revoke_reason='synthetic' WHERE id=10"))
    async with factory() as session:
        try:
            await context(session, token(1))
            raise AssertionError('revoked JWT accepted')
        except Exception as exc:
            assert getattr(exc, 'status_code', 0) in (401,403)
    # Factory retains require_auth. Unknown phase1a paths remain denied by the
    # existing advisor guard; this slice never patches or bypasses that guard.
    dependency = production_principal_dependency()
    assert __import__('inspect').signature(dependency).parameters['ctx'].default.dependency is require_auth
    await engine.dispose()

with tempfile.TemporaryDirectory(prefix='sem-slice3-session-') as temp:
    asyncio.run(run(Path(temp)))
print('session bridge checks passed')
