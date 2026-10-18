"""Revalidate under authorization locks immediately before business commit."""
from datetime import datetime, timezone
import json
import logging

from fastapi import HTTPException
from sqlalchemy import select

from app.models.advisor_tenant_grant import AdvisorTenantGrant
from app.models.role import Role
from app.models.user import User
from app.security.advisor_scope import account_locked
from app.security.advisor_seo_scope import is_advisor_role


def record_seo_action(ctx, tenant_id, method, path, object_type, object_ids):
    """Metadata only; the SEO service retains stderr in its configured log file."""
    event = {"user_id": ctx.user_id, "tenant_id": tenant_id, "method": method,
             "path": path, "object_type": object_type, "object_ids": object_ids,
             "result": "succeeded", "time": datetime.now(timezone.utc).isoformat()}
    # SEO has no root INFO handler; WARNING also reaches the default stderr
    # handler. Never include bodies, account names, URLs, headers or credentials.
    logging.getLogger(__name__).warning("SEO_ACTION_AUDIT %s", json.dumps(event, sort_keys=True))


def record_advisor_write(ctx, row, method, path):
    if getattr(ctx, "is_advisor", False):
        record_seo_action(ctx, row.tenant_id, method, path, row.__tablename__, [row.id])


async def recheck_advisor_before_commit(session, ctx) -> None:
    if not getattr(ctx, "is_advisor", False):
        return
    try:
        await _recheck(session, ctx)
    except Exception:
        # Also undo pending changes/autoflushes made by the business handler.
        await session.rollback()
        raise


async def _recheck(session, ctx):
    def deny(status, code):
        raise HTTPException(status, {"code": code})

    rule = getattr(ctx, "advisor_write_rule", None)
    if rule is None or ctx.scope_kind != "advisor_tenant" or ctx.grant_id is None:
        deny(403, "ADVISOR_HIGH_RISK_WRITES_DISABLED")
    ctx.ensure_tenant(ctx.tenant_id)
    if type(ctx.auth_exp) is not int or ctx.auth_exp <= datetime.now(timezone.utc).timestamp():
        deny(401, "ADVISOR_GRANT_REVOKED")
    # Central grant management locks users (ascending IDs) before changing
    # grants. We lock just this user, then role, then grants; role management
    # locks roles but does not acquire user row locks. Hold through commit.
    # Suppress autoflush until all authorization reads have succeeded.
    with session.no_autoflush:
        user = await session.scalar(select(User).where(User.id == ctx.user_id)
            .with_for_update(read=True).execution_options(populate_existing=True))
        if user is None or not user.is_active or account_locked(user):
            deny(401, "ADVISOR_GRANT_REVOKED")
        role = await session.scalar(select(Role).where(Role.id == user.role_id)
            .with_for_update(read=True).execution_options(populate_existing=True))
        if not is_advisor_role(role):
            deny(403, "ADVISOR_ROLE_CHANGED")
        if not all((role.permissions or {}).get(key) == "edit" for key in rule.edit_all):
            deny(403, "ADVISOR_WRITE_PERMISSION_REQUIRED")
        grants = list(await session.scalars(select(AdvisorTenantGrant).where(
            AdvisorTenantGrant.user_id == ctx.user_id).order_by(AdvisorTenantGrant.id)
            .with_for_update(read=True).execution_options(populate_existing=True)))
        grant = next((g for g in grants if g.id == ctx.grant_id), None)
        if grant is None or grant.revoked_at is not None or grant.tenant_id != ctx.tenant_id:
            deny(401, "ADVISOR_GRANT_REVOKED")
        if user.tenant_id not in {g.tenant_id for g in grants if g.revoked_at is None}:
            deny(403, "ADVISOR_DEFAULT_TENANT_INVALID")
        scope = getattr(ctx, "advisor_write_scope", None)
        if scope is not None:
            from app.security.advisor_write_objects import lock_manual_write_scope
            await lock_manual_write_scope(session, ctx, *scope)
