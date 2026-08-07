"""GEO 内容工作台 API：机会 / 事实 / 任务 / 生成 / 渠道 / 回填。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
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
from app.geo.content.channel_profiles import get_profile, list_profiles
from app.geo.content.channel_registry import (
    channel_options_from_registry,
    enabled_types_from_rows,
    filter_channels_by_registry,
    publication_publish_mode,
    publish_mode_for_channel,
    registry_row_dicts,
)
from app.geo.content.channels import default_channel_rows
from app.geo.content.review import (
    apply_decision,
    apply_submit,
    invalidate_review,
    review_payload,
)
from app.geo.content.ai_settings import (
    apply_provider_preset,
    encrypt_api_key,
    ensure_ai_setting,
    preset_payload,
    resolve_llm_credentials,
    settings_public_payload,
)
from app.geo.content.deliverables import (
    build_deliverables_pack,
    render_deliverables_markdown,
)
from app.geo.content.engines import default_engine_rows
from app.geo.content.probe import (
    resolve_batch_engines,
    resolve_engine_llm,
    run_probe_draft,
)
from app.geo.content.schemas import (
    AiSettingsUpdate,
    AnswerSnapshotCreate,
    AnswerSnapshotExtractUrlsRequest,
    AnswerSnapshotProbeBatchRequest,
    AnswerSnapshotProbeRequest,
    AnswerSnapshotSuggestFieldsRequest,
    AnswerSnapshotUpdate,
    ApplyPatchRequest,
    ArticleUpdate,
    ChannelAccountCreate,
    ChannelAccountUpdate,
    FactCreate,
    FactUpdate,
    MediaPlacementCreate,
    MediaPlacementUpdate,
    PromptExpandRequest,
    PromptPromoteRequest,
    PublishingChannelCreate,
    PublishingChannelUpdate,
    OptimizationBusinessCreate,
    OptimizationBusinessUpdate,
    OptimizationUnitCreate,
    OptimizationUnitUpdate,
    PromptCreate,
    PromptImportRequest,
    PromptUpdate,
    PublicationCreate,
    AiReviewRequest,
    RetrieveFactsApplyRequest,
    RetrieveFactsRequest,
    ReviewDecision,
    ReviewSubmit,
    SuggestBriefRequest,
    WebhookPushRequest,
    PushBatchRequest,
    TaskCreate,
    TaskFactsUpdate,
    TaskFromDiagnosis,
    TaskUpdate,
    TrackingEnginesPut,
    VariantUpdate,
    VariantsCreate,
    VisibilityPatrolCreate,
    VisibilityPatrolSettingsUpdate,
)
from app.geo.content.cn_blueprint import (
    blueprint_payload,
    default_media_placement_rows,
    match_blueprint_for_domain,
)
from app.geo.content.prompt_taxonomy import (
    brand_names_from_tenant,
    normalize_market,
    normalize_question_group,
    resolve_is_brand_probe,
)
from app.geo.content.snapshot_suggest import (
    normalize_suggest_payload,
    suggest_system_prompt,
    suggest_user_prompt,
)
from app.geo.content.snapshots import (
    apply_brand_mention_tags,
    compute_window_metrics,
    domain_matches,
    extract_cited_domain,
    extract_cited_domains,
    extract_cited_urls_from_text,
    in_captured_window,
    needs_recheck,
    normalize_brand_position,
    normalize_cited_urls,
    normalize_competitors,
    normalize_sentiment,
    parse_window_bound,
    rate_delta,
    split_visibility_metrics,
    visibility_mention_rate,
)
from app.geo.content.variants import (
    GeoContentError,
    adapt_for_channel,
    build_adapt_meta,
    normalize_channels,
)
from app.models import (
    GeoAnswerSnapshot,
    GeoArticleVersion,
    GeoChannelVariant,
    GeoChannelAccount,
    GeoContentTask,
    GeoDailyMetric,
    GeoExpandRun,
    GeoFact,
    GeoMediaPlacement,
    GeoOptimizationBusiness,
    GeoOptimizationUnit,
    GeoPrompt,
    GeoPublication,
    GeoPublishingChannel,
    GeoTaskFact,
    GeoTrackingEngine,
    GeoVisibilityPatrolRun,
    GeoVisibilityPatrolSettings,
    Tenant,
)
from app.security.auth import AuthContext, require_scoped_auth

router = APIRouter(tags=["GEO 内容"], dependencies=[Depends(require_scoped_auth)])


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _prompt_payload(
    row: GeoPrompt,
    *,
    last_snapshot: GeoAnswerSnapshot | None = None,
    need_recheck_flag: bool | None = None,
) -> dict[str, Any]:
    payload = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "unit_id": getattr(row, "unit_id", None),
        "question": row.question,
        "language": row.language,
        "priority": row.priority,
        "tags": row.tags or [],
        "demand_note": row.demand_note,
        "status": row.status,
        "source": row.source,
        "question_group": row.question_group,
        "market": row.market or "cn",
        "is_brand_probe": bool(row.is_brand_probe),
        "created_by": row.created_by,
        "owner_user_id": row.owner_user_id,
        "last_task_id": row.last_task_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "last_snapshot_at": None,
        "last_mentions_brand": None,
        "last_snapshot_engine": None,
        "need_recheck": bool(need_recheck_flag) if need_recheck_flag is not None else False,
    }
    if last_snapshot is not None:
        payload["last_snapshot_at"] = _iso(last_snapshot.captured_at)
        payload["last_mentions_brand"] = bool(last_snapshot.mentions_brand)
        payload["last_snapshot_engine"] = last_snapshot.engine
    return payload


async def _latest_snapshots_by_prompt(
    session: AsyncSession, tenant_id: int, prompt_ids: list[int]
) -> dict[int, GeoAnswerSnapshot]:
    if not prompt_ids:
        return {}
    rows = list(
        await session.scalars(
            select(GeoAnswerSnapshot)
            .where(
                GeoAnswerSnapshot.tenant_id == tenant_id,
                GeoAnswerSnapshot.prompt_id.in_(prompt_ids),
            )
            .order_by(
                GeoAnswerSnapshot.prompt_id.asc(),
                GeoAnswerSnapshot.captured_at.desc(),
                GeoAnswerSnapshot.id.desc(),
            )
        )
    )
    latest: dict[int, GeoAnswerSnapshot] = {}
    for row in rows:
        if row.prompt_id not in latest:
            latest[row.prompt_id] = row
    return latest


async def _published_task_updated_by_prompt(
    session: AsyncSession, tenant_id: int, prompt_ids: list[int]
) -> dict[int, datetime]:
    """Map prompt_id -> max updated_at among published tasks."""
    if not prompt_ids:
        return {}
    result = await session.execute(
        select(
            GeoContentTask.prompt_id,
            func.max(GeoContentTask.updated_at),
        )
        .where(
            GeoContentTask.tenant_id == tenant_id,
            GeoContentTask.status == "published",
            GeoContentTask.prompt_id.in_(prompt_ids),
        )
        .group_by(GeoContentTask.prompt_id)
    )
    return {int(pid): updated for pid, updated in result.all() if pid is not None}


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
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
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
        try:
            n = int(fid)
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in unique_ids:
            unique_ids.append(n)
    facts: list[GeoFact] = []
    for fid in unique_ids:
        fact = await _get_fact(session, fid, task.tenant_id)
        if fact.status != "active":
            raise HTTPException(400, f"事实卡 {fid} 已归档")
        facts.append(fact)
    await session.execute(delete(GeoTaskFact).where(GeoTaskFact.task_id == task.id))
    for idx, fact in enumerate(facts):
        session.add(GeoTaskFact(task_id=task.id, fact_id=fact.id, sort_order=idx))
    # flush so _task_facts / pipeline sync see new link rows before commit
    await session.flush()
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
            "status": f.status,
            "author_name": f.author_name,
            "observed_at": f.observed_at.isoformat() if f.observed_at else None,
            "expires_at": f.expires_at.isoformat() if f.expires_at else None,
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


async def _evaluate_and_store_rules(
    session: AsyncSession,
    task: GeoContentTask,
    article: GeoArticleVersion | None,
    *,
    require_channels: bool = False,
) -> dict[str, Any]:
    """Run checks + GEO Score and persist onto task.rule_result.

    Used by check endpoint and after channel-variant generation so
    channel_variant_ready does not stay stale as failed in the UI.
    """
    from app.config import get_settings
    from app.geo.content.draft_lint import lint_draft, lint_summary
    from app.geo.content.extractable_blocks import blocks_payload
    from app.geo.content.geo_score import compute_geo_score, score_blocks_ready

    rule_input = await _build_rule_input(session, task, article)
    checks = run_checks(rule_input)
    check_dicts = [c.to_dict() for c in checks]
    ready = is_ready(checks, require_channels=require_channels)
    patches = build_fix_patches(rule_input)
    lint = lint_summary(
        lint_draft(rule_input.body_markdown or "", facts=rule_input.facts or [])
    )
    blocks = blocks_payload(rule_input.body_markdown or "")
    lint_ok = bool(lint.get("blocks_ready")) if isinstance(lint, dict) else None
    score_payload = compute_geo_score(
        rule_input,
        brief=task.brief if isinstance(task.brief, dict) else {},
        lint_ok=lint_ok,
        rule_checks=checks,
    )
    settings = get_settings()
    score_ok, score_msg = score_blocks_ready(
        score_payload,
        threshold=int(getattr(settings, "geo_score_threshold", 60) or 60),
        gate_enabled=bool(getattr(settings, "geo_score_gate", False)),
    )
    if not score_ok:
        ready = False

    prev_rr = task.rule_result if isinstance(task.rule_result, dict) else {}
    ai_review = prev_rr.get("ai_review") if isinstance(prev_rr.get("ai_review"), dict) else None
    task.rule_result = {
        "ready": ready,
        "require_channels": require_channels,
        "checks": check_dicts,
        "lint": lint,
        "blocks": blocks,
        "geo_score": score_payload["geo_score"],
        "geo_subscores": score_payload["geo_subscores"],
        "geo_actions": score_payload["geo_actions"],
        "geo_score_gate": bool(getattr(settings, "geo_score_gate", False)),
        "geo_score_threshold": int(getattr(settings, "geo_score_threshold", 60) or 60),
        "geo_score_gate_message": score_msg or None,
        "ai_review": ai_review,
        "checked_at": datetime.utcnow().isoformat(),
        "variant_channels": list(rule_input.variants or []),
        "target_channels": list(rule_input.target_channels or []),
    }
    if ready:
        task.status = "ready"
        task.ready_at = task.ready_at or datetime.utcnow()
    elif article is not None:
        # keep terminal export statuses
        if task.status not in {"exported", "published"}:
            task.status = "needs_fix"
    await _sync_task_pipeline(session, task, checks=check_dicts)
    return {
        "ready": ready,
        "checks": check_dicts,
        "patches": patches,
        "lint": lint,
        "blocks": blocks,
        "geo_score": score_payload["geo_score"],
        "geo_subscores": score_payload["geo_subscores"],
        "geo_actions": score_payload["geo_actions"],
        "geo_score_gate": bool(getattr(settings, "geo_score_gate", False)),
        "geo_score_threshold": int(getattr(settings, "geo_score_threshold", 60) or 60),
        "variant_channels": list(rule_input.variants or []),
        "target_channels": list(rule_input.target_channels or []),
    }


async def _task_payload(
    session: AsyncSession, task: GeoContentTask, *, detail: bool = False
) -> dict[str, Any]:
    prompt = await session.get(GeoPrompt, task.prompt_id)
    from app.geo.content.brief import brief_ready, normalize_brief

    from app.geo.content.brief import strategy_richness

    brief = normalize_brief(task.brief)
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
        "brief": brief,
        "brief_ready": brief_ready(brief),
        "strategy_richness": strategy_richness(brief),
        **review_payload(task),
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
                    "adapt_meta": v.adapt_meta or {},
                    "stale": bool(
                        article is not None and v.article_version_id != article.id
                    ),
                    "updated_at": _iso(v.updated_at),
                }
                for v in variants
            ],
            "publications": pubs,
            "channel_profiles": list_profiles(),
            "channel_options": await _channel_options_payload(session, task.tenant_id),
        }
    )
    return payload


async def _channel_options_payload(session: AsyncSession, tenant_id: int) -> list[dict]:
    rows = await _ensure_default_publishing_channels(session, tenant_id)
    return channel_options_from_registry(registry_row_dicts(rows))


@router.get("/content-health")
async def content_health() -> dict:
    return {"module": "geo-content", "status": "ok"}


@router.get("/content-brief-catalog")
async def content_brief_catalog(
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """Brief 枚举与必填字段（前端表单）。"""
    from app.geo.content.brief import catalog_payload

    _ = ctx
    return catalog_payload()


@router.get("/channel-profiles")
async def get_channel_profiles(
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    _ = ctx
    return {"items": list_profiles()}


@router.get("/publishing-channel-options")
async def get_publishing_channel_options(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Enabled registry channels mapped to adapt profiles (editor picker)."""
    ctx.ensure_tenant(tenant_id)
    options = await _channel_options_payload(session, tenant_id)
    return {"items": options}


# ---------- 优化业务 / 单元（三级结构）----------


