"""Advisor/client/day request limits in the existing locked module JSON."""
import hashlib
import json
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from pydantic import TypeAdapter, ValidationError

from app.models.module_workspace import TenantModule
from app.seo_usage_limits import SEO_USAGE_TIMEZONE

KEY = "seo_advisor_daily_requests"
LIMIT = 10
_BOOL = TypeAdapter(bool)
AI_ROUTES = frozenset({
    "/api/v1/seo/content-ai/assist", "/api/v1/seo/qa/planning/semantic",
    "/api/v1/seo/qa/research/draft", "/api/v1/seo/qa/research/extract",
    "/api/v1/seo/qa/research/quality", "/api/v1/seo/site/pages/ai-tdk/generate",
    "/api/v1/seo/content-distribution/adapt", "/api/v1/seo/content-distribution/variants/generate",
    "/api/v1/seo/site-pages/ai-remediation", "/api/v1/seo/site-pages/image-remediation/ai-drafts",
    "/api/v1/seo/workbench/onsite-tasks/{task_id}/ai-proposal", "/api/v1/seo/workbench/assistant/chat",
    "/api/v1/seo/rank-serp/collect",
})
RECOVERABLE_KINDS = {
    '/api/v1/seo/content-ai/assist': 'advisor_content_assist',
    '/api/v1/seo/qa/planning/semantic': 'advisor_qa_semantic',
    '/api/v1/seo/qa/research/extract': 'advisor_qa_extract',
    '/api/v1/seo/qa/research/quality': 'advisor_qa_quality',
    '/api/v1/seo/content-distribution/adapt': 'advisor_distribution_adapt',
    '/api/v1/seo/workbench/assistant/chat': 'advisor_workbench_chat',
}


def uses_ai(body, default):
    try:
        return _BOOL.validate_python(body.get('use_ai', default))
    except ValidationError:
        # The endpoint rejects the same invalid bool; it cannot call AI.
        return False


def request_kind(template, body):
    if template not in AI_ROUTES:
        return None
    if template == "/api/v1/seo/rank-serp/collect" and not uses_ai(body, True):
        return None
    if template in {"/api/v1/seo/content-distribution/adapt", "/api/v1/seo/content-distribution/variants/generate"} and not uses_ai(body, False):
        return None
    if (template == "/api/v1/seo/content-ai/assist" and body.get("action") == "generate"
            or template == "/api/v1/seo/qa/research/draft"):
        return "generation"
    return "suggestion"


def reserve(settings, user_id, template, body, *, now=None, path_params=None):
    """Pure transition; caller must hold the tenant-module UPDATE lock."""
    today = (now or datetime.now(SEO_USAGE_TIMEZONE)).astimezone(SEO_USAGE_TIMEZONE).date().isoformat()
    config = dict(settings or {})
    state = dict(config.get(KEY) or {})
    if state.get("date") != today:
        state = {"date": today, "actors": {}}
    actors = dict(state.get("actors") or {})
    requests = dict(actors.get(str(user_id)) or {})
    fingerprint = hashlib.sha256(json.dumps([template, body, path_params or {}], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    key = str(body.get("request_id") or uuid4())
    if key in requests:
        if requests[key] != fingerprint:
            raise HTTPException(409, {"code": "ADVISOR_AI_REQUEST_CONFLICT", "message": "请求编号已用于其他内容，请重新发起"})
        return config, {"date": today, "used": len(requests), "limit": LIMIT}
    if len(requests) >= LIMIT:
        raise HTTPException(429, {"code": "ADVISOR_AI_DAILY_LIMIT", "message": "今天这个客户的 AI 建议已用完 10 次，明天再试"})
    requests[key] = fingerprint
    actors[str(user_id)] = requests
    state["actors"] = actors
    config[KEY] = state
    return config, {"date": today, "used": len(requests), "limit": LIMIT}


async def admit(session, ctx, rule, body):
    kind = request_kind(rule.template, body)
    session._seo_advisor_ai_kind = kind
    if kind != "suggestion":
        return
    expected_kind = RECOVERABLE_KINDS.get(rule.template)
    if body.get("request_id") and expected_kind:
        from app.models.seo import SeoAiOperation
        key = str(body["request_id"])
        keys = [f"wb:{ctx.user_id}:{key}"] if rule.template == '/api/v1/seo/workbench/assistant/chat' else [key]
        prior = await session.scalar(select(SeoAiOperation).where(
            SeoAiOperation.tenant_id == ctx.tenant_id, SeoAiOperation.request_key.in_(keys),
            SeoAiOperation.actor == str(ctx.user_id), SeoAiOperation.kind == expected_kind,
        ))
        if prior is not None:
            # The handler still validates its full fingerprint before recovery.
            # Retrieving a durable result on another day never spends a new use.
            return
    module = await session.scalar(select(TenantModule).where(
        TenantModule.tenant_id == ctx.tenant_id, TenantModule.module_code == "seo",
    ).with_for_update().execution_options(populate_existing=True))
    if module is None:
        raise HTTPException(403, "当前客户没有可用的 SEO 工作区")
    scope = getattr(ctx, 'advisor_write_scope', None)
    path_params = dict(scope[0].path_params) if scope else {}
    module.module_settings, receipt = reserve(module.module_settings, ctx.user_id, rule.template, body, path_params=path_params)
    session._seo_advisor_quota_receipt = receipt
    # The request commit guard rechecks grants and assignment before charging.
    await session.commit()
