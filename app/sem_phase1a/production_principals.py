"""Unregistered production-session bridge. Imports occur only at explicit wiring.

Never accepts raw role/tenant/grant headers. require_auth verifies JWT and its
current grant generation; this adapter re-reads DB roles and explicit account
bindings. It has no engine/config/URL or grant-writing capability.
"""
from types import SimpleNamespace
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.sem_phase0.store import AdvisorPrincipal, ScopeDenied


class ProductionPrincipalAdapter:
    async def resolve(self, ctx, session):
        from app.security.advisor_scope import is_advisor, account_locked
        from app.module_scope import ensure_module_access
        from app.security.sem_identity import ensure_sem_identity_access

        if ctx.is_superadmin or type(ctx.user_id) is not int or type(ctx.tenant_id) is not int:
            raise ScopeDenied('仅当前客户的真实登录会话可用')
        now = datetime.now(timezone.utc)
        if type(ctx.auth_exp) is not int or ctx.auth_exp <= now.timestamp():
            raise ScopeDenied('会话已过期')
        user = (await session.execute(text(
            'SELECT u.is_active,u.locked_until,u.tenant_id,r.name,r.is_system,r.permissions '
            'FROM users u JOIN roles r ON u.role_id=r.id WHERE u.id=:uid'), {'uid': ctx.user_id})).first()
        if user is None or not user[0]:
            raise ScopeDenied('身份停用')
        import json
        permissions = json.loads(user[5]) if isinstance(user[5], str) else user[5]
        role = SimpleNamespace(name=user[3], is_system=user[4], permissions=permissions)
        locked_until = datetime.fromisoformat(user[1]) if isinstance(user[1], str) else user[1]
        if account_locked(SimpleNamespace(locked_until=locked_until)) or ctx.role_name != role.name:
            raise ScopeDenied('角色或锁定状态已变化')
        advisor = is_advisor(role)
        if advisor:
            scope = ctx.advisor_scope
            if scope is None:
                raise ScopeDenied('缺少顾问客户会话')
            scope.ensure_tenant(ctx.tenant_id)
            # Reuse the same current-generation grant checks as the workbench.
            from app.security.advisor_scope import active_grants, read_grants
            grants = await active_grants(session, await read_grants(session, ctx.user_id))
            if not any(g.id == scope.grant_id and g.tenant_id == ctx.tenant_id for g in grants):
                raise ScopeDenied('当前授权已撤销')
            if user[2] not in {g.tenant_id for g in grants}:
                raise ScopeDenied('顾问默认客户与授权不一致')
            grant_id = scope.grant_id
        else:
            # A tenant-bound read-only role is a customer; elevated/non-bound
            # roles and stale advisor contexts must never be reclassified.
            from app.permissions import effective_role_permissions
            perms = effective_role_permissions(role.name, role.is_system, permissions)
            if (ctx.advisor_scope is not None or user[2] != ctx.tenant_id or not perms
                    or any(v == 'edit' and k not in {'sem.assets', 'seo.assets', 'geo.assets'}
                           for k, v in perms.items())):
                raise ScopeDenied('仅限定客户只读身份可用')
            grant_id = None
        await ensure_module_access(session, ctx, ctx.tenant_id, 'sem')
        await ensure_sem_identity_access(session, ctx.tenant_id)
        rows = (await session.execute(text(
            "SELECT a.id FROM baidu_accounts a JOIN sem_phase1a_account_grants g ON g.account_id=a.id "
            "AND g.tenant_id=a.tenant_id WHERE a.tenant_id=:tid AND a.status='active' "
            "AND g.user_id=:uid AND g.revoked_at IS NULL AND "
            + ("g.advisor_grant_id=:gid" if advisor else "g.advisor_grant_id IS NULL")),
            {'tid': ctx.tenant_id, 'uid': ctx.user_id, 'gid': grant_id})).all()
        accounts = frozenset((ctx.tenant_id, row[0]) for row in rows)
        if not accounts:
            raise ScopeDenied('当前身份无有效SEM账户绑定')
        return AdvisorPrincipal(str(ctx.user_id), 'advisor' if advisor else 'customer',
                                accounts if advisor else frozenset(), accounts)


def production_principal_dependency():
    """Explicit factory only. No router registration, environment switch or IO."""
    from app.database import get_session
    from app.security.auth import require_auth

    async def resolve(ctx=Depends(require_auth), session=Depends(get_session)):
        try:
            return await ProductionPrincipalAdapter().resolve(ctx, session)
        except (ScopeDenied, SQLAlchemyError, ValueError, TypeError):
            raise HTTPException(403, {'code': 'SCOPE_DENIED', 'message': '身份或SEM账户授权不可用'}) from None
    return resolve
