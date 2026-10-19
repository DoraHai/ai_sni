"""Tenant-granted site creation, before a site or site assignment exists."""
from fastapi import HTTPException
from sqlalchemy import select

from app.models.module_workspace import TenantModule
from app.module_scope import module_is_available


def is_site_creation(rule):
    return (getattr(rule, "method", None), getattr(rule, "template", None),
            getattr(rule, "assignment", None)) == (
        "POST", "/api/v1/seo/sites", "tenant_create_site")


async def check_scope(session, ctx, request, body, *, lock=False):
    # Never use a home/default tenant or an existing site's assignment as a
    # substitute for the selected, freshly validated tenant grant.
    from app.security.advisor_write_objects import _positive_id
    ctx.ensure_tenant(ctx.tenant_id)
    if not isinstance(body, dict) or "tenant_id" not in body:
        raise HTTPException(403, {"code": "ADVISOR_TENANT_REQUIRED"})
    ctx.ensure_tenant(_positive_id(body["tenant_id"]))
    for key, value in request.query_params.multi_items():
        if key != "tenant_id":
            raise HTTPException(403, {"code": "ADVISOR_WRITE_FIELD_FORBIDDEN"})
        ctx.ensure_tenant(_positive_id(value))
    if request.path_params:
        raise HTTPException(403, {"code": "ADVISOR_WRITE_FIELD_FORBIDDEN"})
    if lock:
        module = await session.scalar(select(TenantModule).where(
            TenantModule.tenant_id == ctx.tenant_id,
            TenantModule.module_code == "seo",
        ).with_for_update(read=True).execution_options(populate_existing=True))
        if module is None or not module_is_available(module):
            raise HTTPException(403, {"code": "ADVISOR_OBJECT_UNAVAILABLE"})
    # No assignment is created: granting site permissions remains admin-only.
