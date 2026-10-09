"""Database-backed chat admission across workers. Never holds locks during AI calls."""
import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.models.seo import SeoAiOperation
from app.seo_ai_operations import (_module, _refund, retained_result, request_fingerprint,
                                   operation_error, SeoAiReplay)
from app.seo_usage_limits import (SEO_USAGE_KEY, SEO_USAGE_TIMEZONE, WORKBENCH_CHAT_KIND,
                                  WORKBENCH_CHAT_RESOURCE, workbench_user_resource)

CHAT_KINDS = (WORKBENCH_CHAT_KIND, "workbench_chat")
ADMISSION_KEY = "workbench_chat_admission"


def limited(code, message, retry_after):
    return HTTPException(429, {"code": code, "message": message},
                         headers={"Retry-After": str(max(1, math.ceil(retry_after)))})


async def claim_workbench_chat(session, tenant_id, *, request_key, payload, actor, settings):
    module = await _module(session, tenant_id)
    fingerprint = request_fingerprint(payload)
    now = datetime.utcnow()
    row = await session.scalar(select(SeoAiOperation).where(
        SeoAiOperation.tenant_id == tenant_id, SeoAiOperation.request_key == request_key,
    ).with_for_update().execution_options(populate_existing=True))
    # Recovery is checked before quotas, frequency and concurrency, including UI19 results.
    if row is not None:
        if row.request_hash != fingerprint or row.actor != actor or row.kind not in CHAT_KINDS:
            await session.rollback()
            raise operation_error("request_conflict", "请求标识已用于其他内容，请重新提问")
        if row.status == "succeeded":
            try:
                result = retained_result(row)
            finally:
                await session.rollback()
            raise SeoAiReplay(result)
        if row.status == "running" and row.expires_at <= now:
            _refund(module, row)
            await session.commit()
        status = row.status
        await session.rollback()
        if status == "refunded":
            raise operation_error("operation_refunded", "上次操作未完成，额度已退还，请重新提问")
        raise operation_error("operation_running", "上次操作仍在处理中，请稍后取回结果")

    # Reclaim expired chat leases before admission; provider timeout is 45s, lease is 120s.
    expired = list(await session.scalars(select(SeoAiOperation).where(
        SeoAiOperation.tenant_id == tenant_id, SeoAiOperation.kind.in_(CHAT_KINDS),
        SeoAiOperation.status == "running", SeoAiOperation.expires_at <= now,
    ).with_for_update().execution_options(populate_existing=True)))
    for old in expired:
        _refund(module, old)
    if expired:
        await session.flush()
    running = list(await session.scalars(select(SeoAiOperation).where(
        SeoAiOperation.tenant_id == tenant_id, SeoAiOperation.kind.in_(CHAT_KINDS),
        SeoAiOperation.status == "running", SeoAiOperation.expires_at > now,
    )))
    if any(old.actor == actor for old in running):
        await session.rollback()
        raise limited("assistant_user_busy", "上一条问题仍在回答，请稍后再提问", 5)
    if len(running) >= settings.seo_workbench_chat_concurrent_per_tenant:
        await session.rollback()
        raise limited("assistant_workspace_busy", "当前客户的 AI 正在处理其他问题，请稍后再试", 5)

    config = dict(module.module_settings or {})
    utc_now = now.replace(tzinfo=timezone.utc)
    timestamp = utc_now.timestamp()
    admission = {key: [t for t in times if t > timestamp - 60]
                 for key, times in (config.get(ADMISSION_KEY) or {}).items()}
    admission = {key: times for key, times in admission.items() if times}
    recent = admission.get(actor, [])
    if len(recent) >= settings.seo_workbench_chat_requests_per_user_per_minute:
        await session.rollback()
        raise limited("assistant_rate_limited", "提问较频繁，请稍等片刻再发送", recent[0] + 60 - timestamp)
    today = utc_now.astimezone(SEO_USAGE_TIMEZONE).date().isoformat()
    usage = dict(config.get(SEO_USAGE_KEY) or {})
    if usage.get("date") != today:
        usage = {"date": today}
    tenant_used = int(usage.get(WORKBENCH_CHAT_RESOURCE) or 0)
    user_key = workbench_user_resource(actor)
    user_used = int(usage.get(user_key) or 0)
    midnight = (utc_now.astimezone(SEO_USAGE_TIMEZONE)
                + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    retry_daily = midnight.timestamp() - timestamp
    if user_used >= settings.seo_workbench_chat_requests_per_user_per_day:
        await session.rollback()
        raise limited("assistant_user_daily_limit", "今天的账号 AI 对话额度已用完，明天恢复", retry_daily)
    if tenant_used >= settings.seo_workbench_chat_requests_per_tenant_per_day:
        await session.rollback()
        raise limited("assistant_tenant_daily_limit", "今天的客户 AI 对话额度已用完，明天恢复", retry_daily)
    usage[WORKBENCH_CHAT_RESOURCE] = tenant_used + 1
    usage[user_key] = user_used + 1
    admission[actor] = [*recent, timestamp]
    config[SEO_USAGE_KEY] = usage
    config[ADMISSION_KEY] = admission
    module.module_settings = config
    operation_id = str(uuid4())
    session.add(SeoAiOperation(id=operation_id, tenant_id=tenant_id, site_id=payload.get("site_id"),
        request_key=request_key, request_hash=fingerprint, actor=actor, kind=WORKBENCH_CHAT_KIND,
        charged_on=today, status="running", expires_at=now + timedelta(seconds=120)))
    await session.commit()
    return {"date": today, "used": tenant_used + 1, "limit": settings.seo_workbench_chat_requests_per_tenant_per_day,
            "operation_id": operation_id}
