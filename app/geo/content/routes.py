"""GEO 内容工作台 API：机会 / 事实 / 任务 / 生成 / 渠道 / 回填。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.geo.content.bridge import (
    create_and_bind_diagnosis_facts,
    create_task_from_diagnosis,
    editor_path,
)
from app.geo.content.gate import PublishGateError, assert_can_publish
from app.geo.content.generate_article import (
    generate_master_article,
    outline_from_payload,
    to_markdown,
)
from app.geo.content.imports import import_facts_csv, import_prompts_csv
from app.geo.content.pipeline import blocked_reason_from_checks, sync_pipeline_fields
from app.geo.content.rules import RuleInput, build_fix_patches, is_ready, run_checks
from app.geo.content.schemas import (
    ApplyPatchRequest,
    ArticleUpdate,
    FactCreate,
    FactUpdate,
    PromptCreate,
    PromptImportRequest,
    PromptUpdate,
    PublicationCreate,
    TaskCreate,
    TaskFactsUpdate,
    TaskFromDiagnosis,
    TaskUpdate,
    VariantsCreate,
)
from app.geo.content.variants import GeoContentError, adapt_for_channel
from app.models import (
    GeoArticleVersion,
    GeoChannelVariant,
    GeoContentTask,
    GeoFact,
    GeoPrompt,
    GeoPublication,
    GeoTaskFact,
    Tenant,
)
from app.security.auth import AuthContext, require_scoped_auth

router = APIRouter(tags=["GEO 内容"], dependencies=[Depends(require_scoped_auth)])


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _prompt_payload(row: GeoPrompt) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "question": row.question,
        "language": row.language,
        "priority": row.priority,
        "tags": row.tags or [],
        "demand_note": row.demand_note,
        "status": row.status,
        "source": row.source,
        "created_by": row.created_by,
        "owner_user_id": row.owner_user_id,
        "last_task_id": row.last_task_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _fact_payload(row: GeoFact) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "title": row.title,
        "statement": row.statement,
        "fact_type": row.fact_type,
        "source_name": row.source_name,
        "source_url": row.source_url,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "trust_level": row.trust_level,
        "status": row.status,
        "meta": row.meta or {},
        "author_name": row.author_name,
        "import_batch_id": row.import_batch_id,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _validate_fact_source(source_name: str, trust_level: str) -> None:
    if trust_level in ("verified", "needs_review") and not (source_name or "").strip():
        raise HTTPException(400, "事实卡必须填写来源名称")


async def _ensure_tenant_exists(session: AsyncSession, tenant_id: int) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")
    return tenant


async def _get_prompt(
    session: AsyncSession, prompt_id: int, tenant_id: int
) -> GeoPrompt:
    row = await session.get(GeoPrompt, prompt_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "机会问题不存在")
    return row


async def _get_fact(session: AsyncSession, fact_id: int, tenant_id: int) -> GeoFact:
    row = await session.get(GeoFact, fact_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "事实卡不存在")
    return row


async def _get_task(
    session: AsyncSession, task_id: int, tenant_id: int
) -> GeoContentTask:
    row = await session.get(GeoContentTask, task_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "内容任务不存在")
    return row


async def _task_facts(
    session: AsyncSession, task_id: int
) -> list[GeoFact]:
    rows = (
        await session.execute(
            select(GeoFact, GeoTaskFact.sort_order)
            .join(GeoTaskFact, GeoTaskFact.fact_id == GeoFact.id)
            .where(GeoTaskFact.task_id == task_id)
            .order_by(GeoTaskFact.sort_order.asc(), GeoFact.id.asc())
        )
    ).all()
    return [r[0] for r in rows]


async def _latest_article(
    session: AsyncSession, task_id: int
) -> GeoArticleVersion | None:
    return await session.scalar(
        select(GeoArticleVersion)
        .where(GeoArticleVersion.task_id == task_id)
        .order_by(GeoArticleVersion.version_no.desc(), GeoArticleVersion.id.desc())
        .limit(1)
    )


async def _variants(session: AsyncSession, task_id: int) -> list[GeoChannelVariant]:
    result = await session.scalars(
        select(GeoChannelVariant)
        .where(GeoChannelVariant.task_id == task_id)
        .order_by(GeoChannelVariant.id.asc())
    )
    return list(result)


async def _bind_facts(
    session: AsyncSession, task: GeoContentTask, fact_ids: list[int]
) -> list[GeoFact]:
    unique_ids: list[int] = []
    for fid in fact_ids:
        if fid not in unique_ids:
            unique_ids.append(fid)
    facts: list[GeoFact] = []
    for fid in unique_ids:
        fact = await _get_fact(session, fid, task.tenant_id)
        if fact.status != "active":
            raise HTTPException(400, f"事实卡 {fid} 已归档")
        facts.append(fact)
    await session.execute(delete(GeoTaskFact).where(GeoTaskFact.task_id == task.id))
    for idx, fact in enumerate(facts):
        session.add(GeoTaskFact(task_id=task.id, fact_id=fact.id, sort_order=idx))
    task.status = "facts_bound" if len(facts) >= 3 else "draft"
    await _sync_task_pipeline(session, task, checks=task.rule_result.get("checks") if task.rule_result else None)
    return facts


async def _sync_task_pipeline(
    session: AsyncSession,
    task: GeoContentTask,
    *,
    checks: list[dict] | None = None,
) -> None:
    facts = await _task_facts(session, task.id)
    article = await _latest_article(session, task.id)
    variants = await _variants(session, task.id)
    blocked = blocked_reason_from_checks(checks)
    if blocked is None and task.rule_result:
        blocked = blocked_reason_from_checks(task.rule_result.get("checks"))
    sync_pipeline_fields(
        task,
        fact_count=len(facts),
        has_article=article is not None,
        variant_count=len(variants),
        blocked_reason=blocked,
    )
    prompt = await session.get(GeoPrompt, task.prompt_id)
    if prompt is not None:
        prompt.last_task_id = task.id


def _fact_dicts(facts: list[GeoFact]) -> list[dict[str, Any]]:
    return [
        {
            "id": f.id,
            "title": f.title,
            "statement": f.statement,
            "source_name": f.source_name,
            "source_url": f.source_url,
            "fact_type": f.fact_type,
            "trust_level": f.trust_level,
            "author_name": f.author_name,
            "observed_at": f.observed_at.isoformat() if f.observed_at else None,
        }
        for f in facts
    ]


async def _build_rule_input(
    session: AsyncSession, task: GeoContentTask, article: GeoArticleVersion | None
) -> RuleInput:
    prompt = await _get_prompt(session, task.prompt_id, task.tenant_id)
    facts = await _task_facts(session, task.id)
    variants = await _variants(session, task.id)
    tenant = await session.get(Tenant, task.tenant_id)
    default_author = tenant.name if tenant else None
    return RuleInput(
        question=prompt.question,
        title=(article.title if article else task.title) or "",
        body_markdown=article.body_markdown if article else "",
        outline=(article.outline if article else {}) or {},
        facts=_fact_dicts(facts),
        target_channels=list(task.target_channels or []),
        variants=[v.channel for v in variants],
        author_name=article.author_name if article else None,
        default_author=default_author,
    )


async def _task_payload(
    session: AsyncSession, task: GeoContentTask, *, detail: bool = False
) -> dict[str, Any]:
    prompt = await session.get(GeoPrompt, task.prompt_id)
    payload: dict[str, Any] = {
        "id": task.id,
        "tenant_id": task.tenant_id,
        "prompt_id": task.prompt_id,
        "prompt_question": prompt.question if prompt else None,
        "title": task.title,
        "status": task.status,
        "pipeline_step": task.pipeline_step,
        "blocked_reason": task.blocked_reason,
        "diagnosis_audit_id": task.diagnosis_audit_id,
        "diagnosis_advice_code": task.diagnosis_advice_code,
        "target_channels": task.target_channels or [],
        "owner_user_id": task.owner_user_id,
        "brief": task.brief or {},
        "rule_result": task.rule_result,
        "ready_at": _iso(task.ready_at),
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
    }
    if not detail:
        return payload

    facts = await _task_facts(session, task.id)
    article = await _latest_article(session, task.id)
    variants = await _variants(session, task.id)
    pubs: list[dict[str, Any]] = []
    for variant in variants:
        pub = await session.scalar(
            select(GeoPublication)
            .where(GeoPublication.variant_id == variant.id)
            .order_by(GeoPublication.id.desc())
            .limit(1)
        )
        if pub:
            pubs.append(
                {
                    "id": pub.id,
                    "variant_id": pub.variant_id,
                    "channel": pub.channel,
                    "published_url": pub.published_url,
                    "published_at": _iso(pub.published_at),
                    "status": pub.status,
                    "note": pub.note,
                }
            )
    payload.update(
        {
            "facts": [_fact_payload(f) for f in facts],
            "article": None
            if article is None
            else {
                "id": article.id,
                "version_no": article.version_no,
                "title": article.title,
                "body_markdown": article.body_markdown,
                "outline": article.outline or {},
                "author_name": article.author_name,
                "generation_meta": article.generation_meta or {},
                "created_at": _iso(article.created_at),
            },
            "variants": [
                {
                    "id": v.id,
                    "channel": v.channel,
                    "title": v.title,
                    "body_markdown": v.body_markdown,
                    "status": v.status,
                    "export_format": v.export_format,
                    "article_version_id": v.article_version_id,
                    "updated_at": _iso(v.updated_at),
                }
                for v in variants
            ],
            "publications": pubs,
        }
    )
    return payload


@router.get("/content-health")
async def content_health() -> dict:
    return {"module": "geo-content", "status": "ok"}


# ---------- prompts ----------


@router.get("/prompts")
async def list_prompts(
    tenant_id: int = Query(...),
    status: str | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoPrompt).where(GeoPrompt.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(GeoPrompt.status == status)
    stmt = stmt.order_by(GeoPrompt.priority.desc(), GeoPrompt.id.desc())
    rows = list(await session.scalars(stmt))
    return {"items": [_prompt_payload(r) for r in rows]}


@router.post("/prompts")
async def create_prompt(
    req: PromptCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    row = GeoPrompt(
        tenant_id=req.tenant_id,
        question=req.question.strip(),
        language=req.language,
        priority=req.priority,
        tags=req.tags,
        demand_note=req.demand_note,
        source=req.source,
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _prompt_payload(row)


@router.patch("/prompts/{prompt_id}")
async def update_prompt(
    prompt_id: int,
    req: PromptUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await _get_prompt(session, prompt_id, tenant_id)
    data = req.model_dump(exclude_unset=True)
    if "question" in data and data["question"] is not None:
        data["question"] = data["question"].strip()
    for key, value in data.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return _prompt_payload(row)


@router.post("/prompts/import")
async def import_prompts(
    req: PromptImportRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    created = []
    for item in req.items:
        row = GeoPrompt(
            tenant_id=req.tenant_id,
            question=item.question.strip(),
            priority=item.priority,
            tags=item.tags,
            demand_note=item.demand_note,
            source="import",
            created_by=ctx.user_id,
        )
        session.add(row)
        created.append(row)
    await session.commit()
    for row in created:
        await session.refresh(row)
    return {"items": [_prompt_payload(r) for r in created], "count": len(created)}


# ---------- facts ----------


@router.get("/facts")
async def list_facts(
    tenant_id: int = Query(...),
    trust_level: str | None = Query(None),
    status: str = Query("active"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoFact).where(GeoFact.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(GeoFact.status == status)
    if trust_level:
        stmt = stmt.where(GeoFact.trust_level == trust_level)
    stmt = stmt.order_by(GeoFact.id.desc())
    rows = list(await session.scalars(stmt))
    return {"items": [_fact_payload(r) for r in rows]}


@router.post("/facts")
async def create_fact(
    req: FactCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    _validate_fact_source(req.source_name, req.trust_level)
    row = GeoFact(
        tenant_id=req.tenant_id,
        title=req.title.strip(),
        statement=req.statement.strip(),
        fact_type=req.fact_type,
        source_name=req.source_name.strip(),
        source_url=req.source_url,
        observed_at=req.observed_at,
        trust_level=req.trust_level,
        author_name=req.author_name,
        meta=req.meta,
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _fact_payload(row)


@router.patch("/facts/{fact_id}")
async def update_fact(
    fact_id: int,
    req: FactUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await _get_fact(session, fact_id, tenant_id)
    data = req.model_dump(exclude_unset=True)
    trust = data.get("trust_level", row.trust_level)
    source_name = data.get("source_name", row.source_name)
    _validate_fact_source(source_name or "", trust)
    for key, value in data.items():
        if isinstance(value, str) and key in {"title", "statement", "source_name"}:
            value = value.strip()
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return _fact_payload(row)


@router.post("/facts/{fact_id}/verify")
async def verify_fact(
    fact_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await _get_fact(session, fact_id, tenant_id)
    _validate_fact_source(row.source_name, "verified")
    row.trust_level = "verified"
    await session.commit()
    await session.refresh(row)
    return _fact_payload(row)


@router.post("/facts/import")
async def import_facts_file(
    tenant_id: int = Query(...),
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    await _ensure_tenant_exists(session, tenant_id)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "CSV 文件为空")
    result = await import_facts_csv(
        session, tenant_id=tenant_id, user_id=ctx.user_id, file_bytes=raw
    )
    await session.commit()
    return result


# ---------- content tasks ----------


@router.post("/prompts/import-csv")
async def import_prompts_csv_file(
    tenant_id: int = Query(...),
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    await _ensure_tenant_exists(session, tenant_id)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "CSV 文件为空")
    result = await import_prompts_csv(
        session, tenant_id=tenant_id, user_id=ctx.user_id, file_bytes=raw
    )
    await session.commit()
    created = result.pop("items", [])
    for row in created:
        await session.refresh(row)
    return {
        "count": result["count"],
        "errors": result["errors"],
        "items": [_prompt_payload(r) for r in created],
    }


@router.get("/content-tasks")
async def list_tasks(
    tenant_id: int = Query(...),
    status: str | None = Query(None),
    pipeline_step: str | None = Query(None),
    q: str | None = Query(None),
    owner_user_id: int | None = Query(None),
    from_diagnosis: bool | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoContentTask).where(GeoContentTask.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(GeoContentTask.status == status)
    if pipeline_step:
        stmt = stmt.where(GeoContentTask.pipeline_step == pipeline_step)
    if owner_user_id is not None:
        stmt = stmt.where(GeoContentTask.owner_user_id == owner_user_id)
    if from_diagnosis is True:
        stmt = stmt.where(GeoContentTask.diagnosis_audit_id.is_not(None))
    elif from_diagnosis is False:
        stmt = stmt.where(GeoContentTask.diagnosis_audit_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(GeoContentTask.title.ilike(like), GeoContentTask.blocked_reason.ilike(like))
        )
    stmt = stmt.order_by(GeoContentTask.id.desc())
    rows = list(await session.scalars(stmt))
    items = [await _task_payload(session, r, detail=False) for r in rows]
    return {"items": items}


@router.post("/content-tasks")
async def create_task(
    req: TaskCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    prompt = await _get_prompt(session, req.prompt_id, req.tenant_id)
    title = (req.title or prompt.question).strip()
    task = GeoContentTask(
        tenant_id=req.tenant_id,
        prompt_id=prompt.id,
        title=title,
        status="draft",
        target_channels=req.target_channels or ["website", "zhihu"],
        owner_user_id=ctx.user_id,
        pipeline_step="opportunity",
        brief=req.brief,
    )
    session.add(task)
    await session.flush()
    prompt.last_task_id = task.id
    if req.fact_ids:
        await _bind_facts(session, task, req.fact_ids)
    else:
        await _sync_task_pipeline(session, task)
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.post("/content-tasks/from-diagnosis")
async def create_task_from_diagnosis_route(
    req: TaskFromDiagnosis,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    task, _prompt, _facts = await create_task_from_diagnosis(
        session,
        tenant_id=req.tenant_id,
        audit_id=req.audit_id,
        advice_code=req.advice_code,
        user_id=ctx.user_id,
    )
    await session.commit()
    await session.refresh(task)
    payload = await _task_payload(session, task, detail=True)
    payload["editor_path"] = editor_path(task_id=task.id, tenant_id=req.tenant_id)
    return payload


@router.post("/content-tasks/{task_id}/seed-diagnosis-facts")
async def seed_diagnosis_facts_route(
    task_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """为已有诊断桥任务补齐对齐事实卡（仅在尚未绑定时写入）。"""
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    await create_and_bind_diagnosis_facts(
        session, task, user_id=ctx.user_id, replace_empty_only=True
    )
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.patch("/content-tasks/{task_id}")
async def patch_task(
    task_id: int,
    req: TaskUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    data = req.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
    for key, value in data.items():
        setattr(task, key, value)
    await _sync_task_pipeline(session, task)
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.get("/content-tasks/{task_id}")
async def get_task(
    task_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    return await _task_payload(session, task, detail=True)


@router.put("/content-tasks/{task_id}/facts")
async def update_task_facts(
    task_id: int,
    req: TaskFactsUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    await _bind_facts(session, task, req.fact_ids)
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.put("/content-tasks/{task_id}/article")
async def save_article(
    task_id: int,
    req: ArticleUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    latest = await _latest_article(session, task.id)
    version_no = (latest.version_no + 1) if latest else 1
    article = GeoArticleVersion(
        task_id=task.id,
        version_no=version_no,
        kind="master",
        title=req.title.strip(),
        body_markdown=req.body_markdown,
        outline=req.outline or (latest.outline if latest else {}),
        author_name=(latest.author_name if latest else None),
        generation_meta={"source": "manual_edit", "from_version": latest.version_no if latest else None},
        created_by=ctx.user_id,
    )
    session.add(article)
    task.title = req.title.strip()
    if task.status in {"draft", "facts_bound", "generating", "failed"}:
        task.status = "editing"
    await _sync_task_pipeline(session, task)
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.post("/content-tasks/{task_id}/check")
async def check_task(
    task_id: int,
    tenant_id: int = Query(...),
    require_channels: bool = Query(False),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    article = await _latest_article(session, task.id)
    rule_input = await _build_rule_input(session, task, article)
    checks = run_checks(rule_input)
    ready = is_ready(checks, require_channels=require_channels)
    check_dicts = [c.to_dict() for c in checks]
    patches = build_fix_patches(rule_input)
    task.rule_result = {
        "ready": ready,
        "require_channels": require_channels,
        "checks": check_dicts,
        "checked_at": datetime.utcnow().isoformat(),
    }
    if ready:
        task.status = "ready"
        task.ready_at = task.ready_at or datetime.utcnow()
    elif article is not None:
        task.status = "needs_fix"
    await _sync_task_pipeline(session, task, checks=check_dicts)
    await session.commit()
    await session.refresh(task)
    return {
        "ready": ready,
        "checks": check_dicts,
        "patches": patches,
        "task": await _task_payload(session, task, detail=True),
    }


@router.post("/content-tasks/{task_id}/apply-patch")
async def apply_patch(
    task_id: int,
    req: ApplyPatchRequest,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    article = await _latest_article(session, task.id)
    if article is None:
        raise HTTPException(400, "请先生成或保存母稿")
    rule_input = await _build_rule_input(session, task, article)
    patch = next((p for p in build_fix_patches(rule_input) if p["code"] == req.code), None)
    if patch is None:
        raise HTTPException(400, f"无可用修复补丁: {req.code}")
    insert = patch["insert_markdown"]
    if patch.get("cursor_hint") == "prepend":
        new_body = insert + "\n" + article.body_markdown
    else:
        new_body = article.body_markdown.rstrip() + "\n" + insert
    author_name = req.author_name or article.author_name
    if req.code == "author_visible" and req.author_name:
        author_name = req.author_name
    version_no = article.version_no + 1
    new_article = GeoArticleVersion(
        task_id=task.id,
        version_no=version_no,
        kind="master",
        title=article.title,
        body_markdown=new_body,
        outline=article.outline,
        author_name=author_name,
        generation_meta={"source": "apply_patch", "patch_code": req.code},
        created_by=ctx.user_id,
    )
    session.add(new_article)
    task.status = "editing"
    await session.flush()
    rule_input = await _build_rule_input(session, task, new_article)
    checks = run_checks(rule_input)
    check_dicts = [c.to_dict() for c in checks]
    ready = is_ready(checks, require_channels=False)
    task.rule_result = {
        "ready": ready,
        "require_channels": False,
        "checks": check_dicts,
        "checked_at": datetime.utcnow().isoformat(),
    }
    task.status = "ready" if ready else "needs_fix"
    await _sync_task_pipeline(session, task, checks=check_dicts)
    await session.commit()
    await session.refresh(task)
    return {
        "applied": req.code,
        "ready": ready,
        "checks": check_dicts,
        "patches": build_fix_patches(rule_input),
        "task": await _task_payload(session, task, detail=True),
    }


@router.post("/content-tasks/{task_id}/generate")
async def generate_task_article(
    task_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    tenant = await _ensure_tenant_exists(session, tenant_id)
    prompt = await _get_prompt(session, task.prompt_id, tenant_id)
    facts = await _task_facts(session, task.id)
    if len(facts) < 3:
        raise HTTPException(400, "生成前至少绑定 3 条带来源的事实卡")

    task.status = "generating"
    await session.commit()
    try:
        payload = await generate_master_article(
            tenant_name=tenant.name,
            question=prompt.question,
            facts=_fact_dicts(facts),
        )
        body = to_markdown(payload)
        outline = outline_from_payload(payload)
        latest = await _latest_article(session, task.id)
        version_no = (latest.version_no + 1) if latest else 1
        article = GeoArticleVersion(
            task_id=task.id,
            version_no=version_no,
            kind="master",
            title=payload["title"],
            body_markdown=body,
            outline=outline,
            generation_meta={
                "source": payload.get("_source"),
                "used_fact_ids": payload.get("used_fact_ids"),
            },
            created_by=ctx.user_id,
        )
        session.add(article)
        task.title = payload["title"]
        task.status = "editing"
        await session.commit()
    except GeoContentError as exc:
        task.status = "failed"
        await session.commit()
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        task.status = "failed"
        await session.commit()
        raise
    except Exception as exc:
        task.status = "failed"
        await session.commit()
        raise HTTPException(500, f"生成失败: {exc}") from exc

    # auto-check without requiring channels
    await session.refresh(task)
    article = await _latest_article(session, task.id)
    rule_input = await _build_rule_input(session, task, article)
    checks = run_checks(rule_input)
    ready = is_ready(checks, require_channels=False)
    task.rule_result = {
        "ready": ready,
        "require_channels": False,
        "checks": [c.to_dict() for c in checks],
        "checked_at": datetime.utcnow().isoformat(),
    }
    task.status = "ready" if ready else "needs_fix"
    if ready:
        task.ready_at = task.ready_at or datetime.utcnow()
    await _sync_task_pipeline(session, task, checks=[c.to_dict() for c in checks])
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.post("/content-tasks/{task_id}/variants")
async def create_variants(
    task_id: int,
    req: VariantsCreate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    article = await _latest_article(session, task.id)
    if article is None:
        raise HTTPException(400, "请先生成或保存母稿")
    channels = req.channels or list(task.target_channels or ["website", "zhihu"])
    existing = {v.channel: v for v in await _variants(session, task.id)}
    created = []
    for channel in channels:
        try:
            title, body = adapt_for_channel(
                channel, article.title, article.body_markdown, article.outline or {}
            )
        except GeoContentError as exc:
            raise HTTPException(400, str(exc)) from exc
        if channel in existing:
            variant = existing[channel]
            variant.title = title
            variant.body_markdown = body
            variant.article_version_id = article.id
            variant.status = "draft"
        else:
            variant = GeoChannelVariant(
                task_id=task.id,
                article_version_id=article.id,
                channel=channel,
                title=title,
                body_markdown=body,
                export_format="markdown",
                status="draft",
            )
            session.add(variant)
        created.append(channel)
    # refresh target channels union
    task.target_channels = sorted(set((task.target_channels or []) + channels))
    await _sync_task_pipeline(session, task)
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.get("/content-tasks/{task_id}/export")
async def export_variant(
    task_id: int,
    tenant_id: int = Query(...),
    channel: str = Query("website"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    variants = {v.channel: v for v in await _variants(session, task.id)}
    variant = variants.get(channel)
    if variant is None:
        raise HTTPException(404, f"渠道版本不存在: {channel}")
    variant.status = "exported"
    if task.status in {"ready", "editing", "needs_fix"}:
        task.status = "exported"
    await _sync_task_pipeline(session, task)
    await session.commit()
    return {
        "channel": channel,
        "title": variant.title,
        "body_markdown": variant.body_markdown,
        "export_format": variant.export_format,
        "status": variant.status,
    }


@router.post("/content-tasks/{task_id}/publications")
async def record_publication(
    task_id: int,
    req: PublicationCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    task = await _get_task(session, task_id, req.tenant_id)
    url = req.published_url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL 无效，需以 http:// 或 https:// 开头")
    variants = {v.channel: v for v in await _variants(session, task.id)}
    variant = variants.get(req.channel)
    if variant is None:
        raise HTTPException(400, "请先生成该渠道版本")
    article = await _latest_article(session, task.id)
    rule_input = await _build_rule_input(session, task, article)
    try:
        assert_can_publish(rule_input)
    except PublishGateError as exc:
        raise HTTPException(400, str(exc)) from exc
    pub = GeoPublication(
        variant_id=variant.id,
        channel=req.channel,
        publish_mode="manual_export",
        published_url=url,
        published_at=datetime.utcnow(),
        status="published",
        note=req.note,
    )
    session.add(pub)
    variant.status = "published"
    task.status = "published"
    await _sync_task_pipeline(session, task)
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.get("/content-stats")
async def content_stats(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """轻量概览计数，供 dashboard 使用。"""
    ctx.ensure_tenant(tenant_id)
    prompts = await session.scalar(
        select(func.count()).select_from(GeoPrompt).where(
            GeoPrompt.tenant_id == tenant_id, GeoPrompt.status == "active"
        )
    )
    facts = await session.scalar(
        select(func.count()).select_from(GeoFact).where(
            GeoFact.tenant_id == tenant_id, GeoFact.status == "active"
        )
    )
    tasks = await session.scalar(
        select(func.count()).select_from(GeoContentTask).where(
            GeoContentTask.tenant_id == tenant_id
        )
    )
    ready = await session.scalar(
        select(func.count()).select_from(GeoContentTask).where(
            GeoContentTask.tenant_id == tenant_id,
            GeoContentTask.status.in_(["ready", "exported", "published"]),
        )
    )
    published = await session.scalar(
        select(func.count()).select_from(GeoContentTask).where(
            GeoContentTask.tenant_id == tenant_id, GeoContentTask.status == "published"
        )
    )
    todo_blocked = await session.scalar(
        select(func.count()).select_from(GeoContentTask).where(
            GeoContentTask.tenant_id == tenant_id,
            GeoContentTask.status == "needs_fix",
        )
    )
    todo_ready = await session.scalar(
        select(func.count()).select_from(GeoContentTask).where(
            GeoContentTask.tenant_id == tenant_id,
            GeoContentTask.status == "ready",
        )
    )
    todo_publish = await session.scalar(
        select(func.count()).select_from(GeoContentTask).where(
            GeoContentTask.tenant_id == tenant_id,
            GeoContentTask.status == "exported",
        )
    )
    from_diagnosis = await session.scalar(
        select(func.count()).select_from(GeoContentTask).where(
            GeoContentTask.tenant_id == tenant_id,
            GeoContentTask.diagnosis_audit_id.isnot(None),
        )
    )
    return {
        "prompts": int(prompts or 0),
        "facts": int(facts or 0),
        "tasks": int(tasks or 0),
        "ready_or_beyond": int(ready or 0),
        "published": int(published or 0),
        "todo_blocked": int(todo_blocked or 0),
        "todo_ready": int(todo_ready or 0),
        "todo_publish": int(todo_publish or 0),
        "from_diagnosis_count": int(from_diagnosis or 0),
    }
