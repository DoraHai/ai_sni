"""GEO 网站诊断、AI 整改建议、结构化资产与诊断中心共享资料。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import DeepSeekError, is_enabled as ai_enabled
from app.config import get_settings
from app.database import get_session
from app.geo.ai_sampling import (
    build_neutral_questions,
    clean_questions,
    run_deepseek_sample,
)
from app.geo.audit import RULE_VERSION, RULE_WEIGHTS, GeoAuditError, audit_url
from app.geo.generate import ai_advice, generate_json_ld, generate_llms_text
from app.models import GeoAuditRun, Tenant
from app.models.tenant_memory import TenantMemory
from app.security.auth import AuthContext, require_scoped_auth

router = APIRouter(
    prefix="/api/v1/geo",
    tags=["GEO 诊断"],
    dependencies=[Depends(require_scoped_auth)],
)


class AuditCreate(BaseModel):
    tenant_id: int
    url: str = Field(..., min_length=4, max_length=2048)


class AISampleCreate(BaseModel):
    tenant_id: int
    questions: list[str] = Field(default_factory=list, max_length=3)


class BrandAssetUpdate(BaseModel):
    tenant_id: int
    name: str = Field(..., min_length=1, max_length=100)
    website: str = Field(default="", max_length=2048)
    industry: str = Field(default="", max_length=100)
    business_desc: str = Field(default="", max_length=20000)
    brand_terms: list[str] = Field(default_factory=list, max_length=50)
    core_products: list[str] = Field(default_factory=list, max_length=100)
    proof_points: list[str] = Field(default_factory=list, max_length=100)


class AudienceAssetUpdate(BaseModel):
    tenant_id: int
    segments: list[str] = Field(default_factory=list, max_length=100)
    decision_roles: list[str] = Field(default_factory=list, max_length=100)
    pain_points: list[str] = Field(default_factory=list, max_length=100)
    search_scenarios: list[str] = Field(default_factory=list, max_length=100)


class KnowledgeCreate(BaseModel):
    tenant_id: int
    title: str = Field(..., min_length=1, max_length=200)
    item_type: str = Field(default="other", max_length=30)
    body: str = Field(..., min_length=1, max_length=100000)
    source_url: str = Field(default="", max_length=2048)


def _ensure_asset_edit(ctx: AuthContext) -> None:
    if not ctx.can_edit("geo.diagnosis"):
        raise HTTPException(403, "当前账号只有查看权限，无法修改品牌资产")


def _json_content(memory: TenantMemory | None) -> dict[str, Any]:
    if memory is None:
        return {}
    try:
        value = json.loads(memory.content)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


async def _latest_memory(
    session: AsyncSession, tenant_id: int, mem_type: str
) -> TenantMemory | None:
    return await session.scalar(
        select(TenantMemory)
        .where(
            TenantMemory.tenant_id == tenant_id,
            TenantMemory.mem_type == mem_type,
            TenantMemory.active.is_(True),
        )
        .order_by(TenantMemory.id.desc())
        .limit(1)
    )


async def _upsert_memory(
    session: AsyncSession,
    *,
    tenant_id: int,
    mem_type: str,
    data: dict[str, Any],
    ctx: AuthContext,
) -> TenantMemory:
    memory = await _latest_memory(session, tenant_id, mem_type)
    content = json.dumps(data, ensure_ascii=False)
    if memory is None:
        memory = TenantMemory(
            tenant_id=tenant_id,
            mem_type=mem_type,
            content=content,
            source="manual",
            confirmed=True,
            active=True,
            operator_user_id=ctx.user_id,
            operator_name=ctx.username,
        )
        session.add(memory)
    else:
        memory.content = content
        memory.source = "manual"
        memory.confirmed = True
        memory.operator_user_id = ctx.user_id
        memory.operator_name = ctx.username
    return memory


def _knowledge_payload(memory: TenantMemory) -> dict[str, Any]:
    data = _json_content(memory)
    return {
        "id": memory.id,
        "title": data.get("title", "未命名资料"),
        "item_type": data.get("item_type", "other"),
        "body": data.get("body", ""),
        "source_url": data.get("source_url", ""),
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }


def _payload(run: GeoAuditRun) -> dict[str, Any]:
    findings = [
        {
            **item,
            # 兼容 v1.0 已落库的记录：旧数据只有实际扣分，没有固定规则权重。
            "weight": item.get(
                "weight",
                RULE_WEIGHTS.get(item.get("code"), item.get("deduction", 0)),
            ),
        }
        for item in (run.findings or [])
    ]
    return {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "url": run.url,
        "final_url": run.final_url,
        "status": run.status,
        "score": run.score,
        "page_title": run.page_title,
        "page_description": run.page_description,
        "snapshot": run.snapshot or {},
        "findings": findings,
        "problems": [item for item in findings if not item.get("passed")],
        "advice": run.advice or [],
        "advice_source": run.advice_source,
        "json_ld": run.json_ld,
        "llms_text": run.llms_text,
        "ai_enabled": ai_enabled(),
        "rule_version": RULE_VERSION,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


async def _run_for_tenant(
    session: AsyncSession, audit_id: int, tenant_id: int
) -> GeoAuditRun:
    run = await session.get(GeoAuditRun, audit_id)
    if run is None or run.tenant_id != tenant_id:
        raise HTTPException(404, "GEO 诊断记录不存在")
    return run


@router.post("/audits")
async def create_audit(
    req: AuditCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    tenant = await session.get(Tenant, req.tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")
    try:
        result = await audit_url(req.url)
    except GeoAuditError as exc:
        raise HTTPException(400, str(exc)) from exc
    run = GeoAuditRun(
        tenant_id=req.tenant_id,
        url=result["url"],
        final_url=result["final_url"],
        status="completed",
        score=result["score"],
        page_title=result["title"],
        page_description=result["description"],
        snapshot=result["snapshot"],
        findings=result["checks"],
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return _payload(run)


@router.get("/audits/latest")
async def latest_audit(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    run = await session.scalar(
        select(GeoAuditRun)
        .where(GeoAuditRun.tenant_id == tenant_id)
        .order_by(GeoAuditRun.created_at.desc(), GeoAuditRun.id.desc())
        .limit(1)
    )
    return {"audit": _payload(run) if run else None}


@router.get("/audits/{audit_id}")
async def get_audit(
    audit_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    return _payload(await _run_for_tenant(session, audit_id, tenant_id))


@router.post("/audits/{audit_id}/advice")
async def create_advice(
    audit_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    run = await _run_for_tenant(session, audit_id, tenant_id)
    tenant = await session.get(Tenant, tenant_id)
    advice, source = await ai_advice(
        tenant_name=tenant.name if tenant else "当前品牌",
        url=run.final_url or run.url,
        score=run.score or 0,
        title=run.page_title or "",
        description=run.page_description or "",
        findings=run.findings or [],
    )
    run.advice = advice
    run.advice_source = source
    await session.commit()
    await session.refresh(run)
    return _payload(run)


@router.post("/audits/{audit_id}/ai-sample")
async def create_ai_sample(
    audit_id: int,
    req: AISampleCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """使用真实 DeepSeek 回答执行单平台品牌提及抽样。"""
    ctx.ensure_tenant(req.tenant_id)
    if not ai_enabled():
        raise HTTPException(503, "DeepSeek 抽样服务暂未启用")
    run = await _run_for_tenant(session, audit_id, req.tenant_id)
    tenant = await session.get(Tenant, req.tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")

    brand_asset = _json_content(
        await _latest_memory(session, req.tenant_id, "brand_asset")
    )
    audience = _json_content(
        await _latest_memory(session, req.tenant_id, "audience_profile")
    )
    brand_terms = list(
        dict.fromkeys(
            item.strip()
            for item in [tenant.name, *(tenant.brand_terms or [])]
            if item and item.strip()
        )
    )
    try:
        questions = clean_questions(req.questions, brand_terms)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not questions:
        questions = build_neutral_questions(
            industry=tenant.industry or "",
            core_products=brand_asset.get("core_products") or [],
            audience_segments=audience.get("segments") or [],
            brand_terms=brand_terms,
        )
    try:
        sample = await run_deepseek_sample(
            questions=questions,
            brand_name=tenant.name,
            brand_terms=brand_terms,
            model=get_settings().deepseek_model,
        )
    except DeepSeekError as exc:
        # API 客户端已完成一次重试；路由只暴露可操作的失败信息，不泄露密钥或响应体。
        raise HTTPException(502, "DeepSeek 抽样失败，请稍后重试") from exc

    snapshot = dict(run.snapshot or {})
    snapshot["ai_sampling"] = sample
    run.snapshot = snapshot
    await session.commit()
    await session.refresh(run)
    return _payload(run)


@router.post("/audits/{audit_id}/assets")
async def create_assets(
    audit_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    run = await _run_for_tenant(session, audit_id, tenant_id)
    tenant = await session.get(Tenant, tenant_id)
    tenant_name = tenant.name if tenant else "当前品牌"
    final_url = run.final_url or run.url
    run.json_ld = generate_json_ld(
        tenant_name=tenant_name,
        url=final_url,
        title=run.page_title or "",
        description=run.page_description or "",
    )
    run.llms_text = generate_llms_text(
        tenant_name=tenant_name,
        url=final_url,
        title=run.page_title or "",
        description=run.page_description or "",
        snapshot=run.snapshot or {},
    )
    await session.commit()
    await session.refresh(run)
    return _payload(run)


@router.get("/assets/profile")
async def get_asset_profile(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")
    brand_extra = _json_content(await _latest_memory(session, tenant_id, "brand_asset"))
    audience = _json_content(await _latest_memory(session, tenant_id, "audience_profile"))
    return {
        "brand": {
            "name": tenant.name,
            "website": brand_extra.get("website", ""),
            "industry": tenant.industry or "",
            "business_desc": tenant.business_desc or "",
            "brand_terms": tenant.brand_terms or [],
            "core_products": brand_extra.get("core_products", []),
            "proof_points": brand_extra.get("proof_points", []),
        },
        "audience": {
            "segments": audience.get("segments", []),
            "decision_roles": audience.get("decision_roles", []),
            "pain_points": audience.get("pain_points", []),
            "search_scenarios": audience.get("search_scenarios", []),
        },
    }


@router.put("/assets/brand")
async def update_brand_asset(
    req: BrandAssetUpdate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    _ensure_asset_edit(ctx)
    tenant = await session.get(Tenant, req.tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")
    tenant.name = req.name.strip()
    tenant.industry = req.industry.strip() or None
    tenant.business_desc = req.business_desc.strip() or None
    tenant.brand_terms = [value.strip() for value in req.brand_terms if value.strip()]
    await _upsert_memory(
        session,
        tenant_id=req.tenant_id,
        mem_type="brand_asset",
        data={
            "website": req.website.strip(),
            "core_products": [value.strip() for value in req.core_products if value.strip()],
            "proof_points": [value.strip() for value in req.proof_points if value.strip()],
        },
        ctx=ctx,
    )
    await session.commit()
    return {"ok": True}


@router.put("/assets/audience")
async def update_audience_asset(
    req: AudienceAssetUpdate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    _ensure_asset_edit(ctx)
    if await session.get(Tenant, req.tenant_id) is None:
        raise HTTPException(404, "客户不存在")
    await _upsert_memory(
        session,
        tenant_id=req.tenant_id,
        mem_type="audience_profile",
        data={
            "segments": [value.strip() for value in req.segments if value.strip()],
            "decision_roles": [value.strip() for value in req.decision_roles if value.strip()],
            "pain_points": [value.strip() for value in req.pain_points if value.strip()],
            "search_scenarios": [value.strip() for value in req.search_scenarios if value.strip()],
        },
        ctx=ctx,
    )
    await session.commit()
    return {"ok": True}


@router.get("/assets/knowledge")
async def list_knowledge_assets(
    tenant_id: int = Query(...),
    q: str = Query(default="", max_length=200),
    item_type: str = Query(default="", max_length=30),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    rows = (
        await session.scalars(
            select(TenantMemory)
            .where(
                TenantMemory.tenant_id == tenant_id,
                TenantMemory.mem_type == "knowledge_item",
                TenantMemory.active.is_(True),
            )
            .order_by(TenantMemory.created_at.desc(), TenantMemory.id.desc())
        )
    ).all()
    items = [_knowledge_payload(row) for row in rows]
    if item_type:
        items = [item for item in items if item["item_type"] == item_type]
    if q.strip():
        needle = q.strip().lower()
        items = [
            item
            for item in items
            if needle in f'{item["title"]} {item["body"]} {item["source_url"]}'.lower()
        ]
    return {"items": items, "total": len(items)}


@router.post("/assets/knowledge")
async def create_knowledge_asset(
    req: KnowledgeCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    _ensure_asset_edit(ctx)
    if await session.get(Tenant, req.tenant_id) is None:
        raise HTTPException(404, "客户不存在")
    allowed_types = {"product", "case", "whitepaper", "faq", "other"}
    if req.item_type not in allowed_types:
        raise HTTPException(400, "资料类型不正确")
    memory = TenantMemory(
        tenant_id=req.tenant_id,
        mem_type="knowledge_item",
        content=json.dumps(
            {
                "title": req.title.strip(),
                "item_type": req.item_type,
                "body": req.body.strip(),
                "source_url": req.source_url.strip(),
            },
            ensure_ascii=False,
        ),
        source="manual",
        confirmed=True,
        active=True,
        operator_user_id=ctx.user_id,
        operator_name=ctx.username,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return _knowledge_payload(memory)


@router.delete("/assets/knowledge/{knowledge_id}")
async def delete_knowledge_asset(
    knowledge_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    _ensure_asset_edit(ctx)
    memory = await session.get(TenantMemory, knowledge_id)
    if (
        memory is None
        or memory.tenant_id != tenant_id
        or memory.mem_type != "knowledge_item"
        or not memory.active
    ):
        raise HTTPException(404, "知识条目不存在")
    memory.active = False
    memory.operator_user_id = ctx.user_id
    memory.operator_name = ctx.username
    await session.commit()
    return {"ok": True}
