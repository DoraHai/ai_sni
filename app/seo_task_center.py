"""A permission-filtered history of SEO jobs; listing never starts work."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, literal, cast, String, Integer, case, union_all, func, or_

from app.models.seo import SeoAutomationRun, SeoCrawlRun, SeoAiOperation
from app.seo_ai_operations import RESULT_RETENTION

JOB_PERMISSIONS = {"ranking": "seo.keywords", "competitor": "seo.competitors", "backlink": "seo.links"}


def actor_key(ctx):
    return str(ctx.user_id) if ctx.user_id is not None else "api_key"


def planned_checks(settings, ctx):
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    schedules = [("ranking", settings.seo_rank_scheduler_hour, settings.seo_rank_scheduler_minute),
                 ("competitor", 3, 0), ("backlink", 4, 0)]
    return [{"job_type": kind, "next_check_at": CronTrigger(hour=hour, minute=minute, timezone="Asia/Shanghai")
             .get_next_fire_time(None, now).isoformat(),
             "note": "计划调度检查时间；是否执行还取决于配置、采集间隔、额度及服务运行状态"}
            for kind, hour, minute in schedules if ctx.can_view(JOB_PERMISSIONS[kind])]


async def list_task_center(session, tenant_id, site_id, ctx, *, kind=None, status=None, page=1, page_size=20):
    queries = []
    jobs = [job for job, permission in JOB_PERMISSIONS.items() if ctx.can_view(permission)]
    if jobs:
        m = SeoAutomationRun
        filters = [m.tenant_id == tenant_id, m.job_type.in_(jobs)]
        if site_id is not None:
            filters.append(or_(m.site_id == site_id, m.site_id.is_(None)))
        queries.append(select(literal("automation").label("source"), cast(m.id, String).label("id"),
            m.job_type.label("kind"), m.site_id, m.status, m.started_at, m.completed_at,
            m.planned_count.label("planned"), m.success_count.label("succeeded"), m.failed_count.label("failed"),
            m.skipped_count.label("skipped"), m.error_summary.label("detail"), literal(False).label("has_result"),
            m.trigger_type.label("trigger_type")).where(*filters))
    if ctx.can_view("seo.site"):
        m = SeoCrawlRun
        filters = [m.tenant_id == tenant_id]
        if site_id is not None:
            filters.append(m.site_id == site_id)
        queries.append(select(literal("crawl"), cast(m.id, String), literal("crawl"), m.site_id, m.status,
            m.started_at, m.completed_at, m.max_urls, m.fetched_count, m.failed_count, m.blocked_count,
            m.error_summary, literal(False), literal("manual")).where(*filters))
    if ctx.can_view("seo.content"):
        m = SeoAiOperation
        filters = [m.tenant_id == tenant_id, m.actor == actor_key(ctx)]
        if site_id is not None:
            filters.append(m.site_id == site_id)
        available = (m.result.is_not(None)) & (m.completed_at > datetime.utcnow() - RESULT_RETENTION)
        state = case((m.status == "succeeded", case((available, "completed"), else_="expired")), else_=m.status)
        queries.append(select(literal("ai"), m.id, literal("ai"), m.site_id, state,
            m.created_at, m.completed_at, literal(1), case((m.status == "succeeded", 1), else_=0),
            case((m.status == "refunded", 1), else_=0), literal(0),
            case((m.status == "refunded", "操作未完成，额度已退还"),
                 ((m.status == "running") & (m.expires_at <= datetime.utcnow()), "操作已超时，等待额度补偿"),
                 (m.status == "running", "正在生成结果"), else_="结果保存 30 天；取回结果不扣额度"),
            available, literal("manual")).where(*filters))
    if not queries:
        return {"items": [], "total": 0, "summary": {}, "page": page, "page_size": page_size}
    # Explicit names also cover users whose first permitted source is crawl/AI.
    names = ["source", "id", "kind", "site_id", "status", "started_at", "completed_at",
             "planned", "succeeded", "failed", "skipped", "detail", "has_result", "trigger_type"]
    normalized = [query.with_only_columns(*(column.label(name) for column, name in zip(query.selected_columns, names))) for query in queries]
    combined = union_all(*normalized).subquery()
    filters = [] if kind is None else [combined.c.kind == kind]
    counts = (await session.execute(select(combined.c.status, func.count()).where(*filters).group_by(combined.c.status))).all()
    summary = dict(counts)
    if status:
        filters.append(combined.c.status == status)
    total = int(await session.scalar(select(func.count()).select_from(combined).where(*filters)) or 0)
    rows = (await session.execute(select(combined).where(*filters)
        .order_by(combined.c.started_at.desc(), combined.c.source, combined.c.id.desc())
        .offset((page - 1) * page_size).limit(page_size))).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        for key in ("started_at", "completed_at"):
            value = item[key]
            item[key] = value.isoformat() + "Z" if value else None
        item["stale"] = row["status"] in {"queued", "running"} and row["started_at"] < datetime.utcnow() - timedelta(hours=2)
        item["retry_site_id"] = row["site_id"] or site_id
        item["can_retry"] = (row["source"] == "automation" and row["status"] in {"failed", "partial"}
            and bool(item["retry_site_id"]) and ctx.can_edit("seo.dashboard")
            and ctx.can_edit(JOB_PERMISSIONS[row["kind"]]))
        item["has_result"] = bool(item["has_result"])
        items.append(item)
    return {"items": items, "total": total, "summary": summary, "page": page, "page_size": page_size}
