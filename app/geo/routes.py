"""GEO 网站诊断、AI 整改建议与结构化资产生成。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import is_enabled as ai_enabled
from app.database import get_session
from app.geo.audit import GeoAuditError, audit_url
from app.geo.generate import ai_advice, generate_json_ld, generate_llms_text
from app.geo.tenant_scope import list_geo_tenants_for_auth
from app.geo.verify import (
    append_evidence,
    apply_verdict_to_status,
    evaluate_check,
    materialize_ticket_specs,
    ticket_public_dict,
)
from app.models import GeoActionTicket, GeoAuditRun, GeoMediaPlacement, GeoOptimizationBusiness, Tenant
from app.security.auth import AuthContext, require_scoped_auth

router = APIRouter(
    prefix="/api/v1/geo",
    tags=["GEO 诊断"],
    dependencies=[Depends(require_scoped_auth)],
)


@router.get("/tenants")
async def get_geo_tenants(
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Customer switcher data, limited to currently enabled GEO tenants."""
    tenants = await list_geo_tenants_for_auth(session, bound_tenant_id=ctx.tenant_id)
    return {"tenants": [{"id": tenant.id, "name": tenant.name} for tenant in tenants]}


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
    owner_name: str | None = Field(None, max_length=100)
    due_date: date | None = None


class TicketUpdate(BaseModel):
    status: Literal["todo", "doing", "done", "reopened", "blocked"] | None = None
    priority: str | None = None
    action: str | None = None
    acceptance_type: Literal["auto", "manual"] | None = None
    acceptance_check: str | None = None
    acceptance_desc: str | None = None
    manual_pass: bool | None = None
    verification_note: str | None = Field(None, max_length=4000)
    operation_note: str | None = Field(None, max_length=4000)
    owner_name: str | None = Field(None, max_length=100)
    due_date: date | None = None


class TicketExecution(BaseModel):
    content_task_id: int = Field(..., gt=0)
    expected_article_id: int | None = Field(None, gt=0)
    before_snapshot_ids: list[int] = Field(default_factory=list, max_length=100)
    after_snapshot_ids: list[int] = Field(default_factory=list, max_length=100)
    change_note: str = Field(..., min_length=1, max_length=4000)


class TicketPrepareContent(BaseModel):
    prompt_id: int | None = Field(None, gt=0)


