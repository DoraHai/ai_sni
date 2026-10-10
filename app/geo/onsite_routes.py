"""Project-scoped website delivery, independent of article publication and AI visibility."""
import asyncio
import hashlib
import json
from typing import Literal
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from sqlalchemy import select

from app import onsite_workflow as work
from app.database import get_session
from app.models import GeoProject, GeoActionTicket
from app.security.auth import require_scoped_auth
from app.geo.project_scope import project_scope
from app.geo.project_workflows import plan_for, advisor_available
from app.geo.tenant_scope import ensure_geo_entitlement
from app.geo.audit import safe_fetch, GeoAuditError

router = APIRouter()
PREFIX = "onsite:v1:"

class Create(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tenant_id: PositiveInt
    project_id: PositiveInt
    request_id: UUID
    work_type: Literal["startup", "monthly", "remediation"]
    month: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    owner_name: str = Field(min_length=1, max_length=100)

class Update(work.Change):
    tenant_id: PositiveInt
    project_id: PositiveInt

async def can_operate(session, ctx, project):
    return bool(ctx.user_id and ctx.can_edit("geo.assets") and ctx.can_edit("geo.content")
        and project.status == "active" and plan_for(project).get("advisor_user_id") == ctx.user_id
        and await advisor_available(session, project.tenant_id, ctx.user_id))

async def scope(session, ctx, tenant_id, project_id, write=False):
    ctx.ensure_tenant(tenant_id)
    if not (ctx.can_view("geo.assets") and ctx.can_view("geo.content")):
        raise HTTPException(403, "需要官网资产与内容查看权限")
    await ensure_geo_entitlement(session, tenant_id, allow_demo_read=not write, lock_binding=write)
    project, _ = await project_scope(session, tenant_id, project_id)
    if write:
        project = await session.get(GeoProject, project_id, with_for_update=True, populate_existing=True)
        if not await can_operate(session, ctx, project):
            raise HTTPException(403, "需要当前项目有效顾问分配及资产、内容编辑权限；请先配置项目服务计划")
    return project

def public(row, project, can_write):
    value = row.progress["onsite"]
    return dict(id=row.id, module="geo", tenant_id=row.tenant_id, scope_id=project.id,
        title=row.title, workflow=value, allowed_actions=work.allowed_actions(value, can_write),
        completion_evidence=dict(acceptance=value.get("acceptance"), recheck=value.get("recheck")) if value["phase"] == "done" else None)

@router.get("/workbench/onsite-tasks")
async def list_tasks(tenant_id: PositiveInt, project_id: PositiveInt, before_id: PositiveInt | None = None,
                     session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    project = await scope(session, ctx, tenant_id, project_id)
    query = select(GeoActionTicket).where(GeoActionTicket.tenant_id == tenant_id,
        GeoActionTicket.advice_code.startswith(PREFIX),
        GeoActionTicket.progress["onsite"]["project_id"].as_integer() == project_id)
    if before_id:
        query = query.where(GeoActionTicket.id < before_id)
    rows = list(await session.scalars(query.order_by(GeoActionTicket.id.desc()).limit(21)))
    permitted = await can_operate(session, ctx, project)
    return dict(module="geo", tenant_id=tenant_id, scope_id=project_id, can_create=permitted,
        items=[public(r, project, permitted) for r in rows[:20]],
        next_before_id=rows[19].id if len(rows) > 20 else None)

@router.post("/workbench/onsite-tasks")
async def create(req: Create, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    project = await scope(session, ctx, req.tenant_id, req.project_id, True)
    code = PREFIX + str(req.request_id)
    request_hash = hashlib.sha256(json.dumps(req.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    existing = await session.scalar(select(GeoActionTicket).where(GeoActionTicket.tenant_id == req.tenant_id,
        GeoActionTicket.advice_code == code).limit(1))
    if existing:
        if existing.progress["onsite"]["project_id"] != project.id:
            raise HTTPException(409, "此请求编号已用于其他项目")
        if existing.progress["onsite"].get("request_hash") != request_hash:
            raise HTTPException(409, "请求编号已用于不同任务参数")
        return public(existing, project, True)
    domain = project.canonical_domain
    base = f"https://{domain}/"
    definitions = [
        ("structured_content", base, "按实体、产品、服务、适用范围、出处和更新时间组织官网内容，填写需要核对的完整内容片段。"),
        ("knowledge", base, "填写实际知识库页面地址与审核过的知识片段，维护事实来源、版本和适用范围。"),
        ("faq", base, "填写实际 FAQ 页地址与审核过的问答片段，问答需要在页面可见。"),
        ("schema", base, "填写实际页面地址与审核 JSON；标记必须对应页面可见内容，复检核对 JSON 子集。"),
        ("llms", base+"llms.txt", "填写审核过的文件片段及官网、知识库、FAQ 入口；文件需有 Markdown 主标题。"),
    ]
    items = [dict(id=kind, kind=kind, target_url=url, expected="", instruction=instruction)
             for kind, url, instruction in definitions]
    value = work.new_workflow("geo", req.work_type, req.month, domain, items, ctx.user_id, req.owner_name)
    value["project_id"] = project.id
    value["request_hash"] = request_hash
    row = GeoActionTicket(tenant_id=req.tenant_id, advice_code=code, title="GEO 官网与知识内容建设",
        priority="medium", status="todo", owner_name=req.owner_name,
        action="保存审核版本，网站实施后真实复检并人工验收。",
        acceptance_type="manual", acceptance_check="onsite.versioned_delivery",
        acceptance_desc="结构化官网、知识库、FAQ、Schema 与 llms.txt 的当前审核版本均已实施并复检；人工核对事实和质量。",
        created_by=ctx.user_id, progress={"onsite": value}, evidence=[])
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return public(row, project, True)

@router.post("/workbench/onsite-tasks/{task_id}/actions")
async def act(task_id: PositiveInt, req: Update, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    project = await scope(session, ctx, req.tenant_id, req.project_id, True)
    row = await session.get(GeoActionTicket, task_id, with_for_update=True, populate_existing=True)
    if (not row or row.tenant_id != req.tenant_id or not (row.advice_code or "").startswith(PREFIX)
            or (row.progress or {}).get("onsite", {}).get("project_id") != project.id):
        raise HTTPException(404, "当前项目的站内任务不存在")
    value = work.prepare_change(row.progress["onsite"], req, "geo", project.canonical_domain, ctx.user_id)
    if req.action == "recheck":
        project.project_settings = work.reserve_recheck(project.project_settings)
        async def fetch(url, kind):
            try:
                async with asyncio.timeout(20):
                    doc = await safe_fetch(url, allow_text=kind == "llms", allowed_hosts=work.host_scope(project.canonical_domain))
                return dict(body=doc.html, url=doc.final_url)
            except (GeoAuditError, TimeoutError) as exc:
                raise HTTPException(424, "页面读取失败") from exc
        value = await work.recheck(value, fetch)
    row.progress = {**(row.progress or {}), "onsite": value}
    row.status = {"done":"done", "cancelled":"blocked"}.get(value["phase"], "doing")
    row.owner_name = value["owner_name"]
    row.updated_at = datetime.utcnow()
    if value["phase"] == "done":
        row.last_verdict, row.last_verify_at, row.closed_at = "pass", datetime.utcnow(), datetime.utcnow()
        row.last_note = req.note
    await session.commit()
    await session.refresh(row)
    return public(row, project, True)

