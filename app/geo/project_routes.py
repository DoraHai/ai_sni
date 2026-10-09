from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, PositiveInt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import GeoProject
from app.module_scope import ensure_module_access
from app.security.auth import AuthContext, require_scoped_auth


# This router keeps the shared platform project's API contract in a GEO-only
# module, so the independent service does not import the broad app.api package.
geo_projects_router = APIRouter(tags=["GEO 项目"])


def _canonical_domain(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(400, "请填写网站域名")
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower().strip(".")
    if not host or "." not in host:
        raise HTTPException(400, "网站域名格式不正确")
    if host.startswith("www."):
        host = host[4:]
    return host, candidate


class GeoProjectCreate(BaseModel):
    tenant_id: int
    name: str = Field(min_length=1, max_length=120)
    brand_name: str | None = Field(None, max_length=160)
    domain: str = Field(min_length=3, max_length=255)
    description: str | None = Field(None, max_length=4000)


class GeoProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    brand_name: str | None = Field(None, max_length=160)
    domain: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = Field(None, max_length=4000)
    status: str | None = Field(None, pattern="^(active|paused|archived)$")


def _project_payload(row: GeoProject) -> dict:
    from app.geo.project_scope import binding
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "brand_name": row.brand_name,
        "domain": row.primary_domain,
        "canonical_domain": row.canonical_domain,
        "default_url": row.default_url,
        "description": row.description,
        "status": row.status,
        "business_scope": binding(row),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@geo_projects_router.get("/api/v1/geo/projects", dependencies=[Depends(require_scoped_auth)])
async def list_geo_projects(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await ensure_module_access(session, ctx, tenant_id, "geo")
    rows = list(
        (
            await session.scalars(
                select(GeoProject)
                .where(GeoProject.tenant_id == tenant_id)
                .order_by(GeoProject.id)
            )
        ).all()
    )
    return {"projects": [_project_payload(row) for row in rows]}


@geo_projects_router.post("/api/v1/geo/projects", dependencies=[Depends(require_scoped_auth)])
async def create_geo_project(
    req: GeoProjectCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    module = await ensure_module_access(session, ctx, req.tenant_id, "geo")
    canonical, default_url = _canonical_domain(req.domain)
    row = GeoProject(
        tenant_id=req.tenant_id,
        tenant_module_id=module.id,
        name=req.name.strip(),
        brand_name=(req.brand_name or "").strip() or None,
        primary_domain=req.domain.strip(),
        canonical_domain=canonical,
        default_url=default_url,
        description=(req.description or "").strip() or None,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "该客户已经维护了这个 GEO 项目网站") from exc
    await session.refresh(row)
    return _project_payload(row)


@geo_projects_router.patch(
    "/api/v1/geo/projects/{project_id}", dependencies=[Depends(require_scoped_auth)]
)
async def update_geo_project(
    project_id: int,
    tenant_id: int,
    req: GeoProjectUpdate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await ensure_module_access(session, ctx, tenant_id, "geo")
    row = await session.get(GeoProject, project_id, with_for_update=True)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "GEO 项目不存在")
    values = req.model_dump(exclude_unset=True)
    if "domain" in values:
        canonical, default_url = _canonical_domain(values.pop("domain"))
        row.primary_domain = req.domain.strip()
        row.canonical_domain = canonical
        row.default_url = default_url
    for key, value in values.items():
        setattr(row, key, value.strip() or None if isinstance(value, str) else value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "该客户已经维护了这个 GEO 项目网站") from exc
    await session.refresh(row)
    return _project_payload(row)


class GeoProjectBusinessScope(BaseModel):
    business_ids: list[PositiveInt] = Field(default_factory=list, max_length=100)
    expected_revision: int = Field(ge=0)


@geo_projects_router.put("/api/v1/geo/projects/{project_id}/business-scope")
async def update_business_scope(project_id: int, tenant_id: int, req: GeoProjectBusinessScope,
                                ctx: AuthContext = Depends(require_scoped_auth),
                                session: AsyncSession = Depends(get_session)):
    await ensure_module_access(session, ctx, tenant_id, "geo")
    if ctx.user_id is None or not ctx.can_edit("geo.assets"):
        raise HTTPException(403, "设置项目归属需要已登录顾问的项目编辑权限")
    from app.geo.project_scope import set_binding
    result = await set_binding(session, tenant_id, project_id, req.business_ids, req.expected_revision, ctx.user_id)
    await session.commit()
    return {"project_id": project_id, "business_scope": result}


class GeoServicePlanUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    enabled: bool = False
    status: str = Field("paused", pattern="^(active|paused)$")
    prompt_ids: list[PositiveInt] = Field(default_factory=list, max_length=20)
    interval_days: int = Field(7, ge=1, le=90)
    advisor_user_id: PositiveInt | None = None


@geo_projects_router.put("/api/v1/geo/projects/{project_id}/service-plan")
async def update_project_plan(project_id: int, tenant_id: int, req: GeoServicePlanUpdate,
                              ctx: AuthContext = Depends(require_scoped_auth),
                              session: AsyncSession = Depends(get_session)):
    await ensure_module_access(session, ctx, tenant_id, "geo")
    if ctx.user_id is None or not (ctx.can_edit("geo.assets") and ctx.can_edit("geo.content")):
        raise HTTPException(403, "配置服务计划需要项目与内容编辑权限")
    from app.geo.project_workflows import save_plan
    values = req.model_dump(exclude={"expected_revision"})
    result = await save_plan(session, tenant_id, project_id, values, req.expected_revision, ctx.user_id)
    await session.commit()
    return {"project_id": project_id, "service_plan": result}


@geo_projects_router.get("/api/v1/geo/projects/{project_id}/executions")
async def project_executions(project_id: int, tenant_id: int,
                              ctx: AuthContext = Depends(require_scoped_auth),
                              session: AsyncSession = Depends(get_session)):
    await ensure_module_access(session, ctx, tenant_id, "geo")
    if not ctx.can_view("geo.content"):
        raise HTTPException(403, "查看执行需要内容查看权限")
    from app.models import GeoActionTicket, GeoPrompt
    from app.geo.project_scope import project_scope, prompt_ids_for_businesses, binding
    from app.geo.project_workflows import plan_for
    from app.geo.routes import build_ticket_execution_plan
    from app.geo.verify import ticket_public_dict
    project, business_ids = await project_scope(session, tenant_id, project_id)
    prompt_ids = await prompt_ids_for_businesses(session, tenant_id, business_ids)
    prompts = list(await session.scalars(select(GeoPrompt).where(GeoPrompt.tenant_id == tenant_id,
        GeoPrompt.id.in_(prompt_ids), GeoPrompt.status == "active", GeoPrompt.is_brand_probe.is_(False))
        .order_by(GeoPrompt.id).limit(201)))
    codes = [f"workqueue:v1:prompt-{pid}" for pid in prompt_ids]
    rows = list(await session.scalars(select(GeoActionTicket).where(GeoActionTicket.tenant_id == tenant_id,
        GeoActionTicket.advice_code.in_(codes)).order_by(GeoActionTicket.id.desc()).limit(21)))
    items = []
    for row in rows[:20]:
        execution = await build_ticket_execution_plan(session, row, tenant_id, project_id=project_id)
        items.append({"id": row.id, "title": row.title, "status": row.status, "ticket": ticket_public_dict(row), "execution": execution,
            "workflow": (row.progress or {}).get("project_workflow"),
            "links": {"ticket": f"/geo/tickets?ticket_id={row.id}",
                "content": f"/geo/tasks/{execution['selected_task_id']}" if execution["selected_task_id"] else None}})
    return {"project_id": project_id, "business_scope": binding(project), "service_plan": plan_for(project),
        "blocker": (project.project_settings or {}).get("geo_workflow_blocker"),
        "effective_pause": project.status != "active" or plan_for(project).get("status") != "active",
        "prompts": [{"id": p.id, "question": p.question} for p in prompts[:200]],
        "items": items, "truncated": len(rows) > 20, "prompts_truncated": len(prompts) > 200, "read_only": True}
