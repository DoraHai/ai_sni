"""Task-scoped delivery indicators; site totals are explanatory effects only."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.seo import SeoSitePage, SeoPageSnapshot, SeoCrawlRun
from app.seo_content_workflow import utc

CONTENT_METRIC = "seo.content.target_delivery_verified_count"
PAGE_METRIC = "seo.site.target_clean_recheck_count"
DEFINITIONS = {
    CONTENT_METRIC: "限定本任务的内容、准确版本及所选发布记录；任务创建后已发布且有发布后自动页面证据计1，否则计0，不表示搜索效果增长。",
    PAGE_METRIC: "限定本任务目标页面；任务创建后取得与当前页面对应的成功、无问题重新抓取快照计1，否则计0，不表示全站健康页面净增长。",
}


def object_evidence(key, scope, source, effect_context, now=None):
    now = now or datetime.now(timezone.utc)
    return {"metric_key": key, "metric_definition": DEFINITIONS[key], "unit": "count",
        "scope": scope, "before": 0, "after": 1, "change_abs": 1, "as_of": now.isoformat(),
        "completion_basis": "target_object_evidence", "source": source,
        "meaning": source.get("meaning"),
        "effect_context": effect_context, "seo_effect": "not_evaluated"}


async def page_completion(session, task):
    page = await session.get(SeoSitePage, task.params["page_id"])
    now, created = datetime.now(timezone.utc), utc(task.created_at)
    baseline_snapshot_id = task.params.get("source_snapshot_id")
    if (not page or (page.tenant_id, page.site_id) != (task.tenant_id, task.site_id)
            or page.status not in {"healthy", "verified"} or page.issue_codes
            or not page.last_checked_at or not created <= utc(page.last_checked_at) <= now
            or (utc(page.last_checked_at) == created and not baseline_snapshot_id)
            or not page.http_status or not 200 <= page.http_status < 300):
        raise HTTPException(409, "需要任务创建后的页面重新检查确认问题已解决")
    snapshot = await session.scalar(select(SeoPageSnapshot).where(
        SeoPageSnapshot.tenant_id == task.tenant_id, SeoPageSnapshot.site_id == task.site_id,
        SeoPageSnapshot.url == page.url,
    ).order_by(SeoPageSnapshot.fetched_at.desc(), SeoPageSnapshot.id.desc()).limit(1))
    observed = None
    if snapshot and snapshot.fetched_at:
        stamp = snapshot.fetched_at
        # The deployed snapshot column stores naive Shanghai time; page/run use UTC.
        observed = stamp.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc) if stamp.tzinfo is None else utc(stamp)
    if (not snapshot or observed is None or not created <= observed <= now
            or (observed == created and not baseline_snapshot_id)
            or (baseline_snapshot_id is not None and snapshot.id <= baseline_snapshot_id)
            or abs((observed - utc(page.last_checked_at)).total_seconds()) > 1
            or snapshot.error_type or snapshot.fetch_error or snapshot.issue_codes
            or not snapshot.status_code or not 200 <= snapshot.status_code < 300):
        raise HTTPException(409, "需要当前目标页面真实、成功且无问题的重新抓取快照")
    run = await session.get(SeoCrawlRun, snapshot.crawl_run_id)
    if (not run or (run.tenant_id, run.site_id) != (task.tenant_id, task.site_id)
            or run.status != "completed" or not run.started_at or utc(run.started_at) < created
            or not run.completed_at or not created <= utc(run.completed_at) <= now
            or (utc(run.completed_at) == created and not baseline_snapshot_id)):
        raise HTTPException(409, "页面复检缺少任务创建后完成的真实抓取记录")
    before = task.baseline.get("value")
    after = int(await session.scalar(select(func.count()).select_from(SeoSitePage).where(
        SeoSitePage.tenant_id == task.tenant_id, SeoSitePage.site_id == task.site_id,
        SeoSitePage.status.in_(("healthy", "verified")),
    )) or 0)
    return object_evidence(PAGE_METRIC, {"task_id": task.id, "tenant_id": task.tenant_id,
        "site_id": task.site_id, "page_id": page.id},
        {"page_id": page.id, "url": page.url, "status": page.status, "checked_at": observed.isoformat(),
         "snapshot_id": snapshot.id, "crawl_run_id": run.id, "http_status": snapshot.status_code,
         "audit_score": page.audit_score, "issue_codes": [], "source_issue_codes": task.params.get("source_issue_codes"),
         "meaning": "target_page_rechecked_clean"},
        {"metric_key": "seo.site.healthy_page_count", "scope": "site", "before": before, "after": after,
         "change_abs": after - before if before is not None else None,
         "snapshot_url": f"/api/v1/seo/metrics/snapshot?tenant_id={task.tenant_id}&site_id={task.site_id}"}, now)
