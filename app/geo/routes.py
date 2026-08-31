"""GEO 网站诊断、AI 整改建议与结构化资产生成。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import is_enabled as ai_enabled
from app.database import get_session
from app.geo.audit import GeoAuditError, audit_url
from app.geo.generate import ai_advice, generate_json_ld, generate_llms_text
from app.geo.verify import (
    append_evidence,
    apply_verdict_to_status,
    evaluate_check,
    materialize_ticket_specs,
    ticket_public_dict,
)
from app.models import (
    GeoActionTicket,
    GeoAuditRun,
    GeoMediaPlacement,
    GeoOptimizationBusiness,
    Tenant,
)
from app.security.auth import AuthContext, require_scoped_auth

router = APIRouter(
    prefix="/api/v1/geo",
    tags=["GEO 诊断"],
    dependencies=[Depends(require_scoped_auth)],
)


class AuditCreate(BaseModel):
    tenant_id: int
    url: str = Field(..., min_length=4, max_length=2048)


class TicketCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    priority: str = "medium"
    action: str | None = None
    advice_code: str | None = None
    acceptance_type: Literal["auto", "manual"] = "manual"
    acceptance_check: str | None = None
    acceptance_desc: str | None = None
    media_placement_id: int | None = None
    audit_id: int | None = None


class TicketUpdate(BaseModel):
    status: Literal["todo", "doing", "done", "reopened", "blocked"] | None = None
    priority: str | None = None
    action: str | None = None
    acceptance_type: Literal["auto", "manual"] | None = None
    acceptance_check: str | None = None
    acceptance_desc: str | None = None
    manual_pass: bool | None = None


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


def _audit_context(run: GeoAuditRun) -> dict[str, Any]:
    return {
        "findings": run.findings or [],
        "checks": run.findings or [],
        "snapshot": run.snapshot or {},
        "score": run.score,
    }


async def _run_for_tenant(
    session: AsyncSession, audit_id: int, tenant_id: int
) -> GeoAuditRun:
    run = await session.get(GeoAuditRun, audit_id)
    if run is None or run.tenant_id != tenant_id:
        raise HTTPException(404, "GEO 诊断记录不存在")
    return run


async def _ticket_for_tenant(
    session: AsyncSession, ticket_id: int, tenant_id: int
) -> GeoActionTicket:
    row = await session.get(GeoActionTicket, ticket_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "验收工单不存在")
    return row


async def _media_rows(session: AsyncSession, tenant_id: int) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(GeoMediaPlacement).where(GeoMediaPlacement.tenant_id == tenant_id)
        )
    ).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "channel_key": r.channel_key,
            "status": r.status,
            "published_url": r.published_url,
        }
        for r in rows
    ]


def _apply_check_result(
    ticket: GeoActionTicket,
    *,
    ok: bool | None,
    note: str,
    progress: dict[str, Any] | None,
) -> dict[str, Any]:
    was = ticket.status
    new_status, verdict = apply_verdict_to_status(current_status=ticket.status, ok=ok)
    if progress:
        stamped = dict(progress)
        stamped["at"] = datetime.utcnow().isoformat() + "Z"
        if ticket.progress_first is None:
            ticket.progress_first = stamped
        ticket.progress = stamped
    ticket.status = new_status
    ticket.last_verdict = verdict
    ticket.last_note = note
    ticket.last_verify_at = datetime.utcnow()
    ticket.evidence = append_evidence(
        ticket.evidence,
        check=ticket.acceptance_check,
        result=verdict,
        note=note,
    )
    if verdict == "pass":
        ticket.closed_at = ticket.closed_at or datetime.utcnow()
    elif verdict == "fail" and new_status == "reopened":
        ticket.closed_at = None
    return {
        "ok": ok,
        "verdict": {True: "通过", False: "未达标", None: "待人工"}[ok],
        "note": note,
        "was": was,
        "now": ticket.status,
        "progress": ticket.progress,
        "ticket": ticket_public_dict(ticket),
    }


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


def _business_website(row: GeoOptimizationBusiness | None) -> str:
    if row is None:
        return ""
    profile = row.profile or {}
    return str(
        profile.get("website") or profile.get("website_url") or profile.get("official_url") or ""
    ).strip()


def _norm_site(url: str) -> str:
    return url.strip().rstrip("/").lower()


def pick_business_for_website(
    rows: list[GeoOptimizationBusiness],
    website_url: str | None,
) -> GeoOptimizationBusiness | None:
    """Prefer the business whose brand website matches the scan URL."""
    if not rows:
        return None
    want = _norm_site(website_url or "")
    if want:
        for row in rows:
            got = _norm_site(_business_website(row))
            if got and got == want:
                return row
    for row in rows:
        if _business_website(row):
            return row
    return rows[0]


def _brand_from_business(row: GeoOptimizationBusiness | None) -> dict[str, str]:
    profile = (row.profile if row else None) or {}
    name = str(profile.get("product_name") or (row.name if row else "") or "").strip()
    website = str(
        profile.get("website") or profile.get("website_url") or profile.get("official_url") or ""
    ).strip()
    summary = str(profile.get("summary") or (row.description if row else "") or "").strip()
    return {"name": name, "website": website, "summary": summary}


def _structure_payload(run: GeoAuditRun) -> dict[str, Any]:
    snap = run.snapshot or {}
    report = dict(snap.get("structure") or snap)
    report["audit_id"] = run.id
    report["scanned_at"] = run.created_at.isoformat() if run.created_at else None
    report["website"] = report.get("website") or run.url
    return report


@router.get("/structure-scan/latest")
async def latest_structure_scan(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    rows = (
        await session.scalars(
            select(GeoAuditRun)
            .where(GeoAuditRun.tenant_id == tenant_id)
            .order_by(GeoAuditRun.created_at.desc(), GeoAuditRun.id.desc())
            .limit(30)
        )
    ).all()
    run = next(
        (r for r in rows if (r.snapshot or {}).get("kind") == "website_structure"),
        None,
    )
    return {"report": _structure_payload(run) if run else None}


@router.post("/structure-scan")
async def run_structure_scan(
    tenant_id: int = Query(...),
    website_url: str | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")
    rows = list(
        await session.scalars(
            select(GeoOptimizationBusiness)
            .where(
                GeoOptimizationBusiness.tenant_id == tenant_id,
                GeoOptimizationBusiness.status == "active",
            )
            .order_by(GeoOptimizationBusiness.sort_order.asc(), GeoOptimizationBusiness.id.asc())
        )
    )
    biz = pick_business_for_website(rows, website_url)
    brand_info = _brand_from_business(biz)
    site = (website_url or brand_info["website"] or "").strip()
    if not site:
        raise HTTPException(400, "请先在品牌信息中填写官网")
    from app.geo.structure_scan import scan_website
    from app.urlwords import UrlFetchError, validate_url

    try:
        site = validate_url(site)
    except UrlFetchError as exc:
        raise HTTPException(400, str(exc)) from exc
    brand = brand_info["name"] or (tenant.name if tenant else "")
    try:
        report = await scan_website(site, brand=brand, summary=brand_info["summary"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"扫描失败：{exc}") from exc
    findings = [
        {
            "code": f"structure_{i}",
            "title": item.get("title"),
            "passed": False,
            "severity": "high" if item.get("pri") == "P1" else "medium",
            "recommendation": item.get("detail"),
        }
        for i, item in enumerate(report.get("issues") or [])
    ]
    run = GeoAuditRun(
        tenant_id=tenant_id,
        url=site,
        final_url=site,
        status="completed",
        score=report.get("score"),
        page_title="官网结构扫描",
        page_description=report.get("insight"),
        snapshot=report,
        findings=findings,
        json_ld=generate_json_ld(
            tenant_name=brand or site,
            url=site,
            title=brand or "官网",
            description=brand_info["summary"],
        ),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return _structure_payload(run)


@router.post("/audits/{audit_id}/tickets")
async def materialize_tickets(
    audit_id: int,
    tenant_id: int = Query(...),
    replace_open: bool = Query(False),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """从诊断 advice / 失败 findings 生成验收工单。"""
    ctx.ensure_tenant(tenant_id)
    run = await _run_for_tenant(session, audit_id, tenant_id)
    specs = materialize_ticket_specs(advice=run.advice, findings=run.findings or [])
    if not specs:
        return {"created": 0, "items": [], "audit_id": audit_id}

    existing = (
        await session.scalars(
            select(GeoActionTicket).where(
                GeoActionTicket.tenant_id == tenant_id,
                GeoActionTicket.audit_id == audit_id,
            )
        )
    ).all()
    existing_codes = {t.advice_code for t in existing if t.advice_code}
    if replace_open:
        for t in existing:
            if t.status in {"todo", "doing", "reopened", "blocked"}:
                await session.delete(t)
                if t.advice_code:
                    existing_codes.discard(t.advice_code)
        await session.flush()

    created: list[GeoActionTicket] = []
    for spec in specs:
        code = spec.get("advice_code")
        if code and code in existing_codes:
            continue
        row = GeoActionTicket(
            tenant_id=tenant_id,
            audit_id=audit_id,
            created_by=getattr(ctx, "user_id", None),
            **spec,
        )
        session.add(row)
        created.append(row)
        if code:
            existing_codes.add(code)
    await session.commit()
    for row in created:
        await session.refresh(row)
    return {
        "audit_id": audit_id,
        "created": len(created),
        "items": [ticket_public_dict(r) for r in created],
    }


@router.post("/audits/{audit_id}/verify")
async def verify_audit_tickets(
    audit_id: int,
    tenant_id: int = Query(...),
    recrawl: bool = Query(True),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """批量验收：可选重抓诊断，再对关联工单跑 checker。"""
    ctx.ensure_tenant(tenant_id)
    run = await _run_for_tenant(session, audit_id, tenant_id)
    fresh_audit: dict[str, Any] | None = None
    if recrawl:
        try:
            result = await audit_url(run.final_url or run.url)
        except GeoAuditError as exc:
            raise HTTPException(400, str(exc)) from exc
        fresh = GeoAuditRun(
            tenant_id=tenant_id,
            url=result["url"],
            final_url=result["final_url"],
            status="completed",
            score=result["score"],
            page_title=result["title"],
            page_description=result["description"],
            snapshot=result["snapshot"],
            findings=result["checks"],
        )
        session.add(fresh)
        await session.flush()
        fresh_audit = {
            "findings": result["checks"],
            "checks": result["checks"],
            "snapshot": result["snapshot"],
            "blocks": result.get("blocks"),
            "score": result["score"],
            "fresh_audit_id": fresh.id,
        }

    audit_ctx = fresh_audit or _audit_context(run)
    media = await _media_rows(session, tenant_id)
    tickets = (
        await session.scalars(
            select(GeoActionTicket).where(
                GeoActionTicket.tenant_id == tenant_id,
                GeoActionTicket.audit_id == audit_id,
                GeoActionTicket.status.in_(
                    ["todo", "doing", "done", "reopened", "blocked"]
                ),
            )
        )
    ).all()

    results = []
    changed = 0
    for ticket in tickets:
        was = ticket.status
        if ticket.acceptance_type != "auto" or not ticket.acceptance_check:
            ok, note, prog = None, ticket.acceptance_desc or "需人工确认", None
        else:
            ok, note, prog = evaluate_check(
                ticket.acceptance_check, audit=audit_ctx, media_placements=media
            )
        info = _apply_check_result(ticket, ok=ok, note=note, progress=prog)
        info["id"] = ticket.id
        info["title"] = ticket.title
        if was != ticket.status:
            changed += 1
        results.append(info)

    await session.commit()
    passed = sum(1 for r in results if r["ok"] is True)
    failed = sum(1 for r in results if r["ok"] is False)
    manual = sum(1 for r in results if r["ok"] is None)
    return {
        "audit_id": audit_id,
        "fresh_audit_id": (fresh_audit or {}).get("fresh_audit_id"),
        "verified_at": datetime.utcnow().isoformat() + "Z",
        "changed": changed,
        "summary": {"pass": passed, "fail": failed, "manual": manual},
        "results": results,
    }


@router.get("/action-tickets")
async def list_action_tickets(
    tenant_id: int = Query(...),
    status: str | None = Query(None),
    audit_id: int | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoActionTicket).where(GeoActionTicket.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(GeoActionTicket.status == status)
    if audit_id is not None:
        stmt = stmt.where(GeoActionTicket.audit_id == audit_id)
    stmt = stmt.order_by(GeoActionTicket.id.desc())
    rows = (await session.scalars(stmt)).all()
    return {"items": [ticket_public_dict(r) for r in rows], "total": len(rows)}


@router.post("/action-tickets")
async def create_action_ticket(
    req: TicketCreate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    if req.audit_id is not None:
        await _run_for_tenant(session, req.audit_id, tenant_id)
    if req.media_placement_id is not None:
        mp = await session.get(GeoMediaPlacement, req.media_placement_id)
        if mp is None or mp.tenant_id != tenant_id:
            raise HTTPException(404, "媒体布局不存在")
        check = req.acceptance_check or f"media.placement_published:{mp.id}"
        acc_type = req.acceptance_type if req.acceptance_check else "auto"
    else:
        check = req.acceptance_check
        acc_type = req.acceptance_type
    row = GeoActionTicket(
        tenant_id=tenant_id,
        audit_id=req.audit_id,
        advice_code=req.advice_code,
        media_placement_id=req.media_placement_id,
        priority=req.priority,
        title=req.title,
        action=req.action,
        status="todo",
        acceptance_type=acc_type,
        acceptance_check=check,
        acceptance_desc=req.acceptance_desc or "人工或自动验收通过",
        created_by=getattr(ctx, "user_id", None),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ticket_public_dict(row)


@router.patch("/action-tickets/{ticket_id}")
async def patch_action_ticket(
    ticket_id: int,
    req: TicketUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await _ticket_for_tenant(session, ticket_id, tenant_id)
    data = req.model_dump(exclude_unset=True)
    manual_pass = data.pop("manual_pass", None)
    for key, value in data.items():
        setattr(row, key, value)
    if manual_pass is True:
        row.status = "done"
        row.last_verdict = "pass"
        row.last_note = "人工确认通过"
        row.last_verify_at = datetime.utcnow()
        row.closed_at = row.closed_at or datetime.utcnow()
        row.evidence = append_evidence(
            row.evidence,
            check=row.acceptance_check,
            result="pass",
            note="人工确认通过",
        )
    elif manual_pass is False:
        row.status = "reopened" if row.status == "done" else "todo"
        row.last_verdict = "fail"
        row.last_note = "人工确认未达标"
        row.last_verify_at = datetime.utcnow()
        row.closed_at = None
        row.evidence = append_evidence(
            row.evidence,
            check=row.acceptance_check,
            result="fail",
            note="人工确认未达标",
        )
    await session.commit()
    await session.refresh(row)
    return ticket_public_dict(row)


@router.post("/action-tickets/{ticket_id}/verify")
async def verify_one_ticket(
    ticket_id: int,
    tenant_id: int = Query(...),
    recrawl: bool = Query(True),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    ticket = await _ticket_for_tenant(session, ticket_id, tenant_id)
    media = await _media_rows(session, tenant_id)
    audit_ctx: dict[str, Any] = {}
    fresh_audit_id = None
    needs_page = bool(
        ticket.acceptance_check
        and not str(ticket.acceptance_check).startswith("media.")
    )
    if ticket.audit_id and needs_page:
        run = await _run_for_tenant(session, ticket.audit_id, tenant_id)
        if recrawl and ticket.acceptance_type == "auto":
            try:
                result = await audit_url(run.final_url or run.url)
            except GeoAuditError as exc:
                raise HTTPException(400, str(exc)) from exc
            fresh = GeoAuditRun(
                tenant_id=tenant_id,
                url=result["url"],
                final_url=result["final_url"],
                status="completed",
                score=result["score"],
                page_title=result["title"],
                page_description=result["description"],
                snapshot=result["snapshot"],
                findings=result["checks"],
            )
            session.add(fresh)
            await session.flush()
            fresh_audit_id = fresh.id
            audit_ctx = {
                "findings": result["checks"],
                "checks": result["checks"],
                "snapshot": result["snapshot"],
                "blocks": result.get("blocks"),
                "score": result["score"],
            }
        else:
            audit_ctx = _audit_context(run)

    if ticket.acceptance_type != "auto" or not ticket.acceptance_check:
        ok, note, prog = None, ticket.acceptance_desc or "需人工确认", None
    else:
        ok, note, prog = evaluate_check(
            ticket.acceptance_check, audit=audit_ctx, media_placements=media
        )
    info = _apply_check_result(ticket, ok=ok, note=note, progress=prog)
    await session.commit()
    await session.refresh(ticket)
    info["ticket"] = ticket_public_dict(ticket)
    info["fresh_audit_id"] = fresh_audit_id
    return info


# 内容工作台路由（机会/事实/任务/生成/发布回填）
from app.geo.content.routes import router as content_router  # noqa: E402

router.include_router(content_router)
