"""Bounded service cycles on the existing SEO task/evidence ledger."""
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import get_settings, seo_rank_freshness_hours
from app.database import async_session_factory
from app.models.module_workspace import SeoSite
from app.models.seo import (SeoContentAsset, SeoContentPublication, SeoKeywordAsset, SeoPageSnapshot,
                            SeoRankSnapshot, SeoSiteAdvisorAssignment, SeoSitePage)
from app.models.seo_cockpit import SeoTask
from app.models.seo_site_analytics import SeoSiteAnalyticsMonthly, SeoSiteAnalyticsSource
from app.module_scope import seo_site_is_operational
from app.seo_content_workflow import plan_for, schema_ready, transition, utc
from app.seo_page_audit import collect_page_snapshot, save_page_snapshot
from app.seo_service_plan import service_plan_is_paused
from app.seo_serp import domain_matches
from app.seo_usage_limits import charge_seo_usage, SeoUsageLimitError

KINDS = {"website": "site_diagnosis", "monitoring": "ranking_followup", "report": "monthly_report"}
PERMISSIONS = {"site_diagnosis": "seo.site", "ranking_followup": "seo.keywords", "monthly_report": "seo.site"}
METRICS = {"website": "seo.site.observation_count", "monitoring": "seo.ranking.observation_count",
           "report": "seo.reports.prepared_count"}
logger = logging.getLogger(__name__)
TZ = timezone(timedelta(hours=8))


async def evidence_counts(session, tenant_id, site_id):
    result = {}
    for model, key in ((SeoPageSnapshot, METRICS["website"]), (SeoRankSnapshot, METRICS["monitoring"])):
        query = select(func.count()).select_from(model).where(model.tenant_id == tenant_id, model.site_id == site_id)
        if model is SeoRankSnapshot:
            query = query.where(model.subject_type == "own", model.engine == "baidu", model.device == "desktop", model.region == "全国")
        result[key] = int(await session.scalar(query) or 0)
    result[METRICS["report"]] = int(await session.scalar(select(func.count()).select_from(SeoTask).where(
        SeoTask.tenant_id == tenant_id, SeoTask.site_id == site_id, SeoTask.action_type == KINDS["report"],
        SeoTask.params["report"]["sha256"].as_string().is_not(None),
    )) or 0)
    return result