@router.get('/action-tickets/{ticket_id}/execution-plan')
async def get_ticket_execution_plan(
    ticket_id: int, tenant_id: int = Query(...), content_task_id: int | None = Query(None, gt=0),
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
) -> dict:
    from app.models import GeoContentTask, GeoPrompt, GeoAnswerSnapshot, GeoArticleVersion, GeoPublication, GeoChannelVariant
    from app.geo.execution_plan import ticket_prompt_id, candidates, sample_gaps, execution_steps
    from app.geo.content.brief import brief_ready
    from app.geo.content.routes import _task_facts, _fact_dicts
    from app.geo.content.evidence import prepare_facts_for_generation

    ctx.ensure_tenant(tenant_id)
    row = await _ticket_for_tenant(session, ticket_id, tenant_id)
    if not (row.advice_code or '').startswith('workqueue:v1:'):
        raise HTTPException(400, '仅执行待办支持执行计划')
    fixed_prompt = ticket_prompt_id(row)
    tasks_query = select(GeoContentTask).join(GeoPrompt, GeoPrompt.id == GeoContentTask.prompt_id).where(
        GeoContentTask.tenant_id == tenant_id, GeoPrompt.tenant_id == tenant_id,
        GeoPrompt.is_brand_probe.is_(False), GeoContentTask.status.notin_(['archived', 'cancelled']))
    if fixed_prompt:
        tasks_query = tasks_query.where(GeoContentTask.prompt_id == fixed_prompt)
    tasks = list(await session.scalars(tasks_query.order_by(GeoContentTask.id.desc()).limit(100)))
    task_id = content_task_id or row.content_task_id
    task = await session.get(GeoContentTask, task_id) if task_id else (tasks[0] if fixed_prompt and tasks else None)
    if task and (task.tenant_id != tenant_id or (fixed_prompt and task.prompt_id != fixed_prompt)):
        raise HTTPException(404, '内容任务不存在或不属于同一问题')
    if task_id and task is None:
        raise HTTPException(404, '内容任务不存在')
    prompt_id = task.prompt_id if task else fixed_prompt
    prompts = list(await session.scalars(select(GeoPrompt).where(
        GeoPrompt.tenant_id == tenant_id, GeoPrompt.is_brand_probe.is_(False), GeoPrompt.status == 'active',
    ).order_by(GeoPrompt.id.desc()).limit(200)))
    prompt = await session.get(GeoPrompt, prompt_id) if prompt_id else None
    if prompt_id and prompt is None:
        raise HTTPException(404, '问题不存在')
    if prompt and (prompt.tenant_id != tenant_id or prompt.is_brand_probe):
        raise HTTPException(404, '问题不存在')
    article = await session.scalar(select(GeoArticleVersion).where(GeoArticleVersion.task_id == task.id)
                                   .order_by(GeoArticleVersion.version_no.desc()).limit(1)) if task else None
    before, after, excluded, truncated = [], [], 0, False
    if prompt:
        query = select(GeoAnswerSnapshot).where(GeoAnswerSnapshot.tenant_id == tenant_id, GeoAnswerSnapshot.prompt_id == prompt.id)
        before_query = query.where(GeoAnswerSnapshot.captured_at <= article.created_at) if article else query
        before_rows = list(await session.scalars(before_query.order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc()).limit(101)))
        after_rows = list(await session.scalars(query.where(GeoAnswerSnapshot.captured_at > article.created_at)
                         .order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc()).limit(101))) if article else []
        before, b_excluded = candidates(before_rows[:100])
        after, a_excluded = candidates(after_rows[:100])
        excluded = b_excluded + a_excluded
        truncated = len(before_rows) > 100 or len(after_rows) > 100
    pubs = list(await session.scalars(select(GeoPublication).join(GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).where(
        GeoChannelVariant.task_id == task.id, GeoPublication.status == 'published', GeoPublication.published_url.is_not(None),
        GeoChannelVariant.article_version_id == article.id,
    ).order_by(GeoPublication.id.desc()).limit(20))) if task and article else []
    facts = await _task_facts(session, task.id) if task else []
    eligible_facts, _ = prepare_facts_for_generation(_fact_dicts(facts), min_eligible=3)
    steps, next_step = execution_steps(row, task, article, len(eligible_facts), brief_ready(task.brief) if task else False, pubs)
    return dict(prompt_id=prompt_id, question=prompt.question if prompt else None,
                prompts=[dict(id=p.id, question=p.question) for p in prompts],
                tasks=[dict(id=t.id, title=t.title, status=t.status) for t in tasks],
                selected_task_id=task.id if task else None, article_id=article.id if article else None,
                before=before, after=after, excluded=excluded, truncated=truncated,
                steps=steps, next_step=next_step, gaps=sample_gaps(before, after))


