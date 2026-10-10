"""Project-scoped website delivery, independent of article publication and AI visibility."""
import asyncio
import hashlib
import ipaddress
import json
from datetime import date, datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from sqlalchemy import and_, or_, select

from app import onsite_workflow as work
from app.api_metering import background_scope
from app.database import get_session
from app.models import GeoProject, GeoActionTicket, GeoFact, GeoPrompt, Tenant
from app.security.auth import require_scoped_auth
from app.geo.project_scope import binding, project_scope, prompt_ids_for_businesses
from app.geo.project_workflows import PLAN_KEY, plan_for, advisor_available
from app.geo.tenant_scope import ensure_geo_entitlement
from app.geo.audit import safe_fetch, GeoAuditError
from app.geo.ai_client import DeepSeekError, chat_json
from app.geo.content.ai_settings import resolve_llm_credentials
from app.geo import onsite_ai

router = APIRouter()
PREFIX = "onsite:v1:"
MAX_PUBLIC_FACTS = 30
MAX_PRIORITY_QUESTIONS = 50

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


class AiProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tenant_id: PositiveInt
    project_id: PositiveInt
    expected_revision: int = Field(ge=1)
    request_id: UUID
    mode: Literal["initial", "revise"]

async def can_operate(session, ctx, project, *, lock_advisor=False):
    return bool(ctx.user_id and ctx.can_edit("geo.assets") and ctx.can_edit("geo.content")
        and project.status == "active" and plan_for(project).get("advisor_user_id") == ctx.user_id
        and await advisor_available(
            session, project.tenant_id, ctx.user_id, lock=lock_advisor))

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

def _next_action(value: dict) -> str:
    run = onsite_ai.projected_ai_run(value)
    if run and run.get("state") in {"failed", "unknown", "stale"}:
        return "人工核对 AI 调用状态后决定是否重新生成"
    return {
        "draft": "完善方案并提交人工审核",
        "review": "人工核对事实、范围与预期内容",
        "implementation": "按审核方案人工实施官网修改",
        "recheck": "对真实页面执行复检",
        "acceptance": "人工完成最终验收",
        "done": "已完成",
        "cancelled": "已取消",
    }.get(value.get("phase"), "人工核对任务状态")


def _blocker(value: dict, project: GeoProject) -> str | None:
    run = onsite_ai.projected_ai_run(value)
    if run and run.get("state") in {"failed", "unknown", "stale"}:
        return run.get("error") or "AI 方案生成需要人工处理"
    settings = project.project_settings if isinstance(project.project_settings, dict) else {}
    return settings.get("geo_workflow_blocker")


def public(row, project, can_write, *, provider_ready=False, tenant_name=None):
    value = dict(row.progress["onsite"])
    projected = onsite_ai.projected_ai_run(value)
    if projected:
        projected.pop("request_hash", None)
        value["ai_run"] = projected
    return dict(id=row.id, module="geo", tenant_id=row.tenant_id, scope_id=project.id,
        title=row.title, workflow=value, allowed_actions=work.allowed_actions(value, can_write),
        completion_evidence=dict(acceptance=value.get("acceptance"), recheck=value.get("recheck")) if value["phase"] == "done" else None,
        scope_name=project.name, tenant_name=tenant_name,
        next_action=_next_action(value), blocker=_blocker(value, project),
        capabilities=onsite_ai.capabilities(provider_ready=provider_ready, can_write=can_write,
                                            phase=value["phase"]))


async def _provider_ready(session, tenant_id: int) -> bool:
    return bool(await resolve_llm_credentials(session, tenant_id))


async def _public(session, row, project, can_write):
    tenant = await session.get(Tenant, row.tenant_id)
    return public(row, project, can_write,
                  provider_ready=await _provider_ready(session, row.tenant_id),
                  tenant_name=tenant.name if tenant else None)

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
    tenant = await session.get(Tenant, tenant_id)
    provider_ready = await _provider_ready(session, tenant_id)
    return dict(module="geo", tenant_id=tenant_id, scope_id=project_id, can_create=permitted,
        items=[public(r, project, permitted, provider_ready=provider_ready,
                      tenant_name=tenant.name if tenant else None) for r in rows[:20]],
        next_before_id=rows[19].id if len(rows) > 20 else None)


