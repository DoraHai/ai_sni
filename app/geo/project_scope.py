"""Explicit project/business ownership in existing durable project settings.

Unassigned historical businesses remain unassigned. Writes serialize on the
tenant row; selecting an empty project never falls back to tenant-wide data.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models import GeoProject, GeoOptimizationBusiness, GeoOptimizationUnit, GeoPrompt, GeoActionTicket, Tenant

SCOPE_KEY = "geo_business_scope"


def binding(project):
    value = (project.project_settings or {}).get(SCOPE_KEY) or {}
    ids = value.get("business_ids", [])
    if (not isinstance(ids, list) or any(type(i) is not int or i <= 0 for i in ids)
            or len(ids) != len(set(ids))):
        raise HTTPException(409, "项目业务归属无效，请由顾问重新设置")
    return {"revision": int(value.get("revision") or 0), "business_ids": list(ids),
            "updated_at": value.get("updated_at"), "updated_by": value.get("updated_by")}


async def project_scope(session, tenant_id, project_id, business_id=None):
    project = await session.scalar(select(GeoProject).where(
        GeoProject.id == project_id, GeoProject.tenant_id == tenant_id).execution_options(populate_existing=True))
    if project is None:
        raise HTTPException(404, "GEO 项目不存在或不属于当前客户")
    ids = binding(project)["business_ids"]
    existing = set(await session.scalars(select(GeoOptimizationBusiness.id).where(
        GeoOptimizationBusiness.tenant_id == tenant_id, GeoOptimizationBusiness.id.in_(ids))))
    if existing != set(ids):
        raise HTTPException(409, "项目绑定的业务已不存在或归属改变，请重新设置")
    if business_id is not None:
        if business_id not in existing:
            raise HTTPException(404, "业务不属于当前 GEO 项目")
        ids = [business_id]
    return project, ids


async def prompt_ids_for_businesses(session, tenant_id, business_ids):
    units = select(GeoOptimizationUnit.id).where(GeoOptimizationUnit.tenant_id == tenant_id,
                                               GeoOptimizationUnit.business_id.in_(business_ids))
    return list(await session.scalars(select(GeoPrompt.id).where(
        GeoPrompt.tenant_id == tenant_id, GeoPrompt.unit_id.in_(units))))


async def set_binding(session, tenant_id, project_id, business_ids, expected_revision, actor_id):
    await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    projects = list(await session.scalars(select(GeoProject).where(GeoProject.tenant_id == tenant_id)
        .order_by(GeoProject.id).with_for_update().execution_options(populate_existing=True)))
    project = next((p for p in projects if p.id == project_id), None)
    if project is None:
        raise HTTPException(404, "GEO 项目不存在")
    current = binding(project)
    if current["revision"] != expected_revision:
        raise HTTPException(409, "项目业务归属已更新，请刷新后重试")
    ids = sorted(set(business_ids))
    existing = set(await session.scalars(select(GeoOptimizationBusiness.id).where(
        GeoOptimizationBusiness.tenant_id == tenant_id, GeoOptimizationBusiness.id.in_(ids)).with_for_update()))
    if existing != set(ids):
        raise HTTPException(404, "业务不存在或不属于当前客户")
    if any(set(binding(p)["business_ids"]) & set(ids) for p in projects if p.id != project_id):
        raise HTTPException(409, "业务已归属其他项目，请先在原项目解除关联")
    if current["business_ids"] == ids:
        return current
    removed = set(current["business_ids"]) - set(ids)
    if removed:
        removed_prompts = await prompt_ids_for_businesses(session, tenant_id, removed)
        active = await session.scalar(select(GeoActionTicket.id).where(
            GeoActionTicket.tenant_id == tenant_id,
            GeoActionTicket.progress['project_workflow']['project_id'].as_integer() == project_id,
            GeoActionTicket.advice_code.in_([f'workqueue:v1:prompt-{pid}' for pid in removed_prompts]),
            GeoActionTicket.status.in_(['todo', 'doing', 'blocked', 'reopened'])).limit(1))
        if active is not None:
            raise HTTPException(409, "该业务仍有未完成的项目待办，请先处理再解除归属")
    result = {"revision": current["revision"] + 1, "business_ids": ids,
              "updated_by": actor_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    project.project_settings = {**(project.project_settings or {}), SCOPE_KEY: result}
    await session.flush()
    return result
