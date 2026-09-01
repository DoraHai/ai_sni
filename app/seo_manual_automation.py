"""Permission-gated, bounded manual reruns for SEO automation jobs."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.models.module_workspace import SeoSite
from app.models.seo import (
    SeoAutomationRun,
    SeoBacklink,
    SeoCompetitor,
    SeoCompetitorEvent,
    SeoKeywordAsset,
)
from app.process_lock import acquire_file_lock, release_file_lock
from app.seo_automation_runs import finish_automation_run, mark_automation_run_running
from app.seo_competitor import (
    COMPETITOR_MANUAL_COOLDOWN_SECONDS,
    CompetitorCollectionError,
    collect_competitor_content,
)
from app.seo_crawler import fetch_url
from app.seo_monitoring_jobs import backlink_present
from app.seo_rank_limits import (
    MANUAL_RANK_RESERVATION_TTL_SECONDS,
    ManualRankLimitError,
    ManualRankReservation,
    SEO_RANK_COLLECTION_LOCK_PATH,
    renew_manual_rank_collection,
    reserve_manual_rank_collection,
    settle_manual_rank_collection,
)


logger = logging.getLogger(__name__)
MANUAL_AUTOMATION_JOB_TYPES = {"ranking", "competitor", "backlink"}


@dataclass
class ManualAutomationError(Exception):
    code: str
    message: str
    status_code: int = 409
    retry_after: int = 0

    def __str__(self) -> str:
        return self.message


def _target_conditions(tenant_id: int, site_id: int, job_type: str):
    if job_type == "ranking":
        return SeoKeywordAsset, [
            SeoKeywordAsset.tenant_id == tenant_id,
            SeoKeywordAsset.site_id == site_id,
            SeoKeywordAsset.status == "active",
        ]
    if job_type == "competitor":
        cutoff = datetime.utcnow() - timedelta(seconds=COMPETITOR_MANUAL_COOLDOWN_SECONDS)
        return SeoCompetitor, [
            SeoCompetitor.tenant_id == tenant_id,
            SeoCompetitor.site_id == site_id,
            SeoCompetitor.status == "active",
            or_(SeoCompetitor.last_checked_at.is_(None), SeoCompetitor.last_checked_at < cutoff),
        ]
    if job_type == "backlink":
        return SeoBacklink, [
            SeoBacklink.tenant_id == tenant_id,
            SeoBacklink.site_id == site_id,
            SeoBacklink.status.in_(["active", "lost"]),
        ]
    raise ManualAutomationError("unsupported_job", "不支持该自动化任务", 400)


async def manual_target_count(
    session: AsyncSession,
    tenant_id: int,
    site_id: int,
    job_type: str,
) -> int:
    model, conditions = _target_conditions(tenant_id, site_id, job_type)
    count = int(
        await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    )
    settings = get_settings()
    if job_type == "ranking":
        keyword_limit = min(
            max(1, settings.seo_rank_scheduler_max_keywords_per_tenant),
            max(1, settings.seo_rank_scheduler_max_requests_per_run // 2),
            max(1, settings.seo_manual_rank_max_requests_per_day // 2),
        )
        return min(count, keyword_limit) * 2
    if job_type == "competitor":
        return min(count, max(1, settings.seo_competitor_scheduler_max_per_run))
    return min(count, max(1, settings.seo_backlink_scheduler_max_per_run))


async def reserve_manual_automation_run(
    session: AsyncSession,
    *,
    tenant_id: int,
    site_id: int,
    job_type: str,
    requested_by: int | None,
) -> SeoAutomationRun:
    if job_type not in MANUAL_AUTOMATION_JOB_TYPES:
        raise ManualAutomationError("unsupported_job", "不支持该自动化任务", 400)
    site = await session.scalar(
        select(SeoSite)
        .where(SeoSite.id == site_id, SeoSite.tenant_id == tenant_id)
        .with_for_update()
    )
    if site is None:
        raise ManualAutomationError("site_not_found", "SEO 网站不存在", 404)
    if site.status != "active":
        raise ManualAutomationError("site_inactive", "SEO 网站已停用，不能运行采集")
    planned = await manual_target_count(session, tenant_id, site_id, job_type)
    if planned == 0:
        raise ManualAutomationError(
            "no_targets",
            "当前网站没有可运行的已配置数据，请先录入对应资产",
        )
    now = datetime.utcnow()
    active = await session.scalar(
        select(SeoAutomationRun)
        .where(
            SeoAutomationRun.tenant_id == tenant_id,
            SeoAutomationRun.job_type == job_type,
            SeoAutomationRun.status.in_(["queued", "running"]),
            SeoAutomationRun.started_at >= now - timedelta(hours=2),
            or_(
                SeoAutomationRun.site_id == site_id,
                SeoAutomationRun.site_id.is_(None),
            ),
        )
        .order_by(SeoAutomationRun.started_at.desc(), SeoAutomationRun.id.desc())
        .limit(1)
    )
    if active is not None:
        raise ManualAutomationError("run_in_progress", "该任务正在运行，请勿重复提交")
    latest = await session.scalar(
        select(SeoAutomationRun)
        .where(
            SeoAutomationRun.tenant_id == tenant_id,
            SeoAutomationRun.site_id == site_id,
            SeoAutomationRun.job_type == job_type,
            SeoAutomationRun.trigger_type == "manual",
        )
        .order_by(SeoAutomationRun.started_at.desc(), SeoAutomationRun.id.desc())
        .limit(1)
    )
    cooldown = max(1, get_settings().seo_manual_automation_cooldown_seconds)
    if latest and latest.status in {"completed", "partial"}:
        cooldown_from = latest.completed_at or latest.started_at
        retry_after = max(0, int((cooldown_from + timedelta(seconds=cooldown) - now).total_seconds() + 0.999))
        if retry_after:
            raise ManualAutomationError(
                "run_cooldown",
                f"该任务刚刚运行过，请在 {retry_after} 秒后重试",
                429,
                retry_after,
            )
    row = SeoAutomationRun(
        tenant_id=tenant_id,
        site_id=site_id,
        job_type=job_type,
        trigger_type="manual",
        status="queued",
        planned_count=planned,
        requested_by=requested_by,
        started_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _maintain_rank_reservation(
    tenant_id: int,
    site_id: int,
    reservation: ManualRankReservation,
    stop: asyncio.Event,
) -> None:
    interval = max(1, MANUAL_RANK_RESERVATION_TTL_SECONDS // 3)
    delay = interval
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return
        except TimeoutError:
            pass
        try:
            async with async_session_factory() as session:
                if not await renew_manual_rank_collection(
                    session, tenant_id, site_id, reservation
                ):
                    return
            delay = interval
        except Exception:  # noqa: BLE001
            logger.exception(
                "[SEO][AUTOMATION] rank reservation heartbeat failed tenant=%s site=%s",
                tenant_id,
                site_id,
            )
            delay = min(30, max(1, interval // 4))


async def _run_ranking(row: SeoAutomationRun) -> tuple[int, int, int, str]:
    lock = acquire_file_lock(SEO_RANK_COLLECTION_LOCK_PATH)
    if lock is None:
        raise ManualAutomationError("collection_busy", "另一排名采集任务正在运行")
    settings = get_settings()
    reservation: ManualRankReservation | None = None
    stop = asyncio.Event()
    heartbeat: asyncio.Task | None = None
    try:
        async with async_session_factory() as session:
            try:
                reservation = await reserve_manual_rank_collection(
                    session,
                    row.tenant_id,
                    int(row.site_id),
                    row.planned_count,
                    cooldown_seconds=settings.seo_manual_rank_cooldown_seconds,
                    max_requests_per_day=settings.seo_manual_rank_max_requests_per_day,
                )
            except ManualRankLimitError as exc:
                raise ManualAutomationError(exc.code, exc.message, 429, exc.retry_after) from exc
            heartbeat = asyncio.create_task(
                _maintain_rank_reservation(
                    row.tenant_id, int(row.site_id), reservation, stop
                )
            )
            try:
                from app.api.seo import collect_rank_serp_for_tenant

                result = await collect_rank_serp_for_tenant(
                    session=session,
                    tenant_id=row.tenant_id,
                    site_id=row.site_id,
                    devices=["desktop", "mobile"],
                    max_keywords=max(1, row.planned_count // 2),
                    engine="baidu",
                    use_ai=False,
                    commit=False,
                )
            except Exception:
                await session.rollback()
                await settle_manual_rank_collection(
                    session,
                    row.tenant_id,
                    int(row.site_id),
                    reservation,
                    0,
                    cooldown_seconds=settings.seo_manual_rank_cooldown_seconds,
                    max_requests_per_day=settings.seo_manual_rank_max_requests_per_day,
                )
                raise
            finally:
                stop.set()
                if heartbeat is not None:
                    await heartbeat
            success = int(result["snapshots"])
            failed = len(result["errors"])
            await settle_manual_rank_collection(
                session,
                row.tenant_id,
                int(row.site_id),
                reservation,
                success,
                cooldown_seconds=settings.seo_manual_rank_cooldown_seconds,
                max_requests_per_day=settings.seo_manual_rank_max_requests_per_day,
            )
            errors = "; ".join(
                f"{item.get('device', 'unknown')}:{item.get('code', 'provider_error')}"
                for item in result["errors"][:10]
            )
            return success, failed, max(0, row.planned_count - success - failed), errors
    finally:
        release_file_lock(lock)


async def _run_competitors(row: SeoAutomationRun) -> tuple[int, int, int, str]:
    _, conditions = _target_conditions(row.tenant_id, int(row.site_id), "competitor")
    async with async_session_factory() as session:
        candidates = list(
            await session.scalars(
                select(SeoCompetitor)
                .where(*conditions)
                .order_by(SeoCompetitor.id)
                .limit(row.planned_count)
            )
        )
    success = failed = 0
    errors: list[str] = []
    for candidate in candidates:
        try:
            checked_at = datetime.utcnow()
            async with async_session_factory() as session:
                current = await session.get(SeoCompetitor, candidate.id)
                if (
                    current is None
                    or current.tenant_id != row.tenant_id
                    or current.site_id != row.site_id
                    or current.status != "active"
                    or current.domain != candidate.domain
                ):
                    continue
                current.last_checked_at = checked_at
                await session.commit()
            collection = await collect_competitor_content(candidate.domain)
            async with async_session_factory() as session:
                current = await session.get(SeoCompetitor, candidate.id)
                if (
                    current is None
                    or current.tenant_id != row.tenant_id
                    or current.site_id != row.site_id
                    or current.status != "active"
                    or current.domain != candidate.domain
                ):
                    continue
                existing = list(
                    await session.scalars(
                        select(SeoCompetitorEvent).where(
                            SeoCompetitorEvent.tenant_id == row.tenant_id,
                            SeoCompetitorEvent.site_id == row.site_id,
                            SeoCompetitorEvent.competitor_id == candidate.id,
                            SeoCompetitorEvent.event_type == "content",
                        )
                    )
                )
                known = {item.url for item in existing}
                baseline = not existing
                for page in collection.pages:
                    if page.url in known:
                        continue
                    session.add(
                        SeoCompetitorEvent(
                            tenant_id=row.tenant_id,
                            site_id=row.site_id,
                            competitor_id=candidate.id,
                            event_type="content",
                            title=page.title,
                            url=page.url,
                            source_url=f"https://{current.domain}/",
                            summary="首次手动批量采集基线" if baseline else "手动批量采集发现的新内容",
                        )
                    )
                    known.add(page.url)
                await session.commit()
            success += 1
        except CompetitorCollectionError as exc:
            failed += 1
            errors.append(f"{candidate.id}:{exc.code}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append(f"{candidate.id}:{type(exc).__name__}")
            logger.exception("[SEO][AUTOMATION] competitor rerun failed id=%s", candidate.id)
    return success, failed, max(0, row.planned_count - success - failed), "; ".join(errors)


async def _run_backlinks(row: SeoAutomationRun) -> tuple[int, int, int, str]:
    _, conditions = _target_conditions(row.tenant_id, int(row.site_id), "backlink")
    async with async_session_factory() as session:
        candidates = list(
            await session.scalars(
                select(SeoBacklink)
                .where(*conditions)
                .order_by(SeoBacklink.id)
                .limit(row.planned_count)
            )
        )
    success = failed = 0
    errors: list[str] = []
    for candidate in candidates:
        try:
            result = await fetch_url(candidate.source_url)
            if result.error_type or not result.body:
                failed += 1
                errors.append(f"{candidate.id}:{result.error_type or 'empty_response'}")
                continue
            present = backlink_present(result.body, result.final_url, candidate.target_url)
            async with async_session_factory() as session:
                current = await session.get(SeoBacklink, candidate.id)
                if (
                    current is None
                    or current.tenant_id != row.tenant_id
                    or current.site_id != row.site_id
                    or current.status not in {"active", "lost"}
                    or current.source_url != candidate.source_url
                    or current.target_url != candidate.target_url
                ):
                    continue
                current.last_checked_at = datetime.utcnow()
                if present:
                    current.status = "active"
                    current.last_seen_at = current.last_checked_at
                    current.missing_checks = 0
                else:
                    current.missing_checks = (current.missing_checks or 0) + 1
                    if current.missing_checks >= 2:
                        current.status = "lost"
                await session.commit()
            success += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append(f"{candidate.id}:{type(exc).__name__}")
            logger.exception("[SEO][AUTOMATION] backlink rerun failed id=%s", candidate.id)
    return success, failed, max(0, row.planned_count - success - failed), "; ".join(errors)


async def execute_manual_automation_run(run_id: int) -> None:
    if not await mark_automation_run_running(run_id):
        return
    async with async_session_factory() as session:
        row = await session.get(SeoAutomationRun, run_id)
        if row is None or row.trigger_type != "manual" or row.site_id is None:
            return
    try:
        runner = {
            "ranking": _run_ranking,
            "competitor": _run_competitors,
            "backlink": _run_backlinks,
        }[row.job_type]
        success, failed, skipped, errors = await runner(row)
    except ManualAutomationError as exc:
        success, failed, skipped, errors = 0, max(1, row.planned_count), 0, exc.code
    except Exception as exc:  # noqa: BLE001
        logger.exception("[SEO][AUTOMATION] manual rerun failed run_id=%s", run_id)
        success, failed, skipped, errors = 0, max(1, row.planned_count), 0, type(exc).__name__
    await finish_automation_run(
        run_id,
        planned_count=row.planned_count,
        success_count=success,
        failed_count=failed,
        skipped_count=skipped,
        error_summary=errors,
    )