@router.get("/workbench/advisor-tasks")
async def advisor_tasks(tenant_id: PositiveInt | None = None, before_id: PositiveInt | None = None,
                        limit: int = Query(20, ge=1, le=50), session=Depends(get_session),
                        ctx=Depends(require_scoped_auth)):
    """Return only onsite tasks assigned to the authenticated real advisor."""
    if not ctx.user_id or not (ctx.can_edit("geo.assets") and ctx.can_edit("geo.content")):
        raise HTTPException(403, "需要实名 GEO 顾问及资产、内容编辑权限")
    if tenant_id is not None:
        ctx.ensure_tenant(tenant_id)
    query = select(GeoProject).where(
        GeoProject.status == "active",
        GeoProject.project_settings[PLAN_KEY]["advisor_user_id"].as_integer() == ctx.user_id,
    )
    if tenant_id is not None:
        query = query.where(GeoProject.tenant_id == tenant_id)
    if ctx.tenant_id is not None:
        query = query.where(GeoProject.tenant_id == ctx.tenant_id)
    candidates = list(await session.scalars(query.order_by(GeoProject.id)))
    projects: dict[int, GeoProject] = {}
    for project in candidates:
        try:
            await ensure_geo_entitlement(session, project.tenant_id, allow_demo_read=False, lock_binding=False)
            await project_scope(session, project.tenant_id, project.id)
            if await advisor_available(session, project.tenant_id, ctx.user_id):
                projects[project.id] = project
        except HTTPException:
            continue
    if not projects:
        return {"schema": 1, "module": "geo", "items": [], "next_before_id": None}
    stmt = select(GeoActionTicket).where(
        GeoActionTicket.advice_code.startswith(PREFIX),
        or_(*[
            and_(GeoActionTicket.tenant_id == project.tenant_id,
                 GeoActionTicket.progress["onsite"]["project_id"].as_integer() == project.id)
            for project in projects.values()
        ]),
    )
    if before_id is not None:
        stmt = stmt.where(GeoActionTicket.id < before_id)
    rows = list(await session.scalars(stmt.order_by(GeoActionTicket.id.desc()).limit(limit + 1)))
    items = []
    tenant_cache: dict[int, tuple[str | None, bool]] = {}
    for row in rows[:limit]:
        project = projects.get(int(row.progress["onsite"]["project_id"]))
        if project is None or row.tenant_id != project.tenant_id:
            continue
        if row.tenant_id not in tenant_cache:
            tenant = await session.get(Tenant, row.tenant_id)
            tenant_cache[row.tenant_id] = (
                tenant.name if tenant else None,
                await _provider_ready(session, row.tenant_id),
            )
        tenant_name, provider_ready = tenant_cache[row.tenant_id]
        items.append(public(row, project, True, provider_ready=provider_ready,
                            tenant_name=tenant_name))
    return {"schema": 1, "module": "geo", "items": items,
            "next_before_id": rows[limit - 1].id if len(rows) > limit else None}


def _verified_fact(row: GeoFact) -> bool:
    if row.status != "active" or row.trust_level != "verified" or not row.source_url:
        return False
    if row.expires_at is not None and row.expires_at < date.today():
        return False
    try:
        parsed = urlsplit(row.source_url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".internal")):
        return False
    try:
        if not ipaddress.ip_address(host).is_global:
            return False
    except ValueError:
        pass
    meta = row.meta if isinstance(row.meta, dict) else {}
    verification = meta.get("verification") if isinstance(meta.get("verification"), dict) else {}
    return bool(onsite_ai.public_use_authorized(meta)
                and (verification.get("verified_at") or meta.get("verified_at"))
                and (verification.get("excerpt") or meta.get("source_excerpt"))
                and (verification.get("excerpt_locator") or meta.get("excerpt_locator")))


async def _proposal_snapshot(session, project: GeoProject, row: GeoActionTicket) -> dict[str, Any]:
    """Freeze public, project-approved inputs; never include private fact metadata."""
    _, business_ids = await project_scope(session, project.tenant_id, project.id)
    plan = plan_for(project)
    current_prompt_ids = set(await prompt_ids_for_businesses(session, project.tenant_id, business_ids))
    selected_ids = [int(value) for value in plan.get("prompt_ids", []) if int(value) in current_prompt_ids]
    if len(selected_ids) > MAX_PRIORITY_QUESTIONS:
        raise HTTPException(409, f"当前项目重点问题超过 {MAX_PRIORITY_QUESTIONS} 条，请缩小服务计划范围")
    prompts = list(await session.scalars(select(GeoPrompt).where(
        GeoPrompt.tenant_id == project.tenant_id,
        GeoPrompt.id.in_(selected_ids or [-1]),
        GeoPrompt.status == "active",
        GeoPrompt.is_brand_probe.is_(False),
    ).order_by(GeoPrompt.id)))
    facts = list(await session.scalars(select(GeoFact).where(
        GeoFact.tenant_id == project.tenant_id,
        GeoFact.status == "active",
        or_(GeoFact.business_id.is_(None), GeoFact.business_id.in_(business_ids or [-1])),
    ).order_by(GeoFact.id)))
    approved_facts = [onsite_ai.public_source(fact) for fact in facts if _verified_fact(fact)]
    if len(approved_facts) > MAX_PUBLIC_FACTS:
        raise HTTPException(409, f"当前项目获准公开事实超过 {MAX_PUBLIC_FACTS} 条，请缩小事实范围")
    workflow = row.progress["onsite"]
    payload = {
        "project": {
            "id": project.id,
            "name": project.name,
            "brand_name": project.brand_name,
            "domain": project.canonical_domain,
            "scope_revision": binding(project)["revision"],
            "plan_revision": int(plan.get("revision") or 0),
        },
        "questions": [{"id": prompt.id, "question": prompt.question} for prompt in prompts],
        "facts": approved_facts,
        "items": [dict(item) for item in workflow["items"]],
        "workflow_revision": int(workflow["revision"]),
    }
    payload["source_hash"] = onsite_ai.source_hash(payload)
    return payload