def previous_month(now):
    return (now.astimezone(TZ).replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


async def ranking_issues(session, site, now):
    """Fixed Baidu/desktop/nationwide scope; NULL rank is observed, not missing."""
    keywords = list(await session.scalars(select(SeoKeywordAsset).where(
        SeoKeywordAsset.tenant_id == site.tenant_id, SeoKeywordAsset.site_id == site.id,
        SeoKeywordAsset.status == "active",
    ).order_by(SeoKeywordAsset.id).limit(201)))
    if len(keywords) > 200:
        raise HTTPException(409, {"code": "monitoring_keyword_limit_200"})
    cutoff = now - timedelta(hours=seo_rank_freshness_hours(get_settings(), "baidu"))
    issues = []
    for keyword in keywords:
        observations = list(await session.scalars(select(SeoRankSnapshot).where(
            SeoRankSnapshot.tenant_id == site.tenant_id, SeoRankSnapshot.site_id == site.id,
            SeoRankSnapshot.keyword_id == keyword.id, SeoRankSnapshot.subject_type == "own",
            SeoRankSnapshot.engine == "baidu", SeoRankSnapshot.device == "desktop", SeoRankSnapshot.region == "全国",
            SeoRankSnapshot.checked_at <= now.replace(tzinfo=None),
        ).order_by(SeoRankSnapshot.checked_at.desc(), SeoRankSnapshot.id.desc()).limit(2)))
        latest = observations[0] if observations else None
        reason = "missing" if latest is None else "stale" if utc(latest.checked_at) < cutoff else None
        previous = observations[1] if len(observations) > 1 else None
        if reason is None and previous and previous.rank is not None and previous.rank >= 1:
            if latest.rank is None or latest.rank >= previous.rank + 5:
                reason = "rank_drop"
        if reason:
            issues.append({"keyword_id": keyword.id, "reason": reason,
                "observed_id": latest.id if latest else None,
                "recovery_rank": previous.rank if reason == "rank_drop" else None})
    return issues, len(keywords)


async def reserve_service_workflow(session, site, kind, key, actor_id, *, scheduled=False, now=None):
    """Caller holds advisor/site locks. Returns the original task on UUID replay."""
    now = now or datetime.now(timezone.utc)
    action = KINDS[kind]
    filters = (SeoTask.tenant_id == site.tenant_id, SeoTask.site_id == site.id, SeoTask.action_type == action)
    row = await session.scalar(select(SeoTask).where(*filters, SeoTask.params["request_key"].as_string() == key).limit(1))
    if row:
        return row, False
    from app.seo_workflow_capabilities import new_workflow_blocker
    blocker = await new_workflow_blocker(session, site, kind)
    if blocker:
        raise HTTPException(409, {"code": blocker})
    if service_plan_is_paused(site):
        raise HTTPException(409, {"code": "service_plan_paused"})
    active = await session.scalar(select(SeoTask.id).where(*filters, SeoTask.status.in_(("open", "in_progress"))).limit(1))
    if active:
        raise HTTPException(409, {"code": "service_workflow_already_active", "task_id": active})
    plan = plan_for(site)
    params = {"kind": kind, "request_key": key, "plan_revision": plan.get("revision", 0),
              "trigger": "scheduled" if scheduled else "advisor", "triggered_by_user_id": None if scheduled else actor_id}
    if kind == "website":
        pages = list(await session.scalars(select(SeoSitePage.id).where(
            SeoSitePage.tenant_id == site.tenant_id, SeoSitePage.site_id == site.id,
        ).order_by(SeoSitePage.last_checked_at.asc().nulls_first(), SeoSitePage.id).limit(int(plan.get("website_max_pages") or 5))))
        params["pages"] = {str(ident): {"state": "queued"} for ident in pages}
        params["child_task_ids"] = []
    elif kind == "monitoring":
        params["issues"], params["keyword_count"] = await ranking_issues(session, site, now)
        if not params["keyword_count"]:
            raise HTTPException(409, {"code": "keyword_inventory_required"})
    else:
        params["month"] = previous_month(now)
    values = await evidence_counts(session, site.tenant_id, site.id)
    row = SeoTask(tenant_id=site.tenant_id, site_id=site.id, module="seo", action_type=action,
        title={"website": "网站周期诊断与整改", "monitoring": "排名缺报与异常跟进", "report": "月报准备与顾问说明"}[kind],
        status="in_progress", created_by="cockpit" if scheduled else str(actor_id), assignee_role="seo_advisor",
        params=params, baseline={"metric_key": METRICS[kind], "value": values[METRICS[kind]], "as_of": now.isoformat()},
        created_at=now, updated_at=now)
    transition(row, "diagnosis_queued" if kind == "website" else "awaiting_ranking_observations" if kind == "monitoring" else "report_queued", now)
    if kind == "monitoring" and not params["issues"]:
        row.status = "cancelled"
        transition(row, "no_actionable_issues", now, waiting_for=None)
    session.add(row)
    await session.flush()
    if not scheduled:
        settings = dict(site.site_settings or {})
        cursors = dict(settings.get("seo_service_cycle_cursors") or {})
        previous = cursors.get(kind) or {}
        cursors[kind] = {"sequence": int(previous.get("sequence") or 0) + 1,
            "month": params.get("month"), "task_id": row.id, "last_checked_at": now.isoformat(),
            "next_due_at": (now + timedelta(days=int(plan.get(f"{kind}_interval_days") or (1 if kind == "monitoring" else 7)))).isoformat()}
        settings["seo_service_cycle_cursors"] = cursors
        site.site_settings = settings
    return row, True


async def mark_complete(session, site, task, now, source):
    values = await evidence_counts(session, site.tenant_id, site.id)
    key, before = task.baseline["metric_key"], task.baseline["value"]
    after = values[key]
    if after <= before:
        transition(task, "needs_attention", now, blocker="evidence_metric_not_increased")
        return
    task.status = "done"
    task.completion_evidence = {"metric_key": key, "before": before, "after": after, "change_abs": after - before,
        "as_of": now.isoformat(), "source": source, "seo_effect": "not_evaluated"}
    transition(task, "completed_with_evidence", now, waiting_for=None)


async def prepare_report(session, site, task, now):
    """Freeze a bounded HTML report with missing-data disclosures; no PDF/provider."""
    from app.seo_monthly_report import build_report_context, render_report_html
    from app.seo_publication_export import month_bounds
    month = task.params["month"]
    start, end = month_bounds(month)
    filters = (SeoContentPublication.tenant_id == site.tenant_id, SeoContentAsset.tenant_id == site.tenant_id,
        SeoContentAsset.site_id == site.id, SeoContentPublication.status == "published",
        SeoContentPublication.published_at >= start, SeoContentPublication.published_at < end)
    pairs = list((await session.execute(select(SeoContentPublication, SeoContentAsset).join(
        SeoContentAsset, SeoContentAsset.id == SeoContentPublication.content_asset_id).where(*filters)
        .order_by(SeoContentPublication.id).limit(201))).all())
    if len(pairs) > 200:
        transition(task, "report_needs_attention", now, blocker="report_publication_limit_200")
        return
    monthly = list(await session.scalars(select(SeoSiteAnalyticsMonthly).where(
        SeoSiteAnalyticsMonthly.tenant_id == site.tenant_id, SeoSiteAnalyticsMonthly.site_id == site.id,
        SeoSiteAnalyticsMonthly.month == month)))
    # Select configuration names only; no credential material enters report generation.
    source_names = list(await session.scalars(select(SeoSiteAnalyticsSource.source).where(
        SeoSiteAnalyticsSource.tenant_id == site.tenant_id, SeoSiteAnalyticsSource.site_id == site.id,
        SeoSiteAnalyticsSource.enabled.is_(True))))
    rows = [{"platform": p.platform_name, "title": c.title, "keywords": "", "page_url": p.page_url,
             "published_at": p.published_at, "capture_status": "本报告未附截图，请查发布页面证据",
             "image_key": None, "captured_at": None, "notes": "发布不代表收录或效果提升", "capture_kind": None}
            for p, c in pairs]
    from types import SimpleNamespace
    context = build_report_context(site_name=site.name, month=month, rows=rows, monthly_rows=monthly,
        sources=[SimpleNamespace(source=name) for name in source_names], generated_at=now)
    html = render_report_html(context)
    report = {"format": "html", "month": month, "generated_at": now.isoformat(), "html": html,
        "sha256": hashlib.sha256(html.encode()).hexdigest(), "publication_ids": [p.id for p, _ in pairs],
        "analytics_row_ids": [row.id for row in monthly], "scope": "site_month",
        "missing": ["article_click_attribution_unavailable", "screenshot_appendix_not_embedded"] +
                   (["site_analytics_missing"] if not monthly else []),
        "pdf_generated": False, "notification_sent": False}
    task.params = {**task.params, "report": report}
    await session.flush()
    transition(task, "awaiting_advisor_explanation", now)


async def advance_service_workflow(session, site, task, *, explanation=None, report_sha256=None, actor_id=None, retry_page_id=None):
    now = datetime.now(timezone.utc)
    if task.status in {"done", "cancelled"}:
        return
    if service_plan_is_paused(site):
        transition(task, "paused", now, waiting_for=None, blocker="service_plan_paused")
        return
    kind = task.params["kind"]
    if kind == "report":
        if explanation and (not task.params.get("report") or task.params["report"]["sha256"] != report_sha256):
            raise HTTPException(409, {"code": "report_version_conflict"})
        if not task.params.get("report"):
            await prepare_report(session, site, task, now)
        if task.params.get("report") and explanation:
            task.params = {**task.params, "explanation": {"text": explanation, "actor_user_id": actor_id, "at": now.isoformat()}}
            await mark_complete(session, site, task, now, {"month": task.params["month"], "report_sha256": task.params["report"]["sha256"],
                "report_url": f"/api/v1/seo/workbench/executions/{task.id}/report?tenant_id={site.tenant_id}&site_id={site.id}"})
        elif task.params.get("report"):
            transition(task, "awaiting_advisor_explanation", now)
        return
    if kind == "monitoring":
        remaining, resolved = [], []
        for issue in task.params["issues"]:
            keyword = await session.get(SeoKeywordAsset, issue["keyword_id"])
            if not keyword or keyword.tenant_id != site.tenant_id or keyword.site_id != site.id or keyword.status != "active":
                remaining.append({**issue, "current_blocker": "keyword_removed_or_disabled"})
                continue
            row = await session.scalar(select(SeoRankSnapshot).where(
                SeoRankSnapshot.tenant_id == site.tenant_id, SeoRankSnapshot.site_id == site.id,
                SeoRankSnapshot.keyword_id == keyword.id, SeoRankSnapshot.subject_type == "own",
                SeoRankSnapshot.engine == "baidu", SeoRankSnapshot.device == "desktop", SeoRankSnapshot.region == "全国",
                SeoRankSnapshot.checked_at <= now.replace(tzinfo=None),
            ).order_by(SeoRankSnapshot.checked_at.desc(), SeoRankSnapshot.id.desc()).limit(1))
            cutoff = max(utc(task.created_at), now - timedelta(hours=seo_rank_freshness_hours(get_settings(), "baidu")))
            if not row or utc(row.checked_at) <= cutoff or row.id == issue["observed_id"]:
                remaining.append(issue)
            elif issue["reason"] == "rank_drop" and (row.rank is None or row.rank < 1 or row.rank > issue["recovery_rank"]):
                remaining.append(issue)
            else:
                resolved.append(row.id)
        task.params = {**task.params, "remaining_issues": remaining, "resolved_snapshot_ids": resolved}
        if remaining:
            transition(task, "awaiting_ranking_observations", now, blocker="ranking_issues_unresolved")
        else:
            await mark_complete(session, site, task, now, {"rank_snapshot_ids": resolved, "engine": "baidu", "device": "desktop", "region": "全国"})
        return
    pages = {key: dict(value) for key, value in task.params["pages"].items()}
    if retry_page_id is not None:
        key = str(retry_page_id)
        if key not in pages or pages[key]["state"] != "failed":
            raise HTTPException(409, {"code": "page_retry_not_available"})
        pages[key] = {"state": "queued", "retry_by": actor_id, "previous": pages[key]}
    for step in pages.values():
        if step["state"] == "running" and utc(datetime.fromisoformat(step["started_at"])) < now - timedelta(minutes=2):
            step.update(state="failed", error="interrupted_observation_requires_retry")
    task.params = {**task.params, "pages": pages}
    if not pages:
        transition(task, "needs_attention", now, blocker="site_page_inventory_required")
    elif any(step["state"] == "failed" for step in pages.values()):
        transition(task, "diagnosis_needs_attention", now, blocker="page_observation_failed")
    elif any(step["state"] in {"queued", "running"} for step in pages.values()):
        transition(task, "diagnosis_queued", now, waiting_for="system")
    else:
        from app.api.seo_cockpit import completion
        children = list(await session.scalars(select(SeoTask).where(
            SeoTask.tenant_id == site.tenant_id, SeoTask.site_id == site.id,
            SeoTask.id.in_(task.params["child_task_ids"]),
        ).with_for_update()))
        for child in children:
            if child.status in {"open", "in_progress"}:
                try:
                    child.completion_evidence = await completion(session, child)
                    child.status, child.updated_at = "done", now
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
        if len(children) != len(task.params["child_task_ids"]) or any(child.status != "done" for child in children):
            transition(task, "awaiting_site_implementation", now, blocker="remediation_requires_real_recheck")
        else:
            await mark_complete(session, site, task, now, {"snapshot_ids": [step["snapshot_id"] for step in pages.values()],
                "remediation_task_ids": task.params["child_task_ids"], "meaning": "bounded_diagnosis_and_required_remediation"})


async def execute_diagnosis_page(task_id):
    """Claim one page durably; an interrupted external read is never blindly replayed."""
    async with async_session_factory() as session:
        if not await schema_ready(session):
            return
        seed = await session.get(SeoTask, task_id)
        if not seed:
            return
        tenant_id, site_id = seed.tenant_id, seed.site_id
        advisor = await session.scalar(select(SeoSiteAdvisorAssignment.id).where(
            SeoSiteAdvisorAssignment.tenant_id == tenant_id, SeoSiteAdvisorAssignment.site_id == site_id,
            SeoSiteAdvisorAssignment.active.is_(True)).order_by(SeoSiteAdvisorAssignment.id).limit(1).with_for_update())
        if not advisor:
            return
        # Refresh task after locks: a concurrent cancellation must be observed.
        site = await session.get(SeoSite, site_id, with_for_update=True)
        task = await session.get(SeoTask, task_id, with_for_update=True, populate_existing=True)
        if (not site or site.tenant_id != tenant_id or task.status not in {"open", "in_progress"}
                or task.action_type != KINDS["website"] or service_plan_is_paused(site)
                or not await seo_site_is_operational(session, tenant_id, site_id)):
            return
        pages = {key: dict(value) for key, value in task.params["pages"].items()}
        if any(step["state"] == "running" for step in pages.values()):
            return
        key = next((key for key, value in pages.items() if value["state"] == "queued"), None)
        if key is None:
            return
        page = await session.get(SeoSitePage, int(key))
        if not page or page.tenant_id != tenant_id or page.site_id != site_id:
            pages[key] = {"state": "failed", "error": "page_scope_changed"}
            task.params = {**task.params, "pages": pages}
            await session.commit()
            return
        url, token = page.url, str(uuid4())
        if not domain_matches(url, f"https://{site.canonical_domain}"):
            pages[key] = {"state": "failed", "error": "page_url_outside_site"}
            task.params = {**task.params, "pages": pages}
            await session.commit()
            return
        try:
            await charge_seo_usage(session, tenant_id, "crawl_urls", 1,
                get_settings().seo_manual_crawl_max_urls_per_tenant_per_day, commit=False)
        except SeoUsageLimitError:
            task = await session.get(SeoTask, task_id, with_for_update=True, populate_existing=True)
            transition(task, "diagnosis_needs_attention", datetime.now(timezone.utc), blocker="crawl_quota_exhausted")
            await session.commit()
            return
        started_at = datetime.now(timezone.utc)
        pages[key] = {"state": "running", "token": token, "started_at": started_at.isoformat(), "url": url,
                      "previous_checked_at": utc(page.last_checked_at).isoformat() if page.last_checked_at else None}
        task.params = {**task.params, "pages": pages}
        await session.commit()
    try:
        values = await collect_page_snapshot(url)
    except Exception:
        values = None
    async with async_session_factory() as session:
        site = await session.get(SeoSite, site_id, with_for_update=True)
        task = await session.get(SeoTask, task_id, with_for_update=True)
        if not task or task.status not in {"open", "in_progress"}:
            return
        pages = {key: dict(value) for key, value in task.params["pages"].items()}
        if pages[key].get("token") != token or pages[key]["state"] != "running":
            return
        page = await session.get(SeoSitePage, int(key), with_for_update=True)
        if (not site or site.tenant_id != tenant_id or not page or page.tenant_id != tenant_id
                or page.site_id != site_id or page.url != url
                or (utc(page.last_checked_at).isoformat() if page.last_checked_at else None) != pages[key].get("previous_checked_at")
                or not await seo_site_is_operational(session, tenant_id, site_id)):
            values = None
        if values is None:
            pages[key].update(state="failed", error="observation_failed_or_scope_changed")
        else:
            snapshot = await save_page_snapshot(session, page, values, None, started_at.replace(tzinfo=None))
            await session.flush()
            pages[key].update(state="failed" if values.get("error_type") else "observed",
                              snapshot_id=snapshot.id, run_id=snapshot.crawl_run_id, error=values.get("error_type"))
            if not values.get("error_type") and page.issue_codes:
                child = await session.scalar(select(SeoTask).where(
                    SeoTask.tenant_id == tenant_id, SeoTask.site_id == site_id, SeoTask.action_type == "page_remediation",
                    SeoTask.params["page_id"].as_integer() == page.id,
                    SeoTask.status.in_(("open", "in_progress"))).limit(1).with_for_update())
                if child is None:
                    healthy = int(await session.scalar(select(func.count()).select_from(SeoSitePage).where(
                        SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id,
                        SeoSitePage.status.in_(("healthy", "verified")))) or 0)
                    child = SeoTask(tenant_id=tenant_id, site_id=site_id, module="seo", action_type="page_remediation",
                        title=("页面整改 · " + page.url)[:240], params={"page_id": page.id, "source_status": page.status,
                        "source_issue_codes": list(page.issue_codes), "source_snapshot_id": snapshot.id, "parent_task_id": task.id},
                        status="open", created_by="cockpit", assignee_role="seo_advisor",
                        baseline={"metric_key": "seo.site.healthy_page_count", "value": healthy},
                        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
                    session.add(child)
                    await session.flush()
                task.params = {**task.params, "child_task_ids": sorted(set(task.params["child_task_ids"] + [child.id]))}
        task.params = {**task.params, "pages": pages}
        await session.commit()


async def process_service_site(site_id):
    dispatch = []
    async with async_session_factory() as session:
        if not await schema_ready(session):
            return
        advisor = await session.scalar(select(SeoSiteAdvisorAssignment).where(
            SeoSiteAdvisorAssignment.site_id == site_id, SeoSiteAdvisorAssignment.active.is_(True))
            .order_by(SeoSiteAdvisorAssignment.id).limit(1).with_for_update())
        site = await session.get(SeoSite, site_id, with_for_update=True)
        if not site or not advisor or advisor.tenant_id != site.tenant_id or not await seo_site_is_operational(session, site.tenant_id, site_id):
            return
        now, plan = datetime.now(timezone.utc), plan_for(site)
        settings = dict(site.site_settings or {})
        cursors = dict(settings.get("seo_service_cycle_cursors") or {})
        for kind, action in KINDS.items():
            tasks = list(await session.scalars(select(SeoTask).where(
                SeoTask.tenant_id == site.tenant_id, SeoTask.site_id == site_id, SeoTask.action_type == action,
                SeoTask.status.in_(("open", "in_progress"))).order_by(SeoTask.id).with_for_update()))
            for task in tasks:
                await advance_service_workflow(session, site, task)
                if kind == "website" and not service_plan_is_paused(site):
                    dispatch.append(task.id)
            if tasks or service_plan_is_paused(site) or plan.get(f"{kind}_cycle_enabled") is not True:
                continue
            cursor = cursors.get(kind) or {}
            period = previous_month(now) if kind == "report" else None
            if (kind == "report" and cursor.get("month") == period) or (kind != "report" and cursor.get("next_due_at") and now < utc(datetime.fromisoformat(cursor["next_due_at"]))):
                continue
            sequence = int(cursor.get("sequence") or 0) + 1
            try:
                task, _ = await reserve_service_workflow(session, site, kind, f"cycle:{kind}:{sequence}", advisor.advisor_user_id, scheduled=True, now=now)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                cursors[kind] = {**cursor, "last_checked_at": now.isoformat(), "blocker": exc.detail,
                    "next_due_at": (now + timedelta(days=1)).isoformat()}
                continue
            cursors[kind] = {"sequence": sequence, "month": period, "last_checked_at": now.isoformat(),
                "task_id": task.id if task else None,
                "next_due_at": (now + timedelta(days=int(plan.get(f"{kind}_interval_days") or (1 if kind == "monitoring" else 7)))).isoformat()}
        settings["seo_service_cycle_cursors"] = cursors
        site.site_settings = settings
        await session.commit()
    for task_id in dispatch:
        await execute_diagnosis_page(task_id)


async def run_service_workflows():
    cursor = 0
    while True:
        async with async_session_factory() as session:
            if not await schema_ready(session):
                return
            ids = list(await session.scalars(select(SeoSite.id).where(SeoSite.id > cursor, SeoSite.status == "active").order_by(SeoSite.id).limit(100)))
        if not ids:
            return
        for site_id in ids:
            try:
                await process_service_site(site_id)
            except Exception:
                logger.exception("SEO service cycle failed site_id=%s", site_id)
        cursor = ids[-1]
