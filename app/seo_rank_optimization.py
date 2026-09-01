"""Turn material rank drops into safe, review-only SEO content tasks."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.seo import (
    SeoContentAsset,
    SeoKeywordAsset,
    SeoRankSnapshot,
    SeoSitePage,
)


logger = logging.getLogger(__name__)

AUTO_RANK_DROP_AUTHOR = "SEO 自动优化建议"
AUTO_RANK_DROP_TITLE_PREFIX = "【自动建议·勿发布】"
ACTIVE_CONTENT_STATUSES = {"planned", "drafting", "review", "ready"}
ENGINE_LABELS = {"baidu": "百度", "google": "Google", "bing": "Bing"}
DEVICE_LABELS = {"desktop": "PC", "mobile": "移动端"}


@dataclass(frozen=True)
class RankDropCandidate:
    latest: SeoRankSnapshot
    previous: SeoRankSnapshot
    decline: int


def _effective_rank(value: int | None) -> int:
    return int(value) if value is not None else 101


def _keyword_ids(content: SeoContentAsset) -> set[int]:
    values = content.keyword_ids or ([content.keyword_id] if content.keyword_id else [])
    return {int(value) for value in values if value is not None}


def _rank_label(rank: int | None) -> str:
    return f"第 {rank} 位" if rank is not None else "跌出前 100"


def _rank_drop_candidates(
    rows: list[SeoRankSnapshot],
    *,
    trigger_snapshot_ids: set[int],
    threshold: int,
) -> list[RankDropCandidate]:
    grouped: dict[tuple[int, str, str], list[SeoRankSnapshot]] = defaultdict(list)
    for row in sorted(rows, key=lambda value: (value.checked_at, value.id), reverse=True):
        grouped[(int(row.keyword_id), row.engine, row.device)].append(row)

    candidates: list[RankDropCandidate] = []
    for values in grouped.values():
        if len(values) != 2 or int(values[0].id) not in trigger_snapshot_ids:
            continue
        # Do not interpret two history rows imported in one batch as a new alert.
        if int(values[1].id) in trigger_snapshot_ids:
            continue
        decline = _effective_rank(values[0].rank) - _effective_rank(values[1].rank)
        if values[1].rank is not None and decline >= threshold:
            candidates.append(RankDropCandidate(values[0], values[1], decline))
    return candidates


def _suggestion_outline(
    keyword: SeoKeywordAsset,
    candidate: RankDropCandidate,
) -> str:
    latest = candidate.latest
    engine = ENGINE_LABELS.get(latest.engine, latest.engine)
    device = DEVICE_LABELS.get(latest.device, latest.device)
    landing = keyword.landing_page or "尚未绑定承接页"
    return "\n".join(
        [
            "自动触发依据（勿直接发布）",
            f"- 目标关键词：{keyword.keyword}",
            f"- 监测口径：{engine} / {device}",
            f"- 排名变化：{_rank_label(candidate.previous.rank)} → {_rank_label(latest.rank)}，下降 {candidate.decline} 位",
            f"- 当前承接页：{landing}",
            "",
            "人工优化建议",
            "1. 核对搜索意图与当前承接页是否仍匹配。",
            "2. 检查 Title、Description、H1 和正文主题覆盖，不堆砌关键词。",
            "3. 对比当前排名靠前页面的内容结构、时效性与信任信号。",
            "4. 补充相关站内链接，优化后由人工提交审核。",
        ]
    )


async def create_rank_drop_content_tasks(
    session: AsyncSession,
    *,
    tenant_id: int,
    site_id: int,
    trigger_snapshot_ids: set[int],
) -> dict[str, object]:
    """Create idempotent planned tasks for newly observed material rank drops."""
    if not trigger_snapshot_ids or not get_settings().seo_rank_drop_tasks_enabled:
        return {"created": 0, "task_ids": [], "skipped_existing": 0}

    # Manual imports can arrive concurrently. Serialize recommendation decisions
    # per tenant/site so both transactions cannot observe "no active task".
    await session.scalar(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(f"seo-rank-drop:{tenant_id}:{site_id}", 0)
            )
        )
    )
    threshold = max(1, int(get_settings().seo_rank_drop_task_threshold))
    trigger_rows = list(
        await session.scalars(
            select(SeoRankSnapshot).where(
                SeoRankSnapshot.id.in_(trigger_snapshot_ids),
                SeoRankSnapshot.tenant_id == tenant_id,
                SeoRankSnapshot.site_id == site_id,
                SeoRankSnapshot.subject_type == "own",
            )
        )
    )
    if not trigger_rows:
        return {"created": 0, "task_ids": [], "skipped_existing": 0}

    keyword_ids = {int(row.keyword_id) for row in trigger_rows}
    engines = {row.engine for row in trigger_rows}
    devices = {row.device for row in trigger_rows}
    ranked = (
        select(
            SeoRankSnapshot.id.label("rank_id"),
            func.row_number()
            .over(
                partition_by=(
                    SeoRankSnapshot.keyword_id,
                    SeoRankSnapshot.engine,
                    SeoRankSnapshot.device,
                ),
                order_by=(
                    SeoRankSnapshot.checked_at.desc(),
                    SeoRankSnapshot.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(
            SeoRankSnapshot.tenant_id == tenant_id,
            SeoRankSnapshot.site_id == site_id,
            SeoRankSnapshot.subject_type == "own",
            SeoRankSnapshot.keyword_id.in_(keyword_ids),
            SeoRankSnapshot.engine.in_(engines),
            SeoRankSnapshot.device.in_(devices),
        )
        .subquery()
    )
    latest_rows = list(
        await session.scalars(
            select(SeoRankSnapshot)
            .join(ranked, ranked.c.rank_id == SeoRankSnapshot.id)
            .where(ranked.c.position <= 2)
        )
    )
    candidates = _rank_drop_candidates(
        latest_rows,
        trigger_snapshot_ids=trigger_snapshot_ids,
        threshold=threshold,
    )
    if not candidates:
        return {"created": 0, "task_ids": [], "skipped_existing": 0}

    keywords = {
        int(row.id): row
        for row in await session.scalars(
            select(SeoKeywordAsset).where(
                SeoKeywordAsset.tenant_id == tenant_id,
                SeoKeywordAsset.site_id == site_id,
                SeoKeywordAsset.id.in_({item.latest.keyword_id for item in candidates}),
                SeoKeywordAsset.status == "active",
            )
        )
    }
    active_contents = list(
        await session.scalars(
            select(SeoContentAsset).where(
                SeoContentAsset.tenant_id == tenant_id,
                SeoContentAsset.site_id == site_id,
                SeoContentAsset.status.in_(ACTIVE_CONTENT_STATUSES),
            )
        )
    )
    active_keyword_ids = {
        keyword_id
        for content in active_contents
        for keyword_id in _keyword_ids(content)
    }
    occupied_page_ids = {
        int(content.source_page_id)
        for content in await session.scalars(
            select(SeoContentAsset).where(
                SeoContentAsset.tenant_id == tenant_id,
                SeoContentAsset.site_id == site_id,
                SeoContentAsset.source_page_id.is_not(None),
            )
        )
        if content.source_page_id is not None
    }
    pages = list(
        await session.scalars(
            select(SeoSitePage).where(
                SeoSitePage.tenant_id == tenant_id,
                SeoSitePage.site_id == site_id,
                SeoSitePage.target_keyword_id.in_(list(keywords)),
            )
        )
    )
    page_by_keyword = {
        int(page.target_keyword_id): page
        for page in pages
        if page.target_keyword_id is not None and page.id not in occupied_page_ids
    }

    created_rows: list[SeoContentAsset] = []
    skipped_existing = 0
    for candidate in sorted(candidates, key=lambda item: item.latest.id):
        keyword_id = int(candidate.latest.keyword_id)
        keyword = keywords.get(keyword_id)
        if keyword is None or keyword_id in active_keyword_ids:
            skipped_existing += 1
            continue
        page = page_by_keyword.get(keyword_id)
        row = SeoContentAsset(
            tenant_id=tenant_id,
            site_id=site_id,
            source_page_id=page.id if page is not None else None,
            keyword_id=keyword_id,
            keyword_ids=[keyword_id],
            content_type="landing" if keyword.landing_page or page is not None else "article",
            title=f"{AUTO_RANK_DROP_TITLE_PREFIX}{keyword.keyword}排名下降优化",
            outline=_suggestion_outline(keyword, candidate),
            source_text=(
                f"rank_snapshot_id={candidate.latest.id}; "
                f"engine={candidate.latest.engine}; device={candidate.latest.device}; "
                f"previous_rank={candidate.previous.rank}; latest_rank={candidate.latest.rank}"
            ),
            author=AUTO_RANK_DROP_AUTHOR,
            status="planned",
        )
        session.add(row)
        created_rows.append(row)
        active_keyword_ids.add(keyword_id)
        if page is not None:
            occupied_page_ids.add(int(page.id))

    if created_rows:
        await session.flush()
        logger.info(
            "[SEO][OPTIMIZATION] rank-drop tasks created tenant_id=%s site_id=%s count=%s",
            tenant_id,
            site_id,
            len(created_rows),
        )
    return {
        "created": len(created_rows),
        "task_ids": [int(row.id) for row in created_rows],
        "skipped_existing": skipped_existing,
    }


async def create_rank_drop_content_tasks_safely(
    session: AsyncSession,
    *,
    tenant_id: int,
    site_id: int,
    trigger_snapshot_ids: set[int],
) -> dict[str, object]:
    """Keep recommendation failures from rolling back valid ranking evidence."""
    try:
        async with session.begin_nested():
            return await create_rank_drop_content_tasks(
                session,
                tenant_id=tenant_id,
                site_id=site_id,
                trigger_snapshot_ids=trigger_snapshot_ids,
            )
    except Exception:  # noqa: BLE001
        logger.exception(
            "[SEO][OPTIMIZATION] rank-drop task generation failed "
            "tenant_id=%s site_id=%s snapshots=%s",
            tenant_id,
            site_id,
            len(trigger_snapshot_ids),
        )
        return {
            "created": 0,
            "task_ids": [],
            "skipped_existing": 0,
            "error": "optimization_task_generation_failed",
        }
