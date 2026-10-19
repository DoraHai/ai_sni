"""Transaction-bound authority checks for explicitly admitted advisor writes."""
from datetime import datetime, timezone

from sqlalchemy import event, select
from sqlalchemy.orm import load_only
from sqlalchemy.util import await_only
from sqlalchemy.ext.asyncio import AsyncSession

class AdvisorWriteSession(AsyncSession):
    async def commit(self):
        try:
            return await super().commit()
        except BaseException:
            if self.info.get("advisor_scoped_write"):
                # Session.rollback cannot run inside the before_commit state
                # transition. Unwind that event first, then roll back here.
                await self.rollback()
            raise


async def recheck_advisor_before_commit(session, ctx) -> None:
    """Lock user -> role -> grant, then keep those locks until business commit.

    Central grant management locks users in ID order before changing grants;
    this writer locks just its own user, then its role and grant generation.
    No fresh connection or identity-map cached authorization is used.
    """
    if ctx.advisor_scope is None:
        return
    from app.security.advisor_scope import account_locked, deny, is_advisor
    from app.config import get_settings
    from app.models import Role, Tenant, User
    from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant

    if session.info.get('advisor_operation_denied'):
        deny(403, 'ADVISOR_GRANT_REVOKED', '本次操作授权已变化，请重新发起')
    if not get_settings().advisor_scoped_content_writes_enabled:
        deny(403, "ADVISOR_HIGH_RISK_WRITES_DISABLED", "顾问写入暂未开放")
    binding = session.info.get("advisor_scoped_write")
    if binding is None or binding[0] is not ctx:
        deny(403, "ADVISOR_ROUTE_UNAVAILABLE", "缺少受限写入范围")
    _, request, body, rule, expiry = binding
    if expiry <= datetime.now(timezone.utc).timestamp():
        deny(401, "ADVISOR_GRANT_REVOKED", "客户凭证已失效")
    # Suppress autoflush: check authority before pending changes are flushed.
    with session.no_autoflush:
        from app.security.geo_advisor import check_manual_execution_scope
        await check_manual_execution_scope(session, ctx, rule)
        user = await session.scalar(select(User).options(load_only(
            User.id, User.role_id, User.tenant_id, User.is_active, User.locked_until
        )).where(User.id == ctx.user_id).with_for_update().execution_options(populate_existing=True))
        if user is None or not user.is_active or account_locked(user):
            deny(401, "ADVISOR_GRANT_REVOKED", "账号已停用或锁定")
        role = await session.scalar(select(Role).where(Role.id == user.role_id)
                                    .with_for_update().execution_options(populate_existing=True))
        if not is_advisor(role) or any((role.permissions or {}).get(k) != "edit" for k in rule.edit_all):
            deny(403, "ADVISOR_ROLE_CHANGED", "顾问角色或编辑权限已变化")
        scope = ctx.advisor_scope
        grant = await session.scalar(select(Grant).where(Grant.id == scope.grant_id)
                                     .with_for_update().execution_options(populate_existing=True))
        if (grant is None or grant.user_id != ctx.user_id or grant.revoked_at is not None
                or grant.tenant_id != ctx.tenant_id or grant.tenant_id != scope.tenant_id):
            deny(401, "ADVISOR_GRANT_REVOKED", "客户授权已撤销")
        default_grant = await session.scalar(select(Grant.id).where(
            Grant.user_id == ctx.user_id, Grant.tenant_id == user.tenant_id,
            Grant.revoked_at.is_(None)))
        if default_grant is None or await session.get(Tenant, ctx.tenant_id) is None:
            deny(403, "ADVISOR_TENANT_NOT_GRANTED", "客户授权或默认客户已变化")
        ctx.ensure_tenant(grant.tenant_id)
        if any(not ctx.can_edit(k) for k in rule.edit_all):
            deny(403, "ADVISOR_ROLE_CHANGED", "当前角色无编辑权限")
        # B reloads objects with populate_existing. Persist pending edits into
        # this still-uncommitted transaction before those reads, so a fresh
        # ownership check cannot silently discard handler changes. Any later
        # object/assignment rejection rolls this flush back along with the rest.
        deleting = rule.method == "DELETE" and bool(session.deleted)
        if not deleting:
            await session.flush()
        from app.module_scope import ensure_module_access
        from app.security.geo_advisor import check_scoped_write_objects
        await ensure_module_access(session, ctx, ctx.tenant_id, "geo")
        await check_scoped_write_objects(session, ctx, request, body, rule)
        # Supplier inputs may include more than the target object. Quota and
        # business commits must preserve that whole initially-read assignment,
        # using the same authority locks as the commit's object checks.
        from app.security.advisor_read_scope import recheck_initial_scope
        await recheck_initial_scope(session, ctx)
        if rule.assignment == 'operations':
            from app.security.advisor_operations import verify_pending_scope
            await verify_pending_scope(session, ctx)
        if deleting:
            # Validate the still-existing target and lock its project before
            # flushing DELETE. The authority/project locks survive the commit.
            await session.flush()


def bind_advisor_write_commit(session, ctx, request, body, rule, claims) -> None:
    """Install on this dependency's actual session; applies to every commit.

    SQLAlchemy's synchronous event runs in AsyncSession's greenlet, allowing
    await_only to execute the async recheck on the same business transaction.
    AdvisorWriteSession rolls back after the event has unwound. Other session
    factories still reject the commit and their dependency cleanup rolls back.
    """
    session.info["advisor_scoped_write"] = (ctx, request, body, rule, claims["exp"])
    from app.security.advisor_write_audit import bind_write_changes
    bind_write_changes(session, request)
    if session.info.get("advisor_write_commit_hook"):
        return

    def before_commit(sync_session):
        await_only(recheck_advisor_before_commit(session, session.info["advisor_scoped_write"][0]))

    def after_commit(sync_session):
        from app.security.advisor_write_audit import record
        if not sync_session.in_nested_transaction():
            if session.info.pop('advisor_delete_pending', False):
                session.info['advisor_delete_committed'] = True
            record(session.info["advisor_scoped_write"][1].scope, "committed")

    def after_flush(sync_session, _flush_context):
        if sync_session.deleted and session.info['advisor_scoped_write'][3].method == 'DELETE':
            session.info['advisor_delete_pending'] = True
        scope = session.info["advisor_scoped_write"][1].scope
        created = scope.setdefault("geo_advisor_created_ids", {})
        for row in set(sync_session.new) | set(sync_session.dirty) | set(sync_session.deleted):
            ident = getattr(row, "id", None)
            table = getattr(type(row), "__tablename__", None)
            if table and type(ident) is int and ident > 0:
                created.setdefault(table, set()).add(ident)

    event.listen(session.sync_session, "before_commit", before_commit)
    event.listen(session.sync_session, "after_commit", after_commit)
    event.listen(session.sync_session, "after_flush", after_flush)
    session.info["advisor_write_commit_hook"] = True
