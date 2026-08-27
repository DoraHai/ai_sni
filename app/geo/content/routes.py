"""GEO 内容工作台 API：机会 / 事实 / 任务 / 生成 / 渠道 / 回填。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError, ProgrammingError
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
    ChannelPolishPromptsUpdate,
    CompetitorCreateTasksRequest,
    CompetitorReportPatch,
    CompetitorReportUpsert,
    CompetitorTraceReportRequest,
    AnswerSnapshotCreate,
    AnswerSnapshotExtractUrlsRequest,
    AnswerSnapshotProbeBatchRequest,
    AnswerSnapshotProbeRequest,
    AnswerSnapshotSuggestFieldsRequest,
    AnswerSnapshotCitationCheckRequest,
    AnswerSnapshotUpdate,
    ApplyPatchRequest,
    ArticleUpdate,
    ChannelAccountCreate,
    ChannelAccountUpdate,
    FactCreate,
    FactUpdate,
    FactVerifyRequest,
    GapCreateTasksRequest,
    GeoOnboardingApplyRequest,
    GeoOnboardingPreviewRequest,
    MediaPlacementCreate,
    MonitoringStanceUpdate,
    MediaPlacementUpdate,
    PromptExpandRequest,
    PromptPromoteRequest,
    PublishingChannelCreate,
    PublishingChannelUpdate,
    OptimizationBusinessCreate,
    OptimizationBusinessUpdate,
    OptimizationPeriodCreate,
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
from app.geo.content.attribution import (
    domains_from_publications,
    impact_windows,
    load_tenant_publications,
    match_publication_ids,
    merge_domain_lists,
    resolve_matched_publication_ids,
    summarize_snaps,
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
    normalize_citation_accuracy,
    normalize_cited_urls,
    normalize_competitors,
    normalize_sentiment,
    parse_window_bound,
    rate_delta,
    resolve_citation_format,
    split_visibility_metrics,
    visibility_mention_rate,
)
from app.geo.content.variants import (
    GeoContentError,
    build_adapt_meta,
    normalize_channels,
)
from app.models import (
    GeoAnswerSnapshot,
    GeoArticleVersion,
    GeoAsyncJob,
    GeoChannelVariant,
    GeoChannelAccount,
    GeoContentTask,
    GeoDailyMetric,
    GeoExpandRun,
    GeoFact,
    GeoMediaPlacement,
    GeoOptimizationBusiness,
    GeoOptimizationPeriod,
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
        "business_id": getattr(row, "business_id", None),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "verification": _fact_verification(row),
    }
def _fact_verification(row: GeoFact) -> dict[str, Any]:
    meta = row.meta if isinstance(row.meta, dict) else {}
    rec = meta.get("verification") if isinstance(meta.get("verification"), dict) else {}
    return {
        "verified_at": rec.get("verified_at") or meta.get("verified_at"),
        "verified_by": rec.get("verified_by") or meta.get("verified_by"),
        "excerpt": rec.get("excerpt") or meta.get("source_excerpt"),
        "excerpt_locator": rec.get("excerpt_locator") or meta.get("excerpt_locator"),
        "source_url": rec.get("source_url") or row.source_url,
        "note": rec.get("note") or meta.get("verify_note"),
        "complete": bool(
            rec.get("excerpt") and rec.get("excerpt_locator") and rec.get("verified_at")
        ),
    }


def _validate_fact_source(source_name: str, trust_level: str) -> None:
    if trust_level in ("verified", "needs_review") and not (source_name or "").strip():
        raise HTTPException(400, "事实卡必须填写来源名称")


async def _ensure_tenant_exists(session: AsyncSession, tenant_id: int) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")
    return tenant


async def _brand_context_for_prompt(
    session: AsyncSession,
    prompt: GeoPrompt,
    tenant: Tenant,
) -> tuple[str, list[str]]:
    """Business profile product name wins; do not mix another business brand."""
    from app.geo.content.brand_geo import brand_names_from_tenant
    from app.geo.content.business_profile import brand_names_for_profile, display_brand

    fallback = getattr(tenant, "name", None) or f"租户{getattr(tenant, 'id', None) or prompt.tenant_id}"
    biz = None
    unit_id = getattr(prompt, "unit_id", None)
    if unit_id:
        unit = await session.get(GeoOptimizationUnit, unit_id)
        if unit and unit.business_id:
            biz = await session.get(GeoOptimizationBusiness, unit.business_id)
    if biz is None and getattr(prompt, "business_id", None):
        biz = await session.get(GeoOptimizationBusiness, prompt.business_id)
    profile = getattr(biz, "profile", None) if biz else None
    brand = display_brand(profile, fallback=fallback)
    names = brand_names_for_profile(profile, fallback=brand)
    if not names:
        names = brand_names_from_tenant(
            name=getattr(tenant, "name", None),
            brand_terms=getattr(tenant, "brand_terms", None),
        ) or [brand]
    return brand, names


async def _brand_context_for_task(
    session: AsyncSession,
    task: GeoContentTask,
    tenant: Tenant,
) -> tuple[str, list[str]]:
    from app.geo.content.business_profile import brand_names_for_profile, display_brand

    fallback = getattr(tenant, "name", None) or f"租户{task.tenant_id}"
    biz = None
    if getattr(task, "business_id", None):
        biz = await session.get(GeoOptimizationBusiness, task.business_id)
    if biz is None:
        prompt = await session.get(GeoPrompt, task.prompt_id)
        if prompt:
            return await _brand_context_for_prompt(session, prompt, tenant)
    profile = getattr(biz, "profile", None) if biz else None
    brand = display_brand(profile, fallback=fallback)
    return brand, brand_names_for_profile(profile, fallback=brand) or [brand]


def _business_week_actions(
    *,
    gaps: list,
    in_prod: list,
    published: list[dict[str, Any]],
    cite_hit_snaps: int,
) -> list[dict[str, Any]]:
    """业务详情「本周 3 件事」：超 SLA 缺口、待审稿、该复测的已发内容。"""
    from app.config import get_settings

    now = datetime.utcnow()
    sla = int(getattr(get_settings(), "geo_gap_sla_days", 7) or 7)
    actions: list[dict[str, Any]] = []

    sla_hit = None
    for p in gaps:
        anchor = getattr(p, "updated_at", None) or getattr(p, "created_at", None) or now
        if getattr(anchor, "tzinfo", None) is not None:
            anchor = anchor.replace(tzinfo=None)
        age = max(0, (now - anchor).days)
        if age >= sla:
            sla_hit = (p, age)
            break
    if sla_hit:
        p, age = sla_hit
        actions.append(
            {
                "kind": "gap_sla",
                "title": f"超 SLA 缺口：{(p.question or '')[:48]}",
                "detail": f"已 {age} 天未补内容（SLA {sla} 天）",
                "prompt_id": p.id,
                "href": "/geo/recommend",
            }
        )
    elif gaps:
        p = gaps[0]
        actions.append(
            {
                "kind": "gap",
                "title": f"待补缺口：{(p.question or '')[:48]}",
                "detail": "品牌未被提及，可直接建任务",
                "prompt_id": p.id,
                "href": "/geo/recommend",
            }
        )

    pending = [t for t in in_prod if (getattr(t, "review_status", None) or "none") == "pending"]
    blocked = [
        t
        for t in in_prod
        if (t.status or "") in {"needs_fix", "draft", "editing", "facts_bound"}
    ]
    pick = pending[0] if pending else (blocked[0] if blocked else None)
    if pick is not None:
        actions.append(
            {
                "kind": "review" if pending else "draft",
                "title": f"{'待审稿' if pending else '推进稿件'}：{(pick.title or '')[:48]}",
                "detail": f"状态 {pick.status} · 审校 {pick.review_status or 'none'}",
                "task_id": pick.id,
                "href": f"/geo/tasks/{pick.id}",
            }
        )

    if published:
        pub = published[0]
        title = pub.get("title") or pub.get("channel") or f"任务 #{pub.get('task_id')}"
        actions.append(
            {
                "kind": "retest",
                "title": f"复测已发：{str(title)[:48]}",
                "detail": (
                    f"窗口内 {cite_hit_snaps} 条快照命中已发 URL"
                    if cite_hit_snaps
                    else "窗口内尚未命中引用，去看任务效果并复测"
                ),
                "task_id": pub.get("task_id"),
                "href": f"/geo/tasks/{pub.get('task_id')}",
            }
        )
    return actions[:3]


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


def _refresh_article_citations(
    article: GeoArticleVersion | None, facts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from app.geo.content.evidence_cite import (
        build_sentence_citations,
        strip_citation_appendix,
    )

    if article is None:
        return []
    body = strip_citation_appendix(article.body_markdown or "")
    if article.body_markdown != body:
        article.body_markdown = body
    cites = build_sentence_citations(body, facts)
    outline = dict(article.outline or {})
    outline["sentence_citations"] = cites
    article.outline = outline
    meta = dict(article.generation_meta or {})
    meta["sentence_citations"] = cites
    article.generation_meta = meta
    return cites


async def _build_rule_input(
    session: AsyncSession, task: GeoContentTask, article: GeoArticleVersion | None
) -> RuleInput:
    prompt = await _get_prompt(session, task.prompt_id, task.tenant_id)
    facts = await _task_facts(session, task.id)
    fact_dicts = _fact_dicts(facts)
    _refresh_article_citations(article, fact_dicts)
    variants = await _variants(session, task.id)
    tenant = await session.get(Tenant, task.tenant_id)
    default_author = tenant.name if tenant else None
    return RuleInput(
        question=prompt.question,
        title=(article.title if article else task.title) or "",
        body_markdown=article.body_markdown if article else "",
        outline=(article.outline if article else {}) or {},
        facts=fact_dicts,
        target_channels=list(task.target_channels or []),
        variants=[v.channel for v in variants],
        author_name=article.author_name if article else None,
        default_author=default_author,
        variant_bodies=[v.body_markdown or "" for v in variants],
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
    lint_issues = lint_draft(rule_input.body_markdown or "", facts=rule_input.facts or [])
    for vb in rule_input.variant_bodies or []:
        lint_issues.extend(lint_draft(vb or "", facts=rule_input.facts or []))
    lint = lint_summary(lint_issues)
    blocks = blocks_payload(rule_input.body_markdown or "")
    lint_ok = bool(lint.get("blocks_ready")) if isinstance(lint, dict) else None
    tenant_for_score = await _ensure_tenant_exists(session, task.tenant_id)
    score_payload = compute_geo_score(
        rule_input,
        brief=task.brief if isinstance(task.brief, dict) else {},
        lint_ok=lint_ok,
        rule_checks=checks,
        brand=(
            (await _brand_context_for_task(session, task, tenant_for_score))[0]
            if tenant_for_score
            else None
        ),
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
        "variant_polish": prev_rr.get("variant_polish"),
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
        "business_id": getattr(task, "business_id", None),
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
        "variant_polish": (task.rule_result or {}).get("variant_polish")
        if isinstance(task.rule_result, dict)
        else None,
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
                    "body_html": (v.adapt_meta or {}).get("body_html"),
                    "body_plain": (v.adapt_meta or {}).get("body_plain"),
                    "status": v.status,
                    "export_format": v.export_format or "html",
                    "has_table": bool((v.adapt_meta or {}).get("has_table")),
                    "quality": (v.adapt_meta or {}).get("quality"),
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
            "variant_polish": await _latest_variant_polish(session, task),
        }
    )
    return payload


async def _latest_variant_polish(session: AsyncSession, task: GeoContentTask) -> dict | None:
    job = await session.scalar(
        select(GeoAsyncJob)
        .where(
            GeoAsyncJob.tenant_id == task.tenant_id,
            GeoAsyncJob.kind == "create_variants",
            GeoAsyncJob.ref_type == "content_task",
            GeoAsyncJob.ref_id == task.id,
        )
        .order_by(GeoAsyncJob.id.desc())
        .limit(1)
    )
    if job is None or not job.result_meta:
        return None
    polish = job.result_meta.get("variant_polish")
    return polish if isinstance(polish, dict) else None


async def _channel_options_payload(session: AsyncSession, tenant_id: int) -> list[dict]:
    rows = await _ensure_default_publishing_channels(session, tenant_id)
    return channel_options_from_registry(registry_row_dicts(rows))


@router.get("/content-health")
async def content_health(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Module health + schema readiness (migration 0054 hierarchy / daily metrics)."""
    from sqlalchemy import text

    async def _probe(sql: str) -> tuple[str, str | None]:
        try:
            await session.execute(text(sql))
            return "ok", None
        except Exception as exc:  # noqa: BLE001
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return "missing", str(exc)[:160]

    checks: dict[str, Any] = {}
    status = "ok"
    for table, key in (
        ("geo_optimization_businesses", "optimization_businesses"),
        ("geo_optimization_units", "optimization_units"),
        ("geo_daily_metrics", "daily_metrics"),
    ):
        st, err = await _probe(f"SELECT 1 FROM {table} LIMIT 1")
        checks[key] = st
        if err:
            checks[f"{key}_error"] = err
            status = "degraded"
    st, err = await _probe("SELECT unit_id FROM geo_prompts LIMIT 1")
    checks["prompts_unit_id"] = st
    if err:
        checks["prompts_unit_id_error"] = err
        status = "degraded"

    hint = None
    if status != "ok":
        hint = "请在仓库根执行: alembic upgrade head （需 revision 0054_geo_opt_hierarchy）"
    return {
        "module": "geo-content",
        "status": status,
        "schema": checks,
        "hint": hint,
        "display_names": "vue",
        "static_workbench": "compat",
    }


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
    from app.geo.content.business_profile import normalize_profile

    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "description": row.description,
        "profile": normalize_profile(getattr(row, "profile", None)),
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
    from app.geo.content.business_profile import normalize_profile

    row = GeoOptimizationBusiness(
        tenant_id=req.tenant_id,
        name=name,
        description=req.description,
        profile=normalize_profile(req.profile) if req.profile else None,
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
    if "profile" in data:
        from app.geo.content.business_profile import normalize_profile

        data["profile"] = normalize_profile(data.get("profile"))
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


@router.get("/ops-alerts")
async def geo_ops_alerts(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """运营告警：巡检失败、配额、token 过期、OAuth 未授权、推送配置缺口等。"""
    from app.geo.content.ops_alerts import build_ops_alerts

    ctx.ensure_tenant(tenant_id)
    return await build_ops_alerts(session, tenant_id=tenant_id)


@router.get("/gap-workbench")
async def gap_workbench(
    tenant_id: int = Query(...),
    business_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
    sla_days: int | None = Query(None, ge=1, le=90, description="缺口 SLA 天数，默认读配置"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """缺口工作台：聚合 brand_missing 意图词，按优先级/业务排序，驱动内容生产。"""
    from app.config import get_settings

    ctx.ensure_tenant(tenant_id)
    cfg_sla = int(getattr(get_settings(), "geo_gap_sla_days", 7) or 7)
    sla = int(sla_days) if sla_days is not None else max(1, min(cfg_sla, 90))
    now = datetime.utcnow()
    prompts = list(
        await session.scalars(
            select(GeoPrompt)
            .where(
                GeoPrompt.tenant_id == tenant_id,
                GeoPrompt.status == "active",
            )
            .order_by(GeoPrompt.priority.desc(), GeoPrompt.id.desc())
        )
    )
    missing = [p for p in prompts if "brand_missing" in (p.tags or [])]

    unit_ids = {p.unit_id for p in missing if p.unit_id}
    units: dict[int, GeoOptimizationUnit] = {}
    if unit_ids:
        for u in await session.scalars(
            select(GeoOptimizationUnit).where(
                GeoOptimizationUnit.tenant_id == tenant_id,
                GeoOptimizationUnit.id.in_(list(unit_ids)),
            )
        ):
            units[u.id] = u
    biz_ids = {u.business_id for u in units.values() if u.business_id}
    if business_id is not None:
        biz_ids.add(business_id)
    businesses: dict[int, GeoOptimizationBusiness] = {}
    if biz_ids:
        for b in await session.scalars(
            select(GeoOptimizationBusiness).where(
                GeoOptimizationBusiness.tenant_id == tenant_id,
                GeoOptimizationBusiness.id.in_(list(biz_ids)),
            )
        ):
            businesses[b.id] = b

    # Open tasks per prompt (not archived/published complete)
    open_tasks = list(
        await session.scalars(
            select(GeoContentTask).where(
                GeoContentTask.tenant_id == tenant_id,
                GeoContentTask.status.notin_(["archived"]),
            )
        )
    )
    tasks_by_prompt: dict[int, list[GeoContentTask]] = {}
    for t in open_tasks:
        tasks_by_prompt.setdefault(t.prompt_id, []).append(t)

    items: list[dict[str, Any]] = []
    for p in missing:
        unit = units.get(p.unit_id) if p.unit_id else None
        bid = unit.business_id if unit else None
        if business_id is not None and bid != business_id:
            continue
        biz = businesses.get(bid) if bid else None
        related = tasks_by_prompt.get(p.id) or []
        open_related = [
            t
            for t in related
            if t.status not in {"published", "archived"}
        ]
        published_related = [t for t in related if t.status == "published"]
        needs_task = not open_related and not published_related
        anchor = p.updated_at or p.created_at or now
        if getattr(anchor, "tzinfo", None) is not None:
            anchor = anchor.replace(tzinfo=None)
        age_days = max(0, (now - anchor).days)
        sla_breached = bool(needs_task and age_days >= sla)
        items.append(
            {
                "prompt_id": p.id,
                "question": p.question,
                "priority": int(p.priority or 0),
                "tags": list(p.tags or []),
                "question_group": p.question_group,
                "unit_id": p.unit_id,
                "unit_name": unit.name if unit else None,
                "business_id": bid,
                "business_name": biz.name if biz else None,
                "has_open_task": bool(open_related),
                "open_task_count": len(open_related),
                "open_task_ids": [t.id for t in open_related[:5]],
                "published_task_count": len(published_related),
                "last_task_id": p.last_task_id,
                "needs_task": needs_task,
                "age_days": age_days,
                "sla_days": sla,
                "sla_breached": sla_breached,
                "updated_at": _iso(p.updated_at),
            }
        )
    # Sort: SLA breach first, needs_task, priority, no business last
    items.sort(
        key=lambda x: (
            0 if x.get("sla_breached") else 1,
            0 if x["needs_task"] else (1 if x["has_open_task"] else 2),
            -int(x["priority"] or 0),
            0 if x["business_id"] else 1,
            -int(x["prompt_id"]),
        )
    )
    items = items[:limit]

    by_business: dict[str, dict[str, Any]] = {}
    for it in items:
        key = str(it["business_id"] or "unclassified")
        bucket = by_business.setdefault(
            key,
            {
                "business_id": it["business_id"],
                "business_name": it["business_name"] or "未分类",
                "gap_count": 0,
                "needs_task_count": 0,
                "sla_breached_count": 0,
            },
        )
        bucket["gap_count"] += 1
        if it["needs_task"]:
            bucket["needs_task_count"] += 1
        if it.get("sla_breached"):
            bucket["sla_breached_count"] += 1

    return {
        "tenant_id": tenant_id,
        "sla_days": sla,
        "total": len(items),
        "needs_task_total": sum(1 for i in items if i["needs_task"]),
        "sla_breached_total": sum(1 for i in items if i.get("sla_breached")),
        "has_open_task_total": sum(1 for i in items if i["has_open_task"]),
        "by_business": list(by_business.values()),
        "items": items,
    }


@router.post("/gap-workbench/create-tasks")
async def gap_workbench_create_tasks(
    req: GapCreateTasksRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """批量从 brand_missing 意图词创建内容任务（已有未完结任务则跳过）。"""
    from app.geo.content.brief import normalize_brief

    tenant_id = req.tenant_id
    ctx.ensure_tenant(tenant_id)
    await _ensure_tenant_exists(session, tenant_id)
    ids = [int(x) for x in (req.prompt_ids or []) if x][:50]
    if not ids:
        raise HTTPException(400, "请至少选择一个意图词")

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for pid in ids:
        prompt = await session.get(GeoPrompt, pid)
        if prompt is None or prompt.tenant_id != tenant_id:
            skipped.append({"prompt_id": pid, "reason": "意图词不存在"})
            continue
        existing = await session.scalar(
            select(GeoContentTask)
            .where(
                GeoContentTask.tenant_id == tenant_id,
                GeoContentTask.prompt_id == pid,
                GeoContentTask.status.notin_(["archived", "published"]),
            )
            .order_by(GeoContentTask.id.desc())
            .limit(1)
        )
        if existing is not None:
            skipped.append(
                {
                    "prompt_id": pid,
                    "reason": "已有未完结任务",
                    "task_id": existing.id,
                }
            )
            continue
        business_id = await _resolve_task_business_id(session, prompt)
        task = GeoContentTask(
            tenant_id=tenant_id,
            prompt_id=prompt.id,
            business_id=business_id,
            title=(prompt.question or "内容任务")[:300],
            status="draft",
            target_channels=["website", "wechat", "zhihu"],
            owner_user_id=ctx.user_id,
            pipeline_step="opportunity",
            brief=normalize_brief({}),
        )
        session.add(task)
        await session.flush()
        prompt.last_task_id = task.id
        await _sync_task_pipeline(session, task)
        created.append({"prompt_id": pid, "task_id": task.id, "title": task.title})
    await session.commit()
    return {
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
    }


def _period_payload(row: GeoOptimizationPeriod) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "business_id": row.business_id,
        "starts_at": _iso(row.starts_at),
        "ends_at": _iso(row.ends_at),
        "status": row.status or "planned",
        "goal_note": row.goal_note,
        "baseline_meta": row.baseline_meta or {},
        "result_meta": row.result_meta or {},
        "publication_ids": list(row.publication_ids or []),
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _parse_period_dt(raw: str | None, *, label: str) -> datetime:
    if not raw or not str(raw).strip():
        raise HTTPException(400, f"{label} 必填")
    try:
        return parse_window_bound(str(raw).strip(), label=label)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/optimization-periods")
async def list_optimization_periods(
    tenant_id: int = Query(...),
    business_id: int | None = Query(None),
    status: str | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoOptimizationPeriod).where(
        GeoOptimizationPeriod.tenant_id == tenant_id
    )
    if business_id is not None:
        stmt = stmt.where(GeoOptimizationPeriod.business_id == business_id)
    if status:
        stmt = stmt.where(GeoOptimizationPeriod.status == status)
    stmt = stmt.order_by(GeoOptimizationPeriod.starts_at.desc(), GeoOptimizationPeriod.id.desc())
    rows = list(await session.scalars(stmt))
    return {"items": [_period_payload(r) for r in rows]}


@router.post("/optimization-periods")
async def create_optimization_period(
    req: OptimizationPeriodCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """创建优化期次；可选抓取期初基线快照 meta。"""
    tenant_id = req.tenant_id
    ctx.ensure_tenant(tenant_id)
    await _ensure_tenant_exists(session, tenant_id)
    s_at = _parse_period_dt(req.starts_at, label="starts_at")
    e_at = _parse_period_dt(req.ends_at, label="ends_at")
    if s_at > e_at:
        raise HTTPException(400, "starts_at 不得晚于 ends_at")
    if req.business_id is not None:
        biz = await session.scalar(
            select(GeoOptimizationBusiness).where(
                GeoOptimizationBusiness.id == req.business_id,
                GeoOptimizationBusiness.tenant_id == tenant_id,
            )
        )
        if not biz:
            raise HTTPException(400, "目标优化业务不存在")

    baseline: dict[str, Any] | None = None
    if req.capture_baseline:
        try:
            from datetime import timedelta

            from app.geo.content.metric_service import compute_metrics

            b_from = s_at - timedelta(days=14)
            own_domains = await _own_domains_for_tenant(session, tenant_id)
            metrics_b = await compute_metrics(
                session,
                tenant_id,
                start=b_from.date() if hasattr(b_from, "date") else b_from,
                end=s_at.date() if hasattr(s_at, "date") else s_at,
                own_domains=own_domains,
            )
            metrics = metrics_b.to_dict()
            baseline = {
                "captured_at": _iso(datetime.utcnow()),
                "window_from": _iso(b_from),
                "window_to": _iso(s_at),
                "metrics": metrics,
                "sample_count": metrics.get("snapshots_total"),
            }
        except Exception:  # noqa: BLE001
            baseline = {"error": "baseline_capture_failed"}

    row = GeoOptimizationPeriod(
        tenant_id=tenant_id,
        name=req.name.strip()[:160],
        business_id=req.business_id,
        starts_at=s_at,
        ends_at=e_at,
        status="active" if s_at <= datetime.utcnow() <= e_at else "planned",
        goal_note=(req.goal_note or "").strip() or None,
        baseline_meta=baseline,
        result_meta=None,
        publication_ids=[],
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _period_payload(row)


@router.get("/optimization-periods/{period_id}")
async def get_optimization_period(
    period_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoOptimizationPeriod, period_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "优化期次不存在")
    payload = _period_payload(row)

    # Prefer stored publication_ids (especially after close); fall back to live scan
    stored_ids = list(row.publication_ids or [])
    in_period: list[dict[str, Any]] = []
    if stored_ids:
        pub_rows = list(
            await session.scalars(
                select(GeoPublication).where(GeoPublication.id.in_(stored_ids))
            )
        )
        by_id = {int(p.id): p for p in pub_rows}
        for pid in stored_ids:
            p = by_id.get(int(pid))
            if not p:
                continue
            # resolve task_id via variant
            task_id = None
            v = await session.get(GeoChannelVariant, p.variant_id)
            if v:
                task_id = v.task_id
            in_period.append(
                {
                    "id": p.id,
                    "task_id": task_id,
                    "channel": p.channel,
                    "published_url": p.published_url,
                    "published_at": _iso(p.published_at),
                    "from_store": True,
                }
            )
    else:
        pubs = await load_tenant_publications(session, tenant_id)
        for pr in pubs:
            pa = pr.published_at
            if pa is None:
                continue
            if getattr(pa, "tzinfo", None) is not None:
                pa = pa.replace(tzinfo=None)
            if row.starts_at <= pa <= row.ends_at:
                if row.business_id is not None:
                    task = await session.get(GeoContentTask, pr.task_id)
                    if task is None or task.business_id != row.business_id:
                        continue
                in_period.append(
                    {
                        "id": pr.id,
                        "task_id": pr.task_id,
                        "channel": pr.channel,
                        "published_url": pr.published_url,
                        "published_at": _iso(pr.published_at),
                        "from_store": False,
                    }
                )
    payload["publications_in_period"] = in_period
    payload["publication_count"] = len(in_period)
    payload["deliverable_pack"] = (row.result_meta or {}).get("deliverable_pack")
    return payload


@router.post("/optimization-periods/{period_id}/close")
async def close_optimization_period(
    period_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """期末复测：compute_metrics 写 result_meta、固化交付 pack、标记 closed。"""
    from app.geo.content.metric_service import compute_metrics

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoOptimizationPeriod, period_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "优化期次不存在")
    if row.status == "closed":
        raise HTTPException(400, "期次已关闭，不可重复关闭或改窗口")

    s_at, e_at = row.starts_at, row.ends_at
    if getattr(s_at, "tzinfo", None):
        s_at = s_at.replace(tzinfo=None)
    if getattr(e_at, "tzinfo", None):
        e_at = e_at.replace(tzinfo=None)
    start_d = s_at.date() if hasattr(s_at, "date") else s_at
    end_d = e_at.date() if hasattr(e_at, "date") else e_at

    own_domains = await _own_domains_for_tenant(session, tenant_id)
    metrics_bundle = await compute_metrics(
        session,
        tenant_id,
        start=start_d,
        end=end_d,
        own_domains=own_domains,
    )
    metrics = metrics_bundle.to_dict()

    # Prefer publications tagged with this period_id, else date window
    pub_rows = list(
        await session.scalars(
            select(GeoPublication).where(GeoPublication.period_id == period_id)
        )
    )
    pub_ids = [int(p.id) for p in pub_rows]
    if not pub_ids:
        pubs = await load_tenant_publications(session, tenant_id)
        for pr in pubs:
            pa = pr.published_at
            if pa is None:
                continue
            if getattr(pa, "tzinfo", None) is not None:
                pa = pa.replace(tzinfo=None)
            if s_at <= pa <= e_at:
                if row.business_id is not None:
                    task = await session.get(GeoContentTask, pr.task_id)
                    if task is None or task.business_id != row.business_id:
                        continue
                pub_ids.append(pr.id)

    tasks_in = list(
        await session.scalars(
            select(GeoContentTask).where(
                GeoContentTask.tenant_id == tenant_id,
                GeoContentTask.period_id == period_id,
            )
        )
    )
    prompt_ids = {int(t.prompt_id) for t in tasks_in if t.prompt_id}

    baseline_m = (row.baseline_meta or {}).get("metrics") or {}
    delta = {
        "visibility_mention_rate": rate_delta(
            baseline_m.get("visibility_mention_rate")
            or baseline_m.get("brand_mention_rate"),
            metrics.get("visibility_mention_rate"),
        ),
        "own_domain_cite_rate": rate_delta(
            baseline_m.get("own_domain_cite_rate"),
            metrics.get("own_domain_cite_rate"),
        ),
        "probe_recognition_rate": rate_delta(
            baseline_m.get("probe_recognition_rate")
            or baseline_m.get("brand_probe_recognition_rate"),
            metrics.get("probe_recognition_rate"),
        ),
    }

    # Frozen deliverable snapshot (stable after close)
    deliverable_pack = {
        "kind": "geo_period_deliverable_v1",
        "period_id": period_id,
        "period_name": row.name,
        "frozen_at": _iso(datetime.utcnow()),
        "window": {
            "starts_at": _iso(s_at),
            "ends_at": _iso(e_at),
            "timezone": "Asia/Shanghai",
        },
        "headline": {
            "published_count": len(pub_ids),
            "tasks_in_period": len(tasks_in),
            "prompts_covered": len(prompt_ids),
            "mention_rate_before": baseline_m.get("visibility_mention_rate")
            or baseline_m.get("brand_mention_rate"),
            "mention_rate_after": metrics.get("brand_mention_rate"),
            "mention_rate_delta": delta.get("visibility_mention_rate"),
        },
        "metrics": metrics,
        "baseline_metrics": baseline_m,
        "delta_vs_baseline": delta,
        "sample_composition": metrics.get("sample_composition"),
        "methodology_note": (
            "关闭时固化；后续改窗口不会影响本快照。"
            "对照为期前 14 天基线 vs 期内统一口径指标。"
        ),
    }

    row.result_meta = {
        "closed_at": _iso(datetime.utcnow()),
        "metrics": metrics,
        "sample_count": metrics.get("snapshots_total"),
        "delta_vs_baseline": delta,
        "deliverable_pack": deliverable_pack,
        "tasks_in_period": len(tasks_in),
        "prompts_covered": len(prompt_ids),
    }
    row.publication_ids = pub_ids
    row.status = "closed"
    await session.commit()
    await session.refresh(row)
    out = _period_payload(row)
    out["deliverable_pack"] = deliverable_pack
    return out


@router.get("/weekly-insights")
async def geo_weekly_insights(
    tenant_id: int = Query(...),
    scope_key: str = Query("t"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """近 7 天 vs 前 7 天盯盘周洞察（日指标 + 话题覆盖）。"""
    from app.geo.content.weekly_insights import build_weekly_insights

    ctx.ensure_tenant(tenant_id)
    return await build_weekly_insights(
        session, tenant_id=tenant_id, scope_key=scope_key or "t"
    )


@router.get("/topic-heat")
async def geo_topic_heat(
    tenant_id: int = Query(...),
    days: int = Query(14, ge=3, le=90),
    group_by: str = Query("prompt", description="prompt | group"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """意图词覆盖热度（topic×engine×日去重）+ 监测活跃度；外部动态见 /ai-trends。"""
    from app.geo.content.topic_heat import build_topic_heat

    ctx.ensure_tenant(tenant_id)
    gb = group_by if group_by in ("prompt", "group") else "prompt"
    return await build_topic_heat(
        session, tenant_id=tenant_id, days=days, group_by=gb
    )


@router.get("/ai-trends")
async def geo_ai_trends(
    tenant_id: int = Query(...),
    region: str | None = Query(None, description="cn | global | 空=全部"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """国内外 AI 动态目录 + 对本租户 GEO 策略的影响建议。"""
    from app.geo.content.ai_trends import build_ai_trends_payload

    ctx.ensure_tenant(tenant_id)
    reg = region if region in ("cn", "global") else None
    return await build_ai_trends_payload(session, tenant_id=tenant_id, region=reg)


@router.get("/daily-metrics")
async def list_daily_metrics(
    tenant_id: int = Query(...),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    business_id: int | None = Query(None),
    unit_id: int | None = Query(None),
    prompt_id: int | None = Query(None),
    engine: str | None = Query(None, description="按引擎切片，如 deepseek；空则默认不含 @引擎 行"),
    include_engines: bool = Query(False, description="为 true 时返回含引擎切片的行"),
    scope_key: str | None = Query(None),
    scope_level: str | None = Query(
        None,
        description="tenant | business | unit | prompt；与 scope_key 二选一优先 scope_key",
    ),
    format: str | None = Query(None, description="json（默认）或 csv"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    """按天汇总指标（品牌提及率 / 点名认知 / AI 引用次数）。

    切片：
    - scope_key=t / scope_level=tenant：租户全量
    - scope_key=b{id} 或 business_id + scope_level=business：优化业务
    - scope_key=u{id} 或 unit_id + scope_level=unit：优化单元
    - scope_key=p{id} 或 prompt_id + scope_level=prompt：优化意图词
    - scope_key=t@deepseek 或 engine=deepseek：按模型切片

    统计口径见 citation_stat_note。
    """
    from app.geo.content.daily_metrics import (
        CITATION_STAT_NOTE,
        METRIC_LABELS,
        metric_row_payload,
        normalize_engine_key,
        scope_business,
        scope_prompt,
        scope_tenant,
        scope_unit,
        scope_with_engine,
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
        if prompt_id is not None and (scope_level in (None, "prompt")):
            resolved_scope = scope_prompt(prompt_id)
        elif unit_id is not None and (scope_level in (None, "unit")):
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
        elif scope_level == "prompt":
            stmt = stmt.where(GeoDailyMetric.scope_key.like("p%"))

    eng = normalize_engine_key(engine) if engine else None
    if eng and resolved_scope and "@" not in resolved_scope:
        resolved_scope = scope_with_engine(resolved_scope, eng)
        eng = None

    if resolved_scope:
        stmt = stmt.where(GeoDailyMetric.scope_key == resolved_scope)
    elif business_id is not None and scope_level not in ("unit", "business", "prompt"):
        stmt = stmt.where(GeoDailyMetric.scope_key == scope_business(business_id))
    elif unit_id is not None and not resolved_scope:
        stmt = stmt.where(GeoDailyMetric.scope_key == scope_unit(unit_id))

    if eng:
        stmt = stmt.where(GeoDailyMetric.engine == eng)
    elif not include_engines and (not resolved_scope or "@" not in (resolved_scope or "")):
        stmt = stmt.where(~GeoDailyMetric.scope_key.contains("@"))

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

    fmt = (format or "json").strip().lower()
    if fmt == "csv":
        import csv
        import io

        buf = io.StringIO()
        fields = [
            "metric_date",
            "scope_key",
            "scope_level",
            "scope_label",
            "business_id",
            "business_name",
            "unit_id",
            "unit_name",
            "brand_mention_rate",
            "brand_probe_recognition_rate",
            "top1_rate",
            "citation_count",
            "distinct_cited_domains",
            "snapshots_visibility",
            "snapshots_probe",
        ]
        w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for it in items:
            row = {k: it.get(k) for k in fields}
            w.writerow(row)
        filename = f"geo-daily-metrics-{tenant_id}.csv"
        return PlainTextResponse(
            buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return {
        "items": items,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "metric_labels": METRIC_LABELS,
        "citation_stat_note": CITATION_STAT_NOTE,
        "scope_levels": {
            "tenant": "租户全量 · scope_key=t",
            "business": "优化业务 · scope_key=b{id}",
            "unit": "优化单元 · scope_key=u{id}",
            "prompt": "优化意图词 · scope_key=p{id}",
            "engine": "引擎切片 · scope_key={base}@{engine}",
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
    # Enrich roots from verified facts + website publishing channels
    fact_products: list[str] = list(req.products or [])
    website_hints: list[str] = []
    if req.seed_from_tenant:
        facts = list(
            await session.scalars(
                select(GeoFact)
                .where(
                    GeoFact.tenant_id == req.tenant_id,
                    GeoFact.status == "active",
                    GeoFact.trust_level.in_(["verified", "needs_review"]),
                )
                .order_by(GeoFact.updated_at.desc(), GeoFact.id.desc())
                .limit(12)
            )
        )
        for f in facts:
            title = str(f.title or "").strip()
            if title and title not in fact_products:
                fact_products.append(title)
            src = extract_cited_domain(f.source_url)
            if src and src not in website_hints:
                website_hints.append(src)
        for ch in await session.scalars(
            select(GeoPublishingChannel).where(
                GeoPublishingChannel.tenant_id == req.tenant_id,
                GeoPublishingChannel.channel_type.in_(["website", "docs"]),
                GeoPublishingChannel.enabled.is_(True),
            )
        ):
            d = extract_cited_domain(ch.base_url)
            if d and d not in website_hints:
                website_hints.append(d)
            # Use channel name as soft category root
            nm = str(getattr(ch, "name", None) or "").strip()
            if nm and nm not in fact_products:
                fact_products.append(nm)

    roots = build_roots(
        brand_names=brand_names if req.seed_from_tenant else None,
        industry=getattr(tenant, "industry", None) if req.seed_from_tenant else None,
        competitors=req.competitors,
        products=fact_products[:8],
        market=req.market,
        explicit_roots=explicit,
    )
    if not roots:
        raise HTTPException(
            400,
            "缺少词根：请填写 roots，或在租户配置品牌名/行业，或传入 competitors；也可先录入事实库/官网渠道",
        )

    existing_rows = (
        await session.scalars(
            select(GeoPrompt.question).where(
                GeoPrompt.tenant_id == req.tenant_id,
                GeoPrompt.status == "active",
            )
        )
    ).all()
    context_tokens: list[str] = list(fact_products)
    context_tokens.extend(brand_names)
    industry = getattr(tenant, "industry", None)
    if industry:
        context_tokens.append(str(industry))
    result = await expand_candidates(
        roots=roots,
        existing_questions=set(existing_rows),
        max_terms=req.max_terms,
        throttle_s=0.05,
        context_tokens=context_tokens,
    )
    for it in result.get("items") or []:
        it["is_brand_probe"] = resolve_is_brand_probe(
            question=str(it.get("question") or it.get("term") or ""),
            brand_names=brand_names,
            question_group=it.get("question_group"),
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
    result["seed_hints"] = {
        "fact_titles": fact_products[:8],
        "website_domains": website_hints[:8],
        "note": "已用事实库标题与官网/文档渠道域名扩充词根（非抓取公众号正文）",
    }
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
    unit_ids = {item.unit_id for item in req.items if item.unit_id is not None}
    if unit_ids:
        valid_unit_ids = set(
            (
                await session.scalars(
                    select(GeoOptimizationUnit.id).where(
                        GeoOptimizationUnit.tenant_id == req.tenant_id,
                        GeoOptimizationUnit.id.in_(unit_ids),
                    )
                )
            ).all()
        )
        if valid_unit_ids != unit_ids:
            raise HTTPException(status_code=400, detail="优化单元不存在")
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
            unit_id=item.unit_id,
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
    cited = list(row.cited_urls or [])
    fmt = getattr(row, "citation_format", None) or "unknown"
    if fmt == "unknown":
        fmt = resolve_citation_format(
            None,
            cited_urls=cited,
            raw_text=row.raw_text,
            mentions_brand=bool(row.mentions_brand),
        )
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "prompt_id": row.prompt_id,
        "prompt_question": prompt_question,
        "engine": row.engine,
        "raw_text": row.raw_text,
        "captured_at": _iso(row.captured_at),
        "mentions_brand": bool(row.mentions_brand),
        "cited_urls": cited,
        "competitors": row.competitors or [],
        "brand_position": row.brand_position or "unknown",
        "sentiment": row.sentiment or "unknown",
        "citation_format": fmt,
        "citation_accuracy": getattr(row, "citation_accuracy", None) or "unknown",
        "patrol_run_id": getattr(row, "patrol_run_id", None),
        "sample_mode": getattr(row, "sample_mode", None) or "manual",
        "simulated": bool(getattr(row, "simulated", False)),
        "matched_publication_ids": list(
            getattr(row, "matched_publication_ids", None) or []
        ),
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
    patrol_run_id: int | None = Query(None, description="按巡检 run 追溯快照"),
    simulated: bool | None = Query(None, description="过滤模拟/非模拟"),
    sample_mode: str | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoAnswerSnapshot).where(GeoAnswerSnapshot.tenant_id == tenant_id)
    if prompt_id is not None:
        stmt = stmt.where(GeoAnswerSnapshot.prompt_id == prompt_id)
    if engine:
        stmt = stmt.where(GeoAnswerSnapshot.engine == engine)
    if patrol_run_id is not None:
        stmt = stmt.where(GeoAnswerSnapshot.patrol_run_id == patrol_run_id)
    if simulated is not None:
        stmt = stmt.where(GeoAnswerSnapshot.simulated.is_(bool(simulated)))
    if sample_mode:
        stmt = stmt.where(GeoAnswerSnapshot.sample_mode == sample_mode)
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
    from app.geo.content.metric_service import composition_of

    return {
        "items": [
            _snapshot_payload(r, prompt_question=questions.get(r.prompt_id)) for r in rows
        ],
        "sample_composition": composition_of(rows).to_dict(),
        "patrol_run_id": patrol_run_id,
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
    citation_format = resolve_citation_format(
        req.citation_format,
        cited_urls=cited_urls,
        raw_text=req.raw_text,
        mentions_brand=bool(req.mentions_brand),
    )
    matched_ids = await resolve_matched_publication_ids(
        session, tenant_id=req.tenant_id, cited_urls=cited_urls
    )
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
        citation_format=citation_format,
        citation_accuracy=normalize_citation_accuracy(req.citation_accuracy),
        patrol_run_id=None,
        sample_mode="manual",
        simulated=False,
        matched_publication_ids=matched_ids or None,
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
    if req.citation_accuracy is not None:
        row.citation_accuracy = normalize_citation_accuracy(req.citation_accuracy)
    if req.note is not None:
        row.note = req.note
    if req.mentions_brand is not None:
        row.mentions_brand = bool(req.mentions_brand)
        await _apply_brand_mention_side_effect(
            session, prompt, mentions_brand=bool(req.mentions_brand)
        )
    # Re-resolve format when urls/text/mention/format change
    if (
        req.citation_format is not None
        or req.cited_urls is not None
        or req.raw_text is not None
        or req.mentions_brand is not None
    ):
        row.citation_format = resolve_citation_format(
            req.citation_format if req.citation_format is not None else row.citation_format,
            cited_urls=list(row.cited_urls or []),
            raw_text=row.raw_text,
            mentions_brand=bool(row.mentions_brand),
        )
    # W4: raw_text-only PATCH must re-extract URLs and recompute attribution
    if req.raw_text is not None and req.cited_urls is None:
        extracted = extract_cited_urls_from_text(row.raw_text)
        if extracted:
            row.cited_urls = extracted
    if req.cited_urls is not None or req.raw_text is not None:
        row.matched_publication_ids = (
            await resolve_matched_publication_ids(
                session, tenant_id=tenant_id, cited_urls=list(row.cited_urls or [])
            )
            or None
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
                    "urls": set(),
                    "platform_keys": set(),
                    "latest_captured_at": None,
                    "sample_prompt_question": None,
                },
            )
            bucket["mention_count"] += 1
            bucket["prompt_ids"].add(row.prompt_id)
            bucket["engines"].add(row.engine)
            for url in row.cited_urls or []:
                u = str(url or "").strip()
                if not u:
                    continue
                bucket["urls"].add(u)
                domain = extract_cited_domain(u)
                bp = match_blueprint_for_domain(domain or "")
                bucket["platform_keys"].add(bp["channel_key"] if bp else "other")
            if bucket["latest_captured_at"] is None:
                bucket["latest_captured_at"] = _iso(row.captured_at)
                bucket["sample_prompt_question"] = questions.get(row.prompt_id)
    items = []
    all_platforms: set[str] = set()
    for bucket in buckets.values():
        pkeys = sorted(bucket["platform_keys"])
        all_platforms.update(pkeys)
        items.append(
            {
                "name": bucket["name"],
                "mention_count": bucket["mention_count"],
                "prompt_count": len(bucket["prompt_ids"]),
                "engines": sorted(bucket["engines"]),
                "latest_captured_at": bucket["latest_captured_at"],
                "sample_prompt_question": bucket["sample_prompt_question"],
                "source_count": len(bucket["urls"]),
                "platform_count": len(bucket["platform_keys"]),
                "platform_keys": pkeys,
            }
        )
    items.sort(key=lambda x: (-x["mention_count"], x["name"]))

    # Unique cited URLs on competitor-tagged snapshots in last 7 days
    cutoff = datetime.utcnow() - timedelta(days=7)
    urls_7d: set[str] = set()
    for row in rows:
        captured = row.captured_at
        if captured is not None and captured.replace(tzinfo=None) < cutoff:
            continue
        if not (row.competitors or []):
            continue
        for url in row.cited_urls or []:
            u = str(url or "").strip()
            if u:
                urls_7d.add(u)

    from app.geo.content.metric_service import composition_of

    sample = composition_of(rows).to_dict()
    return {
        "items": items,
        "summary": {
            "competitor_count": len(items),
            "platform_count": len(all_platforms),
            "sources_last_7d": len(urls_7d),
            "sample_composition": sample,
            "suitable_for_client": bool(sample.get("suitable_for_client")),
            "verdict": sample.get("verdict"),
            "verdict_reason": sample.get("verdict_reason"),
        },
    }


@router.get("/competitor-insights/daily")
async def competitor_insights_daily(
    tenant_id: int = Query(...),
    days: int = Query(14, ge=3, le=90),
    scope_level: str = Query("tenant", description="tenant|business|unit|prompt"),
    business_id: int | None = Query(None),
    unit_id: int | None = Query(None),
    prompt_id: int | None = Query(None),
    engine: str | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """竞品提及日序列：读 daily_metrics（业务/单元/意图词 × 天 × 引擎）。"""
    from app.geo.content.daily_metrics import (
        metric_row_payload,
        normalize_engine_key,
        scope_business,
        scope_prompt,
        scope_tenant,
        scope_unit,
        scope_with_engine,
    )
    from app.models import GeoDailyMetric

    ctx.ensure_tenant(tenant_id)
    level = (scope_level or "tenant").strip().lower()
    if level == "prompt" and prompt_id:
        base = scope_prompt(int(prompt_id))
    elif level == "unit" and unit_id:
        base = scope_unit(int(unit_id))
    elif level == "business" and business_id:
        base = scope_business(int(business_id))
    else:
        base = scope_tenant()
        level = "tenant"
    sk = scope_with_engine(base, engine) if engine else base

    from app.geo.content.time_windows import shanghai_today

    end = shanghai_today()
    start = end - timedelta(days=days - 1)
    rows = list(
        await session.scalars(
            select(GeoDailyMetric)
            .where(
                GeoDailyMetric.tenant_id == tenant_id,
                GeoDailyMetric.scope_key == sk,
                GeoDailyMetric.metric_date >= start,
                GeoDailyMetric.metric_date <= end,
            )
            .order_by(GeoDailyMetric.metric_date.asc())
        )
    )
    items = [metric_row_payload(r) for r in rows]
    # Flatten top competitors across window for table
    name_totals: dict[str, int] = {}
    for r in rows:
        cm = getattr(r, "competitor_mentions", None) or {}
        if isinstance(cm, dict):
            for name, meta in cm.items():
                n = int((meta or {}).get("mentions") or 0) if isinstance(meta, dict) else int(meta or 0)
                name_totals[name] = name_totals.get(name, 0) + n
    top_names = sorted(name_totals.items(), key=lambda x: (-x[1], x[0]))[:20]
    return {
        "scope_key": sk,
        "scope_level": level,
        "engine": normalize_engine_key(engine) if engine else None,
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "items": items,
        "competitors": [{"name": n, "mentions": m} for n, m in top_names],
        "note": "数据来自 geo_daily_metrics；无行时请先在概览/业务页「重算」日指标。",
    }


@router.get("/competitor-insights/compare")
async def competitor_insights_compare(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Same question set: brand vs competitor mention / recommended position."""
    from app.geo.content.competitor_trace import build_competitor_compare

    ctx.ensure_tenant(tenant_id)
    rows = list(
        await session.scalars(
            select(GeoAnswerSnapshot)
            .where(GeoAnswerSnapshot.tenant_id == tenant_id)
            .order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
        )
    )
    prompt_ids = {r.prompt_id for r in rows if r.prompt_id}
    questions: dict[int, str] = {}
    if prompt_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(list(prompt_ids))
            )
        ):
            questions[p.id] = p.question
    return build_competitor_compare(rows=rows, questions=questions)


@router.get("/competitor-insights/trace")
async def competitor_insights_trace(
    tenant_id: int = Query(...),
    name: str = Query(..., min_length=1, max_length=120),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Reverse-trace cited URLs / CN platforms for one competitor from snapshots."""
    from app.geo.content.competitor_trace import build_competitor_trace

    ctx.ensure_tenant(tenant_id)
    rows = list(
        await session.scalars(
            select(GeoAnswerSnapshot)
            .where(GeoAnswerSnapshot.tenant_id == tenant_id)
            .order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
        )
    )
    prompt_ids = {r.prompt_id for r in rows if r.prompt_id is not None}
    questions: dict[int, str] = {}
    if prompt_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(prompt_ids)
            )
        ):
            questions[p.id] = p.question
    payload = build_competitor_trace(
        competitor=name, rows=rows, questions=questions
    )
    groups: dict[int, str] = {}
    if prompt_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(prompt_ids)
            )
        ):
            if p.question_group:
                groups[p.id] = p.question_group
    from app.geo.content.competitor_placements import attach_geo_reverse
    from app.geo.content.competitor_trace import snapshot_mentions_competitor

    mention_ids: list[int] = []
    for row in rows:
        if snapshot_mentions_competitor(getattr(row, "competitors", None), name):
            if row.prompt_id is not None:
                mention_ids.append(int(row.prompt_id))
    attach_geo_reverse(
        payload,
        competitor=name,
        mention_prompt_ids=mention_ids,
        questions=questions,
        question_groups=groups,
    )
    payload["tenant_id"] = tenant_id
    return payload


@router.post("/competitor-insights/web-search")
async def competitor_web_search(
    tenant_id: int = Query(...),
    name: str = Query(..., min_length=1, max_length=120),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """Public-web harvest of competitor pages. Not snapshot citations."""
    ctx.ensure_tenant(tenant_id)
    from app.geo.content.competitor_web_search import search_competitor_web

    try:
        return await search_competitor_web(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/competitor-insights/report")
async def competitor_insights_report(
    req: CompetitorTraceReportRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Manually assemble a Markdown competitor source-trace report (not persisted)."""
    from app.geo.content.competitor_trace import (
        build_competitor_report_markdown,
        build_competitor_trace,
    )

    ctx.ensure_tenant(req.tenant_id)
    rows = list(
        await session.scalars(
            select(GeoAnswerSnapshot)
            .where(GeoAnswerSnapshot.tenant_id == req.tenant_id)
            .order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
        )
    )
    prompt_ids = {r.prompt_id for r in rows if r.prompt_id is not None}
    questions: dict[int, str] = {}
    if prompt_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == req.tenant_id, GeoPrompt.id.in_(prompt_ids)
            )
        ):
            questions[p.id] = p.question
    trace = build_competitor_trace(
        competitor=req.competitor, rows=rows, questions=questions
    )
    report = build_competitor_report_markdown(
        competitor=req.competitor,
        trace=trace,
        source_urls=req.source_urls,
        platform_keys=req.platform_keys,
        note=req.note,
        insight=req.insight,
        action=req.action,
    )
    report["tenant_id"] = req.tenant_id
    report["competitor"] = req.competitor.strip()
    confirmed_ext = [str(u).strip() for u in (req.confirmed_external_urls or []) if str(u).strip()]
    if confirmed_ext:
        extra = ["", "## 人工确认的外部检索页", ""]
        for u in confirmed_ext[:12]:
            extra.append(f"- {u}")
        extra.append("")
        extra.append("这些页面来自外部检索并经人工勾选，不是本次快照 cited_urls。")
        extra.append("")
        report["markdown"] = (report.get("markdown") or "") + "\n".join(extra)
        report["external_confirmed_count"] = len(confirmed_ext)
    return report


@router.post("/competitor-insights/create-tasks")
async def competitor_insights_create_tasks(
    req: CompetitorCreateTasksRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """把竞品逆向建议落成内容任务。同意图词已有未归档任务则跳过。"""
    from app.geo.content.brief import normalize_brief
    from app.geo.content.channel_profiles import normalize_channels
    from app.geo.content.competitor_placements import _CHANNEL_TO_TASK

    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in req.items[:8]:
        try:
            prompt = await _get_prompt(session, item.prompt_id, req.tenant_id)
        except HTTPException:
            skipped.append({"prompt_id": item.prompt_id, "reason": "意图词不存在"})
            continue
        existing = await session.scalar(
            select(GeoContentTask.id).where(
                GeoContentTask.tenant_id == req.tenant_id,
                GeoContentTask.prompt_id == prompt.id,
                GeoContentTask.status.notin_(["archived", "cancelled"]),
            )
        )
        if existing:
            skipped.append(
                {
                    "prompt_id": prompt.id,
                    "task_id": existing,
                    "reason": "该意图词已有任务",
                }
            )
            continue
        channel = _CHANNEL_TO_TASK.get(item.channel_key or "official", "website")
        title = (item.title or prompt.question).strip()[:300]
        brief = normalize_brief(
            {
                "ai_question": item.sample_question or prompt.question,
                "notes": item.reason or f"竞品逆向：{req.competitor}",
                "competitors": [req.competitor],
                "must_cover": [req.competitor],
            }
        )
        business_id = await _resolve_task_business_id(session, prompt)
        period_id = await _resolve_active_period_id(
            session, tenant_id=req.tenant_id, business_id=business_id
        )
        task = GeoContentTask(
            tenant_id=req.tenant_id,
            prompt_id=prompt.id,
            business_id=business_id,
            period_id=period_id,
            title=title,
            status="draft",
            target_channels=normalize_channels([channel]),
            owner_user_id=ctx.user_id,
            pipeline_step="opportunity",
            brief=brief,
        )
        session.add(task)
        await session.flush()
        prompt.last_task_id = task.id
        created.append(
            {
                "task_id": task.id,
                "prompt_id": prompt.id,
                "title": title,
                "editor_path": f"/geo/tasks/{task.id}",
            }
        )
    await session.commit()
    return {
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
    }


@router.get("/evaluation-insights")
async def evaluation_insights(
    tenant_id: int = Query(...),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    days: int | None = Query(None, ge=1, le=90),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Sentiment / brand-position aggregates from snapshots (Wave C)."""
    from app.geo.content.time_windows import (
        default_observation_window,
        shanghai_day_bounds_utc_naive,
    )

    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoAnswerSnapshot).where(GeoAnswerSnapshot.tenant_id == tenant_id)
    if date_from or date_to or days:
        start_d, end_d = default_observation_window(days=int(days or 14))
        if date_from:
            start_d = date_from
        if date_to:
            end_d = date_to
        lo, _ = shanghai_day_bounds_utc_naive(start_d)
        _, hi = shanghai_day_bounds_utc_naive(end_d)
        stmt = stmt.where(
            GeoAnswerSnapshot.captured_at >= lo,
            GeoAnswerSnapshot.captured_at < hi,
        )
    rows = list(
        await session.scalars(
            stmt.order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
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
        "alternative": 0,
        "mentioned": 0,
        "absent": 0,
        "unknown": 0,
    }
    format_counts: dict[str, int] = {
        "linked": 0,
        "plaintext": 0,
        "mixed": 0,
        "none": 0,
        "unknown": 0,
    }
    accuracy_counts: dict[str, int] = {
        "accurate": 0,
        "partial": 0,
        "inaccurate": 0,
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
        payload = _snapshot_payload(row, prompt_question=questions.get(row.prompt_id))
        fmt = payload.get("citation_format") or "unknown"
        if fmt not in format_counts:
            fmt = "unknown"
        acc = payload.get("citation_accuracy") or "unknown"
        if acc not in accuracy_counts:
            acc = "unknown"
        sentiment_counts[sent] += 1
        position_counts[pos] += 1
        format_counts[fmt] += 1
        accuracy_counts[acc] += 1
        if len(recent) < 40:
            recent.append(payload)
    return {
        "sentiment_counts": sentiment_counts,
        "position_counts": position_counts,
        "format_counts": format_counts,
        "accuracy_counts": accuracy_counts,
        "recent": recent,
        "total": len(rows),
    }


async def _own_domains_for_tenant(session: AsyncSession, tenant_id: int) -> list[str]:
    """自有域 = 渠道 base_url ∪ 已发布 URL 域名（动态，不依赖手填）。"""
    channel_domains: list[str] = []
    for ch in await session.scalars(
        select(GeoPublishingChannel).where(
            GeoPublishingChannel.tenant_id == tenant_id,
            GeoPublishingChannel.channel_type.in_(["website", "docs"]),
            GeoPublishingChannel.enabled.is_(True),
        )
    ):
        domain = extract_cited_domain(ch.base_url)
        if domain and domain not in channel_domains:
            channel_domains.append(domain)
    pubs = await load_tenant_publications(session, tenant_id)
    return merge_domain_lists(channel_domains, domains_from_publications(pubs))


async def _resolve_task_business_id(
    session: AsyncSession, prompt: GeoPrompt
) -> int | None:
    """从意图词 unit → business 反填任务业务归属。"""
    unit_id = getattr(prompt, "unit_id", None)
    if not unit_id:
        return None
    unit = await session.get(GeoOptimizationUnit, unit_id)
    if unit is None or unit.tenant_id != prompt.tenant_id:
        return None
    return int(unit.business_id) if unit.business_id else None


@router.get("/visibility-period-diff")
async def visibility_period_diff(
    tenant_id: int = Query(...),
    before_from: str | None = Query(None),
    before_to: str | None = Query(None),
    after_from: str | None = Query(None),
    after_to: str | None = Query(None),
    period_id: int | None = Query(
        None, description="传入则锁定：before=期前基线窗，after=期次窗"
    ),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Compare visibility metrics across two windows (or a locked optimization period)."""
    from datetime import timedelta

    from app.geo.content.metric_service import compute_metrics

    ctx.ensure_tenant(tenant_id)
    own_domains = await _own_domains_for_tenant(session, tenant_id)
    period_meta: dict[str, Any] | None = None

    if period_id is not None:
        prow = await session.get(GeoOptimizationPeriod, period_id)
        if prow is None or prow.tenant_id != tenant_id:
            raise HTTPException(404, "优化期次不存在")
        s_at, e_at = prow.starts_at, prow.ends_at
        if getattr(s_at, "tzinfo", None):
            s_at = s_at.replace(tzinfo=None)
        if getattr(e_at, "tzinfo", None):
            e_at = e_at.replace(tzinfo=None)
        b_from = s_at - timedelta(days=14)
        b_to = s_at
        a_from, a_to = s_at, e_at
        # Prefer frozen baseline metrics when closed
        baseline_m = (prow.baseline_meta or {}).get("metrics")
        if prow.status == "closed" and baseline_m:
            before = dict(baseline_m)
            before["from"] = _iso(b_from)
            before["to"] = _iso(b_to)
            before["frozen"] = True
        else:
            before_m = await compute_metrics(
                session,
                tenant_id,
                start=b_from.date() if hasattr(b_from, "date") else b_from,
                end=b_to.date() if hasattr(b_to, "date") else b_to,
                own_domains=own_domains,
            )
            before = before_m.to_dict()
            before["from"] = _iso(b_from)
            before["to"] = _iso(b_to)
            before["frozen"] = False
        if prow.status == "closed" and (prow.result_meta or {}).get("metrics"):
            after = dict((prow.result_meta or {}).get("metrics") or {})
            after["from"] = _iso(a_from)
            after["to"] = _iso(a_to)
            after["frozen"] = True
        else:
            after_m = await compute_metrics(
                session,
                tenant_id,
                start=a_from.date() if hasattr(a_from, "date") else a_from,
                end=a_to.date() if hasattr(a_to, "date") else a_to,
                own_domains=own_domains,
            )
            after = after_m.to_dict()
            after["from"] = _iso(a_from)
            after["to"] = _iso(a_to)
            after["frozen"] = False
        period_meta = {
            "id": prow.id,
            "name": prow.name,
            "status": prow.status,
            "business_id": prow.business_id,
        }
    else:
        if not all([before_from, before_to, after_from, after_to]):
            raise HTTPException(
                400, "请提供 before_from/to + after_from/to，或 period_id"
            )
        try:
            b_from = parse_window_bound(before_from, label="before_from")
            b_to = parse_window_bound(before_to, label="before_to")
            a_from = parse_window_bound(after_from, label="after_from")
            a_to = parse_window_bound(after_to, label="after_to")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if b_from > b_to or a_from > a_to:
            raise HTTPException(400, "窗口起止时间无效：from 不得晚于 to")
        before_m = await compute_metrics(
            session,
            tenant_id,
            start=b_from.date() if hasattr(b_from, "date") else b_from,
            end=b_to.date() if hasattr(b_to, "date") else b_to,
            own_domains=own_domains,
        )
        after_m = await compute_metrics(
            session,
            tenant_id,
            start=a_from.date() if hasattr(a_from, "date") else a_from,
            end=a_to.date() if hasattr(a_to, "date") else a_to,
            own_domains=own_domains,
        )
        before = before_m.to_dict()
        after = after_m.to_dict()
        before["from"] = _iso(b_from)
        before["to"] = _iso(b_to)
        after["from"] = _iso(a_from)
        after["to"] = _iso(a_to)

    return {
        "period": period_meta,
        "before": before,
        "after": after,
        "delta": {
            "visibility_mention_rate": rate_delta(
                before.get("visibility_mention_rate")
                or before.get("brand_mention_rate"),
                after.get("visibility_mention_rate")
                or after.get("brand_mention_rate"),
            ),
            "visibility_top1_rate": rate_delta(
                before.get("visibility_top1_rate") or before.get("top1_rate"),
                after.get("visibility_top1_rate") or after.get("top1_rate"),
            ),
            "own_domain_cite_rate": rate_delta(
                before.get("own_domain_cite_rate"), after.get("own_domain_cite_rate")
            ),
            "probe_recognition_rate": rate_delta(
                before.get("probe_recognition_rate")
                or before.get("brand_probe_recognition_rate"),
                after.get("probe_recognition_rate")
                or after.get("brand_probe_recognition_rate"),
            ),
        },
    }


@router.get("/citation-insights")
async def citation_insights(
    tenant_id: int = Query(...),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    days: int | None = Query(None, ge=1, le=90),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Aggregate cited_urls hostnames from answer snapshots."""
    from app.geo.content.time_windows import (
        default_observation_window,
        shanghai_day_bounds_utc_naive,
    )

    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoAnswerSnapshot).where(GeoAnswerSnapshot.tenant_id == tenant_id)
    if date_from or date_to or days:
        start_d, end_d = default_observation_window(days=int(days or 14))
        if date_from:
            start_d = date_from
        if date_to:
            end_d = date_to
        lo, _ = shanghai_day_bounds_utc_naive(start_d)
        _, hi = shanghai_day_bounds_utc_naive(end_d)
        stmt = stmt.where(
            GeoAnswerSnapshot.captured_at >= lo,
            GeoAnswerSnapshot.captured_at < hi,
        )
    rows = list(
        await session.scalars(
            stmt.order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
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
    format_counts: dict[str, int] = {
        "linked": 0,
        "plaintext": 0,
        "mixed": 0,
        "none": 0,
        "unknown": 0,
    }
    accuracy_counts: dict[str, int] = {
        "accurate": 0,
        "partial": 0,
        "inaccurate": 0,
        "unknown": 0,
    }
    for row in rows:
        payload = _snapshot_payload(row)
        fmt = payload.get("citation_format") or "unknown"
        if fmt not in format_counts:
            fmt = "unknown"
        acc = payload.get("citation_accuracy") or "unknown"
        if acc not in accuracy_counts:
            acc = "unknown"
        format_counts[fmt] += 1
        accuracy_counts[acc] += 1
    return {
        "items": items,
        "snapshots_with_citations": snapshots_with_citations,
        "distinct_cited_domains": len(items),
        "own_domains": own_domains,
        "own_domain_cite_rate": own_domain_cite_rate,
        "format_counts": format_counts,
        "accuracy_counts": accuracy_counts,
        "total_snapshots": len(rows),
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
    brand, brand_names = await _brand_context_for_prompt(session, prompt, tenant)
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

    brand, brand_names = await _brand_context_for_prompt(session, prompt, tenant)

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


# ---------- GEO 开户向导 / 业务详情 / 异步作业 / 监测定位 ----------


@router.post("/onboarding/preview")
async def geo_onboarding_preview(
    req: GeoOnboardingPreviewRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """官网 URL → 业务线/意图词/事实草稿（不写库）。"""
    from app.geo.content.onboarding import preview_from_website

    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    existing = set(
        await session.scalars(
            select(GeoPrompt.question).where(
                GeoPrompt.tenant_id == req.tenant_id,
                GeoPrompt.status == "active",
            )
        )
    )
    try:
        payload = await preview_from_website(
            req.website_url,
            expand=bool(req.expand),
            max_prompt_candidates=req.max_prompt_candidates,
            existing_questions=existing,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    payload["tenant_id"] = req.tenant_id
    return payload


@router.post("/onboarding/apply")
async def geo_onboarding_apply(
    req: GeoOnboardingApplyRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """确认写入：业务线 + 意图词 + 事实草稿 + 可选官网渠道。"""
    ctx.ensure_tenant(req.tenant_id)
    tenant = await _ensure_tenant_exists(session, req.tenant_id)

    plan = {
        "businesses": [b.model_dump() for b in req.businesses][:10],
        "prompts": [p.model_dump() for p in req.prompts][:40],
        "facts": [f.model_dump() for f in req.facts][:30],
        "create_website_channel": bool(req.create_website_channel),
        "website_url": req.website_url,
        "brand_terms": list(req.brand_terms or [])[:20],
    }
    if req.dry_run:
        return {"dry_run": True, "would_create": plan, "counts": {
            "businesses": len(plan["businesses"]),
            "prompts": len(plan["prompts"]),
            "facts": len(plan["facts"]),
        }}

    created: dict[str, Any] = {
        "businesses": [],
        "units": [],
        "prompts": [],
        "facts": [],
        "channel": None,
    }

    # brand terms on tenant
    if req.brand_terms:
        existing_terms = list(tenant.brand_terms or [])
        for t in req.brand_terms:
            tt = str(t).strip()
            if tt and tt not in existing_terms:
                existing_terms.append(tt)
        tenant.brand_terms = existing_terms[:30]

    biz_by_name: dict[str, GeoOptimizationBusiness] = {}
    for b in req.businesses[:10]:
        name = b.name.strip()
        if not name:
            continue
        found = await session.scalar(
            select(GeoOptimizationBusiness).where(
                GeoOptimizationBusiness.tenant_id == req.tenant_id,
                GeoOptimizationBusiness.name == name,
            )
        )
        if found:
            biz_by_name[name] = found
            created["businesses"].append({"id": found.id, "name": name, "existed": True})
            continue
        row = GeoOptimizationBusiness(
            tenant_id=req.tenant_id,
            name=name,
            description=(b.description or "").strip() or None,
            status="active",
        )
        session.add(row)
        await session.flush()
        biz_by_name[name] = row
        # default unit under business
        unit = GeoOptimizationUnit(
            tenant_id=req.tenant_id,
            business_id=row.id,
            name="默认单元",
            keyword=name[:200],
            status="active",
        )
        session.add(unit)
        await session.flush()
        created["businesses"].append({"id": row.id, "name": name, "existed": False})
        created["units"].append({"id": unit.id, "business_id": row.id, "name": unit.name})

    from app.geo.content.onboarding import brand_tokens_for_onboarding, match_prompt_business
    from app.geo.content.prompt_taxonomy import brand_names_from_tenant, resolve_is_brand_probe

    apply_brand_names = brand_names_from_tenant(
        name=getattr(tenant, "name", None),
        brand_terms=list(getattr(tenant, "brand_terms", None) or [])
        + list(req.brand_terms or []),
    )
    apply_brand_names = list(
        dict.fromkeys(
            apply_brand_names
            + brand_tokens_for_onboarding(
                getattr(tenant, "name", "") or "",
                extra=apply_brand_names,
            )
        )
    )

    default_biz = next(iter(biz_by_name.values()), None)
    default_unit_id = None
    if default_biz is not None:
        u = await session.scalar(
            select(GeoOptimizationUnit)
            .where(
                GeoOptimizationUnit.tenant_id == req.tenant_id,
                GeoOptimizationUnit.business_id == default_biz.id,
            )
            .order_by(GeoOptimizationUnit.id.asc())
            .limit(1)
        )
        default_unit_id = u.id if u else None

    for p in req.prompts[:40]:
        q = p.question.strip()
        if len(q) < 4:
            continue
        exists = await session.scalar(
            select(GeoPrompt.id).where(
                GeoPrompt.tenant_id == req.tenant_id,
                GeoPrompt.question == q,
                GeoPrompt.status == "active",
            )
        )
        if exists:
            created["prompts"].append({"id": exists, "question": q, "existed": True})
            continue
        unit_id = default_unit_id
        matched_name = match_prompt_business(
            q,
            list(biz_by_name.keys()),
            explicit=p.business_name,
        )
        if matched_name and matched_name in biz_by_name:
            biz = biz_by_name[matched_name]
            u = await session.scalar(
                select(GeoOptimizationUnit)
                .where(
                    GeoOptimizationUnit.tenant_id == req.tenant_id,
                    GeoOptimizationUnit.business_id == biz.id,
                )
                .order_by(GeoOptimizationUnit.id.asc())
                .limit(1)
            )
            unit_id = u.id if u else unit_id
        tags = list(p.tags or ["from_onboarding", "brand_missing"])
        if "from_onboarding" not in tags:
            tags.append("from_onboarding")
        probe = resolve_is_brand_probe(
            question=q,
            brand_names=apply_brand_names,
            explicit=p.is_brand_probe,
            question_group=p.question_group,
        )
        if probe and "brand_probe" not in tags:
            tags.append("brand_probe")
        row = GeoPrompt(
            tenant_id=req.tenant_id,
            question=q,
            priority=int(p.priority or 10),
            tags=tags,
            status="active",
            source="expand",
            question_group=p.question_group,
            market="cn",
            is_brand_probe=probe,
            unit_id=unit_id,
        )
        session.add(row)
        await session.flush()
        created["prompts"].append({"id": row.id, "question": q, "existed": False})

    for f in req.facts[:30]:
        fact_biz = default_biz
        matched_fact_biz = match_prompt_business(
            f"{f.title} {f.statement}",
            list(biz_by_name.keys()),
            explicit=getattr(f, "business_name", None),
        )
        if matched_fact_biz and matched_fact_biz in biz_by_name:
            fact_biz = biz_by_name[matched_fact_biz]
        elif getattr(f, "business_name", None) and f.business_name in biz_by_name:
            fact_biz = biz_by_name[f.business_name]
        row = GeoFact(
            tenant_id=req.tenant_id,
            title=f.title.strip()[:200],
            statement=f.statement.strip(),
            fact_type=f.fact_type,
            source_name=f.source_name.strip()[:200],
            source_url=f.source_url,
            trust_level=f.trust_level,
            status="active",
            business_id=fact_biz.id if fact_biz else None,
            meta={"from_onboarding": True, "website_url": req.website_url},
            created_by=ctx.user_id,
        )
        session.add(row)
        await session.flush()
        created["facts"].append(
            {"id": row.id, "title": row.title, "business_id": row.business_id}
        )

    from app.geo.content.onboarding import attach_orphan_onboarding_facts

    if default_biz is not None:
        await attach_orphan_onboarding_facts(
            session, tenant_id=req.tenant_id, business_id=default_biz.id
        )

    if req.create_website_channel and req.website_url:
        from app.geo.content.onboarding import website_channel_name
        from app.geo.content.snapshots import extract_cited_domain

        base = req.website_url.strip()
        domain = extract_cited_domain(base)
        existing_ch = None
        existing_names: list[str] = []
        for ch in await session.scalars(
            select(GeoPublishingChannel).where(
                GeoPublishingChannel.tenant_id == req.tenant_id,
            )
        ):
            existing_names.append(ch.name)
            if (
                ch.channel_type == "website"
                and domain
                and extract_cited_domain(ch.base_url) == domain
            ):
                existing_ch = ch
        if existing_ch is None:
            ch = GeoPublishingChannel(
                tenant_id=req.tenant_id,
                channel_type="website",
                name=website_channel_name(existing_names, domain),
                base_url=base if base.startswith("http") else f"https://{base}",
                enabled=True,
            )
            session.add(ch)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                raise HTTPException(409, "发布渠道名称已存在，请改名后重试或取消勾选创建官网渠道")
            created["channel"] = {
                "id": ch.id,
                "name": ch.name,
                "base_url": ch.base_url,
                "existed": False,
            }
        else:
            created["channel"] = {
                "id": existing_ch.id,
                "name": existing_ch.name,
                "base_url": existing_ch.base_url,
                "existed": True,
            }

    await session.commit()
    return {
        "dry_run": False,
        "created": created,
        "counts": {
            "businesses": len(created["businesses"]),
            "prompts": len(created["prompts"]),
            "facts": len(created["facts"]),
        },
        "next_paths": {
            "businesses": "/geo/businesses",
            "gaps": "/geo/gaps",
            "facts": "/geo/facts",
            "engines": "/geo/engines",
        },
    }


@router.get("/onboarding/readiness")
async def geo_onboarding_readiness(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """开户完成后的「还差什么」检查表。"""
    from app.geo.content.onboarding import tenant_readiness

    ctx.ensure_tenant(tenant_id)
    await _ensure_tenant_exists(session, tenant_id)
    return await tenant_readiness(session, tenant_id)


@router.get("/optimization-businesses/{business_id}/dashboard")
async def business_dashboard(
    business_id: int,
    tenant_id: int = Query(...),
    days: int = Query(14, ge=1, le=90),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """业务详情一屏：覆盖 / 可见度 / 缺口 / 在产 / 已发 / 效果曲线。"""
    from datetime import timedelta

    from app.geo.content.metric_service import brand_mention_rate, composition_of

    ctx.ensure_tenant(tenant_id)
    biz = await session.scalar(
        select(GeoOptimizationBusiness).where(
            GeoOptimizationBusiness.id == business_id,
            GeoOptimizationBusiness.tenant_id == tenant_id,
        )
    )
    if biz is None:
        raise HTTPException(404, "优化业务不存在")

    units = list(
        await session.scalars(
            select(GeoOptimizationUnit).where(
                GeoOptimizationUnit.tenant_id == tenant_id,
                GeoOptimizationUnit.business_id == business_id,
            )
        )
    )
    unit_ids = [u.id for u in units]
    prompts = []
    if unit_ids:
        prompts = list(
            await session.scalars(
                select(GeoPrompt).where(
                    GeoPrompt.tenant_id == tenant_id,
                    GeoPrompt.unit_id.in_(unit_ids),
                    GeoPrompt.status == "active",
                )
            )
        )
    prompt_ids = [p.id for p in prompts]
    gaps = [p for p in prompts if "brand_missing" in (p.tags or [])]

    tasks = list(
        await session.scalars(
            select(GeoContentTask).where(
                GeoContentTask.tenant_id == tenant_id,
                GeoContentTask.status != "archived",
            )
        )
    )
    # Prefer business_id; fallback prompt in scope
    biz_tasks = [
        t
        for t in tasks
        if getattr(t, "business_id", None) == business_id
        or (t.prompt_id in set(prompt_ids) if prompt_ids else False)
    ]
    in_prod = [
        t
        for t in biz_tasks
        if t.status not in {"published", "archived"}
    ]
    published_tasks = [t for t in biz_tasks if t.status == "published"]

    # publications for published tasks
    pubs: list[dict[str, Any]] = []
    for t in published_tasks[:30]:
        for v in await _variants(session, t.id):
            pub = await session.scalar(
                select(GeoPublication)
                .where(GeoPublication.variant_id == v.id)
                .order_by(GeoPublication.id.desc())
                .limit(1)
            )
            if pub and pub.published_url:
                pubs.append(
                    {
                        "task_id": t.id,
                        "title": t.title,
                        "channel": pub.channel,
                        "published_url": pub.published_url,
                        "published_at": _iso(pub.published_at),
                    }
                )

    from app.geo.content.metric_service import compute_metrics
    from app.geo.content.time_windows import default_observation_window, shanghai_today

    w_start, w_end = default_observation_window(days=days)
    end = datetime.utcnow()  # used only for legacy series lower bound fallback
    start = end - timedelta(days=days)
    own_domains = await _own_domains_for_tenant(session, tenant_id)
    metrics_bundle = await compute_metrics(
        session,
        tenant_id,
        start=w_start,
        end=w_end,
        days=days,
        prompt_ids=prompt_ids or None,
        own_domains=own_domains,
    )
    mention = {
        **metrics_bundle.to_dict(),
        "rate": metrics_bundle.brand_mention_rate,
        "mentions": metrics_bundle.brand_mentions,
        "snapshots": metrics_bundle.snapshots_visibility,
        "days": days,
        "scope": "business" if prompt_ids else "tenant_fallback",
        "business_id": business_id,
    }
    # Load snaps via unified window for deeper drill sections
    from app.geo.content.metric_service import load_snapshots_in_window

    snaps = await load_snapshots_in_window(
        session,
        tenant_id,
        start=w_start,
        end=w_end,
        prompt_ids=prompt_ids or None,
    )
    probe_map = {p.id: bool(p.is_brand_probe) for p in prompts}
    vis_snaps = [s for s in snaps if not probe_map.get(s.prompt_id, False)]
    daily = list(
        await session.scalars(
            select(GeoDailyMetric)
            .where(
                GeoDailyMetric.tenant_id == tenant_id,
                GeoDailyMetric.scope_key == f"b{business_id}",
            )
            .order_by(GeoDailyMetric.metric_date.desc())
            .limit(days)
        )
    )
    if not daily:
        daily = list(
            await session.scalars(
                select(GeoDailyMetric)
                .where(
                    GeoDailyMetric.tenant_id == tenant_id,
                    GeoDailyMetric.scope_key == "t",
                )
                .order_by(GeoDailyMetric.metric_date.desc())
                .limit(days)
            )
        )

    series = [
        {
            "date": str(d.metric_date),
            "brand_mention_rate": getattr(d, "brand_mention_rate", None),
            "probe_recognition_rate": getattr(d, "brand_probe_recognition_rate", None),
            "top1_rate": getattr(d, "top1_rate", None),
            "citation_count": getattr(d, "citation_count", None),
            "distinct_cited_domains": getattr(d, "distinct_cited_domains", None),
            "top_competitor": getattr(d, "top_competitor", None),
            "top_competitor_rate": getattr(d, "top_competitor_rate", None),
            "scope_key": d.scope_key,
        }
        for d in reversed(daily)
    ]

    # ---- deeper metrics: multi-rate window, engine split, citations, competitors ----
    from datetime import timedelta as _td

    prev_end = w_start - _td(days=1)
    prev_start_d = prev_end - _td(days=days - 1)
    prev_bundle = await compute_metrics(
        session,
        tenant_id,
        start=prev_start_d,
        end=prev_end,
        prompt_ids=prompt_ids or None,
        own_domains=own_domains,
    )
    window_now = metrics_bundle.to_dict()
    window_prev = prev_bundle.to_dict()
    visibility_deep = {
        **mention,
        **window_now,
        "delta_vs_previous": {
            "visibility_mention_rate": rate_delta(
                window_prev.get("visibility_mention_rate"),
                window_now.get("visibility_mention_rate"),
            ),
            "visibility_top1_rate": rate_delta(
                window_prev.get("visibility_top1_rate"),
                window_now.get("visibility_top1_rate"),
            ),
            "probe_recognition_rate": rate_delta(
                window_prev.get("probe_recognition_rate"),
                window_now.get("probe_recognition_rate"),
            ),
            "own_domain_cite_rate": rate_delta(
                window_prev.get("own_domain_cite_rate"),
                window_now.get("own_domain_cite_rate"),
            ),
        },
        "previous_window": {
            "from": prev_start_d.isoformat(),
            "to": prev_end.isoformat(),
            **window_prev,
        },
        "current_window": {
            "from": w_start.isoformat(),
            "to": w_end.isoformat(),
        },
    }

    # by engine
    by_engine: dict[str, dict[str, Any]] = {}
    for s in vis_snaps:
        eng = s.engine or "other"
        b = by_engine.setdefault(
            eng, {"engine": eng, "snapshots": 0, "mentions": 0, "simulated": 0}
        )
        b["snapshots"] += 1
        if s.mentions_brand:
            b["mentions"] += 1
        if getattr(s, "simulated", False):
            b["simulated"] += 1
    engine_rows = []
    for b in by_engine.values():
        n = b["snapshots"]
        engine_rows.append(
            {
                **b,
                "mention_rate": round(b["mentions"] / n, 4) if n else None,
            }
        )
    engine_rows.sort(key=lambda x: (-(x["mention_rate"] or 0), -x["snapshots"]))

    # citation domains + competitor counts from snaps
    domain_buckets: dict[str, int] = {}
    competitor_buckets: dict[str, int] = {}
    for s in snaps:
        for d in extract_cited_domains(list(s.cited_urls or [])):
            domain_buckets[d] = domain_buckets.get(d, 0) + 1
        for c in list(s.competitors or []):
            name = str(c or "").strip()
            if name:
                competitor_buckets[name] = competitor_buckets.get(name, 0) + 1
    top_domains = sorted(
        (
            {
                "domain": d,
                "cite_count": n,
                "is_own": bool(
                    own_domains and any(domain_matches(d, o) for o in own_domains)
                ),
            }
            for d, n in domain_buckets.items()
        ),
        key=lambda x: (-x["cite_count"], x["domain"]),
    )[:15]
    top_competitors = sorted(
        ({"name": k, "mentions": v} for k, v in competitor_buckets.items()),
        key=lambda x: (-x["mentions"], x["name"]),
    )[:10]

    # content funnel
    status_counts: dict[str, int] = {}
    for t in biz_tasks:
        st = t.status or "draft"
        status_counts[st] = status_counts.get(st, 0) + 1
    review_pending = sum(
        1 for t in biz_tasks if (t.review_status or "none") == "pending"
    )
    # publication cite hits via matched_publication_ids
    pub_ids = set()
    for t in published_tasks:
        for v in await _variants(session, t.id):
            for pub in await session.scalars(
                select(GeoPublication).where(GeoPublication.variant_id == v.id)
            ):
                if pub.published_url:
                    pub_ids.add(int(pub.id))
    cite_hit_snaps = 0
    if pub_ids and snaps:
        for s in snaps:
            mids = list(getattr(s, "matched_publication_ids", None) or [])
            if any(int(x) in pub_ids for x in mids):
                cite_hit_snaps += 1

    return {
        "business": _business_payload(biz, unit_count=len(units)),
        "units": [_unit_payload(u) for u in units],
        "coverage": {
            "prompt_count": len(prompts),
            "gap_count": len(gaps),
            "covered_count": len(prompts) - len(gaps),
            "coverage_rate": (
                round((len(prompts) - len(gaps)) / len(prompts), 4) if prompts else None
            ),
            "unit_count": len(units),
            "by_unit": [
                {
                    "unit_id": u.id,
                    "unit_name": u.name,
                    "prompt_count": sum(1 for p in prompts if p.unit_id == u.id),
                    "gap_count": sum(
                        1
                        for p in prompts
                        if p.unit_id == u.id and "brand_missing" in (p.tags or [])
                    ),
                }
                for u in units
            ],
        },
        "visibility": visibility_deep,
        "sample_composition": composition_of(snaps).to_dict(),
        "by_engine": engine_rows,
        "citations": {
            "top_domains": top_domains,
            "own_domains": own_domains,
            "snapshots_with_publication_hits": cite_hit_snaps,
            "publication_count": len(pubs),
        },
        "competitors": {
            "top": top_competitors,
            "any_mentions": sum(1 for s in snaps if s.competitors),
        },
        "content_funnel": {
            "total_tasks": len(biz_tasks),
            "status_counts": status_counts,
            "in_production": len(in_prod),
            "published": len(published_tasks),
            "review_pending": review_pending,
        },
        "gaps": [
            {
                "prompt_id": p.id,
                "question": p.question,
                "priority": p.priority,
                "tags": p.tags or [],
            }
            for p in sorted(gaps, key=lambda x: (-(x.priority or 0), -x.id))[:40]
        ],
        "in_production": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "pipeline_step": t.pipeline_step,
                "review_status": t.review_status,
            }
            for t in sorted(in_prod, key=lambda x: -x.id)[:30]
        ],
        "published": pubs[:30],
        "this_week": _business_week_actions(
            gaps=gaps,
            in_prod=in_prod,
            published=pubs,
            cite_hit_snaps=cite_hit_snaps,
        ),
        "effect_series": series,
        "days": days,
        "links": {
            "gaps": "/geo/gaps",
            "tasks": "/geo/tasks",
            "prompts": f"/geo/prompts?business_id={business_id}",
            "periods": "/geo/periods",
            "citations": "/geo/citations",
            "competitors": "/geo/competitors",
        },
    }


@router.get("/monitoring-stance")
async def get_monitoring_stance(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.ai_settings import ensure_ai_setting
    from app.geo.content.monitoring_stance import (
        STANCES,
        build_skip_preview,
        compose_stance_banner,
        normalize_stance,
    )
    from app.models import GeoTrackingEngine

    ctx.ensure_tenant(tenant_id)
    row = await ensure_ai_setting(session, tenant_id)
    stance = normalize_stance(getattr(row, "monitoring_stance", None))
    engines = list(
        await session.scalars(
            select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == tenant_id)
        )
    )
    enabled = [e for e in engines if e.enabled]
    real_ready = [
        e
        for e in enabled
        if (e.sample_mode or "") == "openai_compat" and e.api_key_encrypted
    ]
    banner = compose_stance_banner(
        stance,
        real_ready_engines=len(real_ready),
        enabled_engines=len(enabled),
    )
    skip_preview = build_skip_preview(engines, monitoring_stance=stance)
    return {
        "tenant_id": tenant_id,
        "monitoring_stance": stance,
        "options": list(STANCES.values()),
        "banner": banner,
        "engines_summary": {
            "enabled": len(enabled),
            "real_ready": len(real_ready),
            "mock_persona": sum(
                1 for e in enabled if (e.sample_mode or "mock_persona") == "mock_persona"
            ),
            "will_run": skip_preview["enabled_will_run"],
            "will_skip": skip_preview["enabled_will_skip"],
        },
        "skip_preview": skip_preview,
    }


@router.put("/monitoring-stance")
async def put_monitoring_stance(
    req: MonitoringStanceUpdate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.ai_settings import ensure_ai_setting
    from app.geo.content.monitoring_stance import normalize_stance, stance_payload

    ctx.ensure_tenant(req.tenant_id)
    row = await ensure_ai_setting(session, req.tenant_id)
    row.monitoring_stance = normalize_stance(req.monitoring_stance)
    row.updated_by = ctx.user_id
    await session.commit()
    await session.refresh(row)
    return {
        "tenant_id": req.tenant_id,
        "monitoring_stance": row.monitoring_stance,
        "info": stance_payload(row.monitoring_stance),
    }


@router.post("/attribution/backfill")
async def attribution_backfill(
    tenant_id: int = Query(...),
    limit: int = Query(2000, ge=1, le=10000, description="本批最多处理条数"),
    only_empty: bool = Query(True, description="仅回填 matched 为空的快照"),
    cursor_id: int | None = Query(None, description="游标：只处理 id < cursor_id"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """历史快照归因回填（支持游标分页跑全量）。"""
    from app.geo.content.attribution import (
        load_tenant_publications,
        match_publication_ids,
    )

    ctx.ensure_tenant(tenant_id)
    pubs = await load_tenant_publications(session, tenant_id)
    if not pubs:
        return {
            "tenant_id": tenant_id,
            "scanned": 0,
            "updated": 0,
            "matched_hits": 0,
            "publication_count": 0,
            "next_cursor": None,
            "done": True,
            "message": "无已发布 URL，无需回填",
        }

    stmt = select(GeoAnswerSnapshot).where(GeoAnswerSnapshot.tenant_id == tenant_id)
    if cursor_id is not None:
        stmt = stmt.where(GeoAnswerSnapshot.id < int(cursor_id))
    stmt = stmt.order_by(GeoAnswerSnapshot.id.desc()).limit(limit)
    rows = list(await session.scalars(stmt))
    updated = 0
    hits = 0
    scanned = 0
    min_id = None
    for snap in rows:
        scanned += 1
        min_id = int(snap.id) if min_id is None else min(min_id, int(snap.id))
        existing = list(getattr(snap, "matched_publication_ids", None) or [])
        if only_empty and existing:
            continue
        matched = match_publication_ids(list(snap.cited_urls or []), pubs)
        if matched != existing:
            snap.matched_publication_ids = matched or None
            updated += 1
        if matched:
            hits += 1
    await session.commit()
    next_cursor = min_id if scanned >= limit and min_id is not None else None
    return {
        "tenant_id": tenant_id,
        "scanned": scanned,
        "updated": updated,
        "matched_hits": hits,
        "publication_count": len(pubs),
        "only_empty": only_empty,
        "next_cursor": next_cursor,
        "done": next_cursor is None,
    }


@router.get("/async-jobs/{job_id}")
async def get_async_job(
    job_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.async_jobs import job_payload, reconcile_stale_job

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoAsyncJob, job_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "异步作业不存在")
    row = await reconcile_stale_job(session, row)
    return job_payload(row)


@router.get("/async-jobs")
async def list_async_jobs(
    tenant_id: int = Query(...),
    ref_type: str | None = Query(None),
    ref_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.async_jobs import (
        job_payload,
        reconcile_stale_content_tasks,
        reconcile_stale_job,
    )

    ctx.ensure_tenant(tenant_id)
    released = await reconcile_stale_content_tasks(session, tenant_id=tenant_id)
    stmt = select(GeoAsyncJob).where(GeoAsyncJob.tenant_id == tenant_id)
    if ref_type:
        stmt = stmt.where(GeoAsyncJob.ref_type == ref_type)
    if ref_id is not None:
        stmt = stmt.where(GeoAsyncJob.ref_id == ref_id)
    stmt = stmt.order_by(GeoAsyncJob.id.desc()).limit(limit)
    rows = list(await session.scalars(stmt))
    out = []
    for r in rows:
        r = await reconcile_stale_job(session, r)
        out.append(job_payload(r))
    return {"items": out, "stale_tasks_released": released}


@router.post("/async-jobs/{job_id}/cancel")
async def cancel_async_job(
    job_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.async_jobs import job_payload, request_cancel

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoAsyncJob, job_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "异步作业不存在")
    row = await request_cancel(session, row)
    return job_payload(row)


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
    from app.geo.content.metric_service import composition_of, compute_brand_mention_from_rows
    from app.geo.content.patrol import patrol_run_payload, reconcile_stale_patrol_run

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoVisibilityPatrolRun, run_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "巡检任务不存在")
    row = await reconcile_stale_patrol_run(session, row)
    payload = patrol_run_payload(row)

    # 本次巡检落库快照（可下钻）
    snaps = list(
        await session.scalars(
            select(GeoAnswerSnapshot).where(
                GeoAnswerSnapshot.tenant_id == tenant_id,
                GeoAnswerSnapshot.patrol_run_id == run_id,
            )
        )
    )
    payload["snapshot_ids"] = [s.id for s in snaps]
    payload["snapshot_count"] = len(snaps)
    payload["sample_composition"] = composition_of(snaps).to_dict()

    # 本次 vs 上一 completed 巡检（提及率）
    prev = await session.scalar(
        select(GeoVisibilityPatrolRun)
        .where(
            GeoVisibilityPatrolRun.tenant_id == tenant_id,
            GeoVisibilityPatrolRun.status == "completed",
            GeoVisibilityPatrolRun.id < run_id,
        )
        .order_by(GeoVisibilityPatrolRun.id.desc())
        .limit(1)
    )
    probe_ids = {s.prompt_id for s in snaps}
    prompt_probe: dict[int, bool] = {}
    if probe_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(list(probe_ids))
            )
        ):
            prompt_probe[p.id] = bool(p.is_brand_probe)
    this_m = compute_brand_mention_from_rows(snaps, probe_map=prompt_probe)
    vs_prev: dict[str, Any] = {
        "previous_run_id": prev.id if prev else None,
        "this_brand_mention_rate": this_m.rate,
        "this_snapshots": this_m.visibility_n,
        "this_mentions": this_m.mentions,
        "this_top1_rate": this_m.top1_rate,
        "this_sample_composition": this_m.composition.to_dict(),
    }
    if prev:
        prev_snaps = list(
            await session.scalars(
                select(GeoAnswerSnapshot).where(
                    GeoAnswerSnapshot.tenant_id == tenant_id,
                    GeoAnswerSnapshot.patrol_run_id == prev.id,
                )
            )
        )
        prev_probe_ids = {s.prompt_id for s in prev_snaps}
        prev_map: dict[int, bool] = {}
        if prev_probe_ids:
            for p in await session.scalars(
                select(GeoPrompt).where(
                    GeoPrompt.tenant_id == tenant_id,
                    GeoPrompt.id.in_(list(prev_probe_ids)),
                )
            ):
                prev_map[p.id] = bool(p.is_brand_probe)
        prev_m = compute_brand_mention_from_rows(prev_snaps, probe_map=prev_map)
        vs_prev["previous_brand_mention_rate"] = prev_m.rate
        vs_prev["previous_snapshots"] = prev_m.visibility_n
        delta = None
        if this_m.rate is not None and prev_m.rate is not None:
            delta = round(this_m.rate - prev_m.rate, 4)
        vs_prev["brand_mention_rate_delta"] = delta
    payload["vs_previous"] = vs_prev
    return payload


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
        brand, brand_names = await _brand_context_for_prompt(session, prompt, tenant)

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


@router.post("/answer-snapshots/check-citations")
async def check_answer_snapshot_citations(
    req: AnswerSnapshotCitationCheckRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """校验引用 URL 可达性 / 是否自有域，并建议 citation_accuracy。"""
    from app.geo.content.citation_quality import check_cited_urls

    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    urls = list(req.cited_urls or [])
    row = None
    if req.snapshot_id is not None:
        row = await _get_snapshot(session, req.snapshot_id, req.tenant_id)
        if not urls:
            urls = list(row.cited_urls or [])
    own_domains = await _own_domains_for_tenant(session, req.tenant_id)
    result = await check_cited_urls(urls, own_domains=own_domains)
    applied = False
    if req.apply and row is not None:
        row.citation_accuracy = result["suggested_citation_accuracy"]
        await session.commit()
        await session.refresh(row)
        applied = True
    return {
        "snapshot_id": req.snapshot_id,
        "own_domains": own_domains,
        "applied": applied,
        **result,
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


@router.get("/channel-polish-prompts")
async def get_channel_polish_prompts(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """租户生效的渠道成稿提示词（含代码默认与自定义标记）。"""
    from app.geo.content.channel_polish_prompts import get_effective_prompts

    ctx.ensure_tenant(tenant_id)
    await _ensure_tenant_exists(session, tenant_id)
    return await get_effective_prompts(session, tenant_id)


@router.put("/channel-polish-prompts")
async def put_channel_polish_prompts(
    req: ChannelPolishPromptsUpdate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """保存渠道成稿提示词覆盖；reset_system / channel.reset 恢复代码默认。"""
    from app.geo.content.channel_polish_prompts import upsert_prompts

    ctx.ensure_tenant(req.tenant_id)
    await _ensure_tenant_exists(session, req.tenant_id)
    channel_payload = [c.model_dump() for c in req.channels]
    try:
        return await upsert_prompts(
            session,
            req.tenant_id,
            system_prompt=req.system_prompt,
            reset_system=bool(req.reset_system),
            channels=channel_payload,
            add_channel_key=req.add_channel_key,
            remove_channel_key=req.remove_channel_key,
            updated_by=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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
        # Avoid user="ping" — some models reply literally "PONG" and break JSON parse.
        data = await chat_json(
            '你是连通性检测。只输出一个 JSON 对象，不要 markdown 代码块。',
            '请返回：{"ok": true, "echo": "geo-ai-settings-test"}',
            timeout=30.0,
            api_key=llm["api_key"],
            base_url=llm["base_url"],
            model=llm["model"],
        )
    except DeepSeekError as exc:
        raise HTTPException(502, str(exc)) from exc
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise HTTPException(
            502,
            f"AI 已连通但返回不符合约定：{data!r}",
        )
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
    from app.geo.content.engines import sanitize_engine_endpoint
    from app.security.crypto import decrypt

    plain = None
    if getattr(row, "api_key_encrypted", None):
        try:
            plain = decrypt(row.api_key_encrypted)
        except Exception:  # noqa: BLE001
            plain = None
    url, model, mode, _changed = sanitize_engine_endpoint(
        row.engine_key,
        getattr(row, "api_base_url", None),
        getattr(row, "model", None),
        getattr(row, "sample_mode", None) or "mock_persona",
        has_key=bool(plain),
    )
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "engine_key": row.engine_key,
        "display_name": row.display_name,
        "enabled": bool(row.enabled),
        "note": row.note,
        "sort_order": row.sort_order,
        "sample_mode": mode,
        "api_base_url": url,
        "model": model,
        "api_key_configured": bool(plain),
        "api_key_masked": mask_api_key(plain) if plain else None,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


async def _ensure_default_engines(
    session: AsyncSession, tenant_id: int
) -> list[GeoTrackingEngine]:
    """Ensure tenant has all default engines; add any newly introduced keys (e.g. kimi)."""
    rows = list(
        await session.scalars(
            select(GeoTrackingEngine)
            .where(GeoTrackingEngine.tenant_id == tenant_id)
            .order_by(GeoTrackingEngine.sort_order, GeoTrackingEngine.id)
        )
    )
    existing = {str(r.engine_key) for r in rows}
    missing = [
        item
        for item in default_engine_rows(tenant_id)
        if item["engine_key"] not in existing
    ]
    if not rows and not missing:
        return rows
    if missing:
        await _ensure_tenant_exists(session, tenant_id)
        for item in missing:
            row = GeoTrackingEngine(**item)
            session.add(row)
            rows.append(row)
        await session.commit()
        for row in rows:
            await session.refresh(row)
        rows = list(
            await session.scalars(
                select(GeoTrackingEngine)
                .where(GeoTrackingEngine.tenant_id == tenant_id)
                .order_by(GeoTrackingEngine.sort_order, GeoTrackingEngine.id)
            )
        )
    from app.geo.content.engines import sanitize_engine_endpoint
    from app.security.crypto import decrypt

    dirty = False
    for r in rows:
        has_key = False
        if getattr(r, "api_key_encrypted", None):
            try:
                has_key = bool(decrypt(r.api_key_encrypted))
            except Exception:  # noqa: BLE001
                has_key = False
        url, model, mode, changed = sanitize_engine_endpoint(
            r.engine_key,
            getattr(r, "api_base_url", None),
            getattr(r, "model", None),
            getattr(r, "sample_mode", None),
            has_key=has_key,
        )
        if not changed:
            continue
        r.api_base_url = url
        r.model = model
        r.sample_mode = mode
        dirty = True
    if dirty:
        await session.commit()
        for r in rows:
            await session.refresh(r)
    return rows


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
        from app.geo.content.engines import sanitize_engine_endpoint

        url, model, mode, _changed = sanitize_engine_endpoint(
            item.engine_key,
            item.api_base_url,
            item.model,
            mode,
            has_key=bool(enc),
        )
        row = GeoTrackingEngine(
            tenant_id=req.tenant_id,
            engine_key=item.engine_key,
            display_name=item.display_name.strip(),
            enabled=bool(item.enabled),
            note=item.note,
            sort_order=int(item.sort_order),
            sample_mode=mode,
            api_base_url=url,
            model=model,
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
    token_expires_at = None
    token_expired = False
    token_expiring_soon = False
    if row.credentials_encrypted:
        try:
            from app.geo.content.connectors.social import (
                decrypt_credentials_json,
                resolve_provider,
            )
            from app.geo.content.ops_alerts import account_token_health

            creds = decrypt_credentials_json(row.credentials_encrypted)
            provider = resolve_provider(creds)
            platform = creds.get("platform")
            health = account_token_health(creds)
            oauth_authorized = bool(health.get("oauth_authorized"))
            token_expires_at = health.get("token_expires_at")
            token_expired = bool(health.get("token_expired"))
            token_expiring_soon = bool(health.get("token_expiring_soon"))
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
        "token_expires_at": token_expires_at,
        "token_expired": token_expired,
        "token_expiring_soon": token_expiring_soon,
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
    business_id: int | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoFact).where(GeoFact.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(GeoFact.status == status)
    if trust_level:
        stmt = stmt.where(GeoFact.trust_level == trust_level)
    if business_id is not None:
        stmt = stmt.where(
            or_(GeoFact.business_id == business_id, GeoFact.business_id.is_(None))
        )
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
    if req.trust_level == "verified":
        raise HTTPException(400, "不能直接创建为已核验，请先保存再走核验并填写依据")
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
        business_id=req.business_id,
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
    if data.get("trust_level") == "verified" and row.trust_level != "verified":
        raise HTTPException(400, "请走「核验」并填写摘录依据与定位，不能直接改为已核验")
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
    req: FactVerifyRequest,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    row = await _get_fact(session, fact_id, tenant_id)
    _validate_fact_source(row.source_name, "verified")
    stmt = (row.statement or "").strip()
    if len(stmt) < 8:
        raise HTTPException(400, "陈述过短，无法核验")
    if len(stmt) > 220:
        raise HTTPException(400, "陈述过长。请拆成一条不超过 220 字的原子事实后再核验")
    excerpt = " ".join(req.excerpt.split())
    stmt_n = "".join(stmt.split())
    excerpt_n = "".join(excerpt.split())
    if len(excerpt_n) < 8 or excerpt_n not in stmt_n:
        raise HTTPException(400, "摘录必须是陈述中的连续原文，用于定位核验依据")
    source_url = (req.source_url or row.source_url or "").strip()
    if not source_url:
        raise HTTPException(400, "核验必须填写来源 URL")
    others = list(
        await session.scalars(
            select(GeoFact).where(
                GeoFact.tenant_id == tenant_id,
                GeoFact.status == "active",
                GeoFact.trust_level == "verified",
                GeoFact.id != row.id,
            )
        )
    )
    norm = "".join(stmt.split())
    for other in others:
        other_n = "".join((other.statement or "").split())
        if other_n and (norm[:48] == other_n[:48] or norm in other_n or other_n in norm):
            raise HTTPException(400, f"与已核验事实 #{other.id}「{other.title}」重复，请先去重")
    now = datetime.utcnow().isoformat()
    meta = dict(row.meta or {})
    meta["verification"] = {
        "excerpt": excerpt[:400],
        "excerpt_locator": req.excerpt_locator.strip(),
        "source_url": source_url,
        "note": (req.note or "").strip() or None,
        "verified_at": now,
        "verified_by": ctx.user_id,
    }
    meta["verified_at"] = now
    meta["verified_by"] = ctx.user_id
    meta["source_excerpt"] = excerpt[:160]
    meta["excerpt_locator"] = req.excerpt_locator.strip()
    row.meta = meta
    if not row.source_url:
        row.source_url = source_url
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

    business_id = await _resolve_task_business_id(session, prompt)
    period_id = await _resolve_active_period_id(
        session, tenant_id=req.tenant_id, business_id=business_id
    )
    task = GeoContentTask(
        tenant_id=req.tenant_id,
        prompt_id=prompt.id,
        business_id=business_id,
        period_id=period_id,
        title=title,
        status="draft",
        target_channels=normalize_channels(req.target_channels),
        owner_user_id=ctx.user_id,
        pipeline_step="opportunity",
        brief=normalize_brief(req.brief) if req.brief else {},
    )
    session.add(task)
    try:
        await session.flush()
        prompt.last_task_id = task.id
        if req.fact_ids:
            await _bind_facts(session, task, req.fact_ids)
        else:
            await _sync_task_pipeline(session, task)
        await session.commit()
        await session.refresh(task)
        return await _task_payload(session, task, detail=True)
    except ProgrammingError as exc:
        await session.rollback()
        blob = str(getattr(exc, "orig", None) or exc)
        if "geo_facts" in blob and "business_id" in blob:
            raise HTTPException(
                500,
                "数据库缺 geo_facts.business_id，无法创建优化文章。"
                "请在服务器执行 alembic upgrade head（0073 修复迁移）。",
            ) from exc
        raise HTTPException(500, f"创建优化文章失败：{blob[:240]}") from exc


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


@router.get("/content-tasks/{task_id}/impact")
async def content_task_impact(
    task_id: int,
    tenant_id: int = Query(...),
    window_days: int = Query(14, ge=1, le=90, description="发布前后对比窗天数"),
    min_samples: int = Query(8, ge=1, le=50, description="单侧最小样本量"),
    spillover_scope: str = Query(
        "unit", description="相关意图词范围: prompt|unit|business"
    ),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """发布后效果：引用命中 + 有样本量门槛/外溢/对照的证明层（W4）。"""
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    variants = await _variants(session, task.id)
    variant_ids = [v.id for v in variants]
    pubs: list[GeoPublication] = []
    if variant_ids:
        pubs = list(
            await session.scalars(
                select(GeoPublication)
                .where(GeoPublication.variant_id.in_(variant_ids))
                .order_by(GeoPublication.published_at.asc().nullslast(), GeoPublication.id.asc())
            )
        )
    pub_ids = [int(p.id) for p in pubs if p.published_url]
    first_pub_at = None
    for p in pubs:
        if p.published_at is not None:
            first_pub_at = p.published_at
            break
        if p.created_at is not None and first_pub_at is None:
            first_pub_at = p.created_at

    all_snaps = list(
        await session.scalars(
            select(GeoAnswerSnapshot)
            .where(GeoAnswerSnapshot.tenant_id == tenant_id)
            .order_by(GeoAnswerSnapshot.captured_at.asc(), GeoAnswerSnapshot.id.asc())
        )
    )
    tenant_pubs = await load_tenant_publications(session, tenant_id)
    task_pub_refs = [pr for pr in tenant_pubs if pr.task_id == task.id]
    cite_hits: list[dict[str, Any]] = []
    for snap in all_snaps:
        matched = list(getattr(snap, "matched_publication_ids", None) or [])
        if not matched and task_pub_refs:
            matched = match_publication_ids(list(snap.cited_urls or []), task_pub_refs)
        hit_ids = [pid for pid in matched if pid in pub_ids]
        if not hit_ids:
            continue
        cite_hits.append(
            {
                "snapshot_id": snap.id,
                "prompt_id": snap.prompt_id,
                "engine": snap.engine,
                "captured_at": _iso(snap.captured_at),
                "mentions_brand": bool(snap.mentions_brand),
                "matched_publication_ids": hit_ids,
                "cited_urls": list(snap.cited_urls or []),
                "simulated": bool(getattr(snap, "simulated", False)),
                "sample_mode": getattr(snap, "sample_mode", None) or "manual",
            }
        )

    # Related prompt set: direct + spillover
    direct_prompt_ids = {int(task.prompt_id)}
    spillover_ids: set[int] = set()
    prompt_row = await session.get(GeoPrompt, task.prompt_id)
    scope = (spillover_scope or "unit").strip().lower()
    if prompt_row and scope in {"unit", "business"} and prompt_row.unit_id:
        unit = await session.get(GeoOptimizationUnit, prompt_row.unit_id)
        if unit and scope == "unit":
            for p in await session.scalars(
                select(GeoPrompt).where(
                    GeoPrompt.tenant_id == tenant_id,
                    GeoPrompt.unit_id == unit.id,
                    GeoPrompt.status == "active",
                )
            ):
                if p.id != task.prompt_id:
                    spillover_ids.add(int(p.id))
        elif unit and scope == "business":
            for p in await session.scalars(
                select(GeoPrompt)
                .join(
                    GeoOptimizationUnit,
                    GeoOptimizationUnit.id == GeoPrompt.unit_id,
                )
                .where(
                    GeoPrompt.tenant_id == tenant_id,
                    GeoOptimizationUnit.business_id == unit.business_id,
                    GeoPrompt.status == "active",
                )
            ):
                if p.id != task.prompt_id:
                    spillover_ids.add(int(p.id))
    related_ids = direct_prompt_ids | spillover_ids

    before_start, anchor, after_end = impact_windows(first_pub_at, window_days=window_days)

    def _split_window(snaps: list[GeoAnswerSnapshot]) -> tuple[list, list]:
        b, a = [], []
        if anchor is None or before_start is None or after_end is None:
            return b, a
        for s in snaps:
            ca = s.captured_at
            if ca is None:
                continue
            if getattr(ca, "tzinfo", None) is not None:
                ca = ca.replace(tzinfo=None)
            if before_start <= ca < anchor:
                b.append(s)
            elif anchor <= ca <= after_end:
                a.append(s)
        return b, a

    def _rate_block(snaps_b: list, snaps_a: list) -> dict[str, Any]:
        before_m = summarize_snaps(snaps_b)
        after_m = summarize_snaps(snaps_a)
        n_b = before_m["snapshot_count"]
        n_a = after_m["snapshot_count"]
        insufficient = n_b < min_samples or n_a < min_samples
        delta = None
        if (
            not insufficient
            and before_m["mention_rate"] is not None
            and after_m["mention_rate"] is not None
        ):
            delta = round(after_m["mention_rate"] - before_m["mention_rate"], 4)
        conf = "low"
        if not insufficient and n_b >= min_samples * 2 and n_a >= min_samples * 2:
            conf = "high"
        elif not insufficient:
            conf = "medium"
        return {
            "before": before_m,
            "after": after_m,
            "delta_mention_rate": None if insufficient else delta,
            "insufficient_data": insufficient,
            "min_samples": min_samples,
            "confidence": conf,
            "confidence_reason": (
                f"样本量不足（前 {n_b} / 后 {n_a}，阈值 {min_samples}）"
                if insufficient
                else f"前 {n_b} / 后 {n_a} 条快照"
            ),
        }

    direct_snaps = [s for s in all_snaps if s.prompt_id in direct_prompt_ids]
    spill_snaps = [s for s in all_snaps if s.prompt_id in spillover_ids]
    db, da = _split_window(direct_snaps)
    sb, sa = _split_window(spill_snaps)
    direct_block = _rate_block(db, da)
    spill_block = _rate_block(sb, sa) if spillover_ids else None

    # Control: prompts without any published task in window
    published_prompt_ids = set(
        await session.scalars(
            select(GeoContentTask.prompt_id).where(
                GeoContentTask.tenant_id == tenant_id,
                GeoContentTask.status == "published",
            )
        )
    )
    control_ids = set(
        await session.scalars(
            select(GeoPrompt.id).where(
                GeoPrompt.tenant_id == tenant_id,
                GeoPrompt.status == "active",
                GeoPrompt.id.notin_(list(related_ids | published_prompt_ids) or [0]),
            )
        )
    )
    control_snaps = [s for s in all_snaps if s.prompt_id in control_ids]
    cb, ca = _split_window(control_snaps)
    control_block = _rate_block(cb, ca)
    net_effect = None
    if (
        not direct_block["insufficient_data"]
        and not control_block["insufficient_data"]
        and direct_block["delta_mention_rate"] is not None
        and control_block["delta_mention_rate"] is not None
    ):
        net_effect = round(
            direct_block["delta_mention_rate"] - control_block["delta_mention_rate"], 4
        )

    overall_conf = direct_block["confidence"]
    if direct_block["insufficient_data"]:
        overall_conf = "low"
    elif net_effect is not None and control_block["confidence"] == "high":
        overall_conf = "high"

    pubs_out = []
    for p in pubs:
        hit_count = sum(
            1 for h in cite_hits if int(p.id) in (h.get("matched_publication_ids") or [])
        )
        pubs_out.append(
            {
                "id": p.id,
                "channel": p.channel,
                "published_url": p.published_url,
                "canonical_url": getattr(p, "canonical_url", None),
                "published_at": _iso(p.published_at),
                "status": p.status,
                "cite_hit_count": hit_count,
            }
        )

    return {
        "task_id": task.id,
        "prompt_id": task.prompt_id,
        "related_prompt_ids": {
            "direct": sorted(direct_prompt_ids),
            "spillover": sorted(spillover_ids),
            "control_count": len(control_ids),
        },
        "window_days": window_days,
        "first_published_at": _iso(first_pub_at),
        "publications": pubs_out,
        "cite_hits": {
            "total": len(cite_hits),
            "items": cite_hits[:50],
        },
        "prompt_mention": {
            **direct_block,
            "window": {
                "before_from": _iso(before_start),
                "published_at": _iso(anchor),
                "after_to": _iso(after_end),
            },
            "methodology_note": (
                "非随机实验：对照为同期未发布内容的意图词；"
                "请结合 cite_hits 与样本量解读，不足时勿展示确定变化率。"
            ),
        },
        "spillover_mention": spill_block,
        "control_mention": control_block,
        "net_effect_vs_control": net_effect,
        "confidence": overall_conf,
        "summary": {
            "published_count": len([p for p in pubs if p.published_url]),
            "cite_hit_total": len(cite_hits),
            "mention_rate_before": (
                None
                if direct_block["insufficient_data"]
                else direct_block["before"]["mention_rate"]
            ),
            "mention_rate_after": (
                None
                if direct_block["insufficient_data"]
                else direct_block["after"]["mention_rate"]
            ),
            "mention_rate_delta": direct_block["delta_mention_rate"],
            "insufficient_data": direct_block["insufficient_data"],
            "net_effect_vs_control": net_effect,
            "confidence": overall_conf,
            "has_proof": bool(pubs)
            and (
                len(cite_hits) > 0
                or int(direct_block["after"].get("snapshot_count") or 0) > 0
            ),
            "action_hint": (
                "数据不足以判断，建议提高巡检频率或延长观察期"
                if direct_block["insufficient_data"]
                else None
            ),
        },
    }


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
    brand, _ = await _brand_context_for_task(session, task, tenant)
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
    from app.geo.content.business_profile import display_brand, profile_brief_hints

    biz_row = None
    if getattr(task, "business_id", None):
        biz_row = await session.get(GeoOptimizationBusiness, task.business_id)
    hints = profile_brief_hints(getattr(biz_row, "profile", None) if biz_row else None)
    brand = display_brand(
        getattr(biz_row, "profile", None) if biz_row else None,
        fallback=getattr(tenant, "name", None) or f"租户{tenant_id}",
    )
    suggested = await suggest_brief_for_task(
        question=prompt.question,
        brand=brand,
        existing_brief=existing,
        overwrite=overwrite,
        llm=llm,
        chat_json=chat_json,
        profile_hints=hints,
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
    from app.geo.content.business_profile import normalize_profile, profile_brief_hints

    biz_row = None
    if getattr(task, "business_id", None):
        biz_row = await session.get(GeoOptimizationBusiness, task.business_id)
    profile = normalize_profile(getattr(biz_row, "profile", None) if biz_row else None)
    hints = profile_brief_hints(profile)
    question = prompt.question or task.title or ""
    extra = " ".join(
        filter(
            None,
            [
                profile.get("product_name"),
                profile.get("summary"),
                " ".join(profile.get("capabilities") or []),
            ],
        )
    )
    if extra:
        question = f"{question} {extra}"
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
            "business_id": getattr(f, "business_id", None),
        }
        for f in rows
    ]
    if getattr(task, "business_id", None):
        fact_dicts = [
            f
            for f in fact_dicts
            if f.get("business_id") in (None, task.business_id)
        ]
    brief = task.brief if isinstance(task.brief, dict) else {}
    if hints:
        brief = {**brief, **{k: v for k, v in hints.items() if k not in brief or not brief.get(k)}}
    result = retrieve_facts(
        fact_dicts,
        question=question,
        brief=brief,
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
    from app.geo.content.evidence_cite import strip_citation_appendix

    body = strip_citation_appendix(req.body_markdown)
    outline = dict(req.outline or (latest.outline if latest else {}) or {})
    article = GeoArticleVersion(
        task_id=task.id,
        version_no=version_no,
        kind="master",
        title=req.title.strip(),
        body_markdown=body,
        outline=outline,
        author_name=(latest.author_name if latest else None),
        generation_meta={
            "source": "manual_edit",
            "from_version": latest.version_no if latest else None,
        },
        created_by=ctx.user_id,
    )
    facts = await _task_facts(session, task.id)
    _refresh_article_citations(article, _fact_dicts(facts))
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
    brand, _ = await _brand_context_for_task(session, task, tenant)
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
        raise HTTPException(400, "没有可自动写入的修改（该项可能已通过，请先点「检查就绪」刷新）")
    insert = str(patch.get("insert_markdown") or "")
    if not insert.strip():
        raise HTTPException(400, f"没有可写入的「{req.code}」修改")
    hint = str(patch.get("cursor_hint") or "append")
    if hint == "rewrite":
        new_body = insert.lstrip("\n")
    elif hint == "prepend":
        new_body = insert.lstrip("\n") + ("\n" + old_body if old_body else "")
    else:
        new_body = (old_body.rstrip() + "\n" + insert.lstrip("\n")) if old_body else insert.lstrip("\n")
    if new_body.strip() == old_body.strip():
        raise HTTPException(400, "这次修改没有改变正文，请手工编辑或重新检查")

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
    lint_issues = lint_draft(rule_input.body_markdown or "", facts=rule_input.facts or [])
    for vb in rule_input.variant_bodies or []:
        lint_issues.extend(lint_draft(vb or "", facts=rule_input.facts or []))
    lint = lint_summary(lint_issues)
    blocks = blocks_payload(rule_input.body_markdown or "")
    lint_ok = bool(lint.get("blocks_ready")) if isinstance(lint, dict) else None
    tenant_for_score = await _ensure_tenant_exists(session, task.tenant_id)
    score_payload = compute_geo_score(
        rule_input,
        brief=task.brief if isinstance(task.brief, dict) else {},
        lint_ok=lint_ok,
        rule_checks=checks,
        brand=(
            (await _brand_context_for_task(session, task, tenant_for_score))[0]
            if tenant_for_score
            else None
        ),
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
    run_async: bool = Query(
        True,
        description="默认后台生成；false=同步等待（兼容脚本）",
    ),
    background_tasks: BackgroundTasks = None,  # filled by FastAPI
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # FastAPI injects BackgroundTasks; keep optional for unit tests
    if background_tasks is None:
        background_tasks = BackgroundTasks()
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

    if run_async:
        from app.geo.content.async_jobs import (
            KIND_GENERATE,
            create_job,
            job_payload,
            run_job_in_background,
        )

        job = await create_job(
            session,
            tenant_id=tenant_id,
            kind=KIND_GENERATE,
            ref_type="content_task",
            ref_id=task.id,
            request_meta={},
            created_by=ctx.user_id,
        )
        # create_job already committed; re-load task for status update
        task = await _get_task(session, task_id, tenant_id)
        task.status = "generating"
        await session.commit()
        background_tasks.add_task(run_job_in_background, job.id)
        return {
            "async": True,
            "job": job_payload(job),
            "task_id": task.id,
            "message": "母稿生成已排队，请轮询 /async-jobs/{id}",
        }

    task.status = "generating"
    await session.commit()
    try:
        llm = await resolve_llm_credentials(session, tenant_id)
        biz_row = None
        if getattr(task, "business_id", None):
            biz_row = await session.get(GeoOptimizationBusiness, task.business_id)
        from app.geo.content.business_profile import display_brand

        payload = await generate_master_article(
            tenant_name=display_brand(
                getattr(biz_row, "profile", None) if biz_row else None,
                fallback=tenant.name,
            ),
            question=prompt.question,
            facts=fact_dicts,
            llm=llm,
            brief=brief_norm,
        )
        body = to_markdown(payload)
        outline = outline_from_payload(payload)
        from app.geo.content.evidence_cite import attach_sentence_citations

        body, cites = attach_sentence_citations(body, fact_dicts)
        outline = dict(outline or {})
        outline["sentence_citations"] = cites
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
                "sentence_citations": cites,
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
    run_async: bool = Query(
        True,
        description="默认后台生成渠道稿；false=同步等待",
    ),
    background_tasks: BackgroundTasks = None,  # type: ignore[assignment]
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if background_tasks is None:
        background_tasks = BackgroundTasks()
    ctx.ensure_tenant(tenant_id)
    task = await _get_task(session, task_id, tenant_id)
    article = await _latest_article(session, task.id)
    if article is None:
        raise HTTPException(400, "请先生成或保存母稿")
    await _ensure_default_publishing_channels(session, tenant_id)

    channels = normalize_channels(req.channels or list(task.target_channels or []))
    if run_async:
        from app.geo.content.async_jobs import (
            KIND_VARIANTS,
            create_job,
            job_payload,
            run_job_in_background,
        )

        job = await create_job(
            session,
            tenant_id=tenant_id,
            kind=KIND_VARIANTS,
            ref_type="content_task",
            ref_id=task.id,
            request_meta={
                "channels": channels,
                "use_llm": bool(req.use_llm),
            },
            created_by=ctx.user_id,
        )
        task = await _get_task(session, task_id, tenant_id)
        task.status = "adapting"
        await session.commit()
        background_tasks.add_task(run_job_in_background, job.id)
        return {
            "async": True,
            "job": job_payload(job),
            "task_id": task.id,
            "message": "渠道稿生成已排队，请轮询 /async-jobs/{id}",
        }

    from app.geo.content.variant_execute import execute_variants_for_task

    try:
        result = await execute_variants_for_task(
            session,
            task_id=task.id,
            tenant_id=tenant_id,
            channels=channels,
            use_llm=bool(req.use_llm),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    task = await _get_task(session, task_id, tenant_id)
    article = await _latest_article(session, task.id)
    # Prefer full evaluate for sync path (richer score/lint)
    if article is not None:
        try:
            await _evaluate_and_store_rules(
                session, task, article, require_channels=False
            )
            await session.commit()
            await session.refresh(task)
        except Exception:  # noqa: BLE001
            pass
    payload = await _task_payload(session, task, detail=True)
    payload["variant_polish"] = result.get("variant_polish") or {
        "channels": result.get("channels") or [],
        "failed": result.get("failed") or [],
        "use_llm": bool(req.use_llm),
        "hard_gate": True,
        "article_standard": "full_article_v2",
    }
    payload["async"] = False
    return payload


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
    # Re-render HTML 正稿 so UI/export never sticks on raw MD markers
    if req.body_markdown is not None:
        from app.geo.content.md_to_html import (
            ensure_comparison_table_hint,
            html_to_plain,
            markdown_to_publish_html,
        )

        body_html = markdown_to_publish_html(variant.body_markdown or "", wrap_article=True)
        meta["body_html"] = body_html
        meta["body_plain"] = html_to_plain(body_html)
        meta["has_table"] = ensure_comparison_table_hint(variant.body_markdown or "")
        meta["export_format"] = "html"
        meta["delivery"] = "html_publish_ready"
        variant.export_format = "html"
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
    # Ensure HTML 正稿 exists (含表格渲染)
    meta = dict(variant.adapt_meta or {})
    body_html = meta.get("body_html")
    if not body_html:
        from app.geo.content.md_to_html import (
            ensure_comparison_table_hint,
            html_to_plain,
            markdown_to_publish_html,
        )

        body_html = markdown_to_publish_html(variant.body_markdown or "", wrap_article=True)
        meta["body_html"] = body_html
        meta["body_plain"] = html_to_plain(body_html)
        meta["has_table"] = ensure_comparison_table_hint(variant.body_markdown or "")
        meta["export_format"] = "html"
        meta["delivery"] = "html_publish_ready"
        variant.adapt_meta = meta
    variant.export_format = "html"
    await session.commit()
    return {
        "channel": channel,
        "title": variant.title,
        # 对外发布以 HTML 正稿为准；markdown 仅作中间态/兼容
        "body_html": body_html,
        "body_plain": meta.get("body_plain"),
        "body_markdown": variant.body_markdown,
        "export_format": "html",
        "has_table": bool(meta.get("has_table")),
        "quality": meta.get("quality") or "publish_ready",
        "status": variant.status,
        "copy_hint": "请复制 body_html 到渠道后台（含表格的正式正稿，非 MD）",
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
        apply_submit(task, note=req.note, submitter_id=ctx.user_id)
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


async def _resolve_active_period_id(
    session: AsyncSession, *, tenant_id: int, business_id: int | None
) -> int | None:
    """Pick current active optimization period (same business preferred)."""
    now = datetime.utcnow()
    rows = list(
        await session.scalars(
            select(GeoOptimizationPeriod)
            .where(
                GeoOptimizationPeriod.tenant_id == tenant_id,
                GeoOptimizationPeriod.status == "active",
                GeoOptimizationPeriod.starts_at <= now,
                GeoOptimizationPeriod.ends_at >= now,
            )
            .order_by(GeoOptimizationPeriod.id.desc())
        )
    )
    if not rows:
        return None
    if business_id is not None:
        for r in rows:
            if r.business_id == business_id:
                return int(r.id)
    for r in rows:
        if r.business_id is None:
            return int(r.id)
    return int(rows[0].id)


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
    from app.geo.content.attribution import normalize_url_for_match

    period_id = getattr(task, "period_id", None)
    if period_id is None:
        period_id = await _resolve_active_period_id(
            session,
            tenant_id=task.tenant_id,
            business_id=getattr(task, "business_id", None),
        )
        if period_id is not None:
            task.period_id = period_id
    pub = GeoPublication(
        variant_id=variant.id,
        channel=channel,
        publish_mode=publish_mode,
        published_url=published_url,
        canonical_url=normalize_url_for_match(published_url),
        published_at=datetime.utcnow(),
        status="published",
        period_id=period_id,
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
    if variant.status not in {"exported", "published", "draft"}:
        raise HTTPException(400, "请先生成该渠道稿，再推送")
    if variant.status == "draft":
        if not (variant.body_markdown or "").strip():
            raise HTTPException(400, "渠道稿还是空的，请先生成")
        variant.status = "exported"

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
    run_async: bool = Query(True, description="默认后台推送；false=同步"),
    background_tasks: BackgroundTasks = None,  # type: ignore[assignment]
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Push one task to multiple ready media channels (partial success allowed)."""
    from app.geo.content.connectors.social import SocialError
    from app.geo.content.connectors.webhook import WebhookConnectorError
    from app.geo.content.multi_push import execute_single_push, list_push_targets

    if background_tasks is None:
        background_tasks = BackgroundTasks()
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

    if run_async:
        from app.geo.content.async_jobs import (
            KIND_PUSH_BATCH,
            create_job,
            job_payload,
            run_job_in_background,
        )

        targets_meta = [
            {
                "channel": str(t.get("adapt_key") or t.get("channel_type") or ""),
                "account_id": t.get("account_id"),
            }
            for t in ready
        ]
        job = await create_job(
            session,
            tenant_id=req.tenant_id,
            kind=KIND_PUSH_BATCH,
            ref_type="content_task",
            ref_id=task.id,
            request_meta={
                "targets": targets_meta,
                "mode": req.mode,
                "create_publication": req.create_publication,
                "note": req.note,
            },
            created_by=ctx.user_id,
        )
        background_tasks.add_task(run_job_in_background, job.id)
        return {
            "async": True,
            "job": job_payload(job),
            "task_id": task.id,
            "queued_targets": len(targets_meta),
            "message": "批量推送已排队，请轮询 /async-jobs/{id}",
        }

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


@router.get("/metric-dictionary")
async def geo_metric_dictionary(
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """指标字典：分子/分母/时区/是否剔除探测题。"""
    from app.geo.content.metric_service import metric_dictionary_payload

    _ = ctx
    return metric_dictionary_payload()


@router.get("/metrics/brand-mention")
async def geo_brand_mention_metric(
    tenant_id: int = Query(...),
    days: int = Query(14, ge=1, le=365),
    all_time: bool = Query(False),
    exclude_simulated: bool | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """统一品牌提及率（所有页面应优先调此接口）。"""
    from app.geo.content.metric_service import brand_mention_rate

    ctx.ensure_tenant(tenant_id)
    result = await brand_mention_rate(
        session,
        tenant_id,
        days=days,
        all_time=all_time,
        exclude_simulated=exclude_simulated,
    )
    return result.to_dict()


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
    # W6: unc 桶 — 未挂 unit 的活跃意图词（日指标 scope_key=unc）
    prompts_unclassified = sum(
        1 for p in active_prompts if getattr(p, "unit_id", None) is None
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

    # 统一口径：默认观察期 14 上海日 + 样本构成（真/模拟/人工）
    from app.geo.content.metric_service import brand_mention_rate as unified_brand_mention
    from app.geo.content.metric_service import composition_of

    unified_14 = await unified_brand_mention(
        session, tenant_id, days=14, exclude_brand_probes=True
    )
    unified_all = await unified_brand_mention(
        session, tenant_id, all_time=True, exclude_brand_probes=True
    )
    sample_comp = composition_of(all_snaps)

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
        "prompts_unclassified": int(prompts_unclassified),
        "prompts_probe": int(prompts_probe),
        # Raw all-snapshot rate kept for debugging; primary KPI excludes probes.
        "visibility_mention_rate_raw": visibility_mention_rate(
            total_snapshots=snap_total, mention_snapshots=snap_mention
        ),
        # 主 KPI：默认 14 日观察期（上海时区），与日表/期次对齐
        "visibility_mention_rate": unified_14.rate
        if unified_14.visibility_n
        else split["visibility_mention_rate"],
        "visibility_mention_rate_all_time": unified_all.rate,
        "visibility_top1_rate": unified_14.top1_rate
        if unified_14.visibility_n
        else split.get("visibility_top1_rate"),
        "snapshots_visibility": unified_14.visibility_n or split["snapshots_visibility"],
        "snapshots_visibility_mention": unified_14.mentions
        if unified_14.visibility_n
        else split["snapshots_visibility_mention"],
        "snapshots_visibility_first": unified_14.top1_count
        if unified_14.visibility_n
        else split.get("snapshots_visibility_first"),
        "snapshots_probe": unified_14.probe_n or split["snapshots_probe"],
        "snapshots_probe_mention": unified_14.probe_hits
        if unified_14.probe_n
        else split["snapshots_probe_mention"],
        "probe_recognition_rate": unified_14.probe_rate
        if unified_14.probe_n
        else split["probe_recognition_rate"],
        "visibility_engines_covered": int(engines_covered or 0),
        "snapshots_with_competitors": int(snapshots_with_competitors),
        "snapshots_with_citations": int(snapshots_with_citations),
        "distinct_cited_domains": len(distinct_cited_domains),
        "sample_composition": sample_comp.to_dict(),
        "observation_window": unified_14.to_dict().get("window"),
        # Hygiene notes for UI
        "metric_notes": {
            "visibility_mention_rate": (
                "主 KPI=最近 14 个上海日历日；分母排除品牌探测题；"
                "无可见性样本时为 null（未测，≠0）。全时段见 visibility_mention_rate_all_time"
            ),
            "probe_recognition_rate": "仅品牌探测题；用于认知，不计入可见性提及率",
            "visibility_top1_rate": "可见性样本中 brand_position=first 占比（同观察期）",
            "sample_composition": "真采样/模拟/人工构成；含模拟时交付须强制标注",
            "timezone": "Asia/Shanghai",
        },
    }


@router.get("/deliverables/pack", response_model=None)
async def geo_deliverables_pack(
    tenant_id: int = Query(...),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    format: str | None = Query(None, description="json (default) or md"),
    real_only: bool = Query(True, description="交付默认只统计真采样"),
    top_domains: int = Query(10, ge=1, le=50),
    sample_snapshots: int = Query(12, ge=0, le=50),
    task_limit: int = Query(20, ge=0, le=100),
    business_id: int | None = Query(None, description="按优化业务切片"),
    unit_id: int | None = Query(None, description="按优化单元切片（优先于 business_id）"),
    period_id: int | None = Query(
        None, description="传入则锁定期次窗；closed 期次返回固化 pack"
    ),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    """Client-facing GEO deliverables pack composed from existing GEO data.

    可选 business_id / unit_id：快照与任务按意图词归属切片；并附带 daily_metrics 序列。
    period_id：优先返回关闭期次的固化交付物。
    """
    from app.geo.content.daily_metrics import (
        metric_row_payload,
        scope_business,
        scope_tenant,
        scope_unit,
    )
    from app.geo.content.snapshots import normalize_cited_urls

    from app.geo.content.metric_service import compute_metrics, composition_of
    from app.geo.content.monitoring_stance import normalize_stance
    from app.geo.content.time_windows import default_observation_window, shanghai_today
    from app.geo.content.ai_settings import ensure_ai_setting

    ctx.ensure_tenant(tenant_id)
    tenant = await _ensure_tenant_exists(session, tenant_id)

    # Closed period → frozen pack only
    if period_id is not None:
        prow = await session.get(GeoOptimizationPeriod, period_id)
        if prow is None or prow.tenant_id != tenant_id:
            raise HTTPException(404, "优化期次不存在")
        if prow.status == "closed":
            pack = (prow.result_meta or {}).get("deliverable_pack")
            if pack:
                if format == "md":
                    from fastapi.responses import PlainTextResponse

                    lines = [
                        f"# {pack.get('period_name') or '期次交付'}",
                        f"固化于 {pack.get('frozen_at')}",
                        "",
                        f"- 发布篇数：{(pack.get('headline') or {}).get('published_count')}",
                        f"- 期内任务：{(pack.get('headline') or {}).get('tasks_in_period')}",
                        f"- 覆盖意图词：{(pack.get('headline') or {}).get('prompts_covered')}",
                        f"- 提及率：{(pack.get('headline') or {}).get('mention_rate_before')} → {(pack.get('headline') or {}).get('mention_rate_after')}",
                        f"- Δ：{(pack.get('headline') or {}).get('mention_rate_delta')}",
                        "",
                        pack.get("methodology_note") or "",
                    ]
                    return PlainTextResponse("\n".join(lines), media_type="text/markdown")
                return {"frozen": True, "period_id": period_id, **pack}
        # open period: lock window to period dates
        s_at, e_at = prow.starts_at, prow.ends_at
        start_d = s_at.date() if hasattr(s_at, "date") else s_at
        end_d = e_at.date() if hasattr(e_at, "date") else e_at
        start_dt = datetime.combine(start_d, datetime.min.time())
        end_dt = datetime.combine(end_d, datetime.min.time())
        start, end = start_dt, end_dt
        period = {
            "from": start_d.isoformat(),
            "to": end_d.isoformat(),
            "days": max(1, (end_d - start_d).days + 1),
            "timezone": "Asia/Shanghai",
            "time_basis": "shanghai_calendar_day",
            "period_id": period_id,
            "period_name": prow.name,
        }
    else:
        # W1: 默认观察期对齐上海日历日 14 天；自定义 from/to 按日期解析
        if from_ or to:
            try:
                end_dt = (
                    parse_window_bound(to, label="to") if to else datetime.combine(
                        shanghai_today(), datetime.min.time()
                    )
                )
                start_dt = (
                    parse_window_bound(from_, label="from")
                    if from_
                    else end_dt - timedelta(days=13)
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if start_dt > end_dt:
                raise HTTPException(400, "from 不能晚于 to")
            start_d = start_dt.date() if hasattr(start_dt, "date") else start_dt
            end_d = end_dt.date() if hasattr(end_dt, "date") else end_dt
        else:
            start_d, end_d = default_observation_window(days=14)
            start_dt = datetime.combine(start_d, datetime.min.time())
            end_dt = datetime.combine(end_d, datetime.min.time())
        start, end = start_dt, end_dt

        period = {
            "from": start_d.isoformat(),
            "to": end_d.isoformat(),
            "days": max(1, (end_d - start_d).days + 1),
            "timezone": "Asia/Shanghai",
            "time_basis": "shanghai_calendar_day",
        }

    # W3: real_only + simulated samples → refuse export
    ai_row = await ensure_ai_setting(session, tenant_id)
    stance = normalize_stance(getattr(ai_row, "monitoring_stance", None))
    if stance == "real_only":
        pre = await compute_metrics(
            session,
            tenant_id,
            start=start_d,
            end=end_d,
            apply_stance=False,
        )
        if pre.composition.simulated > 0:
            raise HTTPException(
                400,
                f"监测定位为仅真采样，但观察窗内仍有 {pre.composition.simulated} 条模拟样本；"
                "请排除后重试，或改用 hybrid 并在交付中标注样本构成",
            )

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

    # ---- windowed snapshots + 统一指标（W1 上海日历日）----
    from app.geo.content.metric_service import load_snapshots_in_window

    own_domains = await _own_domains_for_tenant(session, tenant_id)
    window_snaps = await load_snapshots_in_window(
        session,
        tenant_id,
        start=start_d,
        end=end_d,
        prompt_ids=list(allowed_prompt_ids) if allowed_prompt_ids is not None else None,
    )
    if real_only:
        window_snaps = [
            s
            for s in window_snaps
            if not bool(getattr(s, "simulated", False))
            and (getattr(s, "sample_mode", None) or "") != "mock_persona"
        ]
    unified = await compute_metrics(
        session,
        tenant_id,
        start=start_d,
        end=end_d,
        prompt_ids=list(allowed_prompt_ids) if allowed_prompt_ids is not None else None,
        own_domains=own_domains,
    )
    split = unified.to_dict()

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

    engines_covered = len({s.engine for s in window_snaps})
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

    from app.geo.content.metric_service import composition_of

    sample_comp = composition_of(window_snaps)
    mention_rate = split["visibility_mention_rate"]
    top1_rate = split.get("visibility_top1_rate")
    if sample_comp.real <= 0:
        mention_rate = None
        top1_rate = None
    summary = {
        "prompts": len(active_prompts),
        "tasks": len(window_tasks),
        "published": published,
        "snapshots": len(window_snaps),
        "snapshots_visibility": split["snapshots_visibility"],
        "snapshots_visibility_mention": split["snapshots_visibility_mention"],
        "visibility_mention_rate": mention_rate,
        "visibility_top1_rate": top1_rate,
        "snapshots_probe": split["snapshots_probe"],
        "probe_recognition_rate": split["probe_recognition_rate"],
        "visibility_engines_covered": engines_covered,
        "snapshots_with_citations": snapshots_with_citations,
        "distinct_cited_domains": len(cite_items),
        "citation_count": citation_count_total,
        "prompts_need_recheck": sum(
            1 for p in active_prompts if "brand_missing" in (p.tags or [])
        ),
        "sample_composition": sample_comp.to_dict(),
        "has_simulated_samples": sample_comp.to_dict()["has_simulated"],
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
    pack["real_only"] = bool(real_only)
    pack["sample_composition"] = sample_comp.to_dict()
    pack["verdict"] = sample_comp.to_dict().get("verdict")
    pack["suitable_for_client"] = bool(sample_comp.to_dict().get("suitable_for_client"))
    pack["impact_language"] = "发布后观察到的相关变化（非确定因果）"

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


# ---------- 竞品报告资产 ----------


def _get_report(session, report_id: int, tenant_id: int):
    from app.models.geo_competitor_report import GeoCompetitorReport

    return session.get(GeoCompetitorReport, report_id)


@router.get("/competitor-reports")
async def list_competitor_reports(
    tenant_id: int = Query(...),
    competitor: str | None = Query(None),
    status: str | None = Query(None),
    business_id: int | None = Query(None),
    period_id: int | None = Query(None),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.competitor_reports import report_payload
    from app.models.geo_competitor_report import GeoCompetitorReport

    ctx.ensure_tenant(tenant_id)
    stmt = select(GeoCompetitorReport).where(GeoCompetitorReport.tenant_id == tenant_id)
    if competitor:
        stmt = stmt.where(GeoCompetitorReport.competitor == competitor.strip())
    if status:
        stmt = stmt.where(GeoCompetitorReport.status == status)
    if business_id:
        stmt = stmt.where(GeoCompetitorReport.business_id == business_id)
    if period_id:
        stmt = stmt.where(GeoCompetitorReport.period_id == period_id)
    stmt = stmt.order_by(GeoCompetitorReport.updated_at.desc(), GeoCompetitorReport.id.desc())
    rows = list(await session.scalars(stmt.limit(80)))
    return {"items": [report_payload(r) for r in rows], "total": len(rows)}


@router.post("/competitor-reports")
async def upsert_competitor_report(
    req: CompetitorReportUpsert,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.competitor_reports import report_payload, snapshot_version
    from app.models.geo_competitor_report import GeoCompetitorReport

    ctx.ensure_tenant(req.tenant_id)
    title = (req.title or "").strip() or f"竞品溯源报告 · {req.competitor.strip()}"
    row = GeoCompetitorReport(
        tenant_id=req.tenant_id,
        business_id=req.business_id,
        period_id=req.period_id,
        competitor=req.competitor.strip(),
        title=title[:240],
        status=req.status or "draft",
        insight=req.insight,
        action=req.action,
        note=req.note,
        markdown=req.markdown,
        source_urls=req.source_urls,
        platform_keys=req.platform_keys,
        evidence=req.evidence,
        version_no=1,
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.flush()
    session.add(snapshot_version(row, user_id=ctx.user_id))
    await session.commit()
    await session.refresh(row)
    return report_payload(row)


@router.get("/competitor-reports/{report_id}")
async def get_competitor_report(
    report_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.competitor_reports import report_payload
    from app.models.geo_competitor_report import GeoCompetitorReport, GeoCompetitorReportVersion

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoCompetitorReport, report_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "报告不存在")
    vers = list(
        await session.scalars(
            select(GeoCompetitorReportVersion)
            .where(GeoCompetitorReportVersion.report_id == row.id)
            .order_by(GeoCompetitorReportVersion.version_no.desc())
        )
    )
    return report_payload(row, versions=vers)


@router.patch("/competitor-reports/{report_id}")
async def patch_competitor_report(
    report_id: int,
    req: CompetitorReportPatch,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.competitor_reports import report_payload, snapshot_version
    from app.models.geo_competitor_report import GeoCompetitorReport

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoCompetitorReport, report_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "报告不存在")
    data = req.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    row.version_no = int(row.version_no or 1) + 1
    session.add(snapshot_version(row, user_id=ctx.user_id))
    await session.commit()
    await session.refresh(row)
    return report_payload(row)


@router.post("/competitor-reports/{report_id}/confirm")
async def confirm_competitor_report(
    report_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from datetime import datetime

    from app.geo.content.competitor_reports import report_payload
    from app.models.geo_competitor_report import GeoCompetitorReport

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoCompetitorReport, report_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "报告不存在")
    row.status = "confirmed"
    row.confirmed_by = ctx.user_id
    row.confirmed_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return report_payload(row)


@router.post("/competitor-reports/{report_id}/archive")
async def archive_competitor_report(
    report_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.competitor_reports import report_payload
    from app.models.geo_competitor_report import GeoCompetitorReport

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoCompetitorReport, report_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "报告不存在")
    row.status = "archived"
    await session.commit()
    await session.refresh(row)
    return report_payload(row)


@router.get("/competitor-reports/{report_id}/export")
async def export_competitor_report(
    report_id: int,
    tenant_id: int = Query(...),
    format: str = Query("md"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    from fastapi.responses import HTMLResponse, PlainTextResponse

    from app.geo.content.competitor_reports import markdown_to_simple_html
    from app.models.geo_competitor_report import GeoCompetitorReport

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoCompetitorReport, report_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "报告不存在")
    md = row.markdown or f"# {row.title}\n\n{row.insight or ''}\n\n{row.action or ''}\n"
    fmt = (format or "md").lower()
    if fmt in {"html", "htm"}:
        return HTMLResponse(markdown_to_simple_html(md, row.title))
    if fmt == "pdf":
        # 最小可用：返回可打印 HTML，浏览器另存 PDF
        return HTMLResponse(markdown_to_simple_html(md, row.title))
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8")


@router.post("/competitor-reports/{report_id}/restore")
async def restore_competitor_report_version(
    report_id: int,
    tenant_id: int = Query(...),
    version_no: int = Query(..., ge=1),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.geo.content.competitor_reports import report_payload, snapshot_version
    from app.models.geo_competitor_report import GeoCompetitorReport, GeoCompetitorReportVersion

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoCompetitorReport, report_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "报告不存在")
    ver = await session.scalar(
        select(GeoCompetitorReportVersion).where(
            GeoCompetitorReportVersion.report_id == row.id,
            GeoCompetitorReportVersion.version_no == version_no,
        )
    )
    if ver is None:
        raise HTTPException(404, "该版本不存在")
    row.insight = ver.insight
    row.action = ver.action
    row.note = ver.note
    row.markdown = ver.markdown
    row.version_no = int(row.version_no or 1) + 1
    session.add(snapshot_version(row, user_id=ctx.user_id))
    await session.commit()
    await session.refresh(row)
    vers = list(
        await session.scalars(
            select(GeoCompetitorReportVersion)
            .where(GeoCompetitorReportVersion.report_id == row.id)
            .order_by(GeoCompetitorReportVersion.version_no.desc())
        )
    )
    return report_payload(row, versions=vers)


@router.post("/competitor-reports/{report_id}/create-task")
async def create_task_from_competitor_report(
    report_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """把已确认/草稿报告的行动建议落成一条内容任务。"""
    from app.geo.content.brief import normalize_brief
    from app.geo.content.channel_profiles import normalize_channels
    from app.models.geo_competitor_report import GeoCompetitorReport

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoCompetitorReport, report_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "报告不存在")

    prompt = None
    evidence = row.evidence if isinstance(row.evidence, dict) else {}
    recs = evidence.get("recommendations") or []
    rec_prompt_id = None
    for rec in recs:
        if isinstance(rec, dict) and rec.get("prompt_id"):
            rec_prompt_id = int(rec["prompt_id"])
            break
    if rec_prompt_id:
        prompt = await session.scalar(
            select(GeoPrompt).where(
                GeoPrompt.id == rec_prompt_id,
                GeoPrompt.tenant_id == tenant_id,
                GeoPrompt.status == "active",
            )
        )
    if prompt is None and row.business_id:
        unit_ids = list(
            await session.scalars(
                select(GeoOptimizationUnit.id).where(
                    GeoOptimizationUnit.tenant_id == tenant_id,
                    GeoOptimizationUnit.business_id == row.business_id,
                )
            )
        )
        if unit_ids:
            prompt = await session.scalar(
                select(GeoPrompt)
                .where(
                    GeoPrompt.tenant_id == tenant_id,
                    GeoPrompt.status == "active",
                    GeoPrompt.unit_id.in_(unit_ids),
                )
                .order_by(GeoPrompt.id.desc())
                .limit(1)
            )
    if prompt is None:
        prompt = await session.scalar(
            select(GeoPrompt)
            .where(GeoPrompt.tenant_id == tenant_id, GeoPrompt.status == "active")
            .order_by(GeoPrompt.id.desc())
            .limit(1)
        )
    if prompt is None:
        raise HTTPException(400, "该客户还没有意图词，无法从报告建任务")

    existing = await session.scalar(
        select(GeoContentTask.id).where(
            GeoContentTask.tenant_id == tenant_id,
            GeoContentTask.prompt_id == prompt.id,
            GeoContentTask.status.notin_(["archived", "cancelled"]),
        )
    )
    if existing:
        return {
            "created": False,
            "task_id": existing,
            "editor_path": f"/geo/tasks/{existing}",
            "reason": "该意图词已有进行中的任务",
        }

    title = (row.action or "").strip().splitlines()[0][:120] or f"竞品对策 · {row.competitor}"
    brief = normalize_brief(
        {
            "ai_question": prompt.question,
            "notes": f"来自竞品报告 #{row.id}：{row.insight or ''}\n行动：{row.action or ''}",
            "competitors": [row.competitor],
            "must_cover": [row.competitor],
        }
    )
    business_id = row.business_id or await _resolve_task_business_id(session, prompt)
    period_id = row.period_id or await _resolve_active_period_id(
        session, tenant_id=tenant_id, business_id=business_id
    )
    task = GeoContentTask(
        tenant_id=tenant_id,
        prompt_id=prompt.id,
        business_id=business_id,
        period_id=period_id,
        title=title[:300],
        status="draft",
        target_channels=normalize_channels(["website"]),
        owner_user_id=ctx.user_id,
        pipeline_step="opportunity",
        brief=brief,
    )
    session.add(task)
    await session.flush()
    prompt.last_task_id = task.id
    await session.commit()
    return {
        "created": True,
        "task_id": task.id,
        "prompt_id": prompt.id,
        "title": title,
        "editor_path": f"/geo/tasks/{task.id}",
    }


@router.post("/onboarding/sitemap-audit")
async def geo_sitemap_audit(
    tenant_id: int = Query(...),
    website_url: str = Query(..., min_length=8),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    await _ensure_tenant_exists(session, tenant_id)
    from app.geo.sitemap_audit import audit_sitemap

    try:
        return await audit_sitemap(website_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/onboarding/sitemap-audit/create-tasks")
async def geo_sitemap_create_tasks(
    tenant_id: int = Query(...),
    body: dict = Body(default_factory=dict),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """把全站诊断机会落成意图词 + 内容任务（最多 5 条）。"""
    from app.geo.content.brief import normalize_brief
    from app.geo.content.channel_profiles import normalize_channels

    ctx.ensure_tenant(tenant_id)
    await _ensure_tenant_exists(session, tenant_id)
    items = list(body.get("items") or [])[:5]
    if not items:
        raise HTTPException(400, "请至少选择一条机会")
    default_biz = await session.scalar(
        select(GeoOptimizationBusiness)
        .where(
            GeoOptimizationBusiness.tenant_id == tenant_id,
            GeoOptimizationBusiness.status == "active",
        )
        .order_by(GeoOptimizationBusiness.id.desc())
        .limit(1)
    )
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for raw in items:
        title = str((raw or {}).get("title") or "").strip()[:200]
        action = str((raw or {}).get("action") or "").strip()
        urls = [str(u) for u in ((raw or {}).get("urls") or []) if str(u).strip()]
        question = title or action or (urls[0] if urls else "")
        if not question:
            skipped.append({"reason": "缺少标题"})
            continue
        existing_prompt = await session.scalar(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id,
                GeoPrompt.question == question,
            )
        )
        if existing_prompt is None:
            existing_prompt = GeoPrompt(
                tenant_id=tenant_id,
                question=question,
                status="active",
                source="sitemap_audit",
                tags=["from_sitemap", "geo_task_candidate"],
                priority=8,
            )
            session.add(existing_prompt)
            await session.flush()
        existing_task = await session.scalar(
            select(GeoContentTask.id).where(
                GeoContentTask.tenant_id == tenant_id,
                GeoContentTask.prompt_id == existing_prompt.id,
                GeoContentTask.status.notin_(["archived", "cancelled"]),
            )
        )
        if existing_task:
            skipped.append(
                {"prompt_id": existing_prompt.id, "task_id": existing_task, "reason": "已有任务"}
            )
            continue
        brief = normalize_brief(
            {
                "ai_question": question,
                "notes": f"{action}\n来源：{', '.join(urls[:4])}".strip(),
                "must_cover": urls[:3],
            }
        )
        business_id = getattr(default_biz, "id", None) or await _resolve_task_business_id(
            session, existing_prompt
        )
        period_id = await _resolve_active_period_id(
            session, tenant_id=tenant_id, business_id=business_id
        )
        task = GeoContentTask(
            tenant_id=tenant_id,
            prompt_id=existing_prompt.id,
            business_id=business_id,
            period_id=period_id,
            title=title or question[:300],
            status="draft",
            target_channels=normalize_channels(["website"]),
            owner_user_id=ctx.user_id,
            pipeline_step="opportunity",
            brief=brief,
        )
        session.add(task)
        await session.flush()
        existing_prompt.last_task_id = task.id
        created.append(
            {
                "task_id": task.id,
                "prompt_id": existing_prompt.id,
                "title": task.title,
                "editor_path": f"/geo/tasks/{task.id}",
            }
        )
    await session.commit()
    return {
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
    }


# ---------- 竞品别名（租户级）----------


@router.get("/competitor-aliases")
async def list_competitor_aliases(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.models.geo_competitor_alias import GeoCompetitorAlias

    ctx.ensure_tenant(tenant_id)
    rows = list(
        await session.scalars(
            select(GeoCompetitorAlias)
            .where(GeoCompetitorAlias.tenant_id == tenant_id)
            .order_by(GeoCompetitorAlias.canonical_name, GeoCompetitorAlias.alias_name)
        )
    )
    items = [
        {
            "id": r.id,
            "alias_name": r.alias_name,
            "canonical_name": r.canonical_name,
        }
        for r in rows
    ]
    # map form for frontend applyAliasMap
    alias_map = {r.alias_name: r.canonical_name for r in rows}
    return {"items": items, "alias_map": alias_map, "count": len(items)}


@router.put("/competitor-aliases")
async def put_competitor_aliases(
    tenant_id: int = Query(...),
    body: dict = Body(default_factory=dict),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """整表替换租户别名。body: { aliases: [{alias_name, canonical_name}] } 或 { alias_map: {a:c} }"""
    from sqlalchemy import delete

    from app.models.geo_competitor_alias import GeoCompetitorAlias

    ctx.ensure_tenant(tenant_id)
    payload = body or {}
    pairs: list[tuple[str, str]] = []
    if isinstance(payload.get("alias_map"), dict):
        for a, c in payload["alias_map"].items():
            aa, cc = str(a or "").strip(), str(c or "").strip()
            if aa and cc and aa != cc:
                pairs.append((aa, cc))
    for it in payload.get("aliases") or []:
        if not isinstance(it, dict):
            continue
        aa = str(it.get("alias_name") or "").strip()
        cc = str(it.get("canonical_name") or "").strip()
        if aa and cc and aa != cc:
            pairs.append((aa, cc))
    # de-dupe by alias
    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for a, c in pairs:
        if a in seen:
            continue
        seen.add(a)
        uniq.append((a[:200], c[:200]))

    await session.execute(
        delete(GeoCompetitorAlias).where(GeoCompetitorAlias.tenant_id == tenant_id)
    )
    for a, c in uniq:
        session.add(
            GeoCompetitorAlias(tenant_id=tenant_id, alias_name=a, canonical_name=c)
        )
    await session.commit()
    return {
        "count": len(uniq),
        "alias_map": {a: c for a, c in uniq},
        "items": [
            {"alias_name": a, "canonical_name": c} for a, c in uniq
        ],
    }


# ---------- 交付摘要存档 ----------


@router.get("/deliverables/archives")
async def list_deliverable_archives(
    tenant_id: int = Query(...),
    limit: int = Query(30, ge=1, le=100),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.models.geo_deliverable_archive import GeoDeliverableArchive

    ctx.ensure_tenant(tenant_id)
    rows = list(
        await session.scalars(
            select(GeoDeliverableArchive)
            .where(GeoDeliverableArchive.tenant_id == tenant_id)
            .order_by(GeoDeliverableArchive.id.desc())
            .limit(limit)
        )
    )
    return {
        "items": [
            {
                "id": r.id,
                "title": r.title,
                "period_from": _iso(r.period_from),
                "period_to": _iso(r.period_to),
                "share_token": r.share_token,
                "has_simulated": bool(
                    (r.pack_json or {}).get("has_simulated_samples")
                ),
                "created_at": _iso(r.created_at),
            }
            for r in rows
        ]
    }


@router.post("/deliverables/archives")
async def create_deliverable_archive(
    tenant_id: int = Query(...),
    body: dict = Body(default_factory=dict),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """body: { pack: {...}, title?, markdown? } — 生成即存"""
    import secrets

    from app.models.geo_deliverable_archive import GeoDeliverableArchive

    ctx.ensure_tenant(tenant_id)
    payload = body or {}
    pack = payload.get("pack")
    if not isinstance(pack, dict):
        raise HTTPException(400, "缺少 pack 对象")
    period = pack.get("period") or {}

    def _soft_dt(raw):
        if not raw:
            return None
        try:
            return _parse_captured_at(raw)
        except Exception:  # noqa: BLE001
            try:
                from datetime import date as date_cls

                if isinstance(raw, str) and len(raw) >= 10:
                    d = date_cls.fromisoformat(raw[:10])
                    return datetime.combine(d, datetime.min.time())
            except Exception:  # noqa: BLE001
                return None
        return None

    title = (payload.get("title") or "").strip() or (
        f"交付摘要 {period.get('from') or ''} ~ {period.get('to') or ''}".strip()
    )
    md = payload.get("markdown")
    if not md:
        try:
            md = render_deliverables_markdown(pack)
        except Exception:  # noqa: BLE001
            md = None
    token = secrets.token_urlsafe(24)
    row = GeoDeliverableArchive(
        tenant_id=tenant_id,
        title=title[:200],
        period_from=_soft_dt(period.get("from")),
        period_to=_soft_dt(period.get("to")),
        pack_json=pack,
        markdown=md,
        share_token=token,
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {
        "id": row.id,
        "title": row.title,
        "share_token": row.share_token,
        "created_at": _iso(row.created_at),
        "has_simulated": bool(pack.get("has_simulated_samples")),
    }


@router.get("/deliverables/archives/{archive_id}")
async def get_deliverable_archive(
    archive_id: int,
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from app.models.geo_deliverable_archive import GeoDeliverableArchive

    ctx.ensure_tenant(tenant_id)
    row = await session.get(GeoDeliverableArchive, archive_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "存档不存在")
    return {
        "id": row.id,
        "title": row.title,
        "period_from": _iso(row.period_from),
        "period_to": _iso(row.period_to),
        "share_token": row.share_token,
        "pack": row.pack_json,
        "markdown": row.markdown,
        "created_at": _iso(row.created_at),
    }
