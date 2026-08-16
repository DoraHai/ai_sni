"""GEO 长任务异步执行（生成母稿 / 渠道稿 / 批量推送），模式对齐巡检 BackgroundTasks。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GeoAsyncJob, GeoContentTask

logger = logging.getLogger(__name__)

KIND_GENERATE = "generate_article"
KIND_PUSH_BATCH = "push_batch"
KIND_VARIANTS = "create_variants"

# Defaults; runtime reads settings when reconciling
STALE_PENDING_SECONDS = 120
STALE_RUNNING_SECONDS = 45 * 60


def job_payload(row: GeoAsyncJob) -> dict[str, Any]:
    meta = row.request_meta if isinstance(row.request_meta, dict) else {}
    progress = meta.get("progress") if isinstance(meta.get("progress"), dict) else {}
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "kind": row.kind,
        "status": row.status,
        "ref_type": row.ref_type,
        "ref_id": row.ref_id,
        "request_meta": meta,
        "result_meta": row.result_meta or {},
        "progress": progress,
        "progress_label": progress.get("message") or "",
        "progress_pct": progress.get("pct"),
        "cancel_requested": bool(meta.get("cancel_requested")),
        "error": row.error,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


async def set_job_progress(
    session: AsyncSession, job: GeoAsyncJob, *, message: str, pct: int
) -> None:
    meta = dict(job.request_meta or {})
    meta["progress"] = {"message": message, "pct": max(0, min(100, int(pct)))}
    job.request_meta = meta
    await session.commit()


def cancel_requested(job: GeoAsyncJob) -> bool:
    meta = job.request_meta if isinstance(job.request_meta, dict) else {}
    return bool(meta.get("cancel_requested")) or job.status == "cancelled"


async def request_cancel(session: AsyncSession, job: GeoAsyncJob) -> GeoAsyncJob:
    if job.status in {"succeeded", "failed", "cancelled"}:
        return job
    meta = dict(job.request_meta or {})
    meta["cancel_requested"] = True
    job.request_meta = meta
    if job.status == "pending":
        job.status = "cancelled"
        job.error = "已取消"
        job.finished_at = datetime.utcnow()
        await _release_task_lock(session, job, reason="user_cancel")
    await session.commit()
    await session.refresh(job)
    return job


def _stale_limits() -> tuple[int, int]:
    try:
        from app.config import get_settings

        s = get_settings()
        pending = int(
            getattr(s, "geo_async_stale_pending_seconds", STALE_PENDING_SECONDS)
            or STALE_PENDING_SECONDS
        )
        running = int(
            getattr(s, "geo_async_stale_running_seconds", STALE_RUNNING_SECONDS)
            or STALE_RUNNING_SECONDS
        )
        return max(30, pending), max(60, running)
    except Exception:  # noqa: BLE001
        return STALE_PENDING_SECONDS, STALE_RUNNING_SECONDS


def _age_seconds(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    now = datetime.utcnow()
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.replace(tzinfo=None)
    return max(0.0, (now - dt).total_seconds())


async def _release_task_lock(
    session: AsyncSession, job: GeoAsyncJob, *, reason: str
) -> None:
    if not job.ref_id or job.ref_type not in {None, "content_task"}:
        return
    if job.kind not in {KIND_GENERATE, KIND_VARIANTS}:
        return
    task = await session.get(GeoContentTask, job.ref_id)
    if task is None:
        return
    if task.status in {"generating", "adapting"}:
        task.status = "editing"
        logger.warning(
            "async job stale released task=%s status→editing reason=%s",
            task.id,
            reason,
        )


async def reconcile_stale_job(
    session: AsyncSession, row: GeoAsyncJob
) -> GeoAsyncJob:
    """Mark hanging pending/running jobs failed; free content-task locks."""
    if row.status not in {"pending", "running"}:
        return row
    pending_lim, running_lim = _stale_limits()
    if row.status == "pending":
        age = _age_seconds(row.created_at)
        if age is None or age < pending_lim:
            return row
        reason = f"作业排队超时（>{pending_lim}s）已自动失败；请重试"
        row.status = "failed"
        row.error = reason
        row.finished_at = datetime.utcnow()
        await _release_task_lock(session, row, reason=reason)
        await session.commit()
        await session.refresh(row)
        return row
    # running
    age = _age_seconds(row.started_at or row.created_at)
    if age is None or age < running_lim:
        return row
    reason = f"作业执行超时（>{running_lim // 60} 分钟）已自动失败；请缩小任务或检查 LLM"
    row.status = "failed"
    row.error = reason
    row.finished_at = datetime.utcnow()
    await _release_task_lock(session, row, reason=reason)
    await session.commit()
    await session.refresh(row)
    return row


async def reconcile_stale_content_tasks(
    session: AsyncSession,
    *,
    tenant_id: int,
    max_age_seconds: int | None = None,
) -> int:
    """Orphan generating/adapting tasks with no live job → editing."""
    _, running_lim = _stale_limits()
    max_age = max_age_seconds or running_lim
    cutoff = datetime.utcnow() - timedelta(seconds=max_age)
    stuck = list(
        await session.scalars(
            select(GeoContentTask).where(
                GeoContentTask.tenant_id == tenant_id,
                GeoContentTask.status.in_(["generating", "adapting"]),
                GeoContentTask.updated_at < cutoff,
            )
        )
    )
    n = 0
    for task in stuck:
        live = await session.scalar(
            select(GeoAsyncJob.id)
            .where(
                GeoAsyncJob.tenant_id == tenant_id,
                GeoAsyncJob.ref_id == task.id,
                GeoAsyncJob.status.in_(["pending", "running"]),
            )
            .limit(1)
        )
        if live:
            continue
        task.status = "editing"
        n += 1
    if n:
        await session.commit()
    return n


async def create_job(
    session: AsyncSession,
    *,
    tenant_id: int,
    kind: str,
    ref_type: str | None,
    ref_id: int | None,
    request_meta: dict | None,
    created_by: int | None,
) -> GeoAsyncJob:
    row = GeoAsyncJob(
        tenant_id=tenant_id,
        kind=kind,
        status="pending",
        ref_type=ref_type,
        ref_id=ref_id,
        request_meta=request_meta or {},
        created_by=created_by,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def recover_jobs_on_startup(*, requeue_pending: bool = True) -> dict[str, int]:
    """进程启动时：running 一律标失败；pending 未过期则 requeue，过期标失败。

    BackgroundTasks 不跨进程，重启后需显式恢复，否则任务永久卡在 generating。
    """
    import asyncio

    from app.database import async_session_factory

    pending_lim, _running_lim = _stale_limits()
    stats = {"failed_running": 0, "failed_stale_pending": 0, "requeued": 0}
    requeue_ids: list[int] = []

    async with async_session_factory() as session:
        rows = list(
            await session.scalars(
                select(GeoAsyncJob).where(
                    GeoAsyncJob.status.in_(["pending", "running"])
                )
            )
        )
        for row in rows:
            if row.status == "running":
                reason = "进程重启：中断的 running 作业已标记失败，请重试"
                row.status = "failed"
                row.error = reason
                row.finished_at = datetime.utcnow()
                await _release_task_lock(session, row, reason=reason)
                stats["failed_running"] += 1
                continue
            # pending
            age = _age_seconds(row.created_at)
            if age is not None and age >= pending_lim:
                reason = f"进程重启且排队已超时（>{pending_lim}s），标记失败"
                row.status = "failed"
                row.error = reason
                row.finished_at = datetime.utcnow()
                await _release_task_lock(session, row, reason=reason)
                stats["failed_stale_pending"] += 1
            elif requeue_pending:
                requeue_ids.append(int(row.id))
                stats["requeued"] += 1
            else:
                reason = "进程重启：pending 作业未自动续跑（requeue 关闭）"
                row.status = "failed"
                row.error = reason
                row.finished_at = datetime.utcnow()
                await _release_task_lock(session, row, reason=reason)
                stats["failed_stale_pending"] += 1
        await session.commit()

    for jid in requeue_ids:
        try:
            asyncio.create_task(run_job_in_background(jid))
        except Exception:  # noqa: BLE001
            logger.exception("requeue job %s failed", jid)
    if any(stats.values()):
        logger.info("geo async recover_on_startup %s", stats)
    return stats


async def mark_job(
    session: AsyncSession,
    job_id: int,
    *,
    status: str,
    error: str | None = None,
    result_meta: dict | None = None,
) -> None:
    row = await session.get(GeoAsyncJob, job_id)
    if row is None:
        return
    row.status = status
    if status == "running" and row.started_at is None:
        row.started_at = datetime.utcnow()
    if status in {"succeeded", "failed", "cancelled"}:
        row.finished_at = datetime.utcnow()
    if error is not None:
        row.error = error[:2000]
    if result_meta is not None:
        row.result_meta = result_meta
    await session.commit()


async def run_job_in_background(job_id: int) -> None:
    from app.database import async_session_factory

    try:
        async with async_session_factory() as session:
            row = await session.get(GeoAsyncJob, job_id)
            if row is None:
                return
            await mark_job(session, job_id, status="running")
            row = await session.get(GeoAsyncJob, job_id)
            if row is not None and cancel_requested(row):
                await mark_job(session, job_id, status="cancelled", error="已取消")
                return
            try:
                if row.kind == KIND_GENERATE:
                    result = await _execute_generate(session, row)
                elif row.kind == KIND_PUSH_BATCH:
                    result = await _execute_push_batch(session, row)
                elif row.kind == KIND_VARIANTS:
                    result = await _execute_variants(session, row)
                else:
                    raise ValueError(f"未知作业类型: {row.kind}")
                await mark_job(session, job_id, status="succeeded", result_meta=result)
            except Exception as exc:  # noqa: BLE001
                live = await session.get(GeoAsyncJob, job_id) or row
                cancelled = str(exc) == "已取消" or cancel_requested(live)
                if row.ref_id and row.kind in {KIND_GENERATE, KIND_VARIANTS}:
                    task = await session.get(GeoContentTask, row.ref_id)
                    if task is not None and task.status in {
                        "generating",
                        "adapting",
                    }:
                        task.status = "editing"
                        await session.commit()
                if cancelled:
                    await mark_job(session, job_id, status="cancelled", error="已取消")
                    return
                logger.exception("geo async job failed id=%s", job_id)
                await mark_job(
                    session,
                    job_id,
                    status="failed",
                    error=str(exc),
                )
    except Exception:  # noqa: BLE001
        logger.exception("geo async job session failed id=%s", job_id)


async def _execute_generate(session: AsyncSession, job: GeoAsyncJob) -> dict[str, Any]:
    from app.geo.content.ai_settings import resolve_llm_credentials
    from app.geo.content.brief import brief_ready, normalize_brief
    from app.geo.content.evidence import prepare_facts_for_generation
    from app.geo.content.generate_article import generate_master_article, outline_from_payload, to_markdown
    from app.geo.content.review import invalidate_review
    from app.models import GeoArticleVersion, GeoFact, GeoPrompt, GeoTaskFact, Tenant

    task = await session.get(GeoContentTask, job.ref_id)
    if task is None or task.tenant_id != job.tenant_id:
        raise ValueError("内容任务不存在")
    tenant = await session.get(Tenant, job.tenant_id)
    prompt = await session.get(GeoPrompt, task.prompt_id)
    if tenant is None or prompt is None:
        raise ValueError("租户或意图词缺失")

    facts = list(
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
            "fact_type": f.fact_type,
            "source_name": f.source_name,
            "source_url": f.source_url,
            "trust_level": f.trust_level,
        }
        for f in facts
    ]
    brief_norm = normalize_brief(task.brief)
    if not brief_ready(brief_norm):
        raise ValueError("Brief 未就绪，请先完善 Brief")
    _, evidence_preview = prepare_facts_for_generation(fact_dicts, min_eligible=3)
    if not evidence_preview.get("ok"):
        raise ValueError("事实证据不足，请绑定至少 3 条可生成事实")

    task.status = "generating"
    await session.commit()
    await set_job_progress(session, job, message="正在准备事实与 Brief", pct=15)
    if cancel_requested(await session.get(GeoAsyncJob, job.id) or job):
        task.status = "editing"
        await session.commit()
        raise ValueError("已取消")

    llm = await resolve_llm_credentials(session, job.tenant_id)
    from app.geo.content.business_profile import display_brand
    from app.models.geo_optimization import GeoOptimizationBusiness

    biz_row = None
    if getattr(task, "business_id", None):
        biz_row = await session.get(GeoOptimizationBusiness, task.business_id)
    await set_job_progress(session, job, message="正在调用模型写稿", pct=45)
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
    job = await session.get(GeoAsyncJob, job.id) or job
    if cancel_requested(job):
        task.status = "editing"
        await session.commit()
        raise ValueError("已取消")
    await set_job_progress(session, job, message="正在挂事实引用并落库", pct=80)
    body = to_markdown(payload)
    outline = outline_from_payload(payload)
    from app.geo.content.evidence_cite import attach_sentence_citations

    body, cites = attach_sentence_citations(body, fact_dicts)
    outline = dict(outline or {})
    outline["sentence_citations"] = cites
    latest = await session.scalar(
        select(GeoArticleVersion)
        .where(GeoArticleVersion.task_id == task.id)
        .order_by(GeoArticleVersion.version_no.desc())
        .limit(1)
    )
    version_no = (latest.version_no + 1) if latest else 1
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
            "evidence": payload.get("_evidence") or evidence_preview,
            "brief": payload.get("_brief") or brief_norm,
            "async_job_id": job.id,
            "sentence_citations": cites,
        },
        created_by=job.created_by,
    )
    session.add(article)
    task.title = payload["title"]
    task.status = "editing"
    invalidate_review(task)
    await session.commit()
    return {
        "task_id": task.id,
        "article_id": article.id,
        "version_no": version_no,
        "title": article.title,
    }


async def _execute_variants(session: AsyncSession, job: GeoAsyncJob) -> dict[str, Any]:
    from app.geo.content.variant_execute import execute_variants_for_task

    meta = job.request_meta or {}
    channels = meta.get("channels")
    use_llm = bool(meta.get("use_llm", True))
    if not job.ref_id:
        raise ValueError("缺少 task_id")
    return await execute_variants_for_task(
        session,
        task_id=int(job.ref_id),
        tenant_id=job.tenant_id,
        channels=list(channels) if channels else None,
        use_llm=use_llm,
    )


async def _execute_push_batch(session: AsyncSession, job: GeoAsyncJob) -> dict[str, Any]:
    """Run multi-channel push using same connectors as sync endpoint."""
    from app.geo.content.connectors.social import SocialError
    from app.geo.content.connectors.webhook import WebhookConnectorError
    from app.geo.content.multi_push import execute_single_push, list_push_targets
    from app.geo.content.review import assert_review_approved
    from app.models import (
        GeoArticleVersion,
        GeoChannelAccount,
        GeoChannelVariant,
        GeoPublication,
        GeoPublishingChannel,
    )

    meta = job.request_meta or {}
    task = await session.get(GeoContentTask, job.ref_id)
    if task is None or task.tenant_id != job.tenant_id:
        raise ValueError("内容任务不存在")

    assert_review_approved(task)

    variants = list(
        await session.scalars(
            select(GeoChannelVariant).where(GeoChannelVariant.task_id == task.id)
        )
    )
    var_map = {str(v.channel).lower(): v for v in variants}
    article = await session.scalar(
        select(GeoArticleVersion)
        .where(GeoArticleVersion.task_id == task.id)
        .order_by(GeoArticleVersion.version_no.desc())
        .limit(1)
    )

    targets_all = await list_push_targets(
        session, tenant_id=job.tenant_id, task=task, variants=variants
    )
    ready = [t for t in targets_all if t.get("ready")]
    wanted = meta.get("targets")  # list of {channel, account_id}
    if wanted:
        pairs = {
            (
                str(t.get("channel") or t.get("adapt_key") or "").lower(),
                int(t["account_id"]),
            )
            for t in wanted
            if t.get("account_id") is not None
        }
        filtered = []
        for t in ready:
            aid = int(t["account_id"])
            keys = {
                (str(t.get("adapt_key") or "").lower(), aid),
                (str(t.get("channel_type") or "").lower(), aid),
            }
            if keys & pairs:
                filtered.append(t)
        ready = filtered

    if not ready:
        raise ValueError("没有可推送目标")

    mode = str(meta.get("mode") or "publish")
    create_pub = bool(meta.get("create_publication", True))
    results: list[dict[str, Any]] = []
    ok_n = fail_n = 0
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
                mode=mode,
                article=article,
            )
            remote_url = remote.get("remote_url")
            publication_created = False
            if create_pub and remote_url and str(remote_url).startswith(
                ("http://", "https://")
            ):
                pub = GeoPublication(
                    variant_id=variant.id,
                    channel=channel_key,
                    publish_mode="auto_publish",
                    published_url=str(remote_url),
                    published_at=datetime.utcnow(),
                    status="published",
                    note=meta.get("note") or f"async batch {remote.get('connector')}",
                )
                session.add(pub)
                variant.status = "published"
                task.status = "published"
                publication_created = True
            results.append(
                {**remote, "ok": True, "publication_created": publication_created}
            )
            ok_n += 1
        except (WebhookConnectorError, SocialError, ValueError) as exc:
            results.append(
                {
                    "ok": False,
                    "channel": channel_key,
                    "account_id": t.get("account_id"),
                    "error": str(exc),
                }
            )
            fail_n += 1
    await session.commit()
    return {"ok_count": ok_n, "fail_count": fail_n, "results": results}