@router.post('/action-tickets/{ticket_id}/prepare-content')
async def prepare_ticket_content(
    ticket_id: int, req: TicketPrepareContent, tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
) -> dict:
    from app.models import GeoContentTask, GeoPrompt, GeoAnswerSnapshot, GeoArticleVersion
    from app.geo.execution_plan import ticket_prompt_id
    from app.geo.work_execution import freeze_samples
    from app.geo.content.brief import normalize_brief
    from app.geo.content.routes import _resolve_task_business_id, _resolve_active_period_id, _sync_task_pipeline

    ctx.ensure_tenant(tenant_id)
    row = await _work_ticket_for_update(session, ticket_id, tenant_id)
    if not (row.advice_code or '').startswith('workqueue:v1:'):
        raise HTTPException(400, '仅执行待办支持准备内容')
    if row.status == 'done':
        raise HTTPException(409, '请先重新打开待办，再准备内容任务')
    fixed = ticket_prompt_id(row)
    if fixed and req.prompt_id and fixed != req.prompt_id:
        raise HTTPException(400, '必须使用待办的同一问题')
    prompt_id = fixed or req.prompt_id
    if not prompt_id:
        raise HTTPException(400, '请先选择要执行的目标问题')
    prompt = await session.scalar(select(GeoPrompt).where(GeoPrompt.id == prompt_id, GeoPrompt.tenant_id == tenant_id).with_for_update())
    if prompt is None or prompt.is_brand_probe:
        raise HTTPException(404, '非品牌点名问题不存在')
    task = await session.get(GeoContentTask, row.content_task_id) if row.content_task_id else None
    if row.content_task_id and (task is None or task.tenant_id != tenant_id or task.prompt_id != prompt.id):
        raise HTTPException(409, '已有内容关联与目标问题不一致，请先核对')
    if task is None:
        task = await session.scalar(select(GeoContentTask).where(GeoContentTask.tenant_id == tenant_id,
            GeoContentTask.prompt_id == prompt.id, GeoContentTask.status.notin_(['archived', 'cancelled']))
            .order_by(GeoContentTask.id.desc()).limit(1))
    created = task is None
    if created:
        business_id = await _resolve_task_business_id(session, prompt)
        period_id = await _resolve_active_period_id(session, tenant_id=tenant_id, business_id=business_id)
        task = GeoContentTask(tenant_id=tenant_id, prompt_id=prompt.id, business_id=business_id, period_id=period_id,
            title=prompt.question[:300], status='draft', target_channels=['website'], owner_user_id=ctx.user_id,
            pipeline_step='opportunity', brief=normalize_brief({'ai_question': prompt.question,
            'notes': f'来自执行待办 #{row.id}\n{row.action or row.title}\n验收要求：{row.acceptance_desc or "核对事实与出处，完成后同题复测"}',
            'must_cover': ['直接回答目标问题', '明确适用与不适用条件', '为关键事实保留可核验出处'],
            'source_bar': 'verified_only'}))
        session.add(task)
        await session.flush()
        prompt.last_task_id = task.id
        await _sync_task_pipeline(session, task)
    row.content_task_id = task.id
    if not row.baseline_snapshot:
        article = await session.scalar(select(GeoArticleVersion).where(GeoArticleVersion.task_id == task.id)
                                       .order_by(GeoArticleVersion.version_no.desc()).limit(1))
        query = select(GeoAnswerSnapshot).where(GeoAnswerSnapshot.tenant_id == tenant_id, GeoAnswerSnapshot.prompt_id == prompt.id)
        if article:
            query = query.where(GeoAnswerSnapshot.captured_at <= article.created_at)
        snapshots = list(await session.scalars(query.order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc()).limit(100)))
        frozen = []
        for snapshot in snapshots:
            try:
                frozen.extend(freeze_samples([snapshot]))
            except ValueError:
                continue
        row.baseline_snapshot = dict(workflow='content_retest_v1', prompt_id=prompt.id, question=prompt.question, samples=frozen)
    if row.status in {'todo', 'reopened'}:
        row.status = 'doing'
    row.evidence = append_evidence(row.evidence, check='workflow.prepare', result='created' if created else 'linked',
        note=f'已准备内容任务 #{task.id}，保留现有内容；下一步核对创作要求与事实。')
    await session.commit()
    await session.refresh(row)
    return dict(ticket=ticket_public_dict(row), task_id=task.id, created=created)


