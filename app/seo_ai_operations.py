"""Durable claims: charge, result persistence and refund are each atomic.

Every transition locks the tenant module before the operation, including cleanup.
Expired workers cannot persist results after their quota has been refunded.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update, null

from app.database import async_session_factory
from app.models.module_workspace import TenantModule
from app.models.seo import SeoAiOperation
from app.seo_usage_limits import charge_seo_usage, SEO_USAGE_KEY

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=15)
RESULT_RETENTION = timedelta(days=30)


def retained_result(row):
    if row.result is None or row.completed_at is None or row.completed_at <= datetime.utcnow() - RESULT_RETENTION:
        raise operation_error("operation_result_expired", "结果已超过 30 天保存期限；此次取回不会再次扣费，请重新发起操作")
    return row.result


class SeoAiReplay(Exception):
    def __init__(self, result):
        self.result = result


def request_fingerprint(payload) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def operation_error(code, message):
    return HTTPException(409, {"code": code, "message": message}, headers={"Retry-After": "5"})


async def _module(session, tenant_id):
    module = await session.scalar(select(TenantModule).where(
        TenantModule.tenant_id == tenant_id, TenantModule.module_code == "seo",
    ).with_for_update().execution_options(populate_existing=True))
    if module is None:
        raise HTTPException(403, "SEO 工作区不存在")
    return module


def _refund(module, row):
    settings = dict(module.module_settings or {})
    usage = dict(settings.get(SEO_USAGE_KEY) or {})
    if usage.get("date") == row.charged_on:
        usage["ai_requests"] = max(0, int(usage.get("ai_requests") or 0) - 1)
        settings[SEO_USAGE_KEY] = usage
        module.module_settings = settings
    row.status = "refunded"
    row.completed_at = datetime.utcnow()


async def claim_seo_ai_operation(session, tenant_id, *, request_key, payload, actor, kind, limit):
    module = await _module(session, tenant_id)
    fingerprint = request_fingerprint(payload)
    row = await session.scalar(select(SeoAiOperation).where(
        SeoAiOperation.tenant_id == tenant_id, SeoAiOperation.request_key == request_key,
    ).with_for_update().execution_options(populate_existing=True))
    if row is not None:
        if (row.request_hash, row.actor, row.kind) != (fingerprint, actor, kind):
            await session.rollback()
            raise operation_error("request_conflict", "请求标识已用于其他内容，请重新发起操作")
        if row.status == "succeeded":
            try:
                result = retained_result(row)
            finally:
                await session.rollback()
            raise SeoAiReplay(result)
        if row.status == "running" and row.expires_at <= datetime.utcnow():
            _refund(module, row)
            await session.commit()
        if row.status == "refunded":
            await session.rollback()
            raise operation_error("operation_refunded", "上次操作未完成，额度已退还，请重新发起操作")
        await session.rollback()
        raise operation_error("operation_running", "上次操作仍在处理中，请稍后重试以取回结果")
    receipt = await charge_seo_usage(session, tenant_id, "ai_requests", 1, limit, commit=False)
    operation_id = str(uuid4())
    session.add(SeoAiOperation(
        id=operation_id, tenant_id=tenant_id, site_id=payload.get("site_id"), request_key=request_key,
        request_hash=fingerprint, actor=actor, kind=kind, charged_on=receipt["date"],
        status="running", expires_at=datetime.utcnow() + LEASE,
    ))
    await session.commit()
    return {**receipt, "operation_id": operation_id}


async def settle_seo_ai_operation(session, tenant_id, operation_id, *, result=None):
    module = await _module(session, tenant_id)
    row = await session.scalar(select(SeoAiOperation).where(
        SeoAiOperation.id == operation_id, SeoAiOperation.tenant_id == tenant_id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None:
        await session.rollback()
        raise operation_error("operation_missing", "操作记录不存在，请重新发起操作")
    if row.status == "succeeded":
        cached = row.result
        await session.rollback()
        return cached
    if row.status == "refunded":
        await session.rollback()
        if result is not None:
            raise operation_error("operation_refunded", "操作已结束且额度已退还，请重新发起操作")
        return None
    expired = row.expires_at <= datetime.utcnow()
    if result is None or expired:
        _refund(module, row)
    else:
        row.status = "succeeded"
        row.result = result
        row.completed_at = datetime.utcnow()
    await session.commit()
    if result is not None and expired:
        raise operation_error("operation_refunded", "操作已超时且额度已退还，请重新发起操作")
    return result


async def refund_failed_operation(tenant_id, operation_id):
    # A fresh session also works if the request session is already aborted.
    async with async_session_factory() as session:
        await settle_seo_ai_operation(session, tenant_id, operation_id)


async def reconcile_seo_ai_operations():
    async with async_session_factory() as session:
        candidates = (await session.execute(select(SeoAiOperation.id, SeoAiOperation.tenant_id).where(
            SeoAiOperation.status == "running", SeoAiOperation.expires_at <= datetime.utcnow(),
        ).order_by(SeoAiOperation.expires_at).limit(200))).all()
    refunded = 0
    for operation_id, tenant_id in candidates:
        try:
            await refund_failed_operation(tenant_id, operation_id)
            refunded += 1
        except Exception:
            logger.exception("SEO AI quota reconciliation failed operation_id=%s", operation_id)
    async with async_session_factory() as session:
        expired = select(SeoAiOperation.id).where(
            SeoAiOperation.status == "succeeded", SeoAiOperation.result.is_not(None),
            SeoAiOperation.completed_at <= datetime.utcnow() - RESULT_RETENTION,
        ).order_by(SeoAiOperation.completed_at).limit(500).with_for_update(skip_locked=True)
        cleared = await session.execute(update(SeoAiOperation).where(SeoAiOperation.id.in_(expired)).values(result=null()))
        await session.commit()
    return {"examined": len(candidates), "settled": refunded, "results_cleared": cleared.rowcount}