async def _finish_run(session, task_id: int, request_id: str, *, state: str,
                      error: str | None = None) -> None:
    row = await session.get(GeoActionTicket, task_id, with_for_update=True, populate_existing=True)
    if row is None:
        await session.rollback()
        return
    value = dict((row.progress or {}).get("onsite") or {})
    run = dict(value.get("ai_run") or {})
    if run.get("request_id") != request_id:
        await session.rollback()
        return
    run.update(state=state, finished_at=onsite_ai.now_iso())
    if error:
        run["error"] = error[:500]
    else:
        run.pop("error", None)
    value["ai_run"] = run
    row.progress = {**(row.progress or {}), "onsite": value}
    row.updated_at = datetime.utcnow()
    await session.commit()


@router.post("/workbench/onsite-tasks/{task_id}/ai-proposal")
async def ai_proposal(task_id: PositiveInt, req: AiProposal, session=Depends(get_session),
                      ctx=Depends(require_scoped_auth)):
    """Reserve, draft and save an AI proposal with save_proposal semantics."""
    project = await scope(session, ctx, req.tenant_id, req.project_id, True)
    row = await session.get(GeoActionTicket, task_id, with_for_update=True, populate_existing=True)
    if (not row or row.tenant_id != req.tenant_id or not (row.advice_code or "").startswith(PREFIX)
            or (row.progress or {}).get("onsite", {}).get("project_id") != project.id):
        raise HTTPException(404, "当前项目的站内任务不存在")
    value = dict(row.progress["onsite"])
    request_id = str(req.request_id)
    digest = onsite_ai.request_hash(task_id=task_id, tenant_id=req.tenant_id,
                                    project_id=req.project_id,
                                    expected_revision=req.expected_revision, mode=req.mode,
                                    actor_user_id=ctx.user_id)
    existing_run = value.get("ai_run") if isinstance(value.get("ai_run"), dict) else None
    if existing_run and existing_run.get("request_id") == request_id:
        if existing_run.get("request_hash") != digest:
            raise HTTPException(409, "请求编号已用于不同的 AI 方案参数")
        return await _public(session, row, project, True)
    if value["revision"] != req.expected_revision:
        raise HTTPException(409, "任务版本已变化，请重新读取核对后操作")
    if "save_proposal" not in work.allowed_actions(value, True):
        raise HTTPException(409, "当前任务状态不能生成 AI 方案")
    if (req.mode == "initial") != (value["phase"] == "draft"):
        raise HTTPException(409, "draft 阶段使用 initial，其余可写阶段使用 revise")
    if len(value.get("history") or []) >= 100:
        raise HTTPException(409, "任务历史达到上限，请保留记录并建立后续任务")
    projected = onsite_ai.projected_ai_run(value)
    if projected and projected.get("state") == "running":
        raise HTTPException(409, "当前任务已有 AI 方案正在生成")
    credentials = await resolve_llm_credentials(session, req.tenant_id)
    if not credentials:
        raise HTTPException(409, "平台 AI 供应商尚未配置")
    snapshot = await _proposal_snapshot(session, project, row)
    system_prompt, user_prompt = onsite_ai.prompt_text(snapshot, req.mode)
    project.project_settings = onsite_ai.reserve_daily(
        project.project_settings, request_id, request_digest=digest)
    started = onsite_ai.now_iso()
    value["ai_run"] = {
        "request_id": request_id,
        "request_hash": digest,
        "state": "running",
        "mode": req.mode,
        "source_revision": req.expected_revision,
        "source_hash": snapshot["source_hash"],
        "actor_user_id": ctx.user_id,
        "started_at": started,
    }
    row.progress = {**(row.progress or {}), "onsite": value}
    row.updated_at = datetime.utcnow()
    await session.commit()  # release project/task locks before the provider request

    try:
        with background_scope(tenant_id=req.tenant_id, module="geo",
                              operation="onsite.ai_proposal", user_id=ctx.user_id,
                              job_ref=f"geo-onsite-ai:{task_id}:{request_id}"):
            result = await chat_json(system_prompt, user_prompt, timeout=45.0,
                api_key=credentials["api_key"], base_url=credentials["base_url"],
                model=credentials["model"])
    except DeepSeekError:
        await _finish_run(session, task_id, request_id, state="unknown",
                          error="AI 供应商结果未知，系统未自动重试；请核对调用记录后决定下一步")
        raise HTTPException(424, "AI 供应商结果未知，未自动重试") from None
    except Exception:
        await _finish_run(session, task_id, request_id, state="unknown",
                          error="AI 调用未能确认结果，系统未自动重试")
        raise HTTPException(424, "AI 调用结果未知，未自动重试") from None

    try:
        # Entitlement and assignment are revalidated after the paid call.
        await ensure_geo_entitlement(session, req.tenant_id, allow_demo_read=False, lock_binding=True)
        project = await session.get(GeoProject, req.project_id, with_for_update=True, populate_existing=True)
        row = await session.get(GeoActionTicket, task_id, with_for_update=True, populate_existing=True)
        if (project is None or row is None or project.tenant_id != req.tenant_id
                or row.tenant_id != req.tenant_id
                or (row.progress or {}).get("onsite", {}).get("project_id") != project.id):
            raise HTTPException(404, "当前项目的站内任务不存在")
        current = dict(row.progress["onsite"])
        run = dict(current.get("ai_run") or {})
        if run.get("request_id") != request_id:
            raise HTTPException(409, "AI 任务已被其他请求替代")
        if not await can_operate(session, ctx, project, lock_advisor=True):
            await _finish_run(session, task_id, request_id, state="stale",
                              error="项目顾问分配或编辑权限已变化，AI 结果未保存")
            raise HTTPException(409, "项目顾问分配或编辑权限已变化，AI 结果未保存")
        fresh = await _proposal_snapshot(session, project, row)
        if (current["revision"] != req.expected_revision
                or fresh["source_hash"] != snapshot["source_hash"]):
            await _finish_run(session, task_id, request_id, state="stale",
                              error="任务版本、项目范围或事实资料已变化，AI 结果未覆盖当前方案")
            raise HTTPException(409, "任务或资料已变化，AI 结果未保存")
        items, explanation = onsite_ai.validate_provider_result(
            result, current_items=current["items"], facts=fresh["facts"],
            domain=project.canonical_domain)
        deterministic_missing = []
        if not fresh["facts"]:
            deterministic_missing.append("缺少当前项目范围内已核验、未过期且明确授权公开使用的事实资料")
        if not fresh["questions"]:
            deterministic_missing.append("缺少当前项目服务计划中的有效重点问题")
        explanation["missing_information"] = list(dict.fromkeys([
            *deterministic_missing, *explanation.get("missing_information", [])
        ]))[:50]
        change = work.Change(action="save_proposal", expected_revision=req.expected_revision,
                             items=items, note="AI 起草，等待人工核对")
        updated = work.prepare_change(current, change, "geo", project.canonical_domain, ctx.user_id)
        explanation["proposal_revision"] = updated["revision"]
        updated["ai_proposal"] = explanation
        updated["ai_run"] = {
            **run,
            "state": "ready",
            "finished_at": onsite_ai.now_iso(),
        }
        row.progress = {**(row.progress or {}), "onsite": updated}
        row.status = "doing"
        row.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(row)
        return await _public(session, row, project, True)
    except HTTPException as exc:
        if exc.status_code == 422:
            await _finish_run(session, task_id, request_id, state="failed",
                              error="AI 返回内容未通过站内方案安全校验")
        raise

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
        return await _public(session, existing, project, True)
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
    return await _public(session, row, project, True)

@router.post("/workbench/onsite-tasks/{task_id}/actions")
async def act(task_id: PositiveInt, req: Update, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    project = await scope(session, ctx, req.tenant_id, req.project_id, True)
    row = await session.get(GeoActionTicket, task_id, with_for_update=True, populate_existing=True)
    if (not row or row.tenant_id != req.tenant_id or not (row.advice_code or "").startswith(PREFIX)
            or (row.progress or {}).get("onsite", {}).get("project_id") != project.id):
        raise HTTPException(404, "当前项目的站内任务不存在")
    value = work.prepare_change(row.progress["onsite"], req, "geo", project.canonical_domain, ctx.user_id)
    if req.action == "save_proposal":
        # A human edit creates a new proposal revision. Old AI reasoning must not
        # be presented as support for content it did not produce.
        value.pop("ai_proposal", None)
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
    return await _public(session, row, project, True)

