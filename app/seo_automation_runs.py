"""Lightweight persisted summaries for tenant-scoped SEO automation jobs."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update

from app.database import async_session_factory
from app.models.seo import SeoAutomationRun


SEO_AUTOMATION_JOB_TYPES = {"ranking", "competitor", "backlink"}
SEO_AUTOMATION_TRIGGER_TYPES = {"scheduled", "manual"}


async def active_manual_automation_site_ids(
    *,
    tenant_id: int,
    job_type: str,
) -> set[int]:
    """Return exact sites with a recent queued/running operator-triggered job."""
    if job_type not in SEO_AUTOMATION_JOB_TYPES:
        raise ValueError(f"Unsupported SEO automation job type: {job_type}")
    async with async_session_factory() as session:
        values = await session.scalars(
            select(SeoAutomationRun.site_id).where(
                SeoAutomationRun.tenant_id == tenant_id,
                SeoAutomationRun.job_type == job_type,
                SeoAutomationRun.trigger_type == "manual",
                SeoAutomationRun.status.in_(["queued", "running"]),
                SeoAutomationRun.site_id.is_not(None),
                SeoAutomationRun.started_at >= datetime.utcnow() - timedelta(hours=2),
            )
        )
        return {int(site_id) for site_id in values if site_id is not None}


def automation_run_status(*, success_count: int, failed_count: int) -> str:
    if failed_count > 0 and success_count > 0:
        return "partial"
    if failed_count > 0:
        return "failed"
    return "completed"


async def start_automation_run(
    *,
    tenant_id: int,
    job_type: str,
    trigger_type: str = "scheduled",
    site_id: int | None = None,
    planned_count: int = 0,
) -> int:
    if job_type not in SEO_AUTOMATION_JOB_TYPES:
        raise ValueError(f"Unsupported SEO automation job type: {job_type}")
    if trigger_type not in SEO_AUTOMATION_TRIGGER_TYPES:
        raise ValueError(f"Unsupported SEO automation trigger type: {trigger_type}")
    async with async_session_factory() as session:
        row = SeoAutomationRun(
            tenant_id=tenant_id,
            site_id=site_id,
            job_type=job_type,
            trigger_type=trigger_type,
            status="running",
            planned_count=max(0, int(planned_count)),
            started_at=datetime.utcnow(),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return int(row.id)


async def mark_automation_run_running(run_id: int) -> bool:
    async with async_session_factory() as session:
        result = await session.execute(
            update(SeoAutomationRun)
            .where(
                SeoAutomationRun.id == run_id,
                SeoAutomationRun.status == "queued",
                SeoAutomationRun.trigger_type == "manual",
                SeoAutomationRun.site_id.is_not(None),
            )
            .values(status="running", started_at=datetime.utcnow())
        )
        await session.commit()
        return result.rowcount == 1


async def finish_automation_run(
    run_id: int,
    *,
    planned_count: int,
    success_count: int,
    failed_count: int,
    skipped_count: int = 0,
    error_summary: str | None = None,
) -> None:
    success = max(0, int(success_count))
    failed = max(0, int(failed_count))
    async with async_session_factory() as session:
        row = await session.get(SeoAutomationRun, run_id)
        if row is None:
            return
        row.status = automation_run_status(
            success_count=success,
            failed_count=failed,
        )
        row.planned_count = max(0, int(planned_count))
        row.success_count = success
        row.failed_count = failed
        row.skipped_count = max(0, int(skipped_count))
        row.error_summary = str(error_summary or "").strip()[:2000] or None
        row.completed_at = datetime.utcnow()
        await session.commit()