@router.post('/action-tickets/{ticket_id}/execution')
async def save_ticket_execution(
    ticket_id: int, req: TicketExecution, tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
) -> dict:
    from app.models import GeoContentTask, GeoAnswerSnapshot, GeoArticleVersion, GeoPrompt
    from app.geo.work_execution import freeze_samples, compare_samples, utc_naive

    ctx.ensure_tenant(tenant_id)
    row = await _work_ticket_for_update(session, ticket_id, tenant_id)
    if not (row.advice_code or '').startswith('workqueue:v1:'):
        raise HTTPException(400, '仅执行待办支持关联内容与复测')
    if row.status == 'done':
        raise HTTPException(409, '请先重新打开待办，再修改执行证据')
    task = await session.get(GeoContentTask, req.content_task_id)
    if task is None or task.tenant_id != tenant_id:
        raise HTTPException(404, '内容任务不存在')
    if row.advice_code.startswith('workqueue:v1:prompt-') and row.advice_code != f'workqueue:v1:prompt-{task.prompt_id}':
        raise HTTPException(400, '内容任务必须对应待办的同一问题')
    prompt = await session.get(GeoPrompt, task.prompt_id)
    if prompt is None or prompt.tenant_id != tenant_id or prompt.is_brand_probe:
        raise HTTPException(400, '请关联非品牌点名问题的内容任务')
    note = req.change_note.strip()
    if not note:
        raise HTTPException(400, '请填写具体修改内容')
    before_ids, after_ids = set(req.before_snapshot_ids), set(req.after_snapshot_ids)
    if before_ids & after_ids or any(i <= 0 for i in before_ids | after_ids):
        raise HTTPException(400, '前后样本不得重复，编号必须为正整数')
    if after_ids and not before_ids:
        raise HTTPException(400, '请先关联修改前样本')
    ids = before_ids | after_ids
    snapshots = list(await session.scalars(select(GeoAnswerSnapshot).where(
        GeoAnswerSnapshot.tenant_id == tenant_id, GeoAnswerSnapshot.prompt_id == task.prompt_id,
        GeoAnswerSnapshot.id.in_(ids),
    ).order_by(GeoAnswerSnapshot.id).with_for_update())) if ids else []
    if {s.id for s in snapshots} != ids:
        raise HTTPException(400, '样本不存在或不属于当前客户的同一问题')
    article = await session.scalar(select(GeoArticleVersion).where(GeoArticleVersion.task_id == task.id)
                                   .order_by(GeoArticleVersion.version_no.desc()).limit(1))
    if 'expected_article_id' in req.model_fields_set and req.expected_article_id != (article.id if article else None):
        raise HTTPException(409, '内容版本已变化，请刷新执行进度后重新核对证据')
    try:
        before = freeze_samples([s for s in snapshots if s.id in before_ids])
        after = freeze_samples([s for s in snapshots if s.id in after_ids])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if article and any(utc_naive(s.captured_at) > utc_naive(article.created_at) for s in snapshots if s.id in before_ids):
        raise HTTPException(400, '修改前样本必须早于当前内容版本保存时间')
    if after:
        if article is None or not article.created_at:
            raise HTTPException(400, '请先保存内容修改，再关联复测样本')
        if min(utc_naive(s.captured_at) for s in snapshots if s.id in after_ids) <= max(utc_naive(s.captured_at) for s in snapshots if s.id in before_ids):
            raise HTTPException(400, '复测必须晚于全部修改前样本')
        if any(utc_naive(s.captured_at) < utc_naive(article.created_at) for s in snapshots if s.id in after_ids):
            raise HTTPException(400, '复测样本必须采集于当前内容版本保存之后')
    row.content_task_id = task.id
    row.baseline_snapshot = dict(workflow='content_retest_v1', prompt_id=task.prompt_id,
                                 question=prompt.question, samples=before)
    row.progress = dict(workflow='content_retest_v1', prompt_id=task.prompt_id,
                        article_id=article.id if article else None, version_no=article.version_no if article else None,
                        change_note=note, samples=after, comparison=compare_samples(before, after),
                        recorded_at=datetime.utcnow().isoformat() + 'Z')
    row.evidence = append_evidence(row.evidence, check='workflow.execution', result='recorded',
                                   note=f'关联内容任务 #{task.id}；修改前 {len(before)} 条，复测 {len(after)} 条。{note}')
    await session.commit()
    await session.refresh(row)
    return ticket_public_dict(row)


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


