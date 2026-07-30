"""GEO 网站诊断、AI 整改建议与结构化资产生成。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import is_enabled as ai_enabled
from app.database import get_session
from app.geo.audit import GeoAuditError, audit_url
from app.geo.generate import ai_advice, generate_json_ld, generate_llms_text
from app.models import GeoAuditRun, Tenant
from app.security.auth import AuthContext, require_scoped_auth

router = APIRouter(
    prefix="/api/v1/geo",
    tags=["GEO 诊断"],
    dependencies=[Depends(require_scoped_auth)],
)


class AuditCreate(BaseModel):
    tenant_id: int
    url: str = Field(..., min_length=4, max_length=2048)


def _payload(run: GeoAuditRun) -> dict[str, Any]:
    findings = run.findings or []
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


# 内容工作台路由（机会/事实/任务/生成/发布回填）
from app.geo.content.routes import router as content_router  # noqa: E402

router.include_router(content_router)
