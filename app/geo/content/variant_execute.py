"""渠道稿生成核心逻辑：同步 API 与异步 job 共用，避免 routes 循环依赖。"""

from __future__ import annotations

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
    session: AsyncSession, task_id: int
) -> GeoArticleVersion | None:
    return await session.scalar(
        select(GeoArticleVersion)
        .where(GeoArticleVersion.task_id == task_id)
        .order_by(GeoArticleVersion.version_no.desc(), GeoArticleVersion.id.desc())
        .limit(1)
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
    channel_list = filter_channels_by_registry(
        normalize_channels(channels or list(task.target_channels or [])),
        enabled_types=enabled_types or None,
    )
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

    for channel in channel_list:
        prompts = await resolve_for_channel(session, tenant_id, channel)
        try:
            title, body, polish_meta = await adapt_or_polish_for_channel(
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
        except ArticleQualityError as exc:
            polish_stats["rejected"] += 1
            failed.append(
                {
                    "channel": channel,
                    "reason": "article_quality",
                    "issues": list(exc.issues)[:8],
                    "message": str(exc),
                }
            )
            continue
        except GeoContentError as exc:
            polish_stats["rejected"] += 1
            failed.append(
                {
                    "channel": channel,
                    "reason": "polish_error",
                    "issues": [str(exc)],
                    "message": str(exc),
                }
            )
            continue

        if polish_meta.get("fallback"):
            polish_stats["fallback"] += 1
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
        task.rule_result = {
            **prev,
            "ready": ready,
            "checks": [c.to_dict() for c in checks],
            "variant_channels": [v.channel for v in variants_now],
            "target_channels": list(task.target_channels or []),
            "checked_at": datetime.utcnow().isoformat(),
            "source": "variant_execute",
        }
        if ready and task.status not in {"exported", "published"}:
            task.status = "ready"
            task.ready_at = task.ready_at or datetime.utcnow()
        elif task.status not in {"exported", "published", "ready"}:
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
