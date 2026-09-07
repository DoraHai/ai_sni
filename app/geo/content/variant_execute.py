"""渠道稿生成核心逻辑：同步 API 与异步 job 共用，避免 routes 循环依赖。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.ai_settings import resolve_llm_credentials
from app.geo.content.channel_polish import ArticleQualityError, adapt_or_polish_for_channel
from app.geo.content.channel_polish_prompts import resolve_for_channel
from app.geo.content.channel_profiles import get_profile
from app.geo.content.channel_registry import (
    enabled_types_from_rows,
    filter_channels_by_registry,
    profile_key_for_registry_type,
    registry_row_dicts,
)
from app.geo.content.variants import GeoContentError, build_adapt_meta, normalize_channels
from app.models import (
    GeoArticleVersion,
    GeoChannelVariant,
    GeoContentTask,
    GeoFact,
    GeoOptimizationBusiness,
    GeoPublishingChannel,
    GeoTaskFact,
    Tenant,
)


async def _latest_article(
    session: AsyncSession, task_id: int, *, fresh: bool = False
) -> GeoArticleVersion | None:
    return await session.scalar(
        select(GeoArticleVersion)
        .where(GeoArticleVersion.task_id == task_id)
        .order_by(GeoArticleVersion.version_no.desc(), GeoArticleVersion.id.desc())
        .limit(1)
        .execution_options(populate_existing=fresh)
    )


async def _list_variants(
    session: AsyncSession, task_id: int
) -> list[GeoChannelVariant]:
    return list(
        await session.scalars(
            select(GeoChannelVariant)
            .where(GeoChannelVariant.task_id == task_id)
            .order_by(GeoChannelVariant.id.asc())
        )
    )


async def execute_variants_for_task(
    session: AsyncSession,
    *,
    task_id: int,
    tenant_id: int,
    channels: list[str] | None,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Generate/overwrite channel variants for a task. Commits at end.

    Returns polish stats; raises ValueError on hard failure (no article / all rejected).
    """
    task = await session.get(GeoContentTask, task_id)
    if task is None or task.tenant_id != tenant_id:
        raise ValueError("内容任务不存在")
    # Serialize regeneration with manual edits and review decisions.
    await session.refresh(task, with_for_update=True)
    article = await _latest_article(session, task.id)
    if article is None:
        raise ValueError("请先生成或保存母稿")

    ch_rows = list(
        await session.scalars(
            select(GeoPublishingChannel).where(
                GeoPublishingChannel.tenant_id == tenant_id
            )
        )
    )
    registry_rows = registry_row_dicts(ch_rows)
    enabled_types = enabled_types_from_rows(registry_rows)
    raw_picks = list(channels or task.target_channels or [])
    channel_list = filter_channels_by_registry(
        normalize_channels(raw_picks),
        enabled_types=enabled_types or None,
    )
    # Keep 分发平台 types (docs / industry_media / …) instead of collapsing to adapt keys.
    if enabled_types:
        picked: list[str] = []
        for item in raw_picks:
            key = str(item or "").strip().lower()
            if key in enabled_types and key not in picked:
                picked.append(key)
            elif key:
                for ctype in enabled_types:
                    if profile_key_for_registry_type(ctype) == key and ctype not in picked:
                        picked.append(ctype)
        if picked:
            channel_list = picked
    if not channel_list:
        raise ValueError("没有可用的启用发布渠道，请先在「发布渠道」配置中启用")

    tenant = await session.get(Tenant, tenant_id)
    from app.geo.content.business_profile import display_brand

    brand = tenant.name if tenant else None
    if getattr(task, "business_id", None):
        biz = await session.get(GeoOptimizationBusiness, task.business_id)
        brand = display_brand(getattr(biz, "profile", None) if biz else None, fallback=brand or "")
    llm = None
    if use_llm:
        llm = await resolve_llm_credentials(session, tenant_id)

    existing = {v.channel: v for v in await _list_variants(session, task.id)}
    created: list[str] = []
    failed: list[dict[str, Any]] = []
    polish_stats = {"llm": 0, "fallback": 0, "rejected": 0}

    fact_rows = list(
        (
            await session.execute(
                select(GeoFact)
                .join(GeoTaskFact, GeoTaskFact.fact_id == GeoFact.id)
                .where(GeoTaskFact.task_id == task.id)
                .order_by(GeoTaskFact.sort_order.asc(), GeoFact.id.asc())
            )
        ).scalars()
    )
    fact_dicts = [
        {
            "id": f.id,
            "title": f.title,
            "statement": f.statement,
            "source_name": f.source_name,
            "trust_level": f.trust_level,
        }
        for f in fact_rows
    ]

    prepared: list[tuple[str, dict[str, Any] | None]] = []
    for channel in channel_list:
        prompts = await resolve_for_channel(session, tenant_id, channel)
        prepared.append((channel, prompts))

    async def _polish_one(channel: str, prompts: dict[str, Any] | None):
        try:
            triple = await adapt_or_polish_for_channel(
                channel,
                article.title,
                article.body_markdown,
                article.outline or {},
                llm=llm,
                brand=brand,
                use_llm=bool(use_llm),
                prompts=prompts,
                facts=fact_dicts,
            )
            return channel, triple, None
        except (ArticleQualityError, GeoContentError) as exc:
            return channel, None, exc

    polished = await asyncio.gather(
        *[_polish_one(ch, pr) for ch, pr in prepared],
        return_exceptions=False,
    )

    async def _fresh_brand_checks():
        from app.geo.content.brand_geo import markdown_brand_validation
        from app.geo.content.routes import (
            _brand_context_for_task,
            _ensure_tenant_exists,
        )

        current_article = await _latest_article(session, task.id, fresh=True)
        if current_article is None or current_article.id != article.id:
            raise ValueError("母稿已变化，请基于最新版本重新生成渠道稿")
        current_tenant = await _ensure_tenant_exists(
            session, tenant_id, fresh=True
        )
        current_brand, _ = await _brand_context_for_task(
            session, task, current_tenant, fresh=True
        )
        master = markdown_brand_validation(
            brand=current_brand,
            title=current_article.title or task.title or "",
            body_markdown=current_article.body_markdown or "",
        )
        variants = []
        for channel, triple, exc in polished:
            if exc is not None or triple is None:
                continue
            candidate_title, candidate_body, _ = triple
            validation = markdown_brand_validation(
                brand=current_brand,
                title=candidate_title or "",
                body_markdown=candidate_body or "",
            )
            if validation.get("passed") is False:
                variants.append(
                    {
                        "channel": channel,
                        "brand_validation": validation,
                    }
                )
        return current_article, current_tenant, current_brand, master, variants

    async def _stop_for_brand_change(master_validation, variant_failures):
        from app.geo.content.review import invalidate_review

        issues = list(master_validation.get("issues") or [])
        for row in variant_failures:
            validation = row["brand_validation"]
            first = (validation.get("issues") or ["品牌标准未满足"])[0]
            issues.append(f"{row['channel']}：{first}")
        prev = task.rule_result if isinstance(task.rule_result, dict) else {}
        old_checks = [
            row
            for row in (prev.get("checks") or [])
            if row.get("code") not in {"geo_brand_standard", "geo_variant_brand_standard"}
        ]
        old_checks.append(
            {
                "code": "geo_brand_standard",
                "passed": bool(master_validation.get("passed")),
                "message": (
                    "当前母稿品牌标准已通过"
                    if master_validation.get("passed")
                    else str((master_validation.get("issues") or ["品牌标准未满足"])[0])
                ),
            }
        )
        if variant_failures:
            old_checks.append(
                {
                    "code": "geo_variant_brand_standard",
                    "passed": False,
                    "message": issues[-1],
                    "details": variant_failures,
                }
            )
        task.rule_result = {
            **prev,
            "ready": False,
            "checks": old_checks,
            "brand_validation": master_validation,
            "variant_brand_validation": variant_failures,
            "checked_at": datetime.utcnow().isoformat(),
            "source": "variant_execute_fresh_brand_gate",
        }
        task.status = "needs_fix"
        task.ready_at = None
        invalidate_review(task)
        await session.commit()
        raise ValueError("当前品牌标准已变化，渠道稿未标记就绪：" + "；".join(issues[:4]))

    article, tenant, brand, master_brand, variant_brand_failures = (
        await _fresh_brand_checks()
    )
    if master_brand.get("passed") is False or variant_brand_failures:
        await _stop_for_brand_change(master_brand, variant_brand_failures)

    for channel, triple, exc in polished:
        if exc is not None:
            polish_stats["rejected"] += 1
            issues = list(getattr(exc, "issues", None) or [str(exc)])
            failed.append(
                {
                    "channel": channel,
                    "reason": "article_quality"
                    if isinstance(exc, ArticleQualityError)
                    else "polish_error",
                    "issues": issues[:8],
                    "message": str(exc),
                }
            )
            continue
        title, body, polish_meta = triple

        if polish_meta.get("quality") == "adapted_draft_not_publishable" or polish_meta.get(
            "fallback"
        ):
            polish_stats["fallback"] += 1
            issues = list(polish_meta.get("quality_issues") or [])
            if issues:
                failed.append(
                    {
                        "channel": channel,
                        "reason": "article_quality",
                        "issues": issues[:8],
                        "message": "已出非正式渠道稿，未过发布门控",
                    }
                )
        else:
            polish_stats["llm"] += 1

        meta = build_adapt_meta(
            channel,
            master_version_id=article.id,
            title=title,
            body_md=body,
            extra=polish_meta,
        )
        if channel in existing:
            variant = existing[channel]
            if variant.status == "published":
                failed.append(
                    {
                        "channel": channel,
                        "reason": "already_published",
                        "issues": ["已发布，跳过覆盖"],
                        "message": f"渠道 {channel} 已发布",
                    }
                )
                polish_stats["rejected"] += 1
                continue
            profile = get_profile(channel)
            variant.title = title
            variant.body_markdown = body
            variant.article_version_id = article.id
            if (variant.adapt_meta or {}).get("push_deliveries"):
                meta["push_deliveries"] = variant.adapt_meta["push_deliveries"]
            if (variant.adapt_meta or {}).get("publication_monitor"):
                meta["publication_monitor"] = variant.adapt_meta["publication_monitor"]
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

    # Generation can take long enough for another transaction to change the
    # business profile. Refresh once more immediately before persisting drafts
    # or deriving readiness from them.
    article, tenant, brand, master_brand, variant_brand_failures = (
        await _fresh_brand_checks()
    )
    if master_brand.get("passed") is False or variant_brand_failures:
        await _stop_for_brand_change(master_brand, variant_brand_failures)

    if not created and failed:
        detail_bits = []
        for f in failed[:5]:
            ch = f.get("channel")
            iss = f.get("issues") or [f.get("message")]
            detail_bits.append(f"{ch}: " + "；".join(str(x) for x in iss[:3]))
        raise ValueError(
            "渠道成稿均未过完整文章硬门控，未保存正稿。" + " | ".join(detail_bits)
        )

    task.target_channels = sorted(set((task.target_channels or []) + created))
    if created:
        from app.geo.content.review import invalidate_review

        invalidate_review(task)

    # Soft status: stay editing/needs_fix until explicit check; don't mark generating
    if task.status == "generating":
        task.status = "editing"
    await session.flush()

    # Light rule re-score (channel_variant_ready etc.)
    try:
        from app.geo.content.rules import RuleInput, is_ready, run_checks
        from app.models import GeoPrompt

        variants_now = await _list_variants(session, task.id)
        prompt_q = ""
        if task.prompt_id:
            p = await session.get(GeoPrompt, task.prompt_id)
            if p:
                prompt_q = p.question or ""
        ri = RuleInput(
            question=prompt_q,
            title=article.title or task.title or "",
            body_markdown=article.body_markdown or "",
            outline=article.outline or {},
            facts=fact_dicts,
            target_channels=list(task.target_channels or []),
            variants=[v.channel for v in variants_now],
            author_name=article.author_name,
            default_author=tenant.name if tenant else None,
            variant_bodies=[v.body_markdown or "" for v in variants_now],
        )
        checks = run_checks(ri)
        ready = is_ready(checks, require_channels=False)
        prev = task.rule_result if isinstance(task.rule_result, dict) else {}
        from app.geo.content.brand_geo import markdown_brand_validation

        brand_validation = markdown_brand_validation(
            brand=brand,
            title=article.title or task.title or "",
            body_markdown=article.body_markdown or "",
        )
        check_dicts = [c.to_dict() for c in checks]
        brand_ok = bool(brand_validation.get("passed"))
        check_dicts.append(
            {
                "code": "geo_brand_standard",
                "passed": brand_ok,
                "message": (
                    f"开篇与结论已点名品牌「{brand_validation.get('brand') or '当前品牌'}」"
                    if brand_ok
                    else str((brand_validation.get("issues") or ["品牌标准未满足"])[0])
                ),
                "action": "核对品牌配置，并在开篇与结论中使用有证据支持的品牌名",
                "details": list(brand_validation.get("issues") or []),
            }
        )
        if not brand_ok:
            ready = False
        task.rule_result = {
            **prev,
            "ready": ready,
            "checks": check_dicts,
            "brand_validation": brand_validation,
            "variant_polish": {
                **polish_stats,
                "failed": failed,
                "created": created,
            },
            "variant_channels": [v.channel for v in variants_now],
            "target_channels": list(task.target_channels or []),
            "checked_at": datetime.utcnow().isoformat(),
            "source": "variant_execute",
        }
        if ready and task.status not in {"exported", "published"}:
            task.status = "ready"
            task.ready_at = task.ready_at or datetime.utcnow()
        elif task.status not in {"exported", "published"}:
            task.status = "needs_fix"
    except Exception:  # noqa: BLE001
        pass

    await session.commit()
    await session.refresh(task)
    return {
        "task_id": task.id,
        "channels": created,
        "failed": failed,
        "variant_polish": {
            **polish_stats,
            "use_llm": bool(use_llm),
            "channels": created,
            "failed": failed,
            "hard_gate": True,
            "article_standard": "full_article_v2",
        },
    }
