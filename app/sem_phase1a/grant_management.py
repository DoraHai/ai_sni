"""Account-grant management; explicit session transaction factory only.

No engine, URL, config, production wiring or new role definitions. Every service
entry rechecks the existing platform-admin policy against locked database rows.
"""
from datetime import date, datetime, timezone
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.sem_phase1a.errors import ShadowError


class GrantError(ShadowError):
    def __init__(self, code, status=422):
        super().__init__(code, '账户授权检查未通过')
        self.status = status


class AccountGrantService:
    def __init__(self, transaction_factory):
        # e.g. explicitly supplied async_sessionmaker.begin; owns commit/rollback.
        self.transaction_factory = transaction_factory

    @asynccontextmanager
    async def _transaction(self):
        async with self.transaction_factory() as db:
            if db.bind.dialect.name == 'sqlite':
                await db.execute(text('BEGIN IMMEDIATE'))
            yield db

    async def _row(self, db, sql, params, *, lock=True):
        if lock and db.bind.dialect.name == 'postgresql':
            sql += ' FOR UPDATE'
        return (await db.execute(text(sql), params)).mappings().first()

    async def _user(self, db, uid):
        row = await self._row(db, 'SELECT id,is_active,locked_until,tenant_id,role_id FROM users WHERE id=:id', {'id': uid})
        if row is None or not row['is_active']:
            raise GrantError('GRANT_IDENTITY_UNAVAILABLE', 403)
        from app.security.advisor_scope import account_locked
        until = row['locked_until']
        if isinstance(until, str):
            until = datetime.fromisoformat(until)
        if account_locked(SimpleNamespace(locked_until=until)):
            raise GrantError('GRANT_IDENTITY_UNAVAILABLE', 403)
        role = await self._row(db, 'SELECT name,is_system,permissions FROM roles WHERE id=:id', {'id': row['role_id']})
        if role is None:
            raise GrantError('GRANT_ROLE_INVALID', 403)
        raw = role['permissions']
        perms = json.loads(raw) if isinstance(raw, str) else raw
        return row, SimpleNamespace(name=role['name'], is_system=role['is_system'], permissions=perms)

    async def _admin(self, db, ctx):
        from app.security.auth import AuthContext, require_admin
        from app.permissions import effective_role_permissions
        # A real user is required for attributable audit; anonymous API-key
        # superadmin fallback cannot create account grants.
        if (type(ctx.user_id) is not int or ctx.is_superadmin or ctx.advisor_scope is not None
                or ctx.tenant_id is not None):
            raise GrantError('GRANT_ADMIN_REQUIRED', 403)
        user, role = await self._user(db, ctx.user_id)
        if role.name != ctx.role_name:
            raise GrantError('GRANT_ADMIN_REQUIRED', 403)
        current = AuthContext(ctx.user_id, '', role.name, user['tenant_id'],
            permissions=effective_role_permissions(role.name, role.is_system, role.permissions))
        try:
            await require_admin(current)
        except HTTPException:
            raise GrantError('GRANT_ADMIN_REQUIRED', 403) from None

    async def _account(self, db, tenant_id, account_id, *, active):
        tenant = await self._row(db, 'SELECT id FROM tenants WHERE id=:id', {'id': tenant_id})
        account = await self._row(db, 'SELECT id,tenant_id,status FROM baidu_accounts WHERE id=:id', {'id': account_id})
        if tenant is None or account is None or account['tenant_id'] != tenant_id:
            raise GrantError('GRANT_ACCOUNT_SCOPE_INVALID', 403)
        from app.module_scope import module_is_available
        # Use the existing SEM availability policy, with the module row locked
        # in this same transaction. Administrators cannot bypass a suspension;
        # listing and revocation follow the same gate as granting.
        module = await self._row(db, 'SELECT status,expires_at FROM tenant_modules '
            'WHERE tenant_id=:tid AND module_code=:code', {'tid': tenant_id, 'code': 'sem'})
        if module is None:
            raise GrantError('GRANT_MODULE_UNAVAILABLE', 403)
        expires = module['expires_at']
        if isinstance(expires, str):
            expires = date.fromisoformat(expires)
        if not module_is_available(SimpleNamespace(status=module['status'], expires_at=expires)):
            raise GrantError('GRANT_MODULE_UNAVAILABLE', 403)
        if active and account['status'] != 'active':
            raise GrantError('GRANT_ACCOUNT_INACTIVE', 422)

    async def _target(self, db, user_id, tenant_id, grant_id):
        from app.permissions import effective_role_permissions
        from app.security.advisor_scope import is_advisor
        user, role = await self._user(db, user_id)
        if is_advisor(role):
            grant = await self._row(db, 'SELECT id,user_id,tenant_id,revoked_at FROM advisor_tenant_grants WHERE id=:id', {'id': grant_id})
            if (grant is None or grant['user_id'] != user_id or grant['tenant_id'] != tenant_id
                    or grant['revoked_at'] is not None):
                raise GrantError('GRANT_ADVISOR_GENERATION_INVALID', 409)
            # Mirror ProductionPrincipalAdapter's default-tenant restriction.
            default = await self._row(db, 'SELECT id FROM advisor_tenant_grants WHERE user_id=:uid '
                'AND tenant_id=:tid AND revoked_at IS NULL', {'uid': user_id, 'tid': user['tenant_id']})
            if default is None:
                raise GrantError('GRANT_TARGET_TENANT_INVALID', 422)
        else:
            perms = effective_role_permissions(role.name, role.is_system, role.permissions)
            if (not perms or any(v == 'edit' and k not in {'sem.assets','seo.assets','geo.assets'}
                                 for k, v in perms.items())):
                raise GrantError('GRANT_TARGET_ROLE_INVALID', 422)
            if user['tenant_id'] != tenant_id or grant_id is not None:
                raise GrantError('GRANT_TARGET_TENANT_INVALID', 422)

    @staticmethod
    def _view(row):
        return {key: row[key] for key in ('user_id', 'tenant_id', 'account_id', 'advisor_grant_id', 'generation', 'revoked_at')}

    async def list_grants(self, ctx, tenant_id, account_id):
        async with self._transaction() as db:
            await self._admin(db, ctx)
            await self._account(db, tenant_id, account_id, active=False)
            rows = (await db.execute(text('SELECT user_id,tenant_id,account_id,advisor_grant_id,generation,revoked_at '
                'FROM sem_phase1a_account_grants WHERE tenant_id=:tid AND account_id=:aid ORDER BY user_id'),
                {'tid': tenant_id, 'aid': account_id})).mappings().all()
            return [self._view(row) for row in rows]

    async def change(self, ctx, tenant_id, account_id, user_id, advisor_grant_id=None, *, revoke=False):
        async with self._transaction() as db:
            # SQLite takes BEGIN IMMEDIATE before any reads. PostgreSQL locks
            # account even when the binding is absent,
            # serializing first grants, revoke and regrant on this account.
            await self._admin(db, ctx)
            await self._account(db, tenant_id, account_id, active=not revoke)
            if not revoke:
                await self._target(db, user_id, tenant_id, advisor_grant_id)
            row = await self._row(db, 'SELECT user_id,tenant_id,account_id,advisor_grant_id,generation,revoked_at '
                'FROM sem_phase1a_account_grants WHERE user_id=:uid AND account_id=:aid', {'uid': user_id, 'aid': account_id})
            if row is not None and row['tenant_id'] != tenant_id:
                raise GrantError('GRANT_ACCOUNT_SCOPE_INVALID', 403)
            if revoke:
                if row is None:
                    return {'changed': False, 'grant': None}
                if row['revoked_at'] is not None:
                    return {'changed': False, 'grant': self._view(row)}
            elif row is not None and row['revoked_at'] is None and row['advisor_grant_id'] == advisor_grant_id:
                return {'changed': False, 'grant': self._view(row)}
            now = datetime.now(timezone.utc)
            generation = row['generation'] if revoke else (row['generation'] + 1 if row else 1)
            gid = row['advisor_grant_id'] if revoke else advisor_grant_id
            params = {'uid': user_id, 'tid': tenant_id, 'aid': account_id, 'gid': gid,
                      'generation': generation, 'revoked': now if revoke else None}
            if row is None:
                await db.execute(text('INSERT INTO sem_phase1a_account_grants '
                    '(user_id,tenant_id,account_id,advisor_grant_id,generation,revoked_at) '
                    'VALUES(:uid,:tid,:aid,:gid,:generation,:revoked)'), params)
            else:
                await db.execute(text('UPDATE sem_phase1a_account_grants SET advisor_grant_id=:gid,'
                    'generation=:generation,revoked_at=:revoked WHERE user_id=:uid AND account_id=:aid'), params)
            await db.execute(text('INSERT INTO sem_phase1a_grant_audit '
                '(id,actor_id,user_id,tenant_id,account_id,advisor_grant_id,generation,action,occurred_at) '
                'VALUES(:id,:actor,:uid,:tid,:aid,:gid,:generation,:action,:now)'),
                {**params, 'id': uuid4().hex, 'actor': ctx.user_id, 'action': 'revoke' if revoke else 'grant', 'now': now})
            return {'changed': True, 'grant': dict(user_id=user_id, tenant_id=tenant_id, account_id=account_id,
                advisor_grant_id=gid, generation=generation, revoked_at=params['revoked'])}