async def _work_ticket_for_update(session: AsyncSession, ticket_id: int, tenant_id: int) -> GeoActionTicket:
    row = await _ticket_for_tenant(session, ticket_id, tenant_id)
    if not (row.advice_code or '').startswith('workqueue:v1:'):
        return row
    # Same lock order as creation. Reload after waiting so history is not based
    # on an older identity-map copy read before another writer committed.
    await session.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    row = await session.get(GeoActionTicket, ticket_id, with_for_update=True, populate_existing=True)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, '验收工单不存在')
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
        if (ticket.advice_code or '').startswith('workqueue:v1:'):
            results.append({'id': ticket.id, 'title': ticket.title, 'ok': None, 'note': '请在执行待办中填写结果并人工验收', 'skipped': True})
            continue
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
    if (req.advice_code or '').startswith('workqueue:v1:'):
        # Serialize acceptance of the same suggestion without changing legacy tickets.
        await session.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
        existing = (await session.execute(select(GeoActionTicket).where(
            GeoActionTicket.tenant_id == tenant_id,
            GeoActionTicket.advice_code == req.advice_code,
            GeoActionTicket.status != 'done',
        ).order_by(GeoActionTicket.id.desc()).limit(1))).scalar_one_or_none()
        if existing is not None:
            return ticket_public_dict(existing)
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
        owner_name=(req.owner_name or '').strip() or None,
        due_date=req.due_date,
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
    row = await _work_ticket_for_update(session, ticket_id, tenant_id)
    data = req.model_dump(exclude_unset=True)
    manual_pass = data.pop("manual_pass", None)
    verification_note = (data.pop("verification_note", None) or '').strip()
    operation_note = (data.pop('operation_note', None) or '').strip()
    if 'owner_name' in data:
        data['owner_name'] = (data['owner_name'] or '').strip() or None
    queue_ticket = (row.advice_code or '').startswith('workqueue:v1:')
    previous_status = row.status
    previous_assignment = (row.owner_name, row.due_date)
    if queue_ticket and 'status' in data and data['status'] is None:
        raise HTTPException(400, '状态不能为空')
    if queue_ticket and manual_pass is not None and 'status' in data:
        raise HTTPException(400, '状态变更与验收请分别提交')
    if queue_ticket and data.get('status') == 'blocked' and not operation_note:
        raise HTTPException(400, '请填写受阻原因和需要的协助')
    if queue_ticket and manual_pass is not None and not verification_note:
        raise HTTPException(400, '请填写执行结果与核验依据后再验收')
    if queue_ticket and data.get('status') == 'done' and manual_pass is not True:
        raise HTTPException(400, '请通过人工验收完成待办')
    if queue_ticket and manual_pass is True and row.content_task_id:
        if previous_status == 'done':
            raise HTTPException(409, '该待办已验收，请先重新打开后再记录新的验收结果')
        from app.geo.execution_plan import acceptance_blockers
        plan = await get_ticket_execution_plan(ticket_id, tenant_id, row.content_task_id, ctx, session)
        blockers = acceptance_blockers(plan)
        if blockers:
            raise HTTPException(409, '执行验收尚未就绪：' + '；'.join(blockers))
        row.progress = {**(row.progress or {}), 'acceptance': {
            'checked_at': datetime.utcnow().isoformat() + 'Z',
            'article_id': plan['article_id'], 'content_task_id': row.content_task_id,
            'steps': plan['steps'], 'note': verification_note,
        }}
    reopening = previous_status == 'done' and (manual_pass is False or data.get('status') in {'todo', 'doing', 'reopened', 'blocked'})
    if queue_ticket and reopening:
        existing = (await session.execute(select(GeoActionTicket).where(
            GeoActionTicket.tenant_id == tenant_id,
            GeoActionTicket.advice_code == row.advice_code,
            GeoActionTicket.id != row.id,
            GeoActionTicket.status != 'done',
        ).order_by(GeoActionTicket.id.desc()).limit(1))).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(409, f'同类工作已有未完成待办 #{existing.id}，请刷新列表并继续处理该待办')
    for key, value in data.items():
        setattr(row, key, value)
    if queue_ticket and data.get('status') in {'todo', 'doing', 'reopened', 'blocked'}:
        row.closed_at = None
        row.last_verdict = None
        if row.status != previous_status or operation_note:
            labels = {'todo': '待开始', 'doing': '执行中', 'reopened': '重新处理', 'blocked': '受阻', 'done': '已验收'}
            note = f"{labels.get(previous_status, previous_status)} → {labels.get(row.status, row.status)}"
            if operation_note:
                note += f"：{operation_note}"
            row.evidence = append_evidence(row.evidence, check='workflow.status', result=row.status, note=note)
    if queue_ticket and previous_assignment != (row.owner_name, row.due_date):
        def assignment_text(owner, due):
            return f"负责人：{owner or '未指定'}，截止日期：{due.isoformat() if due else '未设置'}"
        row.evidence = append_evidence(
            row.evidence, check='workflow.assignment', result='updated',
            note=f"{assignment_text(*previous_assignment)} → {assignment_text(row.owner_name, row.due_date)}",
        )
    if manual_pass is True:
        row.status = "done"
        row.last_verdict = "pass"
        row.last_note = verification_note or "人工确认通过"
        row.last_verify_at = datetime.utcnow()
        row.closed_at = row.closed_at or datetime.utcnow()
        row.evidence = append_evidence(
            row.evidence,
            check=row.acceptance_check,
            result="pass",
            note=row.last_note,
        )
    elif manual_pass is False:
        row.status = "reopened" if row.status == "done" else "todo"
        row.last_verdict = "fail"
        row.last_note = verification_note or "人工确认未达标"
        row.last_verify_at = datetime.utcnow()
        row.closed_at = None
        row.evidence = append_evidence(
            row.evidence,
            check=row.acceptance_check,
            result="fail",
            note=row.last_note,
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
    if (ticket.advice_code or '').startswith('workqueue:v1:'):
        raise HTTPException(400, '请在执行待办中填写结果并人工验收')
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
