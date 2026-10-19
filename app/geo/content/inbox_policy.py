"""Live GEO target authority; no platform, channel or native publication writes."""
import hashlib
from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import load_only

from app.distribution_inbox_protocol import fail
from app.models import (User, Role, Tenant, TenantModule, GeoProject, GeoContentTask,
                        GeoArticleVersion, GeoPrompt, GeoOptimizationUnit, GeoOptimizationBusiness)
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.security.advisor_scope import account_locked, is_advisor


async def fresh_actor(session, ctx, *, write=False, lock=True):
    if not ctx.user_id or ctx.is_superadmin:
        fail('INBOX_FORBIDDEN', 403)
    if getattr(ctx, 'inbox_exp', float('inf')) <= datetime.now(timezone.utc).timestamp():
        fail('INBOX_FORBIDDEN', 403)
    query = (select(User).options(load_only(
        User.id, User.role_id, User.tenant_id, User.is_active, User.locked_until))
        .where(User.id == ctx.user_id).execution_options(populate_existing=True))
    user = await session.scalar(query.with_for_update() if lock else query)
    if user is None or not user.is_active or account_locked(user):
        fail('INBOX_FORBIDDEN', 403)
    query = select(Role).where(Role.id == user.role_id).execution_options(populate_existing=True)
    role = await session.scalar(query.with_for_update() if lock else query)
    admin = bool(role and role.is_system and role.name == '管理员')
    if admin:
        if ctx.advisor_scope is not None:
            fail('INBOX_FORBIDDEN', 403)
        return SimpleNamespace(user=user, role=role, admin=True, ctx=ctx)
    if not is_advisor(role) or ctx.advisor_scope is None or ctx.advisor_scope.grant_id is None:
        fail('INBOX_FORBIDDEN', 403)
    permission = (role.permissions or {}).get('geo.content')
    if permission not in ({'edit'} if write else {'view', 'edit'}):
        fail('INBOX_FORBIDDEN', 403)
    if write:
        from app.config import get_settings
        if not get_settings().advisor_scoped_content_writes_enabled:
            fail('INBOX_FORBIDDEN', 403)
    return SimpleNamespace(user=user, role=role, admin=False, ctx=ctx)


async def target_authorized(session, actor, tenant, scope_id, *, article=None):
    ctx = actor.ctx
    if not actor.admin:
        ctx.ensure_tenant(tenant)
        grant = await session.scalar(select(Grant).where(Grant.id == ctx.advisor_scope.grant_id)
            .with_for_update().execution_options(populate_existing=True))
        if (grant is None or grant.user_id != actor.user.id or grant.tenant_id != tenant
                or grant.revoked_at is not None):
            fail('INBOX_FORBIDDEN', 403)
        default_grant = await session.scalar(select(Grant.id).where(
            Grant.user_id == actor.user.id, Grant.tenant_id == actor.user.tenant_id, Grant.revoked_at.is_(None)))
        if default_grant is None:
            fail('INBOX_FORBIDDEN', 403)
    elif actor.user.tenant_id not in {None, tenant}:
        fail('INBOX_FORBIDDEN', 403)
    await session.scalar(select(Tenant.id).where(Tenant.id == tenant).with_for_update())
    module = await session.scalar(select(TenantModule).where(TenantModule.tenant_id == tenant,
        TenantModule.module_code == 'geo').with_for_update().execution_options(populate_existing=True))
    if module is None or module.status not in {'active', 'trial'} or (module.expires_at and module.expires_at < date.today()):
        fail('INBOX_FORBIDDEN', 403)
    from app.geo.tenant_scope import ensure_geo_entitlement
    await ensure_geo_entitlement(session, tenant)
    if scope_id is None:
        return
    from app.geo.project_scope import project_scope, binding
    from app.geo.project_workflows import plan_for
    projects = list(await session.scalars(select(GeoProject).where(GeoProject.tenant_id == tenant)
        .order_by(GeoProject.id).with_for_update().execution_options(populate_existing=True)))
    project = next((p for p in projects if p.id == scope_id), None)
    if project is None or project.status != 'active' or project.tenant_module_id != module.id:
        fail('INBOX_FORBIDDEN', 403)
    _, businesses = await project_scope(session, tenant, scope_id)
    if any(set(binding(p)['business_ids']) & set(businesses) for p in projects if p.id != scope_id):
        fail('INBOX_FORBIDDEN', 403)
    assigned = plan_for(project).get('advisor_user_id')
    if not actor.admin and (type(assigned) is not int or assigned != actor.user.id):
        fail('INBOX_FORBIDDEN', 403)
    if article is not None:
        await article_authorized(session, tenant, businesses, article)


async def article_authorized(session, tenant, businesses, data):
    task = await session.scalar(select(GeoContentTask).where(GeoContentTask.id == data['articleId'],
        GeoContentTask.tenant_id == tenant).with_for_update().execution_options(populate_existing=True))
    if task is None or task.review_status != 'approved' or task.status in {'archived', 'cancelled'}:
        fail('INBOX_FORBIDDEN', 403)
    prompt = await session.scalar(select(GeoPrompt).where(GeoPrompt.id == task.prompt_id,
        GeoPrompt.tenant_id == tenant).with_for_update().execution_options(populate_existing=True))
    unit = await session.scalar(select(GeoOptimizationUnit).where(GeoOptimizationUnit.id == prompt.unit_id,
        GeoOptimizationUnit.tenant_id == tenant).with_for_update().execution_options(populate_existing=True)) if prompt else None
    business = await session.scalar(select(GeoOptimizationBusiness).where(
        GeoOptimizationBusiness.id == task.business_id, GeoOptimizationBusiness.tenant_id == tenant)
        .with_for_update().execution_options(populate_existing=True))
    if (prompt is None or unit is None or business is None or task.business_id not in businesses
            or unit.business_id != task.business_id or any(x.status != 'active' for x in (prompt, unit, business))):
        fail('INBOX_FORBIDDEN', 403)
    latest = await session.scalar(select(GeoArticleVersion).where(GeoArticleVersion.task_id == task.id,
        GeoArticleVersion.kind == 'master').order_by(GeoArticleVersion.version_no.desc(), GeoArticleVersion.id.desc())
        .limit(1).with_for_update().execution_options(populate_existing=True))
    # GEO articleId denotes the content task; articleVersion pins its latest
    # master version. The body digest never grants native publication approval.
    if (latest is None or latest.version_no != data['articleVersion']
            or hashlib.sha256(latest.body_markdown.encode('utf-8')).hexdigest() != data['articleDigest']):
        fail('REVISION_CONFLICT', 409)
