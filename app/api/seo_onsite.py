"""SEO onsite tasks reuse the ledger and the live site advisor assignment."""
import asyncio
import hashlib
import json
from typing import Literal
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from sqlalchemy import select

from app import onsite_workflow as work
from app.api.seo_service_workflows import read_scope, can_operate
from app.models.module_workspace import SeoSite
from app.models.seo import SeoKeywordAsset, SeoSitePage
from app.models.seo_cockpit import SeoTask
from app.seo_demo_source import get_seo_session as get_session, require_seo_scoped_auth as require_scoped_auth
from app.seo_crawler import fetch_url

router = APIRouter()
ACTION_TYPE = "onsite_optimization"

class Create(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tenant_id: PositiveInt
    site_id: PositiveInt
    request_id: UUID
    work_type: Literal["startup", "monthly", "remediation"]
    month: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    keyword_ids: list[PositiveInt] = Field(default_factory=list, max_length=3)
    page_ids: list[PositiveInt] = Field(default_factory=list, max_length=3)
    owner_name: str = Field(min_length=1, max_length=100)

class Update(work.Change):
    tenant_id: PositiveInt
    site_id: PositiveInt

async def scope(session, ctx, tenant_id, site_id, write=False):
    site = await read_scope(session, ctx, tenant_id, site_id)
    if write:
        site = await session.get(SeoSite, site_id, with_for_update=True, populate_existing=True)
        if not await can_operate(session, ctx, site):
            raise HTTPException(403, "需要当前网站有效顾问分配及网站、内容编辑权限")
    return site

def public(row, can_write, site_settings=None, can_ai=None):
    from app.seo_onsite_ai import capabilities
    value = row.params["onsite"]
    actions = work.allowed_actions(value, can_write)
    if value.get("ai_run", {}).get("state") in {"queued", "running"}:
        actions = [action for action in actions if action == "cancel"]
    return dict(id=row.id, module="seo", tenant_id=row.tenant_id, scope_id=row.site_id, title=row.title,
                workflow=value, allowed_actions=actions,
                completion_evidence=row.completion_evidence,
                capabilities=capabilities(value, can_write if can_ai is None else can_ai, site_settings,
                                          len(row.params.get("onsite_ai_requests") or {})))

async def sources_current(session, row):
    source = row.params["onsite"]["source"]
    for old in source.get("keywords", []):
        kw = await session.get(SeoKeywordAsset, old["id"], populate_existing=True)
        if (not kw or kw.tenant_id != row.tenant_id or kw.site_id != row.site_id or kw.status != "active"
                or kw.keyword != old["keyword"] or kw.landing_page != old["landing_page"]):
            raise HTTPException(409, "重点关键词或部署页面已变化，请重新建立任务")
    for old in source.get("pages", []):
        page = await session.get(SeoSitePage, old["id"], populate_existing=True)
        if not page or page.tenant_id != row.tenant_id or page.site_id != row.site_id or page.url != old["url"]:
            raise HTTPException(409, "页面归属或地址已变化，请重新建立任务")

@router.get("/workbench/onsite-tasks")
async def list_tasks(tenant_id: PositiveInt, site_id: PositiveInt, before_id: PositiveInt | None = None,
                     session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    site = await scope(session, ctx, tenant_id, site_id)
    query = select(SeoTask).where(SeoTask.tenant_id == tenant_id, SeoTask.site_id == site_id, SeoTask.action_type == ACTION_TYPE)
    if before_id:
        query = query.where(SeoTask.id < before_id)
    rows = list(await session.scalars(query.order_by(SeoTask.id.desc()).limit(21)))
    can_write = await can_operate(session, ctx, site)
    return dict(module="seo", tenant_id=tenant_id, scope_id=site_id, can_create=can_write,
                items=[public(r, can_write, site.site_settings, can_write and ctx.can_view("seo.keywords")) for r in rows[:20]],
                next_before_id=rows[19].id if len(rows) > 20 else None)

@router.post("/workbench/onsite-tasks")
async def create(req: Create, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    site = await scope(session, ctx, req.tenant_id, req.site_id, True)
    key = str(req.request_id)
    request_hash = hashlib.sha256(json.dumps(req.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    existing = await session.scalar(select(SeoTask).where(SeoTask.tenant_id == req.tenant_id,
        SeoTask.site_id == req.site_id, SeoTask.action_type == ACTION_TYPE,
        SeoTask.params["request_id"].astext == key).limit(1))
    if existing:
        if existing.params.get("request_hash") != request_hash:
            raise HTTPException(409, "请求编号已用于不同任务参数")
        return public(existing, True, site.site_settings, ctx.can_view("seo.keywords"))
    kw_query = select(SeoKeywordAsset).where(SeoKeywordAsset.tenant_id == req.tenant_id,
        SeoKeywordAsset.site_id == req.site_id, SeoKeywordAsset.status == "active")
    if req.keyword_ids:
        kw_query = kw_query.where(SeoKeywordAsset.id.in_(req.keyword_ids))
    else:
        kw_query = kw_query.where(SeoKeywordAsset.priority.in_(["P0", "P1"]))
    keywords = list(await session.scalars(kw_query.order_by(SeoKeywordAsset.priority, SeoKeywordAsset.id).limit(3)))
    if req.keyword_ids and set(req.keyword_ids) != {k.id for k in keywords}:
        raise HTTPException(404, "关键词不属于当前网站或已停用")
    if req.work_type == "monthly" and not keywords:
        raise HTTPException(409, "请先设置当月重点关键词；未指定时采用本站 P0/P1 关键词（最多 3 个）")
    page_query = select(SeoSitePage).where(SeoSitePage.tenant_id == req.tenant_id, SeoSitePage.site_id == req.site_id)
    if req.page_ids:
        page_query = page_query.where(SeoSitePage.id.in_(req.page_ids))
    elif req.work_type == "monthly":
        page_query = page_query.where(SeoSitePage.url.in_([k.landing_page for k in keywords if k.landing_page]))
    pages = list(await session.scalars(page_query.order_by(SeoSitePage.id).limit(3)))
    if req.page_ids and set(req.page_ids) != {p.id for p in pages}:
        raise HTTPException(404, "页面不属于当前网站")
    if req.work_type == "monthly" and (not pages or any(k.landing_page not in {p.url for p in pages} for k in keywords)):
        raise HTTPException(409, "每个重点关键词需要绑定本站已登记的部署页面，请先补齐页面和 landing_page")
    domain = site.canonical_domain
    base = f"https://{domain}/"
    items = []
    def add(id, kind, url, expected, instruction):
        items.append(dict(id=id, kind=kind, target_url=url, expected=expected or "", instruction=instruction))
    if req.work_type == "startup":
        add("robots", "robots", base+"robots.txt", "", "核对抓取许可并填写经审核的 robots 内容片段。")
        add("sitemap", "sitemap", base+"sitemap.xml", "", "填写实际网站地图地址及需要核对的 XML 内容片段。")
        add("architecture", "canonical", pages[0].url if pages else base, "",
            "梳理栏目层级、URL、重复页与索引策略；记录实施说明，填写该代表页面预期规范地址。此项静态检查仅验证 canonical。")
    else:
        if not pages:
            raise HTTPException(409, "请先登记需要优化的本站页面")
        for page in pages:
            related = [k for k in keywords if k.landing_page == page.url]
            add(f"title-{page.id}", "title", page.url, page.title_suggestion, "根据当月重点关键词和当前页面事实制定 Title。")
            add(f"description-{page.id}", "description", page.url, page.description_suggestion, "补齐 Description，核对型号、事实与适用范围。")
            add(f"meta-keywords-{page.id}", "meta_keywords", page.url, ",".join(k.keyword for k in related),
                "核对该页面的 Meta Keywords，与当月重点词匹配；此字段匹配不能证明排名提升。")
            for kw in related:
                add(f"keyword-{kw.id}", "keyword", page.url, kw.keyword, "在正文及合适标题部署关键词，避免堆砌；静态复检检查正文包含。")
            add(f"link-{page.id}", "internal_link", page.url, "", "选择本站相关内容作为内链目标，人工核对锚文本与链接相关性。")
    workflow = work.new_workflow("seo", req.work_type, req.month, domain, items, ctx.user_id, req.owner_name,
        dict(keywords=[dict(id=k.id, keyword=k.keyword, landing_page=k.landing_page) for k in keywords],
             pages=[dict(id=p.id, url=p.url) for p in pages]))
    row = SeoTask(tenant_id=req.tenant_id, site_id=req.site_id, module="seo", action_type=ACTION_TYPE,
        title={"startup":"SEO 启动站内基础建设", "monthly":"SEO 月度站内优化", "remediation":"SEO 站内专项整改"}[req.work_type],
        params=dict(request_id=key, request_hash=request_hash, onsite=workflow), status="open", created_by=str(ctx.user_id),
        assignee_role="seo_advisor", baseline={})
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return public(row, True, site.site_settings, ctx.can_view("seo.keywords"))

@router.post("/workbench/onsite-tasks/{task_id}/actions")
async def act(task_id: PositiveInt, req: Update, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    site = await scope(session, ctx, req.tenant_id, req.site_id, True)
    row = await session.get(SeoTask, task_id, with_for_update=True, populate_existing=True)
    if not row or row.tenant_id != req.tenant_id or row.site_id != req.site_id or row.action_type != ACTION_TYPE:
        raise HTTPException(404, "当前网站的站内任务不存在")
    if req.action != "cancel" and row.params["onsite"].get("ai_run", {}).get("state") in {"queued", "running"}:
        raise HTTPException(409, {"code": "onsite_ai_busy", "message": "AI 方案正在排队或生成，请等待或先取消请求"})
    if req.action != "cancel":
        await sources_current(session, row)
    value = work.prepare_change(row.params["onsite"], req, "seo", site.canonical_domain, ctx.user_id)
    if req.action == "save_proposal":
        value.pop("ai_proposal", None)
    if req.action == "recheck":
        site.site_settings = work.reserve_recheck(site.site_settings)
        async def fetch(url, kind):
            try:
                async with asyncio.timeout(20):
                    result = await fetch_url(url, allow_text=kind in {"robots", "llms"}, allow_xml=kind=="sitemap",
                        allowed_hosts=work.host_scope(site.canonical_domain))
                if result.error_type or result.status_code != 200:
                    raise HTTPException(424, "页面不可读取")
                return dict(body=result.body, url=result.final_url)
            except TimeoutError:
                raise HTTPException(424, "页面读取超时")
        value = await work.recheck(value, fetch)
    row.params = {**row.params, "onsite": value}
    active = value.get("ai_run") or {}
    if req.action == "cancel" and active.get("state") in {"queued", "running"}:
        from app.api.seo_onsite_ai import save_run
        run = row.params["onsite_ai_requests"][active["request_id"]]
        save_run(row, {**run, "state": "cancelled" if run["state"] == "queued" else "unknown",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": {"code": "onsite_ai_task_cancelled", "message": "任务已取消，生成结果不再采用；已开始的调用需人工核对"}})
    row.status = {"done":"done", "cancelled":"cancelled"}.get(value["phase"], "in_progress")
    if value["phase"] == "done":
        row.completion_evidence = dict(acceptance=value["acceptance"], recheck=value["recheck"],
            note="站内交付验收；不代表已收录、排名或 AI 引用增长")
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return public(row, True, site.site_settings, ctx.can_view("seo.keywords"))

