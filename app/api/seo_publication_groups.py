"""Separate internal and workbench admission for the SELECT-only group index."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_session
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.models.module_workspace import SeoSite, TenantModule
from app.models.role import Role
from app.models.seo import SeoSiteAdvisorAssignment as Assignment
from app.models.user import User
from app.security.advisor_scope import account_locked, is_advisor
from app.security.auth import require_scoped_auth, _jwt_secret
from app.security.distribution_inbox_auth import is_inbox_admin
from app import seo_publication_groups as groups


class ReadRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                response = await original(request)
            except SQLAlchemyError:
                response = JSONResponse(status_code=503, content={"detail": {
                    "code": "GROUPS_READ_INCOMPLETE", "message": "发布记录暂时无法完整读取，请重试"}})
            except HTTPException as exc:
                response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            response.headers["Cache-Control"] = "private, no-store"
            return response
        return handle


router = APIRouter(route_class=ReadRoute)


async def snapshot(session=Depends(get_session)):
    # This dependency MUST precede require_scoped_auth, which shares get_session.
    # No DML/flush/commit, locks, suppliers or tasks in this request transaction.
    if session.in_transaction():
        groups.error("GROUPS_READ_INCOMPLETE", 503)
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    await session.execute(text("SET LOCAL statement_timeout = '5000ms'"))
    await session.execute(text("SET LOCAL lock_timeout = '1000ms'"))
    return session


async def authorized(session, ctx, args, *, customer):
    tenant, site_id = args["tenant"], args["scope"]
    ctx.ensure_tenant(tenant)
    if not (ctx.can_view("seo.content") and ctx.can_view("seo.site")):
        groups.error("GROUPS_FORBIDDEN", 403)
    from datetime import date
    module = (await session.execute(select(TenantModule.id, TenantModule.status, TenantModule.expires_at,
                                          TenantModule.updated_at).where(
        TenantModule.tenant_id == tenant, TenantModule.module_code == "seo"))).first()
    if (module is None or module.status not in {"active", "trial"} or
            module.expires_at is not None and module.expires_at < date.today()):
        groups.error("GROUPS_FORBIDDEN", 403)
    site = await session.scalar(select(SeoSite.id).where(
        SeoSite.id == site_id, SeoSite.tenant_id == tenant, SeoSite.tenant_module_id == module.id))
    if site is None:
        groups.error("GROUPS_NOT_FOUND", 404)
    # Read just scope metadata, never site/module settings (which can hold credentials).
    # Workbench preserves _seo_site(require_active=False): historical reads on a
    # paused site remain available to customers; advisors still need active assignment/site.
    site_data = (await session.execute(select(SeoSite.status, SeoSite.updated_at).where(
        SeoSite.id == site_id, SeoSite.tenant_id == tenant))).one()
    user = await session.get(User, ctx.user_id, populate_existing=True) if ctx.user_id else None
    role = await session.get(Role, user.role_id, populate_existing=True) if user else None
    admin = is_inbox_admin(user, role)
    if not customer:
        if (ctx.user_id is None or ctx.is_superadmin or not user or not user.is_active or account_locked(user) or
                not (admin or is_advisor(role)) or
                (admin and ctx.scope_kind is not None) or
                (not admin and (not ctx.is_advisor or ctx.scope_kind != "advisor_tenant")) or
                site_data.status != "active"):
            groups.error("GROUPS_FORBIDDEN", 403)
    assignment = grant = None
    if ctx.is_advisor:
        grant = (await session.execute(select(Grant.id, Grant.granted_at).where(
            Grant.id == ctx.grant_id, Grant.user_id == ctx.user_id,
            Grant.tenant_id == tenant, Grant.revoked_at.is_(None)))).first()
        assignment = (await session.execute(select(Assignment.id, Assignment.updated_at).where(
            Assignment.tenant_id == tenant, Assignment.site_id == site_id,
            Assignment.advisor_user_id == ctx.user_id, Assignment.active.is_(True)))).first()
        if grant is None or assignment is None or site_data.status != "active":
            groups.error("GROUPS_FORBIDDEN", 403)
    revision = groups.digest([ctx.permissions, ctx.scope_kind, ctx.grant_id, list(grant) if grant else None,
                              list(assignment) if assignment else None, list(site_data),
                              module.id, module.status, module.expires_at, module.updated_at])
    return revision, admin


@router.get("/api/v1/seo/distribution/v2/publication-groups")
async def internal_groups(request: Request, session=Depends(snapshot), ctx=Depends(require_scoped_auth)):
    args = groups.query(request, customer=False)
    revision, admin = await authorized(session, ctx, args, customer=False)
    from app.config import get_settings
    writes = ctx.can_edit("seo.content") and (admin or get_settings().advisor_scoped_content_writes_enabled)
    return await groups.read_groups(session, ctx, args, customer=False, authorization_revision=revision,
                                    admin=admin, writes=writes, secret=_jwt_secret())


@router.get("/api/v1/seo/workbench/publication-groups")
async def workbench_groups(request: Request, session=Depends(snapshot), ctx=Depends(require_scoped_auth)):
    args = groups.query(request, customer=True)
    revision, _ = await authorized(session, ctx, args, customer=True)
    return await groups.read_groups(session, ctx, args, customer=True, authorization_revision=revision,
                                    secret=_jwt_secret())