def _business_payload(row: GeoOptimizationBusiness, *, unit_count: int | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "sort_order": row.sort_order,
        "unit_count": unit_count,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _unit_payload(row: GeoOptimizationUnit, *, prompt_count: int | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "business_id": row.business_id,
        "name": row.name,
        "keyword": row.keyword,
        "description": row.description,
        "status": row.status,
        "sort_order": row.sort_order,
        "prompt_count": prompt_count,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


@router.get("/optimization-businesses")
async def list_optimization_businesses(
    tenant_id: int = Query(...),
    status: str | None = Query("active"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """优化业务列表。"""
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoOptimizationBusiness).where(GeoOptimizationBusiness.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(GeoOptimizationBusiness.status == status)
    stmt = stmt.order_by(GeoOptimizationBusiness.sort_order.asc(), GeoOptimizationBusiness.id.desc())
    rows = list(await session.scalars(stmt))
    items = []
    for r in rows:
        cnt = await session.scalar(
            select(func.count())
            .select_from(GeoOptimizationUnit)
            .where(
                GeoOptimizationUnit.business_id == r.id,
                GeoOptimizationUnit.tenant_id == tenant_id,
            )
        )
        items.append(_business_payload(r, unit_count=int(cnt or 0)))
    return {"items": items}


@router.post("/optimization-businesses")
async def create_optimization_business(
    req: OptimizationBusinessCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="业务名称不能为空")
    exists = await session.scalar(
        select(GeoOptimizationBusiness).where(
            GeoOptimizationBusiness.tenant_id == req.tenant_id,
            GeoOptimizationBusiness.name == name,
        )
    )
    if exists:
        raise HTTPException(status_code=409, detail="同名优化业务已存在")
    row = GeoOptimizationBusiness(
        tenant_id=req.tenant_id,
        name=name,
        description=req.description,
        sort_order=req.sort_order,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _business_payload(row, unit_count=0)


@router.patch("/optimization-businesses/{business_id}")
async def update_optimization_business(
    business_id: int,
    req: OptimizationBusinessUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await session.scalar(
        select(GeoOptimizationBusiness).where(
            GeoOptimizationBusiness.id == business_id,
            GeoOptimizationBusiness.tenant_id == tenant_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="优化业务不存在")
    data = req.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(status_code=400, detail="业务名称不能为空")
    for key, value in data.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return _business_payload(row)


@router.get("/optimization-units")
async def list_optimization_units(
    tenant_id: int = Query(...),
    business_id: int | None = Query(None),
    status: str | None = Query("active"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """优化单元（关键词）列表。"""
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoOptimizationUnit).where(GeoOptimizationUnit.tenant_id == tenant_id)
    if business_id is not None:
        stmt = stmt.where(GeoOptimizationUnit.business_id == business_id)
    if status:
        stmt = stmt.where(GeoOptimizationUnit.status == status)
    stmt = stmt.order_by(GeoOptimizationUnit.sort_order.asc(), GeoOptimizationUnit.id.desc())
    rows = list(await session.scalars(stmt))
    items = []
    for r in rows:
        cnt = await session.scalar(
            select(func.count())
            .select_from(GeoPrompt)
            .where(GeoPrompt.unit_id == r.id, GeoPrompt.tenant_id == tenant_id)
        )
        items.append(_unit_payload(r, prompt_count=int(cnt or 0)))
    return {"items": items}


@router.post("/optimization-units")
async def create_optimization_unit(
    req: OptimizationUnitCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    biz = await session.scalar(
        select(GeoOptimizationBusiness).where(
            GeoOptimizationBusiness.id == req.business_id,
            GeoOptimizationBusiness.tenant_id == req.tenant_id,
        )
    )
    if not biz:
        raise HTTPException(status_code=400, detail="所属优化业务不存在")
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="单元名称不能为空")
    row = GeoOptimizationUnit(
        tenant_id=req.tenant_id,
        business_id=req.business_id,
        name=name,
        keyword=(req.keyword or "").strip() or name,
        description=req.description,
        sort_order=req.sort_order,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _unit_payload(row, prompt_count=0)


@router.patch("/optimization-units/{unit_id}")
async def update_optimization_unit(
    unit_id: int,
    req: OptimizationUnitUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await session.scalar(
        select(GeoOptimizationUnit).where(
            GeoOptimizationUnit.id == unit_id,
            GeoOptimizationUnit.tenant_id == tenant_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="优化单元不存在")
    data = req.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
    if "keyword" in data and data["keyword"] is not None:
        data["keyword"] = data["keyword"].strip() or None
    if "business_id" in data and data["business_id"] is not None:
        biz = await session.scalar(
            select(GeoOptimizationBusiness).where(
                GeoOptimizationBusiness.id == data["business_id"],
                GeoOptimizationBusiness.tenant_id == tenant_id,
            )
        )
        if not biz:
            raise HTTPException(status_code=400, detail="目标优化业务不存在")
    for key, value in data.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return _unit_payload(row)


@router.get("/daily-metrics")
async def list_daily_metrics(
    tenant_id: int = Query(...),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    business_id: int | None = Query(None),
    unit_id: int | None = Query(None),
    scope_key: str | None = Query(None),
    scope_level: str | None = Query(
        None, description="tenant | business | unit；与 scope_key 二选一优先 scope_key"
    ),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """按天汇总指标（品牌提及率 / 点名认知 / AI 引用次数）。

    切片：
    - scope_key=t / scope_level=tenant：租户全量
    - scope_key=b{id} 或 business_id + scope_level=business：优化业务
    - scope_key=u{id} 或 unit_id + scope_level=unit：优化单元

    统计口径见 citation_stat_note。
    """
    from app.geo.content.daily_metrics import (
        CITATION_STAT_NOTE,
        METRIC_LABELS,
        metric_row_payload,
        scope_business,
        scope_tenant,
        scope_unit,
    )

    ctx.ensure_tenant(tenant_id)
    end = date_to or date.today()
    start = date_from or (end - timedelta(days=13))
    stmt = select(GeoDailyMetric).where(
        GeoDailyMetric.tenant_id == tenant_id,
        GeoDailyMetric.metric_date >= start,
        GeoDailyMetric.metric_date <= end,
    )

    resolved_scope = scope_key
    if not resolved_scope:
        if unit_id is not None and (scope_level in (None, "unit")):
            resolved_scope = scope_unit(unit_id)
        elif business_id is not None and scope_level == "business":
            resolved_scope = scope_business(business_id)
        elif scope_level == "tenant":
            resolved_scope = scope_tenant()
        elif scope_level == "business":
            stmt = stmt.where(GeoDailyMetric.scope_key.like("b%"))
        elif scope_level == "unit":
            stmt = stmt.where(GeoDailyMetric.scope_key.like("u%"))
            if business_id is not None:
                stmt = stmt.where(GeoDailyMetric.business_id == business_id)

    if resolved_scope:
        stmt = stmt.where(GeoDailyMetric.scope_key == resolved_scope)
    elif business_id is not None and scope_level not in ("unit", "business"):
        # 兼容：只传 business_id 时返回该业务 scope（b{id}），不含下属 unit
        stmt = stmt.where(GeoDailyMetric.scope_key == scope_business(business_id))
    elif unit_id is not None and not resolved_scope:
        stmt = stmt.where(GeoDailyMetric.scope_key == scope_unit(unit_id))

    stmt = stmt.order_by(
        GeoDailyMetric.metric_date.asc(),
        GeoDailyMetric.scope_key.asc(),
        GeoDailyMetric.id.asc(),
    )
    rows = list(await session.scalars(stmt))

    biz_names: dict[int, str] = {}
    unit_names: dict[int, str] = {}
    unit_biz: dict[int, int] = {}
    unit_ids = {r.unit_id for r in rows if r.unit_id}
    biz_ids = {r.business_id for r in rows if r.business_id}
    if unit_ids:
        for u in await session.scalars(
            select(GeoOptimizationUnit).where(
                GeoOptimizationUnit.tenant_id == tenant_id,
                GeoOptimizationUnit.id.in_(list(unit_ids)),
            )
        ):
            unit_names[u.id] = u.name
            unit_biz[u.id] = u.business_id
            biz_ids.add(u.business_id)
    if biz_ids:
        for b in await session.scalars(
            select(GeoOptimizationBusiness).where(
                GeoOptimizationBusiness.tenant_id == tenant_id,
                GeoOptimizationBusiness.id.in_(list(biz_ids)),
            )
        ):
            biz_names[b.id] = b.name

    items = []
    for r in rows:
        payload = metric_row_payload(r)
        bid = payload.get("business_id")
        uid = payload.get("unit_id")
        if bid is None and uid and uid in unit_biz:
            bid = unit_biz[uid]
            payload["business_id"] = bid
        payload["business_name"] = biz_names.get(bid) if bid else None
        payload["unit_name"] = unit_names.get(uid) if uid else None
        if payload["scope_level"] == "tenant":
            payload["scope_label"] = "租户"
        elif payload["scope_level"] == "business":
            payload["scope_label"] = payload["business_name"] or f"业务#{bid}"
        elif payload["scope_level"] == "unit":
            un = payload["unit_name"] or f"单元#{uid}"
            bn = payload["business_name"]
            payload["scope_label"] = f"{bn} / {un}" if bn else un
        else:
            payload["scope_label"] = payload["scope_key"]
        items.append(payload)

    return {
        "items": items,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "metric_labels": METRIC_LABELS,
        "citation_stat_note": CITATION_STAT_NOTE,
        "scope_levels": {
            "tenant": "租户全量 · scope_key=t",
            "business": "优化业务 · scope_key=b{id}",
            "unit": "优化单元 · scope_key=u{id}",
        },
    }


@router.post("/daily-metrics/rebuild")
async def rebuild_daily_metrics(
    tenant_id: int = Query(...),
    metric_date: date | None = Query(
        None, description="单日重算；与 date_from/date_to 二选一，优先区间"
    ),
    date_from: date | None = Query(None, description="区间起点（含）"),
    date_to: date | None = Query(None, description="区间终点（含）"),
    include_empty_slices: bool = Query(
        False, description="为活跃业务/单元写入 0 快照行"
    ),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """按日重算租户 + 业务 + 单元切片。

    快照经意图词 unit_id → 单元 → 业务归属后分别聚合。
    未挂单元的意图词只进租户级 t，不进业务/单元切片。
    """
    from app.geo.content.daily_metrics import rebuild_day, rebuild_range

    ctx.ensure_tenant(tenant_id)
    if date_from or date_to:
        end = date_to or date.today()
        start = date_from or end
        result = await rebuild_range(
            session,
            tenant_id,
            start,
            end,
            include_empty_slices=include_empty_slices,
        )
        return {"mode": "range", **result}

    day = metric_date or date.today()
    result = await rebuild_day(
        session, tenant_id, day, include_empty_slices=include_empty_slices
    )
    return {"mode": "day", **result}


# ---------- prompts（优化意图词）----------


@router.get("/prompts")
async def list_prompts(
    tenant_id: int = Query(...),
    status: str | None = Query(None),
    tag: str | None = Query(None),
    question_group: str | None = Query(None),
    is_brand_probe: bool | None = Query(None),
    need_recheck: bool | None = Query(None),
    unit_id: int | None = Query(None),
    business_id: int | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoPrompt).where(GeoPrompt.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(GeoPrompt.status == status)
    if is_brand_probe is not None:
        stmt = stmt.where(GeoPrompt.is_brand_probe.is_(bool(is_brand_probe)))
    if question_group:
        stmt = stmt.where(GeoPrompt.question_group == question_group.strip())
    if unit_id is not None:
        stmt = stmt.where(GeoPrompt.unit_id == unit_id)
    elif business_id is not None:
        unit_ids = list(
            await session.scalars(
                select(GeoOptimizationUnit.id).where(
                    GeoOptimizationUnit.tenant_id == tenant_id,
                    GeoOptimizationUnit.business_id == business_id,
                )
            )
        )
        if unit_ids:
            stmt = stmt.where(GeoPrompt.unit_id.in_(unit_ids))
        else:
            return {"items": []}
    stmt = stmt.order_by(GeoPrompt.priority.desc(), GeoPrompt.id.desc())
    rows = list(await session.scalars(stmt))
    if tag:
        needle = tag.strip()
        rows = [r for r in rows if needle in (r.tags or [])]
    prompt_ids = [r.id for r in rows]
    latest = await _latest_snapshots_by_prompt(session, tenant_id, prompt_ids)
    published_at = await _published_task_updated_by_prompt(session, tenant_id, prompt_ids)
    items = []
    for r in rows:
        snap = latest.get(r.id)
        flag = needs_recheck(
            has_published_task=r.id in published_at,
            task_updated_at=published_at.get(r.id),
            last_snapshot_at=snap.captured_at if snap else None,
        )
        if need_recheck is True and not flag:
            continue
        if need_recheck is False and flag:
            continue
        items.append(
            _prompt_payload(r, last_snapshot=snap, need_recheck_flag=flag)
        )
    return {"items": items}


@router.post("/prompts")
async def create_prompt(
    req: PromptCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    tenant = await _ensure_tenant_exists(session, req.tenant_id)
    q_group = normalize_question_group(req.question_group)
    brand_names = brand_names_from_tenant(
        name=getattr(tenant, "name", None),
        brand_terms=getattr(tenant, "brand_terms", None),
    )
    probe = resolve_is_brand_probe(
        question=req.question,
        brand_names=brand_names,
        explicit=req.is_brand_probe,
        question_group=q_group,
    )
    unit_id = req.unit_id
    if unit_id is not None:
        unit = await session.scalar(
            select(GeoOptimizationUnit).where(
                GeoOptimizationUnit.id == unit_id,
                GeoOptimizationUnit.tenant_id == req.tenant_id,
            )
        )
        if not unit:
            raise HTTPException(status_code=400, detail="优化单元不存在")
    row = GeoPrompt(
        tenant_id=req.tenant_id,
        unit_id=unit_id,
        question=req.question.strip(),
        language=req.language,
        priority=req.priority,
        tags=req.tags,
        demand_note=req.demand_note,
        source=req.source,
        question_group=q_group,
        market=normalize_market(req.market),
        is_brand_probe=probe,
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _prompt_payload(row)


@router.post("/prompts/expand-candidates")
async def expand_prompt_candidates(
    req: PromptExpandRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """百度/Google 下拉拓词 → 候选问句（不入库）。"""
    from app.geo.content.expand import (
        annotate_vs_last_run,
        build_roots,
        candidate_term_key,
        expand_candidates,
    )

    ctx.ensure_tenant(req.tenant_id)
    tenant = await _ensure_tenant_exists(session, req.tenant_id)
    brand_names = brand_names_from_tenant(
        name=getattr(tenant, "name", None),
        brand_terms=getattr(tenant, "brand_terms", None),
    )
    explicit = [r.model_dump() for r in req.roots] if req.roots else None
    roots = build_roots(
        brand_names=brand_names if req.seed_from_tenant else None,
        industry=getattr(tenant, "industry", None) if req.seed_from_tenant else None,
        competitors=req.competitors,
        products=req.products,
        market=req.market,
        explicit_roots=explicit,
    )
    if not roots:
        raise HTTPException(
            400,
            "缺少词根：请填写 roots，或在租户配置品牌名/行业，或传入 competitors",
        )

    existing_rows = (
        await session.scalars(
            select(GeoPrompt.question).where(
                GeoPrompt.tenant_id == req.tenant_id,
                GeoPrompt.status == "active",
            )
        )
    ).all()
    result = await expand_candidates(
        roots=roots,
        existing_questions=set(existing_rows),
        max_terms=req.max_terms,
        throttle_s=0.05,
    )

    prev_run = await session.scalar(
        select(GeoExpandRun)
        .where(GeoExpandRun.tenant_id == req.tenant_id)
        .order_by(GeoExpandRun.created_at.desc(), GeoExpandRun.id.desc())
        .limit(1)
    )
    prev_keys: set[str] | None = None
    last_run_id = None
    if prev_run is not None:
        last_run_id = prev_run.id
        prev_keys = {
            candidate_term_key(it)
            for it in (prev_run.items or [])
            if candidate_term_key(it)
        }
    annotated = annotate_vs_last_run(result["items"], prev_keys)
    result["items"] = annotated["items"]
    result["new_vs_last_count"] = annotated["new_vs_last_count"]
    result["last_run_id"] = last_run_id

    run_id = None
    if req.persist:
        row = GeoExpandRun(
            tenant_id=req.tenant_id,
            market=req.market,
            roots=result.get("roots"),
            items=result.get("items"),
            calls=int(result.get("calls") or 0),
            total=int(result.get("total") or 0),
            new_count=int(result.get("new_count") or 0),
            errors=result.get("errors") or [],
            created_by=ctx.user_id,
        )
        session.add(row)
        await session.flush()
        run_id = row.id
        # Keep last 20 runs per tenant.
        old_ids = list(
            await session.scalars(
                select(GeoExpandRun.id)
                .where(GeoExpandRun.tenant_id == req.tenant_id)
                .order_by(GeoExpandRun.created_at.desc(), GeoExpandRun.id.desc())
                .offset(20)
            )
        )
        if old_ids:
            await session.execute(
                delete(GeoExpandRun).where(GeoExpandRun.id.in_(list(old_ids)))
            )
        await session.commit()
    result["run_id"] = run_id
    return result


@router.post("/prompts/promote-candidates")
async def promote_prompt_candidates(
    req: PromptPromoteRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """勾选拓词候选后批量入库（显式确认）。"""
    ctx.ensure_tenant(req.tenant_id)
    tenant = await _ensure_tenant_exists(session, req.tenant_id)
    brand_names = brand_names_from_tenant(
        name=getattr(tenant, "name", None),
        brand_terms=getattr(tenant, "brand_terms", None),
    )
    existing = {
        str(q).strip().lower()
        for q in (
            await session.scalars(
                select(GeoPrompt.question).where(
                    GeoPrompt.tenant_id == req.tenant_id,
                    GeoPrompt.status == "active",
                )
            )
        ).all()
    }
    created: list[GeoPrompt] = []
    skipped = 0
    for item in req.items:
        q = item.question.strip()
        if q.lower() in existing:
            skipped += 1
            continue
        q_group = normalize_question_group(item.question_group)
        probe = resolve_is_brand_probe(
            question=q,
            brand_names=brand_names,
            explicit=item.is_brand_probe,
            question_group=q_group,
        )
        row = GeoPrompt(
            tenant_id=req.tenant_id,
            question=q,
            language="zh-CN" if item.market != "global" else "en",
            priority=item.priority,
            tags=item.tags or ["from_expand"],
            demand_note=item.demand_note or "来自拓词候选",
            source="expand",
            question_group=q_group,
            market=normalize_market(item.market),
            is_brand_probe=probe,
            created_by=ctx.user_id,
        )
        session.add(row)
        created.append(row)
        existing.add(q.lower())
    await session.commit()
    for row in created:
        await session.refresh(row)
    return {
        "created": len(created),
        "skipped": skipped,
        "items": [_prompt_payload(r) for r in created],
    }


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
    tenant = await _ensure_tenant_exists(session, tenant_id)
    data = req.model_dump(exclude_unset=True)
    if "question" in data and data["question"] is not None:
        data["question"] = data["question"].strip()
    if "question_group" in data:
        data["question_group"] = normalize_question_group(data.get("question_group"))
    if "market" in data and data["market"] is not None:
        data["market"] = normalize_market(data["market"])
    if "unit_id" in data and data["unit_id"] is not None:
        unit = await session.scalar(
            select(GeoOptimizationUnit).where(
                GeoOptimizationUnit.id == data["unit_id"],
                GeoOptimizationUnit.tenant_id == tenant_id,
            )
        )
        if not unit:
            raise HTTPException(status_code=400, detail="优化单元不存在")
    for key, value in data.items():
        if key == "is_brand_probe":
            continue
        setattr(row, key, value)
    brand_names = brand_names_from_tenant(
        name=getattr(tenant, "name", None),
        brand_terms=getattr(tenant, "brand_terms", None),
    )
    if "is_brand_probe" in data:
        row.is_brand_probe = bool(data["is_brand_probe"])
    elif "question" in data or "question_group" in data:
        row.is_brand_probe = resolve_is_brand_probe(
            question=row.question,
            brand_names=brand_names,
            explicit=None,
            question_group=row.question_group,
        )
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
    tenant = await _ensure_tenant_exists(session, req.tenant_id)
    brand_names = brand_names_from_tenant(
        name=getattr(tenant, "name", None),
        brand_terms=getattr(tenant, "brand_terms", None),
    )
    created = []
    for item in req.items:
        q_group = normalize_question_group(item.question_group)
        probe = resolve_is_brand_probe(
            question=item.question,
            brand_names=brand_names,
            explicit=item.is_brand_probe,
            question_group=q_group,
        )
        row = GeoPrompt(
            tenant_id=req.tenant_id,
            question=item.question.strip(),
            priority=item.priority,
            tags=item.tags,
            demand_note=item.demand_note,
            source="import",
            question_group=q_group,
            market=normalize_market(item.market),
            is_brand_probe=probe,
            created_by=ctx.user_id,
        )
        session.add(row)
        created.append(row)
    await session.commit()
    for row in created:
        await session.refresh(row)
    return {"items": [_prompt_payload(r) for r in created], "count": len(created)}


# ---------- answer snapshots (Wave B visibility) ----------


def _parse_captured_at(raw: str | None) -> datetime:
    if not raw or not str(raw).strip():
        return datetime.utcnow()
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(400, f"captured_at 无效: {raw}") from exc
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    return value


def _snapshot_payload(row: GeoAnswerSnapshot, *, prompt_question: str | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "prompt_id": row.prompt_id,
        "prompt_question": prompt_question,
        "engine": row.engine,
        "raw_text": row.raw_text,
        "captured_at": _iso(row.captured_at),
        "mentions_brand": bool(row.mentions_brand),
        "cited_urls": row.cited_urls or [],
        "competitors": row.competitors or [],
        "brand_position": row.brand_position or "unknown",
        "sentiment": row.sentiment or "unknown",
        "note": row.note,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
    }


async def _get_snapshot(
    session: AsyncSession, snapshot_id: int, tenant_id: int
) -> GeoAnswerSnapshot:
    row = await session.get(GeoAnswerSnapshot, snapshot_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "回答快照不存在")
    return row


async def _apply_brand_mention_side_effect(
    session: AsyncSession, prompt: GeoPrompt, *, mentions_brand: bool
) -> None:
    _ = session
    prompt.tags = apply_brand_mention_tags(prompt.tags, mentions_brand=mentions_brand)


@router.get("/answer-snapshots")
async def list_answer_snapshots(
    tenant_id: int = Query(...),
    prompt_id: int | None = Query(None),
    engine: str | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoAnswerSnapshot).where(GeoAnswerSnapshot.tenant_id == tenant_id)
    if prompt_id is not None:
        stmt = stmt.where(GeoAnswerSnapshot.prompt_id == prompt_id)
    if engine:
        stmt = stmt.where(GeoAnswerSnapshot.engine == engine)
    stmt = stmt.order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
    rows = list(await session.scalars(stmt))
    prompt_ids = {r.prompt_id for r in rows}
    questions: dict[int, str] = {}
    if prompt_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(prompt_ids)
            )
        ):
            questions[p.id] = p.question
    return {
        "items": [
            _snapshot_payload(r, prompt_question=questions.get(r.prompt_id)) for r in rows
        ]
    }


@router.post("/answer-snapshots")
async def create_answer_snapshot(
    req: AnswerSnapshotCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    prompt = await _get_prompt(session, req.prompt_id, req.tenant_id)
    cited_urls = normalize_cited_urls(req.cited_urls)
    if not cited_urls:
        cited_urls = extract_cited_urls_from_text(req.raw_text)
    row = GeoAnswerSnapshot(
        tenant_id=req.tenant_id,
        prompt_id=prompt.id,
        engine=req.engine,
        raw_text=req.raw_text.strip(),
        captured_at=_parse_captured_at(req.captured_at),
        mentions_brand=bool(req.mentions_brand),
        cited_urls=cited_urls,
        competitors=normalize_competitors(req.competitors),
        brand_position=normalize_brand_position(req.brand_position),
        sentiment=normalize_sentiment(req.sentiment),
        note=req.note,
        created_by=ctx.user_id,
    )
    session.add(row)
    await _apply_brand_mention_side_effect(
        session, prompt, mentions_brand=bool(req.mentions_brand)
    )
    await session.commit()
    await session.refresh(row)
    try:
        from app.geo.content.daily_metrics import safe_rebuild_for_captured_at

        await safe_rebuild_for_captured_at(req.tenant_id, row.captured_at)
    except Exception:  # noqa: BLE001
        pass
    return _snapshot_payload(row, prompt_question=prompt.question)


@router.patch("/answer-snapshots/{snapshot_id}")
async def update_answer_snapshot(
    snapshot_id: int,
    req: AnswerSnapshotUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await _get_snapshot(session, snapshot_id, tenant_id)
    prompt = await _get_prompt(session, row.prompt_id, tenant_id)
    if req.engine is not None:
        row.engine = req.engine
    if req.raw_text is not None:
        row.raw_text = req.raw_text.strip()
    if req.captured_at is not None:
        row.captured_at = _parse_captured_at(req.captured_at)
    if req.cited_urls is not None:
        row.cited_urls = normalize_cited_urls(req.cited_urls)
    if req.competitors is not None:
        row.competitors = normalize_competitors(req.competitors)
    if req.brand_position is not None:
        row.brand_position = normalize_brand_position(req.brand_position)
    if req.sentiment is not None:
        row.sentiment = normalize_sentiment(req.sentiment)
    if req.note is not None:
        row.note = req.note
    if req.mentions_brand is not None:
        row.mentions_brand = bool(req.mentions_brand)
        await _apply_brand_mention_side_effect(
            session, prompt, mentions_brand=bool(req.mentions_brand)
        )
    await session.commit()
    await session.refresh(row)
    try:
        from app.geo.content.daily_metrics import safe_rebuild_for_captured_at

        await safe_rebuild_for_captured_at(tenant_id, row.captured_at)
    except Exception:  # noqa: BLE001
        pass
    return _snapshot_payload(row, prompt_question=prompt.question)


@router.delete("/answer-snapshots/{snapshot_id}")
async def delete_answer_snapshot(
    snapshot_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Hard-delete one answer snapshot (test data / wrong paste cleanup)."""
    ctx.ensure_tenant(tenant_id)
    row = await _get_snapshot(session, snapshot_id, tenant_id)
    captured = row.captured_at
    await session.delete(row)
    await session.commit()
    try:
        from app.geo.content.daily_metrics import safe_rebuild_for_captured_at

        await safe_rebuild_for_captured_at(tenant_id, captured)
    except Exception:  # noqa: BLE001
        pass
    return {"deleted": True, "id": snapshot_id}


@router.get("/competitor-insights")
async def competitor_insights(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Aggregate competitor mentions from answer snapshots (Wave C)."""
    ctx.ensure_tenant(tenant_id)
    rows = list(
        await session.scalars(
            select(GeoAnswerSnapshot)
            .where(GeoAnswerSnapshot.tenant_id == tenant_id)
            .order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
        )
    )
    prompt_ids = {r.prompt_id for r in rows}
    questions: dict[int, str] = {}
    if prompt_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(prompt_ids)
            )
        ):
            questions[p.id] = p.question
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        for name in row.competitors or []:
            key = str(name).strip()
            if not key:
                continue
            bucket = buckets.setdefault(
                key,
                {
                    "name": key,
                    "mention_count": 0,
                    "prompt_ids": set(),
                    "engines": set(),
                    "latest_captured_at": None,
                    "sample_prompt_question": None,
                },
            )
            bucket["mention_count"] += 1
            bucket["prompt_ids"].add(row.prompt_id)
            bucket["engines"].add(row.engine)
            if bucket["latest_captured_at"] is None:
                bucket["latest_captured_at"] = _iso(row.captured_at)
                bucket["sample_prompt_question"] = questions.get(row.prompt_id)
    items = []
    for bucket in buckets.values():
        items.append(
            {
                "name": bucket["name"],
                "mention_count": bucket["mention_count"],
                "prompt_count": len(bucket["prompt_ids"]),
                "engines": sorted(bucket["engines"]),
                "latest_captured_at": bucket["latest_captured_at"],
                "sample_prompt_question": bucket["sample_prompt_question"],
            }
        )
    items.sort(key=lambda x: (-x["mention_count"], x["name"]))
    return {"items": items}


@router.get("/evaluation-insights")
async def evaluation_insights(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Sentiment / brand-position aggregates from snapshots (Wave C)."""
    ctx.ensure_tenant(tenant_id)
    rows = list(
        await session.scalars(
            select(GeoAnswerSnapshot)
            .where(GeoAnswerSnapshot.tenant_id == tenant_id)
            .order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
        )
    )
    sentiment_counts: dict[str, int] = {
        "positive": 0,
        "neutral": 0,
        "negative": 0,
        "unknown": 0,
    }
    position_counts: dict[str, int] = {
        "first": 0,
        "mentioned": 0,
        "absent": 0,
        "unknown": 0,
    }
    prompt_ids = {r.prompt_id for r in rows}
    questions: dict[int, str] = {}
    if prompt_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(prompt_ids)
            )
        ):
            questions[p.id] = p.question
    recent = []
    for row in rows:
        sent = row.sentiment if row.sentiment in sentiment_counts else "unknown"
        pos = row.brand_position if row.brand_position in position_counts else "unknown"
        sentiment_counts[sent] += 1
        position_counts[pos] += 1
        if len(recent) < 40:
            recent.append(
                _snapshot_payload(row, prompt_question=questions.get(row.prompt_id))
            )
    return {
        "sentiment_counts": sentiment_counts,
        "position_counts": position_counts,
        "recent": recent,
        "total": len(rows),
    }


async def _own_domains_for_tenant(session: AsyncSession, tenant_id: int) -> list[str]:
    own_domains: list[str] = []
    for ch in await session.scalars(
        select(GeoPublishingChannel).where(
            GeoPublishingChannel.tenant_id == tenant_id,
            GeoPublishingChannel.channel_type.in_(["website", "docs"]),
            GeoPublishingChannel.enabled.is_(True),
        )
    ):
        domain = extract_cited_domain(ch.base_url)
        if domain and domain not in own_domains:
            own_domains.append(domain)
    return own_domains


@router.get("/visibility-period-diff")
async def visibility_period_diff(
    tenant_id: int = Query(...),
    before_from: str = Query(...),
    before_to: str = Query(...),
    after_from: str = Query(...),
    after_to: str = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Compare visibility mention + own-domain cite rates across two capture windows."""
    ctx.ensure_tenant(tenant_id)
    try:
        b_from = parse_window_bound(before_from, label="before_from")
        b_to = parse_window_bound(before_to, label="before_to")
        a_from = parse_window_bound(after_from, label="after_from")
        a_to = parse_window_bound(after_to, label="after_to")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if b_from > b_to or a_from > a_to:
        raise HTTPException(400, "窗口起止时间无效：from 不得晚于 to")

    prompts = list(
        await session.scalars(
            select(GeoPrompt).where(GeoPrompt.tenant_id == tenant_id)
        )
    )
    prompt_probe = {p.id: bool(p.is_brand_probe) for p in prompts}
    own_domains = await _own_domains_for_tenant(session, tenant_id)
    all_snaps = list(
        await session.scalars(
            select(GeoAnswerSnapshot).where(GeoAnswerSnapshot.tenant_id == tenant_id)
        )
    )
    before_rows = [
        r
        for r in all_snaps
        if in_captured_window(r.captured_at, start=b_from, end=b_to)
    ]
    after_rows = [
        r
        for r in all_snaps
        if in_captured_window(r.captured_at, start=a_from, end=a_to)
    ]
    before = compute_window_metrics(
        before_rows, prompt_probe=prompt_probe, own_domains=own_domains
    )
    after = compute_window_metrics(
        after_rows, prompt_probe=prompt_probe, own_domains=own_domains
    )
    before["from"] = _iso(b_from)
    before["to"] = _iso(b_to)
    after["from"] = _iso(a_from)
    after["to"] = _iso(a_to)
    return {
        "before": before,
        "after": after,
        "delta": {
            "visibility_mention_rate": rate_delta(
                before["visibility_mention_rate"], after["visibility_mention_rate"]
            ),
            "visibility_top1_rate": rate_delta(
                before.get("visibility_top1_rate"), after.get("visibility_top1_rate")
            ),
            "own_domain_cite_rate": rate_delta(
                before["own_domain_cite_rate"], after["own_domain_cite_rate"]
            ),
            "probe_recognition_rate": rate_delta(
                before["probe_recognition_rate"], after["probe_recognition_rate"]
            ),
        },
    }


@router.get("/citation-insights")
async def citation_insights(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Aggregate cited_urls hostnames from answer snapshots."""
    ctx.ensure_tenant(tenant_id)
    rows = list(
        await session.scalars(
            select(GeoAnswerSnapshot)
            .where(GeoAnswerSnapshot.tenant_id == tenant_id)
            .order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
        )
    )
    prompt_ids = {r.prompt_id for r in rows}
    questions: dict[int, str] = {}
    if prompt_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(prompt_ids)
            )
        ):
            questions[p.id] = p.question

    own_domains = await _own_domains_for_tenant(session, tenant_id)

    buckets: dict[str, dict[str, Any]] = {}
    snapshots_with_citations = 0
    snapshots_own_domain = 0
    for row in rows:
        urls = list(row.cited_urls or [])
        domains = extract_cited_domains(urls)
        if not domains:
            continue
        snapshots_with_citations += 1
        if own_domains and any(
            domain_matches(d, own) for d in domains for own in own_domains
        ):
            snapshots_own_domain += 1
        for domain in domains:
            bucket = buckets.setdefault(
                domain,
                {
                    "domain": domain,
                    "cite_count": 0,
                    "prompt_ids": set(),
                    "engines": set(),
                    "sample_urls": [],
                    "latest_captured_at": None,
                    "sample_prompt_question": None,
                },
            )
            bucket["cite_count"] += 1
            bucket["prompt_ids"].add(row.prompt_id)
            bucket["engines"].add(row.engine)
            if bucket["latest_captured_at"] is None:
                bucket["latest_captured_at"] = _iso(row.captured_at)
                bucket["sample_prompt_question"] = questions.get(row.prompt_id)
            for url in urls:
                if extract_cited_domain(url) != domain:
                    continue
                if url not in bucket["sample_urls"] and len(bucket["sample_urls"]) < 3:
                    bucket["sample_urls"].append(url)

    items = []
    for bucket in buckets.values():
        bp = match_blueprint_for_domain(bucket["domain"])
        items.append(
            {
                "domain": bucket["domain"],
                "cite_count": bucket["cite_count"],
                "prompt_count": len(bucket["prompt_ids"]),
                "engines": sorted(bucket["engines"]),
                "latest_captured_at": bucket["latest_captured_at"],
                "sample_prompt_question": bucket["sample_prompt_question"],
                "sample_urls": bucket["sample_urls"],
                "is_own_domain": bool(
                    own_domains
                    and any(domain_matches(bucket["domain"], own) for own in own_domains)
                ),
                "blueprint_channel_key": bp["channel_key"] if bp else None,
                "blueprint_channel_name": bp["channel_name"] if bp else None,
                "priority_band": bp["priority_band"] if bp else None,
                "citation_national": bp["citation_national"] if bp else None,
            }
        )
    items.sort(key=lambda x: (-x["cite_count"], x["domain"]))
    own_domain_cite_rate = (
        visibility_mention_rate(
            total_snapshots=snapshots_with_citations,
            mention_snapshots=snapshots_own_domain,
        )
        if own_domains
        else None
    )
    return {
        "items": items,
        "snapshots_with_citations": snapshots_with_citations,
        "distinct_cited_domains": len(items),
        "own_domains": own_domains,
        "own_domain_cite_rate": own_domain_cite_rate,
    }


@router.post("/answer-snapshots/probe")
async def probe_answer_snapshot(
    req: AnswerSnapshotProbeRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """单引擎草稿探测：不写库，供运营确认后手工保存。

    默认租户 LLM + 引擎人设模拟；引擎配置 sample_mode=openai_compat 且有 Key 时走真采样。
    """
    from app.ai.deepseek import DeepSeekError, chat_json

    ctx.ensure_tenant(req.tenant_id)
    prompt = await _get_prompt(session, req.prompt_id, req.tenant_id)
    tenant = await _ensure_tenant_exists(session, req.tenant_id)
    tenant_llm = await resolve_llm_credentials(session, req.tenant_id)
    engine_rows = await _ensure_default_engines(session, req.tenant_id)
    engine_row = next((r for r in engine_rows if r.engine_key == req.engine), None)
    llm, sample_mode, fallback_reason = resolve_engine_llm(
        engine=req.engine, tenant_llm=tenant_llm, engine_row=engine_row
    )
    if not llm or not llm.get("api_key"):
        raise HTTPException(
            503,
            "未配置 AI 能力：请在「AI 能力配置」或引擎 openai_compat 凭证中填写 API Key，或改用粘贴登记",
        )
    brand = getattr(tenant, "name", None) or f"租户{req.tenant_id}"
    brand_names = brand_names_from_tenant(
        name=getattr(tenant, "name", None),
        brand_terms=getattr(tenant, "brand_terms", None),
    ) or [brand]
    try:
        draft = await run_probe_draft(
            question=prompt.question,
            brand=brand,
            brand_names=brand_names,
            engine=req.engine,
            llm=llm,
            chat_json=chat_json,
            sample_mode=sample_mode,
            fallback_reason=fallback_reason,
        )
    except DeepSeekError as exc:
        raise HTTPException(502, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "prompt_id": prompt.id,
        "prompt_question": prompt.question,
        **draft,
    }


@router.post("/answer-snapshots/probe-batch")
async def probe_answer_snapshot_batch(
    req: AnswerSnapshotProbeBatchRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """对多个跟踪引擎生成探测草稿；不写库。失败引擎记入 error，不中断整批。

    每引擎可独立 openai_compat 凭证；未配置则回退租户 LLM + 人设模拟。
    """
    from app.ai.deepseek import DeepSeekError, chat_json

    ctx.ensure_tenant(req.tenant_id)
    prompt = await _get_prompt(session, req.prompt_id, req.tenant_id)
    tenant = await _ensure_tenant_exists(session, req.tenant_id)
    tenant_llm = await resolve_llm_credentials(session, req.tenant_id)
    engine_rows = await _ensure_default_engines(session, req.tenant_id)
    row_by_key = {r.engine_key: r for r in engine_rows}
    enabled_keys = [r.engine_key for r in engine_rows if r.enabled]
    if not enabled_keys:
        enabled_keys = [r.engine_key for r in engine_rows]
    engines = resolve_batch_engines(req.engines, enabled_keys)
    if not engines:
        raise HTTPException(400, "没有可探测的引擎，请先在「AI 引擎管理」启用引擎")
    if not tenant_llm and not any(
        getattr(row_by_key.get(e), "api_key_encrypted", None) for e in engines
    ):
        raise HTTPException(
            503,
            "未配置 AI 能力：请在「AI 能力配置」或引擎 openai_compat 凭证中填写 API Key，或改用粘贴登记",
        )

    brand = getattr(tenant, "name", None) or f"租户{req.tenant_id}"
    brand_names = brand_names_from_tenant(
        name=getattr(tenant, "name", None),
        brand_terms=getattr(tenant, "brand_terms", None),
    ) or [brand]

    items: list[dict] = []
    for engine in engines:
        try:
            llm, sample_mode, fallback_reason = resolve_engine_llm(
                engine=engine,
                tenant_llm=tenant_llm,
                engine_row=row_by_key.get(engine),
            )
            if not llm or not llm.get("api_key"):
                raise ValueError("该引擎无可用 LLM 凭证")
            draft = await run_probe_draft(
                question=prompt.question,
                brand=brand,
                brand_names=brand_names,
                engine=engine,
                llm=llm,
                chat_json=chat_json,
                sample_mode=sample_mode,
                fallback_reason=fallback_reason,
            )
            items.append(
                {
                    "prompt_id": prompt.id,
                    "prompt_question": prompt.question,
                    "ok": True,
                    "error": None,
                    **draft,
                }
            )
        except (DeepSeekError, ValueError) as exc:
            items.append(
                {
                    "prompt_id": prompt.id,
                    "prompt_question": prompt.question,
                    "engine": engine,
                    "ok": False,
                    "error": str(exc),
                    "persisted": False,
                }
            )
    return {
        "prompt_id": prompt.id,
        "prompt_question": prompt.question,
        "provider": (tenant_llm or {}).get("provider"),
        "model": (tenant_llm or {}).get("model"),
        "engines": engines,
        "items": items,
        "ok_count": sum(1 for i in items if i.get("ok")),
        "error_count": sum(1 for i in items if not i.get("ok")),
        "persisted": False,
    }


# ---------- visibility auto patrol ----------


@router.get("/visibility-patrol/ops-status")
async def visibility_patrol_ops_status(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Operational snapshot for patrol: engines health, quota, last run alerts."""
    from app.config import get_settings
    from app.geo.content.patrol import count_patrol_runs_today, patrol_settings_payload
    from app.models import GeoTrackingEngine

    ctx.ensure_tenant(tenant_id)
    settings_row = await session.get(GeoVisibilityPatrolSettings, tenant_id)
    day_limit = int(getattr(get_settings(), "geo_patrol_max_runs_per_day", 24) or 24)
    used = await count_patrol_runs_today(session, tenant_id)
    engines = list(
        await session.scalars(
            select(GeoTrackingEngine)
            .where(GeoTrackingEngine.tenant_id == tenant_id)
            .order_by(GeoTrackingEngine.sort_order, GeoTrackingEngine.id)
        )
    )
    engine_items = []
    for e in engines:
        has_key = bool(getattr(e, "api_key_encrypted", None))
        mode = str(getattr(e, "sample_mode", None) or "mock_persona")
        engine_items.append(
            {
                "engine_key": e.engine_key,
                "display_name": e.display_name or e.engine_key,
                "enabled": bool(e.enabled),
                "sample_mode": mode,
                "has_engine_key": has_key,
                "ready_for_real": mode == "openai_compat" and has_key,
                "health": (
                    "real_ready"
                    if mode == "openai_compat" and has_key
                    else ("persona" if e.enabled else "disabled")
                ),
            }
        )
    last_runs = list(
        await session.scalars(
            select(GeoVisibilityPatrolRun)
            .where(GeoVisibilityPatrolRun.tenant_id == tenant_id)
            .order_by(GeoVisibilityPatrolRun.id.desc())
            .limit(5)
        )
    )
    last = last_runs[0] if last_runs else None
    alerts: list[str] = []
    if last and last.status == "failed":
        alerts.append(f"最近巡检 #{last.id} 失败：{(last.error or '未知')[:200]}")
    if last and last.status == "completed":
        summary = last.summary or {}
        fail = int(summary.get("cells_fail") or 0)
        if fail:
            alerts.append(f"最近巡检 #{last.id} 有 {fail} 格失败，请检查引擎 Key / LLM")
        if summary.get("truncated"):
            alerts.append(summary.get("truncated_reason") or "最近巡检触发格数截断")
    if used >= day_limit:
        alerts.append(f"今日巡检已达配额上限 {used}/{day_limit}")
    if not any(e["enabled"] for e in engine_items):
        alerts.append("无启用引擎，巡检无法运行")
    if not any(e["ready_for_real"] for e in engine_items):
        alerts.append("未配置 openai_compat 引擎 Key：巡检将以人设模拟为主")

    from app.geo.content.patrol import patrol_run_payload

    return {
        "tenant_id": tenant_id,
        "settings": patrol_settings_payload(settings_row, tenant_id),
        "quota": {
            "used_today": used,
            "max_per_day": day_limit,
            "remaining": max(0, day_limit - used),
        },
        "engines": engine_items,
        "last_run": patrol_run_payload(last) if last else None,
        "recent_runs": [
            {
                "id": r.id,
                "status": r.status,
                "trigger": r.trigger,
                "summary": r.summary or {},
                "error": r.error,
                "created_at": _iso(r.created_at),
            }
            for r in last_runs
        ],
        "alerts": alerts,
    }


@router.get("/visibility-patrol/settings")
async def get_visibility_patrol_settings(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.patrol import patrol_settings_payload

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoVisibilityPatrolSettings, tenant_id)
    return patrol_settings_payload(row, tenant_id)


@router.put("/visibility-patrol/settings")
async def put_visibility_patrol_settings(
    req: VisibilityPatrolSettingsUpdate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.patrol import (
        clamp_hour,
        clamp_interval_hours,
        patrol_settings_payload,
    )

    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    row = await session.get(GeoVisibilityPatrolSettings, req.tenant_id)
    if row is None:
        row = GeoVisibilityPatrolSettings(tenant_id=req.tenant_id)
        session.add(row)
    row.enabled = bool(req.enabled)
    start_h = clamp_hour(req.window_start_hour, 6)
    end_h = clamp_hour(req.window_end_hour, 22)
    row.window_start_hour = start_h
    row.window_end_hour = end_h
    row.interval_hours = clamp_interval_hours(req.interval_hours, 24)
    row.daily_hour = start_h  # compat column
    row.auto_persist = bool(req.auto_persist)
    row.prefer_real = bool(req.prefer_real)
    row.prompt_limit = int(req.prompt_limit)
    row.engine_keys = req.engine_keys
    await session.commit()
    await session.refresh(row)
    return patrol_settings_payload(row, req.tenant_id)


@router.get("/visibility-patrol/runs")
async def list_visibility_patrol_runs(
    tenant_id: int = Query(...),
    limit: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.patrol import patrol_run_payload, reconcile_stale_patrol_run

    ctx.ensure_tenant(tenant_id)
    rows = list(
        await session.scalars(
            select(GeoVisibilityPatrolRun)
            .where(GeoVisibilityPatrolRun.tenant_id == tenant_id)
            .order_by(GeoVisibilityPatrolRun.id.desc())
            .limit(limit)
        )
    )
    # Close zombie pending/running so history UI does not hang forever
    out = []
    for r in rows:
        out.append(await reconcile_stale_patrol_run(session, r))
    return {"items": [patrol_run_payload(r) for r in out]}


@router.get("/visibility-patrol/runs/{run_id}")
async def get_visibility_patrol_run(
    run_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.patrol import patrol_run_payload, reconcile_stale_patrol_run

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoVisibilityPatrolRun, run_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "巡检任务不存在")
    row = await reconcile_stale_patrol_run(session, row)
    return patrol_run_payload(row)


@router.post("/visibility-patrol/runs")
async def create_visibility_patrol_run(
    req: VisibilityPatrolCreate,
    background_tasks: BackgroundTasks,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """启动一次全自动巡检：多机会词 × 启用引擎探测，默认自动落库快照。

    真采样：引擎 sample_mode=openai_compat 且配置 Key；否则租户 LLM + 人设（标记 simulated）。
    产品化配额：GEO_PATROL_MAX_RUNS_PER_DAY 限制单租户自然日启动次数。

    异步执行使用 Starlette BackgroundTasks（请求返回后再跑），避免 asyncio.create_task
    被 GC/连接结束取消，导致状态永久 pending。
    """
    from app.config import get_settings
    from app.geo.content.patrol import (
        count_patrol_runs_today,
        execute_patrol_run,
        patrol_quota_message,
        patrol_run_payload,
        run_patrol_in_background,
    )

    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    day_limit = int(getattr(get_settings(), "geo_patrol_max_runs_per_day", 24) or 24)
    day_limit = max(1, min(day_limit, 500))
    used = await count_patrol_runs_today(session, req.tenant_id)
    if used >= day_limit:
        raise HTTPException(
            429,
            patrol_quota_message(used=used, limit=day_limit),
        )
    run = GeoVisibilityPatrolRun(
        tenant_id=req.tenant_id,
        status="pending",
        trigger="manual",
        auto_persist=bool(req.auto_persist),
        prefer_real=bool(req.prefer_real),
        prompt_limit=int(req.prompt_limit),
        engine_keys=req.engine_keys,
        created_by=ctx.user_id,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    run_id = run.id

    if req.run_async:
        # Mark queued→running intent so UI leaves pure "pending" immediately after worker picks up;
        # execute_patrol_run also sets running on start.
        background_tasks.add_task(run_patrol_in_background, run_id)
        return {"run": patrol_run_payload(run), "started": True, "async": True}

    done = await execute_patrol_run(session, run_id)
    return {"run": patrol_run_payload(done), "started": True, "async": False}


@router.delete("/visibility-patrol/runs/{run_id}")
async def delete_visibility_patrol_run(
    run_id: int,
    tenant_id: int = Query(...),
    force: bool = Query(False, description="true 时取消 running/pending 并删除"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a patrol run history row. Blocks active runs unless force=true."""
    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoVisibilityPatrolRun, run_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "巡检任务不存在")
    if row.status in ("pending", "running") and not force:
        raise HTTPException(
            400,
            "进行中的巡检不可删除；请等待结束，或 force=true 强制删除",
        )
    await session.delete(row)
    await session.commit()
    return {"deleted": True, "id": run_id}


@router.post("/visibility-patrol/runs/cleanup")
async def cleanup_visibility_patrol_runs(
    tenant_id: int = Query(...),
    keep_latest: int = Query(20, ge=0, le=200),
    only_terminal: bool = Query(True, description="仅清理 completed/failed/cancelled"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Keep newest N terminal runs; delete older history for this tenant."""
    ctx.ensure_tenant(tenant_id)
    stmt = (
        select(GeoVisibilityPatrolRun)
        .where(GeoVisibilityPatrolRun.tenant_id == tenant_id)
        .order_by(GeoVisibilityPatrolRun.id.desc())
    )
    rows = list(await session.scalars(stmt))
    keep_ids: set[int] = set()
    kept = 0
    deleted = 0
    for r in rows:
        terminal = r.status in ("completed", "failed", "cancelled")
        if only_terminal and not terminal:
            continue
        if kept < keep_latest:
            keep_ids.add(r.id)
            kept += 1
            continue
        if only_terminal and not terminal:
            continue
        if r.status in ("pending", "running"):
            continue
        await session.delete(r)
        deleted += 1
    await session.commit()
    return {"deleted": deleted, "kept": len(keep_ids), "keep_latest": keep_latest}


@router.post("/answer-snapshots/extract-urls")
async def extract_answer_snapshot_urls(
    req: AnswerSnapshotExtractUrlsRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """Deterministic URL extract from pasted answer text (no LLM, no DB write)."""
    ctx.ensure_tenant(req.tenant_id)
    urls = extract_cited_urls_from_text(req.raw_text)
    return {
        "suggested_cited_urls": urls,
        "domains": extract_cited_domains(urls),
    }


@router.post("/answer-snapshots/suggest-fields")
async def suggest_answer_snapshot_fields(
    req: AnswerSnapshotSuggestFieldsRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Suggest Wave C labels from pasted text; never writes snapshots."""
    from app.ai.deepseek import DeepSeekError, chat_json

    ctx.ensure_tenant(req.tenant_id)
    tenant = await _ensure_tenant_exists(session, req.tenant_id)
    brand = getattr(tenant, "name", None) or f"租户{req.tenant_id}"
    brand_names = brand_names_from_tenant(
        name=getattr(tenant, "name", None),
        brand_terms=getattr(tenant, "brand_terms", None),
    ) or [brand]
    question = None
    if req.prompt_id is not None:
        prompt = await _get_prompt(session, req.prompt_id, req.tenant_id)
        question = prompt.question

    llm_data: dict | None = None
    llm_meta: dict[str, Any] = {"used": False}
    if req.use_llm:
        llm = await resolve_llm_credentials(session, req.tenant_id)
        if not llm:
            raise HTTPException(
                503,
                "未配置 AI 能力：请在「AI 能力配置」填写 API Key，或将 use_llm=false 仅用启发式",
            )
        try:
            llm_data = await chat_json(
                suggest_system_prompt(brand),
                suggest_user_prompt(
                    brand=brand, question=question, raw_text=req.raw_text
                ),
                timeout=45.0,
                api_key=llm["api_key"],
                base_url=llm["base_url"],
                model=llm["model"],
            )
        except DeepSeekError as exc:
            raise HTTPException(502, str(exc)) from exc
        llm_meta = {
            "used": True,
            "provider": llm.get("provider"),
            "model": llm.get("model"),
        }

    suggest = normalize_suggest_payload(
        llm_data, raw_text=req.raw_text, brand_names=brand_names
    )
    return {
        "prompt_id": req.prompt_id,
        "persisted": False,
        "llm": llm_meta,
        **suggest,
    }


@router.get("/ai-settings")
async def get_ai_settings(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    await _ensure_tenant_exists(session, tenant_id)
    row = await ensure_ai_setting(session, tenant_id)
    effective = await resolve_llm_credentials(session, tenant_id)
    payload = settings_public_payload(row)
    payload["presets"] = preset_payload()
    payload["effective"] = (
        {
            "enabled": True,
            "provider": effective["provider"],
            "base_url": effective["base_url"],
            "model": effective["model"],
            "source": effective["source"],
        }
        if effective
        else {"enabled": False, "source": None}
    )
    return payload


@router.put("/ai-settings")
async def put_ai_settings(
    req: AiSettingsUpdate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    row = await ensure_ai_setting(session, req.tenant_id)
    if req.apply_preset:
        preset = apply_provider_preset(req.provider)
        row.provider = preset["provider"]
        row.base_url = preset["base_url"]
        row.model = preset["model"]
    else:
        row.provider = req.provider
        if req.base_url:
            row.base_url = req.base_url.strip().rstrip("/")
        elif not row.base_url:
            row.base_url = apply_provider_preset(req.provider)["base_url"]
        if req.model:
            row.model = req.model.strip()
        elif not row.model:
            row.model = apply_provider_preset(req.provider)["model"]
    row.enabled = bool(req.enabled)
    row.note = req.note
    row.updated_by = ctx.user_id
    if req.clear_api_key:
        row.api_key_encrypted = None
    elif req.api_key:
        row.api_key_encrypted = encrypt_api_key(req.api_key)
    await session.commit()
    await session.refresh(row)
    effective = await resolve_llm_credentials(session, req.tenant_id)
    payload = settings_public_payload(row)
    payload["presets"] = preset_payload()
    payload["effective"] = (
        {
            "enabled": True,
            "provider": effective["provider"],
            "base_url": effective["base_url"],
            "model": effective["model"],
            "source": effective["source"],
        }
        if effective
        else {"enabled": False, "source": None}
    )
    return payload


@router.post("/ai-settings/test")
async def test_ai_settings(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """用当前生效配置打一条极短 JSON 请求，验证 Key / 线路。"""
    from app.ai.deepseek import DeepSeekError, chat_json

    ctx.ensure_tenant(tenant_id)
    llm = await resolve_llm_credentials(session, tenant_id)
    if not llm:
        raise HTTPException(503, "尚未配置可用的 AI API Key")
    try:
        data = await chat_json(
            '只返回 JSON：{"ok": true}',
            "ping",
            timeout=30.0,
            api_key=llm["api_key"],
            base_url=llm["base_url"],
            model=llm["model"],
        )
    except DeepSeekError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "ok": True,
        "provider": llm["provider"],
        "model": llm["model"],
        "source": llm["source"],
        "sample": data,
    }


# ---------- tracking engines (Wave B2) ----------


def _engine_payload(row: GeoTrackingEngine) -> dict[str, Any]:
    from app.geo.content.ai_settings import mask_api_key
    from app.security.crypto import decrypt

    plain = None
    if getattr(row, "api_key_encrypted", None):
        try:
            plain = decrypt(row.api_key_encrypted)
        except Exception:  # noqa: BLE001
            plain = None
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "engine_key": row.engine_key,
        "display_name": row.display_name,
        "enabled": bool(row.enabled),
        "note": row.note,
        "sort_order": row.sort_order,
        "sample_mode": getattr(row, "sample_mode", None) or "mock_persona",
        "api_base_url": getattr(row, "api_base_url", None),
        "model": getattr(row, "model", None),
        "api_key_configured": bool(plain),
        "api_key_masked": mask_api_key(plain) if plain else None,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


async def _ensure_default_engines(
    session: AsyncSession, tenant_id: int
) -> list[GeoTrackingEngine]:
    rows = list(
        await session.scalars(
            select(GeoTrackingEngine)
            .where(GeoTrackingEngine.tenant_id == tenant_id)
            .order_by(GeoTrackingEngine.sort_order, GeoTrackingEngine.id)
        )
    )
    if rows:
        return rows
    await _ensure_tenant_exists(session, tenant_id)
    created: list[GeoTrackingEngine] = []
    for item in default_engine_rows(tenant_id):
        row = GeoTrackingEngine(**item)
        session.add(row)
        created.append(row)
    await session.commit()
    for row in created:
        await session.refresh(row)
    return created


@router.get("/tracking-engines")
async def list_tracking_engines(
    tenant_id: int = Query(...),
    enabled_only: bool = Query(False),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    rows = await _ensure_default_engines(session, tenant_id)
    if enabled_only:
        rows = [r for r in rows if r.enabled]
    return {"items": [_engine_payload(r) for r in rows]}


@router.put("/tracking-engines")
async def put_tracking_engines(
    req: TrackingEnginesPut,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    # Preserve encrypted keys when client does not resend api_key
    existing_rows = list(
        await session.scalars(
            select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == req.tenant_id)
        )
    )
    existing_keys = {r.engine_key: r.api_key_encrypted for r in existing_rows}
    await session.execute(
        delete(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == req.tenant_id)
    )
    created: list[GeoTrackingEngine] = []
    seen: set[str] = set()
    from app.geo.content.ai_settings import encrypt_api_key

    for item in req.items:
        if item.engine_key in seen:
            continue
        seen.add(item.engine_key)
        enc = existing_keys.get(item.engine_key)
        if item.clear_api_key:
            enc = None
        elif item.api_key:
            try:
                enc = encrypt_api_key(item.api_key)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        mode = (item.sample_mode or "mock_persona").strip()
        if mode not in ("mock_persona", "openai_compat"):
            mode = "mock_persona"
        row = GeoTrackingEngine(
            tenant_id=req.tenant_id,
            engine_key=item.engine_key,
            display_name=item.display_name.strip(),
            enabled=bool(item.enabled),
            note=item.note,
            sort_order=int(item.sort_order),
            sample_mode=mode,
            api_base_url=(item.api_base_url or None),
            model=(item.model or None),
            api_key_encrypted=enc,
        )
        session.add(row)
        created.append(row)
    await session.commit()
    for row in created:
        await session.refresh(row)
    created.sort(key=lambda r: (r.sort_order, r.id or 0))
    return {"items": [_engine_payload(r) for r in created], "count": len(created)}


# ---------- publishing channels ----------


def _channel_payload(row: GeoPublishingChannel) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "channel_type": row.channel_type,
        "publish_mode": row.publish_mode,
        "base_url": row.base_url,
        "content_rules": row.content_rules,
        "enabled": row.enabled,
        "sort_order": row.sort_order,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _channel_account_payload(row: GeoChannelAccount) -> dict:
    provider = None
    platform = None
    oauth_authorized = False
    if row.credentials_encrypted:
        try:
            from app.geo.content.connectors.social import (
                decrypt_credentials_json,
                resolve_provider,
            )

            creds = decrypt_credentials_json(row.credentials_encrypted)
            provider = resolve_provider(creds)
            platform = creds.get("platform")
            oauth_authorized = bool(creds.get("access_token"))
        except Exception:  # noqa: BLE001
            pass
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "channel_id": row.channel_id,
        "display_name": row.display_name,
        "auth_type": row.auth_type,
        "has_credentials": bool(row.credentials_encrypted),
        "provider": provider,
        "platform": platform,
        "oauth_authorized": oauth_authorized,
        "status": row.status,
        "expires_at": _iso(row.expires_at),
        "last_verified_at": _iso(row.last_verified_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


async def _ensure_default_publishing_channels(
    session: AsyncSession, tenant_id: int
) -> list[GeoPublishingChannel]:
    """Seed missing default multi-media channels (does not override existing modes)."""
    rows = list(
        await session.scalars(
            select(GeoPublishingChannel)
            .where(GeoPublishingChannel.tenant_id == tenant_id)
            .order_by(GeoPublishingChannel.sort_order, GeoPublishingChannel.id)
        )
    )
    existing_types = {str(r.channel_type or "").lower() for r in rows}
    await _ensure_tenant_exists(session, tenant_id)
    missing = [
        item
        for item in default_channel_rows(tenant_id)
        if str(item.get("channel_type") or "").lower() not in existing_types
    ]
    if not rows and not missing:
        missing = list(default_channel_rows(tenant_id))
    if missing:
        created = [GeoPublishingChannel(**item) for item in missing]
        session.add_all(created)
        await session.commit()
        rows = list(
            await session.scalars(
                select(GeoPublishingChannel)
                .where(GeoPublishingChannel.tenant_id == tenant_id)
                .order_by(GeoPublishingChannel.sort_order, GeoPublishingChannel.id)
            )
        )
    return rows


async def _get_publishing_channel(
    session: AsyncSession, channel_id: int, tenant_id: int
) -> GeoPublishingChannel:
    row = await session.get(GeoPublishingChannel, channel_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "发布渠道不存在")
    return row


async def _get_channel_account(
    session: AsyncSession, account_id: int, tenant_id: int
) -> GeoChannelAccount:
    row = await session.get(GeoChannelAccount, account_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "渠道账号不存在")
    return row


@router.get("/publishing-channels")
async def list_publishing_channels(
    tenant_id: int = Query(...),
    enabled_only: bool = Query(False),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    rows = await _ensure_default_publishing_channels(session, tenant_id)
    if enabled_only:
        rows = [row for row in rows if row.enabled]
    return {"items": [_channel_payload(row) for row in rows]}


@router.get("/publishing-channels/auto-push-status")
async def publishing_auto_push_status(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Multi-media auto-push config matrix (what is ready vs missing credentials)."""
    from app.geo.content.multi_push import tenant_auto_push_matrix

    ctx.ensure_tenant(tenant_id)
    await _ensure_default_publishing_channels(session, tenant_id)
    return await tenant_auto_push_matrix(session, tenant_id=tenant_id)


@router.post("/publishing-channels/enable-multi-media-auto")
async def enable_multi_media_auto_pack(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ensure multi-media pack exists and set auto_publish on pushable types.

    Does not create credentials — ops only fill account tokens after this.
    """
    from app.geo.content.multi_push import AUTO_PUSH_TYPES

    ctx.ensure_tenant(tenant_id)
    rows = await _ensure_default_publishing_channels(session, tenant_id)
    updated = 0
    for row in rows:
        ctype = str(row.channel_type or "").lower()
        if ctype not in AUTO_PUSH_TYPES:
            continue
        changed = False
        if not row.enabled:
            row.enabled = True
            changed = True
        if str(row.publish_mode) != "auto_publish":
            row.publish_mode = "auto_publish"
            changed = True
        if changed:
            updated += 1
    await session.commit()
    from app.geo.content.multi_push import tenant_auto_push_matrix

    matrix = await tenant_auto_push_matrix(session, tenant_id=tenant_id)
    return {
        "ok": True,
        "channels_updated": updated,
        "matrix": matrix,
        "next_step": "为 config_ready=false 的渠道创建 webhook/social_api 账号并填写凭证",
    }


@router.post("/publishing-channels")
async def create_publishing_channel(
    req: PublishingChannelCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    row = GeoPublishingChannel(
        tenant_id=req.tenant_id,
        name=req.name.strip(),
        channel_type=req.channel_type,
        publish_mode=req.publish_mode,
        base_url=req.base_url,
        content_rules=req.content_rules,
        enabled=req.enabled,
        sort_order=req.sort_order,
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _channel_payload(row)


@router.delete("/publishing-channels/{channel_id}")
async def delete_publishing_channel(
    channel_id: int,
    tenant_id: int = Query(...),
    hard: bool = Query(False, description="false=enabled=false；true=物理删除（级联账号）"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoPublishingChannel, channel_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "发布渠道不存在")
    if hard:
        await session.delete(row)
        await session.commit()
        return {"deleted": True, "hard": True, "id": channel_id}
    row.enabled = False
    await session.commit()
    await session.refresh(row)
    return {"deleted": False, "disabled": True, "channel": _channel_payload(row)}


@router.patch("/publishing-channels/{channel_id}")
async def update_publishing_channel(
    channel_id: int,
    req: PublishingChannelUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await _get_publishing_channel(session, channel_id, tenant_id)
    for field in ("channel_type", "publish_mode", "base_url", "content_rules", "enabled", "sort_order"):
        value = getattr(req, field)
        if value is not None:
            setattr(row, field, value)
    if req.name is not None:
        row.name = req.name.strip()
    await session.commit()
    await session.refresh(row)
    return _channel_payload(row)


@router.get("/channel-accounts")
async def list_channel_accounts(
    tenant_id: int = Query(...),
    channel_id: int | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    if channel_id is not None:
        await _get_publishing_channel(session, channel_id, tenant_id)
    stmt = select(GeoChannelAccount).where(GeoChannelAccount.tenant_id == tenant_id)
    if channel_id is not None:
        stmt = stmt.where(GeoChannelAccount.channel_id == channel_id)
    rows = list(await session.scalars(stmt.order_by(GeoChannelAccount.id.desc())))
    return {"items": [_channel_account_payload(row) for row in rows]}


@router.post("/channel-accounts")
async def create_channel_account(
    req: ChannelAccountCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _get_publishing_channel(session, req.channel_id, req.tenant_id)
    credentials_encrypted = None
    if req.credentials:
        try:
            credentials_encrypted = encrypt_api_key(
                json.dumps(req.credentials, ensure_ascii=False, sort_keys=True)
            )
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
    row = GeoChannelAccount(
        tenant_id=req.tenant_id,
        channel_id=req.channel_id,
        display_name=req.display_name.strip(),
        auth_type=req.auth_type,
        credentials_encrypted=credentials_encrypted,
        status="active" if credentials_encrypted else "unconfigured",
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _channel_account_payload(row)


@router.patch("/channel-accounts/{account_id}")
async def update_channel_account(
    account_id: int,
    req: ChannelAccountUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await _get_channel_account(session, account_id, tenant_id)
    if req.display_name is not None:
        row.display_name = req.display_name.strip()
    if req.auth_type is not None:
        row.auth_type = req.auth_type
    if req.credentials is not None:
        try:
            row.credentials_encrypted = encrypt_api_key(
                json.dumps(req.credentials, ensure_ascii=False, sort_keys=True)
            )
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
        row.status = "active"
    if req.clear_credentials:
        row.credentials_encrypted = None
        row.status = "unconfigured"
    if req.status is not None:
        row.status = req.status
    await session.commit()
    await session.refresh(row)
    return _channel_account_payload(row)


@router.post("/oauth/social/start")
async def oauth_social_start(
    tenant_id: int = Query(...),
    account_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Build OAuth2 authorize URL for a channel account (auth_type=oauth2)."""
    from app.geo.content.connectors.oauth2 import (
        OAuth2Error,
        build_authorize_url,
        sign_oauth_state,
    )
    from app.geo.content.connectors.social import decrypt_credentials_json, resolve_provider

    ctx.ensure_tenant(tenant_id)
    row = await _get_channel_account(session, account_id, tenant_id)
    if not row.credentials_encrypted:
        raise HTTPException(400, "账号未配置 OAuth 客户端凭证（client_id 等）")
    try:
        creds = decrypt_credentials_json(row.credentials_encrypted)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    if resolve_provider(creds) != "oauth2" and row.auth_type not in {"oauth2", "social_api"}:
        raise HTTPException(400, "仅 oauth2 / social_api(oauth2 provider) 支持授权跳转")
    if resolve_provider(creds) != "oauth2":
        raise HTTPException(400, "凭证 provider 不是 oauth2，请填写 authorize_url/token_url/client_id")
    try:
        state = sign_oauth_state(tenant_id=tenant_id, account_id=account_id)
        url = build_authorize_url(creds, state=state)
    except OAuth2Error as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "authorize_url": url,
        "state": state,
        "account_id": account_id,
        "expires_in_sec": 600,
    }


@router.post("/oauth/social/refresh")
async def oauth_social_refresh(
    tenant_id: int = Query(...),
    account_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Refresh OAuth2 access_token using stored refresh_token."""
    from app.geo.content.ai_settings import encrypt_api_key
    from app.geo.content.connectors.oauth2 import OAuth2Error, refresh_access_token
    from app.geo.content.connectors.social import decrypt_credentials_json

    ctx.ensure_tenant(tenant_id)
    row = await _get_channel_account(session, account_id, tenant_id)
    if not row.credentials_encrypted:
        raise HTTPException(400, "账号未配置凭证")
    try:
        creds = decrypt_credentials_json(row.credentials_encrypted)
        patch = await refresh_access_token(creds)
        merged = {**creds, **patch}
        row.credentials_encrypted = encrypt_api_key(
            json.dumps(merged, ensure_ascii=False, sort_keys=True)
        )
        row.last_verified_at = datetime.utcnow()
        await session.commit()
    except OAuth2Error as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "account_id": account_id, "refreshed": True}


@router.post("/channel-accounts/{account_id}/verify-social")
async def verify_social_account(
    account_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Probe social credentials (WeChat token / OAuth token presence)."""
    from app.geo.content.ai_settings import encrypt_api_key
    from app.geo.content.connectors.social import (
        decrypt_credentials_json,
        resolve_provider,
    )
    from app.geo.content.connectors.wechat_mp import ensure_wechat_access_token

    ctx.ensure_tenant(tenant_id)
    row = await _get_channel_account(session, account_id, tenant_id)
    if not row.credentials_encrypted:
        raise HTTPException(400, "账号未配置凭证")
    try:
        creds = decrypt_credentials_json(row.credentials_encrypted)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    provider = resolve_provider(creds)
    detail: dict[str, Any] = {"provider": provider, "platform": creds.get("platform")}
    if provider == "wechat_mp":
        try:
            token, patch = await ensure_wechat_access_token(creds)
            if patch:
                merged = {**creds, **patch}
                row.credentials_encrypted = encrypt_api_key(
                    json.dumps(merged, ensure_ascii=False, sort_keys=True)
                )
            row.last_verified_at = datetime.utcnow()
            row.status = "active"
            await session.commit()
            detail["ok"] = True
            detail["token_prefix"] = (token[:8] + "…") if token else None
            detail["mock"] = bool(str(creds.get("app_id") or "").startswith("mock_"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc)) from exc
    elif provider == "oauth2":
        detail["ok"] = bool(creds.get("access_token"))
        detail["oauth_authorized"] = bool(creds.get("access_token"))
        if not detail["ok"]:
            raise HTTPException(400, "尚未完成 OAuth 授权（无 access_token）")
        row.last_verified_at = datetime.utcnow()
        await session.commit()
    else:
        detail["ok"] = bool(creds.get("access_token") and (creds.get("api_url") or creds.get("webhook_url")))
        if not detail["ok"]:
            raise HTTPException(400, "gateway 需要 api_url + access_token")
        row.last_verified_at = datetime.utcnow()
        await session.commit()
    return detail


@router.delete("/channel-accounts/{account_id}")
async def delete_channel_account(
    account_id: int,
    tenant_id: int = Query(...),
    hard: bool = Query(False, description="true=物理删除；默认仅 status=disabled"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Disable or hard-delete a channel account (demo cleanup / revoke)."""
    ctx.ensure_tenant(tenant_id)
    row = await _get_channel_account(session, account_id, tenant_id)
    if hard:
        await session.delete(row)
        await session.commit()
        return {"deleted": True, "id": account_id, "hard": True}
    row.status = "disabled"
    await session.commit()
    await session.refresh(row)
    return {"deleted": False, "disabled": True, "account": _channel_account_payload(row)}


# ---------- media placements (Wave B2) ----------


def _media_payload(row: GeoMediaPlacement) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "channel_type": row.channel_type,
        "channel_key": row.channel_key,
        "target_url": row.target_url,
        "authority_note": row.authority_note,
        "status": row.status,
        "published_url": row.published_url,
        "priority": row.priority,
        "priority_band": row.priority_band,
        "fits_groups": row.fits_groups or [],
        "citation_national": row.citation_national,
        "related_prompt_id": row.related_prompt_id,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


async def _ensure_default_media_placements(
    session: AsyncSession, tenant_id: int
) -> list[GeoMediaPlacement]:
    rows = list(
        await session.scalars(
            select(GeoMediaPlacement)
            .where(GeoMediaPlacement.tenant_id == tenant_id)
            .order_by(GeoMediaPlacement.priority.desc(), GeoMediaPlacement.id.desc())
        )
    )
    if rows:
        return rows
    await _ensure_tenant_exists(session, tenant_id)
    created = [GeoMediaPlacement(**item) for item in default_media_placement_rows(tenant_id)]
    session.add_all(created)
    await session.commit()
    for row in created:
        await session.refresh(row)
    return created


async def _get_media_placement(
    session: AsyncSession, placement_id: int, tenant_id: int
) -> GeoMediaPlacement:
    row = await session.get(GeoMediaPlacement, placement_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "信源布局不存在")
    return row


@router.get("/media-placements")
async def list_media_placements(
    tenant_id: int = Query(...),
    status: str | None = Query(None),
    seed_defaults: bool = Query(
        True,
        description="When empty, seed CN citation blueprint placements (D1)",
    ),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    if seed_defaults:
        rows = await _ensure_default_media_placements(session, tenant_id)
    else:
        rows = list(
            await session.scalars(
                select(GeoMediaPlacement)
                .where(GeoMediaPlacement.tenant_id == tenant_id)
                .order_by(GeoMediaPlacement.priority.desc(), GeoMediaPlacement.id.desc())
            )
        )
    if status:
        rows = [r for r in rows if r.status == status]
    return {"items": [_media_payload(r) for r in rows]}


@router.get("/channel-blueprint")
async def get_channel_blueprint(
    tenant_id: int = Query(...),
    group: str | None = Query(None, description="问题组：推荐/比较/替代/…"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """CN citation-weighted channel recommendations (GeoLook D1)."""
    ctx.ensure_tenant(tenant_id)
    await _ensure_tenant_exists(session, tenant_id)
    payload = blueprint_payload(group=normalize_question_group(group))
    # Annotate with tenant placement coverage by channel_key
    placements = await _ensure_default_media_placements(session, tenant_id)
    by_key = {p.channel_key: p for p in placements if p.channel_key}
    for item in payload["channels"]:
        row = by_key.get(item["channel_key"])
        item["placement_status"] = row.status if row else None
        item["placement_id"] = row.id if row else None
        item["published_url"] = row.published_url if row else None
    for item in payload["all_channels"]:
        row = by_key.get(item["channel_key"])
        item["placement_status"] = row.status if row else None
        item["placement_id"] = row.id if row else None
    return payload


@router.post("/media-placements")
async def create_media_placement(
    req: MediaPlacementCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    if req.related_prompt_id is not None:
        await _get_prompt(session, req.related_prompt_id, req.tenant_id)
    row = GeoMediaPlacement(
        tenant_id=req.tenant_id,
        name=req.name.strip(),
        channel_type=req.channel_type,
        channel_key=req.channel_key,
        target_url=req.target_url,
        authority_note=req.authority_note,
        status=req.status,
        published_url=req.published_url,
        priority=int(req.priority),
        priority_band=req.priority_band,
        fits_groups=req.fits_groups,
        citation_national=req.citation_national,
        related_prompt_id=req.related_prompt_id,
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _media_payload(row)


@router.patch("/media-placements/{placement_id}")
async def update_media_placement(
    placement_id: int,
    req: MediaPlacementUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await _get_media_placement(session, placement_id, tenant_id)
    if req.name is not None:
        row.name = req.name.strip()
    if req.channel_type is not None:
        row.channel_type = req.channel_type
    if req.channel_key is not None:
        row.channel_key = req.channel_key
    if req.target_url is not None:
        row.target_url = req.target_url
    if req.authority_note is not None:
        row.authority_note = req.authority_note
    if req.status is not None:
        row.status = req.status
    if req.published_url is not None:
        row.published_url = req.published_url
    if req.priority is not None:
        row.priority = int(req.priority)
    if req.priority_band is not None:
        row.priority_band = req.priority_band
    if req.fits_groups is not None:
        row.fits_groups = req.fits_groups
    if req.citation_national is not None:
        row.citation_national = req.citation_national
    if req.related_prompt_id is not None:
        if req.related_prompt_id:
            await _get_prompt(session, req.related_prompt_id, tenant_id)
        row.related_prompt_id = req.related_prompt_id or None
    await session.commit()
    await session.refresh(row)
    return _media_payload(row)


@router.delete("/media-placements/{placement_id}")
async def delete_media_placement(
    placement_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await _get_media_placement(session, placement_id, tenant_id)
    await session.delete(row)
    await session.commit()
    return {"deleted": True, "id": placement_id}


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
        expires_at=req.expires_at,
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
    include_archived: bool = Query(False, description="默认不列出 archived"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    filters = [GeoContentTask.tenant_id == tenant_id]
    if status:
        filters.append(GeoContentTask.status == status)
    elif not include_archived:
        filters.append(GeoContentTask.status != "archived")
    if pipeline_step:
        filters.append(GeoContentTask.pipeline_step == pipeline_step)
    if owner_user_id is not None:
        filters.append(GeoContentTask.owner_user_id == owner_user_id)
    if from_diagnosis is True:
        filters.append(GeoContentTask.diagnosis_audit_id.is_not(None))
    elif from_diagnosis is False:
        filters.append(GeoContentTask.diagnosis_audit_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            or_(GeoContentTask.title.ilike(like), GeoContentTask.blocked_reason.ilike(like))
        )
    total = int(
        await session.scalar(
            select(func.count()).select_from(GeoContentTask).where(*filters)
        )
        or 0
    )
    stmt = (
        select(GeoContentTask)
        .where(*filters)
        .order_by(GeoContentTask.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list(await session.scalars(stmt))
    items = [await _task_payload(session, r, detail=False) for r in rows]
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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
    from app.geo.content.brief import normalize_brief

    task = GeoContentTask(
        tenant_id=req.tenant_id,
        prompt_id=prompt.id,
        title=title,
        status="draft",
        target_channels=normalize_channels(req.target_channels),
        owner_user_id=ctx.user_id,
        pipeline_step="opportunity",
        brief=normalize_brief(req.brief) if req.brief else {},
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
    if "brief" in data:
        from app.geo.content.brief import normalize_brief

        raw = data["brief"]
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(exclude_unset=True)
        data["brief"] = normalize_brief(raw)
    if "target_channels" in data and data["target_channels"] is not None:
        data["target_channels"] = normalize_channels(data["target_channels"])
    if "status" in data and data["status"] is not None:
        st = str(data["status"]).strip().lower()
        allowed = {
            "draft",
            "facts_bound",
            "editing",
            "needs_fix",
            "ready",
            "published",
            "archived",
        }
        if st not in allowed:
            raise HTTPException(400, f"非法 status，允许: {', '.join(sorted(allowed))}")
        data["status"] = st
    for key, value in data.items():
        setattr(task, key, value)
    if task.status != "archived":
        await _sync_task_pipeline(session, task)
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.delete("/content-tasks/{task_id}")
async def delete_content_task(
    task_id: int,
    tenant_id: int = Query(...),
    hard: bool = Query(False, description="false=归档；true=物理删除（级联文章/渠道稿）"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Archive (default) or hard-delete a content task for test data cleanup."""
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    if hard:
        await session.delete(task)
        await session.commit()
        return {"deleted": True, "hard": True, "id": task_id}
    task.status = "archived"
    await session.commit()
    await session.refresh(task)
    return {
        "deleted": False,
        "archived": True,
        "id": task_id,
        "status": task.status,
    }


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


@router.post("/content-tasks/{task_id}/suggest-brief")
async def suggest_task_brief(
    task_id: int,
    req: SuggestBriefRequest,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Draft strategy brief from prompt (does not write unless client PATCHes)."""
    from app.geo.content.ai_settings import resolve_llm_credentials
    from app.geo.content.brief import strategy_richness
    from app.geo.content.brief_suggest import suggest_brief_for_task

    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    prompt = await _get_prompt(session, task.prompt_id, tenant_id)
    tenant = await _ensure_tenant_exists(session, tenant_id)
    brand = getattr(tenant, "name", None) or f"租户{tenant_id}"
    llm = None
    chat_json = None
    if req.use_llm:
        llm = await resolve_llm_credentials(session, tenant_id)
        if llm:
            try:
                from app.ai.deepseek import chat_json as _chat_json

                chat_json = _chat_json
            except Exception:  # noqa: BLE001
                chat_json = None
                llm = None
    existing = task.brief if isinstance(task.brief, dict) else {}
    # Auto-overwrite when required strategy fields are blank so empty drafts
    # (schema-normalized "") always get AI/heuristic fills.
    overwrite = bool(req.overwrite)
    if not overwrite:
        required = ("industry", "audience", "intent", "content_type", "cta")
        if all(not str(existing.get(k) or "").strip() for k in required):
            overwrite = True
    suggested = await suggest_brief_for_task(
        question=prompt.question,
        brand=brand,
        existing_brief=existing,
        overwrite=overwrite,
        llm=llm,
        chat_json=chat_json,
    )
    return {
        "task_id": task.id,
        "prompt_id": prompt.id,
        "suggested_brief": suggested,
        "strategy_richness": strategy_richness(suggested),
        "persisted": False,
        "overwrite": overwrite,
        "used_llm": bool(llm and chat_json),
    }


@router.post("/content-tasks/{task_id}/retrieve-facts")
async def retrieve_task_facts(
    task_id: int,
    req: RetrieveFactsRequest,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Keyword rank tenant facts for this task; optional auto_bind top results."""
    from app.geo.content.fact_retrieve import retrieve_facts

    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    prompt = await _get_prompt(session, task.prompt_id, tenant_id)
    rows = list(
        await session.scalars(
            select(GeoFact)
            .where(GeoFact.tenant_id == tenant_id, GeoFact.status == "active")
            .order_by(GeoFact.id.desc())
            .limit(2000)
        )
    )
    fact_dicts = [
        {
            "id": f.id,
            "title": f.title,
            "statement": f.statement,
            "source_name": f.source_name,
            "fact_type": f.fact_type,
            "trust_level": f.trust_level,
            "status": f.status,
        }
        for f in rows
    ]
    result = retrieve_facts(
        fact_dicts,
        question=prompt.question or task.title or "",
        brief=task.brief if isinstance(task.brief, dict) else {},
        limit=req.limit,
        verified_only=bool(req.verified_only),
    )
    items = list(result.get("items") or [])
    # Hard guarantee: if tenant has active facts, never return empty items
    # (frontend "0 candidates" was often a miss on soft ranking, not an empty library).
    if not items and fact_dicts:
        ranked = sorted(
            fact_dicts,
            key=lambda f: (
                0 if str(f.get("trust_level") or "") == "verified" else 1,
                -int(f.get("id") or 0),
            ),
        )
        for f in ranked[: max(1, min(int(req.limit or 8), 50))]:
            items.append(
                {
                    "fact_id": f.get("id"),
                    "score": 0.0,
                    "reasons": ["library_fallback"],
                    "title": f.get("title"),
                    "trust_level": f.get("trust_level"),
                    "fact_type": f.get("fact_type"),
                    "source_name": f.get("source_name"),
                    "eligible_hint": str(f.get("trust_level") or "") == "verified",
                }
            )
        result["query_meta"] = {
            **(result.get("query_meta") or {}),
            "fallback_all_active": True,
            "library_fallback": True,
            "active_fact_count": len(fact_dicts),
        }
    else:
        meta = dict(result.get("query_meta") or {})
        meta["active_fact_count"] = len(fact_dicts)
        result["query_meta"] = meta

    bound = False
    if req.auto_bind and items:
        if req.limit > 20:
            raise HTTPException(400, "auto_bind 时 limit 不能超过 20")
        fact_ids = [int(i["fact_id"]) for i in items if i.get("fact_id")]
        await _bind_facts(session, task, fact_ids)
        await session.commit()
        await session.refresh(task)
        bound = True
    return {
        "task_id": task.id,
        "prompt_id": prompt.id,
        "items": items,
        "count": len(items),
        "query_meta": result["query_meta"],
        "auto_bound": bound,
        "task": await _task_payload(session, task, detail=True) if bound else None,
    }


@router.post("/content-tasks/{task_id}/retrieve-facts/apply")
async def apply_retrieved_facts(
    task_id: int,
    req: RetrieveFactsApplyRequest,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Bind selected fact ids (same as PUT facts, dedicated apply path)."""
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    await _bind_facts(session, task, req.fact_ids)
    await session.commit()
    await session.refresh(task)
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
    invalidate_review(task)
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
    scored = await _evaluate_and_store_rules(
        session, task, article, require_channels=require_channels
    )
    await session.commit()
    await session.refresh(task)
    return {
        **scored,
        "task": await _task_payload(session, task, detail=True),
    }


@router.post("/content-tasks/{task_id}/ai-review")
async def ai_review_task(
    task_id: int,
    req: AiReviewRequest,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """P3 AI Reviewer — drafts issues; persist into rule_result when requested."""
    from app.geo.content.ai_reviewer import run_ai_review
    from app.geo.content.ai_settings import resolve_llm_credentials

    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    article = await _latest_article(session, task.id)
    if article is None:
        raise HTTPException(400, "请先生成或保存母稿")
    prompt = await _get_prompt(session, task.prompt_id, tenant_id)
    tenant = await _ensure_tenant_exists(session, tenant_id)
    brand = getattr(tenant, "name", None) or f"租户{tenant_id}"
    llm = await resolve_llm_credentials(session, tenant_id)
    if not llm:
        raise HTTPException(
            503,
            "未配置 AI 能力：请在「AI 能力配置」填写 API Key 后再审稿",
        )
    from app.ai.deepseek import DeepSeekError, chat_json

    rule_input = await _build_rule_input(session, task, article)
    try:
        review = await run_ai_review(
            brand=brand,
            question=prompt.question,
            brief=task.brief if isinstance(task.brief, dict) else {},
            rule_input=rule_input,
            llm=llm,
            chat_json=chat_json,
        )
    except DeepSeekError as exc:
        raise HTTPException(502, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc

    if req.persist:
        rr = task.rule_result if isinstance(task.rule_result, dict) else {}
        rr = dict(rr)
        rr["ai_review"] = review
        task.rule_result = rr
        await session.commit()
        await session.refresh(task)

    return {
        "task_id": task.id,
        "persisted": bool(req.persist),
        "ai_review": review,
        "task": await _task_payload(session, task, detail=True) if req.persist else None,
    }


@router.post("/content-tasks/{task_id}/lint")
async def lint_task_article(
    task_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """编造风险扫描（不改任务状态）。"""
    from app.geo.content.draft_lint import lint_draft, lint_summary
    from app.geo.content.extractable_blocks import blocks_payload

    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    article = await _latest_article(session, task.id)
    if article is None:
        raise HTTPException(400, "请先生成或保存母稿")
    rule_input = await _build_rule_input(session, task, article)
    lint = lint_summary(
        lint_draft(article.body_markdown or "", facts=rule_input.facts or [])
    )
    blocks = blocks_payload(article.body_markdown or "")
    return {
        "task_id": task.id,
        "lint": lint,
        "blocks": blocks,
    }


@router.post("/content-tasks/{task_id}/apply-patch")
async def apply_patch(
    task_id: int,
    req: ApplyPatchRequest,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Insert a rule fix into a new master article version and re-score.

    Returns geo_score + body lengths so the UI can prove the body changed
    (avoids “已应用补丁” false success when the editor does not refresh).
    """
    from app.config import get_settings
    from app.geo.content.draft_lint import lint_draft, lint_summary
    from app.geo.content.extractable_blocks import blocks_payload
    from app.geo.content.geo_score import compute_geo_score, score_blocks_ready

    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    article = await _latest_article(session, task.id)
    if article is None:
        raise HTTPException(400, "请先生成或保存母稿")
    old_body = article.body_markdown or ""
    rule_input = await _build_rule_input(session, task, article)
    patch = next((p for p in build_fix_patches(rule_input) if p["code"] == req.code), None)
    if patch is None:
        raise HTTPException(400, f"无可用修复补丁: {req.code}（该规则可能已通过，请先点「检查就绪」刷新）")
    insert = str(patch.get("insert_markdown") or "")
    if not insert.strip():
        raise HTTPException(400, f"补丁 {req.code} 内容为空")
    if patch.get("cursor_hint") == "prepend":
        new_body = insert.lstrip("\n") + ("\n" + old_body if old_body else "")
    else:
        new_body = (old_body.rstrip() + "\n" + insert.lstrip("\n")) if old_body else insert.lstrip("\n")
    if new_body.strip() == old_body.strip():
        raise HTTPException(400, f"补丁 {req.code} 未改变正文，请手动编辑或重新检查")

    author_name = req.author_name or article.author_name
    if req.code == "author_visible" and req.author_name:
        author_name = req.author_name
    # Drop stale outline FAQ/sections that can mask body-based detectors
    outline = dict(article.outline or {}) if isinstance(article.outline, dict) else {}
    if req.code == "faq_min" and isinstance(outline.get("faq"), list):
        outline.pop("faq", None)
    if req.code in {"definition", "conclusion_extractable"} and isinstance(
        outline.get("sections"), list
    ):
        drop_type = "definition" if req.code == "definition" else "conclusion"
        outline["sections"] = [
            s
            for s in outline["sections"]
            if not (isinstance(s, dict) and s.get("type") == drop_type)
        ]

    version_no = article.version_no + 1
    new_article = GeoArticleVersion(
        task_id=task.id,
        version_no=version_no,
        kind="master",
        title=article.title,
        body_markdown=new_body,
        outline=outline,
        author_name=author_name,
        generation_meta={
            "source": "apply_patch",
            "patch_code": req.code,
            "body_len_before": len(old_body),
            "body_len_after": len(new_body),
        },
        created_by=ctx.user_id,
    )
    session.add(new_article)
    task.status = "editing"
    invalidate_review(task)
    await session.flush()

    rule_input = await _build_rule_input(session, task, new_article)
    checks = run_checks(rule_input)
    check_dicts = [c.to_dict() for c in checks]
    ready = is_ready(checks, require_channels=False)
    lint = lint_summary(
        lint_draft(rule_input.body_markdown or "", facts=rule_input.facts or [])
    )
    blocks = blocks_payload(rule_input.body_markdown or "")
    lint_ok = bool(lint.get("blocks_ready")) if isinstance(lint, dict) else None
    score_payload = compute_geo_score(
        rule_input,
        brief=task.brief if isinstance(task.brief, dict) else {},
        lint_ok=lint_ok,
        rule_checks=checks,
    )
    settings = get_settings()
    score_ok, score_msg = score_blocks_ready(
        score_payload,
        threshold=int(getattr(settings, "geo_score_threshold", 60) or 60),
        gate_enabled=bool(getattr(settings, "geo_score_gate", False)),
    )
    if not score_ok:
        ready = False

    target = next((c for c in check_dicts if c.get("code") == req.code), None)
    target_passed = bool(target and target.get("passed"))
    prev_rr = task.rule_result if isinstance(task.rule_result, dict) else {}
    ai_review = prev_rr.get("ai_review") if isinstance(prev_rr.get("ai_review"), dict) else None

    task.rule_result = {
        "ready": ready,
        "require_channels": False,
        "checks": check_dicts,
        "lint": lint,
        "blocks": blocks,
        "geo_score": score_payload["geo_score"],
        "geo_subscores": score_payload["geo_subscores"],
        "geo_actions": score_payload["geo_actions"],
        "geo_score_gate": bool(getattr(settings, "geo_score_gate", False)),
        "geo_score_threshold": int(getattr(settings, "geo_score_threshold", 60) or 60),
        "geo_score_gate_message": score_msg or None,
        "ai_review": ai_review,
        "last_patch": {
            "code": req.code,
            "effective": target_passed,
            "body_len_before": len(old_body),
            "body_len_after": len(new_body),
        },
        "checked_at": datetime.utcnow().isoformat(),
    }
    task.status = "ready" if ready else "needs_fix"
    await _sync_task_pipeline(session, task, checks=check_dicts)
    await session.commit()
    await session.refresh(task)
    task_payload = await _task_payload(session, task, detail=True)
    return {
        "applied": req.code,
        "effective": target_passed,
        "body_changed": True,
        "body_len_before": len(old_body),
        "body_len_after": len(new_body),
        "ready": ready,
        "checks": check_dicts,
        "patches": build_fix_patches(rule_input),
        "lint": lint,
        "blocks": blocks,
        "geo_score": score_payload["geo_score"],
        "geo_subscores": score_payload["geo_subscores"],
        "geo_actions": score_payload["geo_actions"],
        "task": task_payload,
        "article": (task_payload or {}).get("article"),
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
    fact_dicts = _fact_dicts(facts)
    from app.geo.content.brief import (
        brief_generation_error_message,
        brief_ready,
        normalize_brief,
    )
    from app.geo.content.evidence import (
        generation_evidence_error_message,
        prepare_facts_for_generation,
    )

    brief_norm = normalize_brief(task.brief)
    if not brief_ready(brief_norm):
        raise HTTPException(400, brief_generation_error_message(brief_norm))

    _, evidence_preview = prepare_facts_for_generation(fact_dicts, min_eligible=3)
    if not evidence_preview["ok"]:
        raise HTTPException(400, generation_evidence_error_message(evidence_preview))

    task.status = "generating"
    await session.commit()
    try:
        llm = await resolve_llm_credentials(session, tenant_id)
        payload = await generate_master_article(
            tenant_name=tenant.name,
            question=prompt.question,
            facts=fact_dicts,
            llm=llm,
            brief=brief_norm,
        )
        body = to_markdown(payload)
        outline = outline_from_payload(payload)
        latest = await _latest_article(session, task.id)
        version_no = (latest.version_no + 1) if latest else 1
        evidence_meta = payload.get("_evidence") or evidence_preview
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
                "evidence": evidence_meta,
                "brief": payload.get("_brief") or brief_norm,
            },
            created_by=ctx.user_id,
        )
        session.add(article)
        task.title = payload["title"]
        task.status = "editing"
        invalidate_review(task)
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
    registry_rows = registry_row_dicts(
        await _ensure_default_publishing_channels(session, tenant_id)
    )
    enabled_types = enabled_types_from_rows(registry_rows)
    channels = filter_channels_by_registry(
        normalize_channels(req.channels or list(task.target_channels or [])),
        enabled_types=enabled_types or None,
    )
    if not channels:
        raise HTTPException(400, "没有可用的启用发布渠道，请先在「发布渠道」配置中启用")
    existing = {v.channel: v for v in await _variants(session, task.id)}
    created = []
    for channel in channels:
        try:
            title, body = adapt_for_channel(
                channel, article.title, article.body_markdown, article.outline or {}
            )
        except GeoContentError as exc:
            raise HTTPException(400, str(exc)) from exc
        meta = build_adapt_meta(
            channel,
            master_version_id=article.id,
            title=title,
            body_md=body,
        )
        if channel in existing:
            variant = existing[channel]
            if variant.status == "published":
                raise HTTPException(
                    409,
                    f"渠道 {channel} 已发布，请先确认后再覆盖或新增任务",
                )
            profile = get_profile(channel)
            variant.title = title
            variant.body_markdown = body
            variant.article_version_id = article.id
            variant.adapt_meta = meta
            variant.status = "draft"
            if profile:
                variant.export_format = profile.export_format
        else:
            profile = get_profile(channel)
            variant = GeoChannelVariant(
                task_id=task.id,
                article_version_id=article.id,
                channel=channel,
                title=title,
                body_markdown=body,
                export_format=(profile.export_format if profile else "markdown"),
                status="draft",
                adapt_meta=meta,
            )
            session.add(variant)
        created.append(channel)
    # refresh target channels union
    task.target_channels = sorted(set((task.target_channels or []) + channels))
    # flush new variant rows so channel_variant_ready sees them
    await session.flush()
    article = await _latest_article(session, task.id)
    # re-score rules so UI no longer shows stale「缺少 website/wechat/zhihu」
    await _evaluate_and_store_rules(session, task, article, require_channels=False)
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.patch("/content-tasks/{task_id}/variants/{channel}")
async def update_variant(
    task_id: int,
    channel: str,
    req: VariantUpdate,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    channel_key = str(channel or "").strip().lower()
    existing = {v.channel: v for v in await _variants(session, task.id)}
    variant = existing.get(channel_key)
    if variant is None:
        raise HTTPException(404, f"渠道版本不存在: {channel_key}")
    if req.title is not None:
        variant.title = req.title.strip()
    if req.body_markdown is not None:
        variant.body_markdown = req.body_markdown
    meta = dict(variant.adapt_meta or {})
    meta["manually_edited"] = True
    variant.adapt_meta = meta
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


@router.post("/content-tasks/{task_id}/submit-review")
async def submit_task_review(
    task_id: int,
    req: ReviewSubmit,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    article = await _latest_article(session, task.id)
    if article is None:
        raise HTTPException(400, "请先生成母稿后再提交审校")
    try:
        apply_submit(task, note=req.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await _sync_task_pipeline(session, task)
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.post("/content-tasks/{task_id}/review")
async def decide_task_review(
    task_id: int,
    req: ReviewDecision,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    try:
        apply_decision(
            task,
            decision=req.decision,
            note=req.note,
            reviewer_id=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await _sync_task_pipeline(session, task)
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


async def _write_publication(
    session: AsyncSession,
    *,
    task: GeoContentTask,
    variant: GeoChannelVariant,
    channel: str,
    published_url: str,
    note: str | None,
    publish_mode: str,
) -> None:
    pub = GeoPublication(
        variant_id=variant.id,
        channel=channel,
        publish_mode=publish_mode,
        published_url=published_url,
        published_at=datetime.utcnow(),
        status="published",
        note=note,
    )
    session.add(pub)
    variant.status = "published"
    task.status = "published"
    await _sync_task_pipeline(session, task)


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
        assert_can_publish(rule_input, task=task)
    except PublishGateError as exc:
        raise HTTPException(400, str(exc)) from exc
    registry_rows = registry_row_dicts(
        await _ensure_default_publishing_channels(session, req.tenant_id)
    )
    registry_mode = publish_mode_for_channel(req.channel, registry_rows)
    await _write_publication(
        session,
        task=task,
        variant=variant,
        channel=req.channel,
        published_url=url,
        note=req.note,
        publish_mode=publication_publish_mode(registry_mode),
    )
    await session.commit()
    await session.refresh(task)
    return await _task_payload(session, task, detail=True)


@router.get("/content-tasks/{task_id}/push-targets")
async def list_task_push_targets(
    task_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List multi-media push targets for a task (ready vs missing config/export)."""
    from app.geo.content.multi_push import list_push_targets

    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    await _ensure_default_publishing_channels(session, tenant_id)
    variants = await _variants(session, task.id)
    targets = await list_push_targets(
        session, tenant_id=tenant_id, task=task, variants=variants
    )
    ready = [t for t in targets if t.get("ready")]
    return {
        "task_id": task_id,
        "review_status": task.review_status,
        "targets": targets,
        "ready_count": len(ready),
        "ready_targets": ready,
    }


@router.post("/content-tasks/{task_id}/push")
async def push_variant_webhook(
    task_id: int,
    req: WebhookPushRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Push one media channel (website/docs webhook or social_api)."""
    from app.geo.content.channel_registry import profile_key_for_registry_type
    from app.geo.content.connectors.social import SocialError
    from app.geo.content.connectors.webhook import WebhookConnectorError
    from app.geo.content.multi_push import execute_single_push

    ctx.ensure_tenant(req.tenant_id)
    task = await _get_task(session, task_id, req.tenant_id)
    channel = str(req.channel or "").strip().lower()
    variants = {v.channel: v for v in await _variants(session, task.id)}
    variant = variants.get(channel)
    if variant is None:
        raise HTTPException(400, "请先生成该渠道版本")
    if variant.status not in {"exported", "published"}:
        raise HTTPException(400, "请先导出渠道稿，再推送")

    article = await _latest_article(session, task.id)
    rule_input = await _build_rule_input(session, task, article)
    try:
        assert_can_publish(rule_input, task=task)
    except PublishGateError as exc:
        raise HTTPException(400, str(exc)) from exc

    account = await session.get(GeoChannelAccount, req.account_id)
    if account is None or account.tenant_id != req.tenant_id:
        raise HTTPException(404, "渠道账号不存在")
    channel_row = await session.get(GeoPublishingChannel, account.channel_id)
    if channel_row is None or channel_row.tenant_id != req.tenant_id:
        raise HTTPException(404, "发布渠道不存在")
    if not channel_row.enabled:
        raise HTTPException(400, "发布渠道已停用")
    if channel_row.publish_mode != "auto_publish":
        raise HTTPException(400, "该渠道发布方式不是 auto_publish")

    adapt = profile_key_for_registry_type(channel_row.channel_type)
    ctype = str(channel_row.channel_type or "").lower()
    if adapt != channel and ctype != channel:
        raise HTTPException(
            400,
            f"账号渠道类型 {channel_row.channel_type} 与变体渠道 {channel} 不匹配",
        )

    try:
        remote = await execute_single_push(
            session,
            task=task,
            variant=variant,
            channel_row=channel_row,
            account=account,
            mode=req.mode,
            article=article,
        )
    except (WebhookConnectorError, SocialError, ValueError) as exc:
        status = 502 if "HTTP" in str(exc) or "请求失败" in str(exc) else 400
        raise HTTPException(status, str(exc)) from exc

    remote_url = (req.published_url or "").strip() or remote.get("remote_url")
    publication_created = False
    if req.create_publication and remote_url:
        if not str(remote_url).startswith(("http://", "https://")):
            raise HTTPException(400, "发布 URL 无效")
        await _write_publication(
            session,
            task=task,
            variant=variant,
            channel=channel,
            published_url=str(remote_url),
            note=req.note or f"{remote.get('connector')} {req.mode}",
            publish_mode="auto_publish",
        )
        publication_created = True
        await session.commit()
        await session.refresh(task)
    else:
        await session.commit()

    detail = await _task_payload(session, task, detail=True)
    return {
        "ok": True,
        "connector": remote.get("connector"),
        "platform": remote.get("platform"),
        "http_status": remote.get("http_status"),
        "remote_url": remote_url,
        "webhook_host": remote.get("host"),
        "publication_created": publication_created,
        "mode": req.mode,
        "task": detail,
    }


@router.post("/content-tasks/{task_id}/push-batch")
async def push_variant_batch(
    task_id: int,
    req: PushBatchRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Push one task to multiple ready media channels (partial success allowed)."""
    from app.geo.content.connectors.social import SocialError
    from app.geo.content.connectors.webhook import WebhookConnectorError
    from app.geo.content.multi_push import execute_single_push, list_push_targets

    ctx.ensure_tenant(req.tenant_id)
    task = await _get_task(session, task_id, req.tenant_id)
    await _ensure_default_publishing_channels(session, req.tenant_id)
    variants = await _variants(session, task.id)
    var_map = {str(v.channel).lower(): v for v in variants}

    article = await _latest_article(session, task.id)
    rule_input = await _build_rule_input(session, task, article)
    try:
        assert_can_publish(rule_input, task=task)
    except PublishGateError as exc:
        raise HTTPException(400, str(exc)) from exc

    ready_all = [
        t
        for t in await list_push_targets(
            session, tenant_id=req.tenant_id, task=task, variants=variants
        )
        if t.get("ready")
    ]
    if req.targets:
        wanted = {(t.channel.lower(), int(t.account_id)) for t in req.targets}
        ready = []
        for t in ready_all:
            aid = int(t["account_id"])
            keys = {
                (str(t.get("adapt_key") or "").lower(), aid),
                (str(t.get("channel_type") or "").lower(), aid),
            }
            if keys & wanted:
                ready.append(t)
    else:
        ready = ready_all

    if not ready:
        raise HTTPException(
            400,
            "没有可推送目标：请确认渠道 auto_publish、账号凭证、渠道稿已导出（见 push-targets）",
        )

    results: list[dict[str, Any]] = []
    ok_n = 0
    fail_n = 0
    for t in ready:
        channel_key = str(t.get("adapt_key") or t.get("channel_type") or "").lower()
        variant = var_map.get(channel_key)
        account = await session.get(GeoChannelAccount, int(t["account_id"]))
        channel_row = await session.get(GeoPublishingChannel, int(t["channel_id"]))
        if not variant or not account or not channel_row:
            results.append(
                {
                    "ok": False,
                    "channel": channel_key,
                    "error": "目标数据缺失",
                    "account_id": t.get("account_id"),
                }
            )
            fail_n += 1
            continue
        try:
            remote = await execute_single_push(
                session,
                task=task,
                variant=variant,
                channel_row=channel_row,
                account=account,
                mode=req.mode,
                article=article,
            )
            remote_url = remote.get("remote_url")
            publication_created = False
            if req.create_publication and remote_url and str(remote_url).startswith(
                ("http://", "https://")
            ):
                await _write_publication(
                    session,
                    task=task,
                    variant=variant,
                    channel=channel_key,
                    published_url=str(remote_url),
                    note=req.note or f"batch {remote.get('connector')} {req.mode}",
                    publish_mode="auto_publish",
                )
                publication_created = True
            results.append({**remote, "publication_created": publication_created})
            ok_n += 1
        except (WebhookConnectorError, SocialError, ValueError) as exc:
            import logging

            logging.getLogger(__name__).warning(
                "push-batch fail channel=%s: %s", channel_key, exc
            )
            results.append(
                {
                    "ok": False,
                    "channel": channel_key,
                    "channel_type": t.get("channel_type"),
                    "account_id": t.get("account_id"),
                    "account_name": t.get("account_name"),
                    "error": str(exc),
                }
            )
            fail_n += 1

    await session.commit()
    await session.refresh(task)
    detail = await _task_payload(session, task, detail=True)
    return {
        "ok": fail_n == 0,
        "ok_count": ok_n,
        "fail_count": fail_n,
        "results": results,
        "mode": req.mode,
        "task": detail,
    }


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
    snapshots = await session.scalar(
        select(func.count()).select_from(GeoAnswerSnapshot).where(
            GeoAnswerSnapshot.tenant_id == tenant_id
        )
    )
    snapshots_mention = await session.scalar(
        select(func.count()).select_from(GeoAnswerSnapshot).where(
            GeoAnswerSnapshot.tenant_id == tenant_id,
            GeoAnswerSnapshot.mentions_brand.is_(True),
        )
    )
    media_planned = await session.scalar(
        select(func.count()).select_from(GeoMediaPlacement).where(
            GeoMediaPlacement.tenant_id == tenant_id,
            GeoMediaPlacement.status.in_(["planned", "in_progress"]),
        )
    )
    media_published = await session.scalar(
        select(func.count()).select_from(GeoMediaPlacement).where(
            GeoMediaPlacement.tenant_id == tenant_id,
            GeoMediaPlacement.status == "published",
        )
    )
    active_prompts = list(
        await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.status == "active"
            )
        )
    )
    prompts_brand_missing = sum(
        1 for p in active_prompts if "brand_missing" in (p.tags or [])
    )
    prompt_ids = [p.id for p in active_prompts]
    latest = await _latest_snapshots_by_prompt(session, tenant_id, prompt_ids)
    published_at = await _published_task_updated_by_prompt(session, tenant_id, prompt_ids)
    prompts_need_recheck = 0
    for p in active_prompts:
        snap = latest.get(p.id)
        if needs_recheck(
            has_published_task=p.id in published_at,
            task_updated_at=published_at.get(p.id),
            last_snapshot_at=snap.captured_at if snap else None,
        ):
            prompts_need_recheck += 1
    snap_total = int(snapshots or 0)
    snap_mention = int(snapshots_mention or 0)
    engines_covered = await session.scalar(
        select(func.count(func.distinct(GeoAnswerSnapshot.engine))).where(
            GeoAnswerSnapshot.tenant_id == tenant_id
        )
    )
    competitor_cols = list(
        await session.scalars(
            select(GeoAnswerSnapshot.competitors).where(
                GeoAnswerSnapshot.tenant_id == tenant_id
            )
        )
    )
    snapshots_with_competitors = sum(1 for c in competitor_cols if c)

    # D0: exclude brand-probe prompts from category visibility mention_rate
    prompt_probe = {p.id: bool(p.is_brand_probe) for p in active_prompts}
    all_snaps = list(
        await session.scalars(
            select(GeoAnswerSnapshot).where(GeoAnswerSnapshot.tenant_id == tenant_id)
        )
    )
    split_rows = [
        {
            "mentions_brand": bool(s.mentions_brand),
            "is_brand_probe": bool(prompt_probe.get(s.prompt_id, False)),
            "brand_position": s.brand_position,
        }
        for s in all_snaps
    ]
    split = split_visibility_metrics(split_rows)
    prompts_probe = sum(1 for p in active_prompts if p.is_brand_probe)

    cited_url_cols = [s.cited_urls for s in all_snaps]
    snapshots_with_citations = 0
    distinct_cited_domains: set[str] = set()
    for urls in cited_url_cols:
        domains = extract_cited_domains(list(urls or []))
        if domains:
            snapshots_with_citations += 1
            distinct_cited_domains.update(domains)

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
        "snapshots": snap_total,
        "snapshots_mention_brand": snap_mention,
        "media_open": int(media_planned or 0),
        "media_published": int(media_published or 0),
        "prompts_brand_missing": int(prompts_brand_missing),
        "prompts_need_recheck": int(prompts_need_recheck),
        "prompts_probe": int(prompts_probe),
        # Raw all-snapshot rate kept for debugging; primary KPI excludes probes.
        "visibility_mention_rate_raw": visibility_mention_rate(
            total_snapshots=snap_total, mention_snapshots=snap_mention
        ),
        "visibility_mention_rate": split["visibility_mention_rate"],
        "visibility_top1_rate": split.get("visibility_top1_rate"),
        "snapshots_visibility": split["snapshots_visibility"],
        "snapshots_visibility_mention": split["snapshots_visibility_mention"],
        "snapshots_visibility_first": split.get("snapshots_visibility_first"),
        "snapshots_probe": split["snapshots_probe"],
        "snapshots_probe_mention": split["snapshots_probe_mention"],
        "probe_recognition_rate": split["probe_recognition_rate"],
        "visibility_engines_covered": int(engines_covered or 0),
        "snapshots_with_competitors": int(snapshots_with_competitors),
        "snapshots_with_citations": int(snapshots_with_citations),
        "distinct_cited_domains": len(distinct_cited_domains),
        # Hygiene notes for UI
        "metric_notes": {
            "visibility_mention_rate": "分母排除品牌探测题；无可见性样本时为 null（未测，≠0）",
            "probe_recognition_rate": "仅品牌探测题；用于认知，不计入可见性提及率",
            "visibility_top1_rate": "可见性样本中 brand_position=first 占比",
        },
    }


@router.get("/deliverables/pack", response_model=None)
async def geo_deliverables_pack(
    tenant_id: int = Query(...),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    format: str | None = Query(None, description="json (default) or md"),
    top_domains: int = Query(10, ge=1, le=50),
    sample_snapshots: int = Query(12, ge=0, le=50),
    task_limit: int = Query(20, ge=0, le=100),
    business_id: int | None = Query(None, description="按优化业务切片"),
    unit_id: int | None = Query(None, description="按优化单元切片（优先于 business_id）"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    """Client-facing GEO deliverables pack composed from existing GEO data.

    可选 business_id / unit_id：快照与任务按意图词归属切片；并附带 daily_metrics 序列。
    """
    from app.geo.content.daily_metrics import (
        metric_row_payload,
        scope_business,
        scope_tenant,
        scope_unit,
    )
    from app.geo.content.snapshots import normalize_cited_urls

    ctx.ensure_tenant(tenant_id)
    tenant = await _ensure_tenant_exists(session, tenant_id)

    end = (
        parse_window_bound(to, label="to")
        if to
        else datetime.utcnow()
    )
    start = (
        parse_window_bound(from_, label="from")
        if from_
        else end - timedelta(days=30)
    )
    if start > end:
        raise HTTPException(400, "from 不能晚于 to")

    period = {
        "from": start.isoformat(timespec="seconds"),
        "to": end.isoformat(timespec="seconds"),
        "days": max(1, (end.date() - start.date()).days + 1),
    }

    # ---- scope: unit > business > tenant ----
    scope_level = "tenant"
    scope_biz_id: int | None = None
    scope_unit_id: int | None = None
    scope_biz_name: str | None = None
    scope_unit_name: str | None = None
    allowed_prompt_ids: set[int] | None = None  # None = all

    all_units = list(
        await session.scalars(
            select(GeoOptimizationUnit).where(GeoOptimizationUnit.tenant_id == tenant_id)
        )
    )
    unit_biz = {u.id: u.business_id for u in all_units}
    unit_names = {u.id: u.name for u in all_units}
    biz_rows = list(
        await session.scalars(
            select(GeoOptimizationBusiness).where(
                GeoOptimizationBusiness.tenant_id == tenant_id
            )
        )
    )
    biz_names = {b.id: b.name for b in biz_rows}

    if unit_id is not None:
        unit_row = next((u for u in all_units if u.id == unit_id), None)
        if not unit_row:
            raise HTTPException(400, "优化单元不存在")
        scope_level = "unit"
        scope_unit_id = unit_id
        scope_biz_id = unit_row.business_id
        scope_unit_name = unit_row.name
        scope_biz_name = biz_names.get(unit_row.business_id)
        allowed_prompt_ids = set(
            await session.scalars(
                select(GeoPrompt.id).where(
                    GeoPrompt.tenant_id == tenant_id,
                    GeoPrompt.unit_id == unit_id,
                )
            )
        )
    elif business_id is not None:
        if business_id not in biz_names:
            raise HTTPException(400, "优化业务不存在")
        scope_level = "business"
        scope_biz_id = business_id
        scope_biz_name = biz_names[business_id]
        unit_ids_in_biz = {u.id for u in all_units if u.business_id == business_id}
        if unit_ids_in_biz:
            allowed_prompt_ids = set(
                await session.scalars(
                    select(GeoPrompt.id).where(
                        GeoPrompt.tenant_id == tenant_id,
                        GeoPrompt.unit_id.in_(list(unit_ids_in_biz)),
                    )
                )
            )
        else:
            allowed_prompt_ids = set()

    if scope_level == "tenant":
        scope_label = "租户全量"
        dm_scope_key = scope_tenant()
    elif scope_level == "business":
        scope_label = f"优化业务 · {scope_biz_name or ('#' + str(scope_biz_id))}"
        dm_scope_key = scope_business(int(scope_biz_id))
    else:
        scope_label = (
            f"优化单元 · {(scope_biz_name + ' / ') if scope_biz_name else ''}"
            f"{scope_unit_name or ('#' + str(scope_unit_id))}"
        )
        dm_scope_key = scope_unit(int(scope_unit_id))

    scope_meta = {
        "level": scope_level,
        "business_id": scope_biz_id,
        "unit_id": scope_unit_id,
        "business_name": scope_biz_name,
        "unit_name": scope_unit_name,
        "label": scope_label,
        "scope_key": dm_scope_key,
    }

    # ---- windowed snapshots (optionally filtered by prompt scope) ----
    snap_rows = list(
        await session.scalars(
            select(GeoAnswerSnapshot)
            .where(GeoAnswerSnapshot.tenant_id == tenant_id)
            .order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
        )
    )
    window_snaps = [
        s
        for s in snap_rows
        if in_captured_window(s.captured_at, start=start, end=end)
        and (allowed_prompt_ids is None or s.prompt_id in allowed_prompt_ids)
    ]

    prompt_ids = {s.prompt_id for s in window_snaps}
    active_prompts = list(
        await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.status == "active"
            )
        )
    )
    if allowed_prompt_ids is not None:
        active_prompts = [p for p in active_prompts if p.id in allowed_prompt_ids]
    prompt_probe = {p.id: bool(p.is_brand_probe) for p in active_prompts}
    questions = {p.id: p.question for p in active_prompts}
    if prompt_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(list(prompt_ids))
            )
        ):
            questions[p.id] = p.question
            prompt_probe.setdefault(p.id, bool(p.is_brand_probe))

    split = split_visibility_metrics(
        [
            {
                "mentions_brand": bool(s.mentions_brand),
                "is_brand_probe": bool(prompt_probe.get(s.prompt_id, False)),
                "brand_position": s.brand_position,
            }
            for s in window_snaps
        ]
    )
    engines_covered = len({s.engine for s in window_snaps})

    own_domains = await _own_domains_for_tenant(session, tenant_id)
    buckets: dict[str, dict[str, Any]] = {}
    snapshots_with_citations = 0
    citation_count_total = 0
    for row in window_snaps:
        urls = normalize_cited_urls(list(row.cited_urls or []))
        citation_count_total += len(urls)
        domains = extract_cited_domains(list(row.cited_urls or []))
        if not domains:
            continue
        snapshots_with_citations += 1
        for domain in domains:
            bucket = buckets.setdefault(
                domain,
                {
                    "domain": domain,
                    "cite_count": 0,
                    "engines": set(),
                },
            )
            bucket["cite_count"] += 1
            bucket["engines"].add(row.engine)
    cite_items = []
    for bucket in buckets.values():
        bp = match_blueprint_for_domain(bucket["domain"])
        cite_items.append(
            {
                "domain": bucket["domain"],
                "cite_count": bucket["cite_count"],
                "engines": sorted(bucket["engines"]),
                "is_own_domain": bool(
                    own_domains
                    and any(domain_matches(bucket["domain"], own) for own in own_domains)
                ),
                "blueprint_channel_key": bp["channel_key"] if bp else None,
                "blueprint_channel_name": bp["channel_name"] if bp else None,
            }
        )
    cite_items.sort(key=lambda x: (-x["cite_count"], x["domain"]))
    citations_top = cite_items[:top_domains]

    # ---- tasks in window (by updated_at), filter by prompt scope ----
    task_rows = list(
        await session.scalars(
            select(GeoContentTask)
            .where(GeoContentTask.tenant_id == tenant_id)
            .order_by(GeoContentTask.updated_at.desc(), GeoContentTask.id.desc())
        )
    )
    window_tasks = [
        t
        for t in task_rows
        if t.updated_at is not None
        and start <= t.updated_at.replace(tzinfo=None) <= end
        and (allowed_prompt_ids is None or t.prompt_id in allowed_prompt_ids)
    ]
    published = sum(1 for t in window_tasks if t.status == "published")
    task_items = []
    for t in window_tasks[:task_limit]:
        task_items.append(
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "prompt_id": t.prompt_id,
                "prompt_question": questions.get(t.prompt_id),
                "updated_at": _iso(t.updated_at),
                "pipeline_step": t.pipeline_step,
            }
        )

    missing_pids = {
        t["prompt_id"] for t in task_items if t["prompt_id"] and not t["prompt_question"]
    }
    if missing_pids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(missing_pids)
            )
        ):
            for item in task_items:
                if item["prompt_id"] == p.id:
                    item["prompt_question"] = p.question

    snaps_sample = [
        {
            "id": s.id,
            "prompt_id": s.prompt_id,
            "prompt_question": questions.get(s.prompt_id),
            "engine": s.engine,
            "mentions_brand": bool(s.mentions_brand),
            "brand_position": s.brand_position or "unknown",
            "sentiment": s.sentiment or "unknown",
            "competitors": s.competitors or [],
            "captured_at": _iso(s.captured_at),
        }
        for s in window_snaps[:sample_snapshots]
    ]

    summary = {
        "prompts": len(active_prompts),
        "tasks": len(window_tasks),
        "published": published,
        "snapshots": len(window_snaps),
        "snapshots_visibility": split["snapshots_visibility"],
        "snapshots_visibility_mention": split["snapshots_visibility_mention"],
        "visibility_mention_rate": split["visibility_mention_rate"],
        "visibility_top1_rate": split.get("visibility_top1_rate"),
        "snapshots_probe": split["snapshots_probe"],
        "probe_recognition_rate": split["probe_recognition_rate"],
        "visibility_engines_covered": engines_covered,
        "snapshots_with_citations": snapshots_with_citations,
        "distinct_cited_domains": len(cite_items),
        "citation_count": citation_count_total,
        "prompts_need_recheck": sum(
            1 for p in active_prompts if "brand_missing" in (p.tags or [])
        ),
    }

    # ---- daily_metrics series for selected scope ----
    day_from = start.date() if hasattr(start, "date") else start
    day_to = end.date() if hasattr(end, "date") else end
    dm_rows = list(
        await session.scalars(
            select(GeoDailyMetric)
            .where(
                GeoDailyMetric.tenant_id == tenant_id,
                GeoDailyMetric.metric_date >= day_from,
                GeoDailyMetric.metric_date <= day_to,
                GeoDailyMetric.scope_key == dm_scope_key,
            )
            .order_by(GeoDailyMetric.metric_date.asc())
        )
    )
    daily_series = [metric_row_payload(r) for r in dm_rows]

    business_slices: list[dict[str, Any]] = []
    unit_slices: list[dict[str, Any]] = []
    if scope_level == "tenant":
        biz_dm = list(
            await session.scalars(
                select(GeoDailyMetric).where(
                    GeoDailyMetric.tenant_id == tenant_id,
                    GeoDailyMetric.metric_date >= day_from,
                    GeoDailyMetric.metric_date <= day_to,
                    GeoDailyMetric.scope_key.like("b%"),
                )
            )
        )
        latest_biz: dict[int, GeoDailyMetric] = {}
        for r in biz_dm:
            bid = r.business_id
            if bid is None:
                continue
            prev = latest_biz.get(bid)
            if prev is None or r.metric_date >= prev.metric_date:
                latest_biz[bid] = r
        for bid, r in sorted(latest_biz.items()):
            payload = metric_row_payload(r)
            payload["business_name"] = biz_names.get(bid)
            business_slices.append(payload)

        unit_dm = list(
            await session.scalars(
                select(GeoDailyMetric).where(
                    GeoDailyMetric.tenant_id == tenant_id,
                    GeoDailyMetric.metric_date >= day_from,
                    GeoDailyMetric.metric_date <= day_to,
                    GeoDailyMetric.scope_key.like("u%"),
                )
            )
        )
        latest_unit: dict[int, GeoDailyMetric] = {}
        for r in unit_dm:
            uid = r.unit_id
            if uid is None:
                continue
            prev = latest_unit.get(uid)
            if prev is None or r.metric_date >= prev.metric_date:
                latest_unit[uid] = r
        for uid, r in sorted(latest_unit.items()):
            payload = metric_row_payload(r)
            payload["unit_name"] = unit_names.get(uid)
            bid = r.business_id or unit_biz.get(uid)
            payload["business_id"] = bid
            payload["business_name"] = biz_names.get(bid) if bid else None
            unit_slices.append(payload)
    elif scope_level == "business" and scope_biz_id is not None:
        unit_dm = list(
            await session.scalars(
                select(GeoDailyMetric).where(
                    GeoDailyMetric.tenant_id == tenant_id,
                    GeoDailyMetric.metric_date >= day_from,
                    GeoDailyMetric.metric_date <= day_to,
                    GeoDailyMetric.business_id == scope_biz_id,
                    GeoDailyMetric.scope_key.like("u%"),
                )
            )
        )
        latest_unit = {}
        for r in unit_dm:
            uid = r.unit_id
            if uid is None:
                continue
            prev = latest_unit.get(uid)
            if prev is None or r.metric_date >= prev.metric_date:
                latest_unit[uid] = r
        for uid, r in sorted(latest_unit.items()):
            payload = metric_row_payload(r)
            payload["unit_name"] = unit_names.get(uid)
            payload["business_name"] = scope_biz_name
            unit_slices.append(payload)

    pack = build_deliverables_pack(
        tenant_id=tenant_id,
        tenant_name=getattr(tenant, "name", None) or f"租户{tenant_id}",
        period=period,
        summary=summary,
        citations_top=citations_top,
        tasks=task_items,
        snapshots_sample=snaps_sample,
        scope=scope_meta,
        daily_series=daily_series,
        business_slices=business_slices,
        unit_slices=unit_slices,
    )

    fmt = (format or "json").strip().lower()
    if fmt in ("md", "markdown"):
        body = render_deliverables_markdown(pack)
        filename = f"geo-deliverables-{tenant_id}.md"
        return PlainTextResponse(
            body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    if fmt not in ("", "json"):
        raise HTTPException(400, "format 仅支持 json 或 md")
    return pack

