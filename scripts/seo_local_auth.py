"""Local composition of the shared workspace's read-only session catalog.

The SEO branch's auth router lacks /modules and the module-filtered /tenants.
This bridge uses the real JWT/database dependencies and existing scope helpers;
it is mounted only by the local acceptance runner, never the production app.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.database import get_session
from app.models import TenantModule
from app.module_scope import list_module_tenants, module_is_available
from app.security.auth import require_auth

router = APIRouter(prefix="/api/v1/auth")
PERMISSIONS = {
    "sem": ("sem.assets", "assistant", "onboarding", "monitor.dashboard", "monitor.alerts", "monitor.profile",
            "optimize.expand", "optimize.keywords", "optimize.searchterms", "optimize.negatives", "verify.adjustments",
            "verify.pending", "verify.leads", "manage.account", "manage.campaigns", "manage.adgroups", "manage.ocpc",
            "delivery.report", "settings.customers"),
    "seo": ("seo.assets", "seo.dashboard", "seo.keywords", "seo.content", "seo.site"),
    "geo": ("geo.assets", "geo.content", "geo.diagnosis"),
}


@router.get("/modules")
async def modules(ctx=Depends(require_auth), session=Depends(get_session)):
    by_code = {}
    if ctx.tenant_id is not None:
        rows = (await session.scalars(select(TenantModule).where(TenantModule.tenant_id == ctx.tenant_id))).all()
        by_code = {row.module_code: row for row in rows}
    items = []
    for code, permissions in PERMISSIONS.items():
        permitted = ctx.can_view(*permissions)
        row = by_code.get(code)
        if ctx.tenant_id is not None:
            available = bool(row and permitted and module_is_available(row))
            items.append({"module_code": code, "status": row.status if row else "not_opened", "available": available,
                          "expires_at": row.expires_at.isoformat() if row and row.expires_at else None,
                          "tenant_count": int(available)})
        else:
            tenants = await list_module_tenants(session, ctx, code)
            items.append({"module_code": code, "status": "active" if permitted else "no_permission",
                          "available": permitted, "expires_at": None, "tenant_count": len(tenants)})
    return {"tenant_id": ctx.tenant_id, "modules": items}


@router.get("/tenants")
async def tenants(module: str | None = Query(None, pattern="^(sem|seo|geo)$"),
                  ctx=Depends(require_auth), session=Depends(get_session)):
    if module is None:
        from app.api.auth import list_tenants
        return await list_tenants(ctx=ctx, session=session)
    if not ctx.can_view(*PERMISSIONS[module]):
        raise HTTPException(403, "当前账号无权访问该模块的客户列表")
    rows = await list_module_tenants(session, ctx, module)
    return {"module": module, "tenants": [{"id": row.id, "name": row.name} for row in rows]}
