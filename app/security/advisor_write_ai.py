"""Exact advisor AI contracts, durable suggestion quota and worker authority."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from starlette.requests import Request

from app.security.advisor_scope import AdvisorScope, deny

GENERATE = "/api/v1/geo/content-tasks/{task_id}/generate"
SUGGEST = "/api/v1/geo/content-tasks/{task_id}/suggest-brief"
AI_REVIEW = "/api/v1/geo/content-tasks/{task_id}/ai-review"
TASK_TEMPLATES = {GENERATE, SUGGEST, AI_REVIEW}
SUGGEST_KIND = "advisor_suggest_brief"
QUOTA_MESSAGE = "今天这个客户的 AI 建议已用完 10 次，明天再试"


def rules():
    from app.security.advisor_write_routes import FORBIDDEN, WriteRule

    return {
        ("POST", AI_REVIEW): WriteRule("POST", AI_REVIEW, frozenset({"persist"}), FORBIDDEN,
                                        ("geo.assets", "geo.content"), "project"),
        ("POST", GENERATE): WriteRule("POST", GENERATE, frozenset(), FORBIDDEN,
                                      ("geo.assets", "geo.content"), "project"),
        ("POST", SUGGEST): WriteRule("POST", SUGGEST, frozenset({"overwrite", "use_llm"}),
                                     FORBIDDEN - {"use_llm"},
                                     ("geo.assets", "geo.content"), "project"),
    }


async def read_contract(request, rule):
    """Validate raw input before FastAPI's bool coercion or JSON key loss."""
    import json

    def invalid():
        deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", "请只提交此操作支持的参数，开关只能用 true 或 false")

    seen = set()
    for key, value in request.query_params.multi_items():
        if key in seen or key not in ({"tenant_id", "run_async"} if rule.template == GENERATE else {"tenant_id"}):
            invalid()
        seen.add(key)
        if key == "run_async" and value not in {"true", "false"}:
            invalid()
    raw = await request.body()
    if rule.template == GENERATE:
        if raw.strip() not in {b"", b"null"}:
            invalid()
        return {}

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                invalid()
            result[key] = value
        return result

    try:
        body = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        invalid()
    fields = {"persist"} if rule.template == AI_REVIEW else {"overwrite", "use_llm"}
    if not isinstance(body, dict) or set(body) - fields:
        invalid()
    if any(type(value) is not bool for value in body.values()):
        invalid()
    return body


async def recheck_request(session, ctx, task):
    if getattr(ctx, "advisor_scope", None) is None:
        return
    from app.security.advisor_write_commit import recheck_advisor_before_commit
    from app.security.advisor_write_handlers import lock_manual_task
    from app.security.geo_advisor import check_manual_execution_scope

    # Match the HTTP guard's tenant -> authority/object lock order, including
    # checks after the quota reservation released the previous transaction.
    await check_manual_execution_scope(session, ctx, rules()[("POST", SUGGEST)])
    await lock_manual_task(session, ctx, task)
    await recheck_advisor_before_commit(session, ctx)


def job_authority(session, ctx):
    """Persist identifiers and expiry, never a bearer token or credential."""
    if getattr(ctx, "advisor_scope", None) is None:
        return {}
    binding = session.info["advisor_scoped_write"]
    return {"advisor_authority": {"user_id": ctx.user_id,
            "tenant_id": ctx.tenant_id, "grant_id": ctx.advisor_scope.grant_id,
            "expires_at": binding[4], "operation": binding[3].template,
            "body": binding[2]}}


async def recheck_job(session, job):
    """Fresh user/role/grant/module/project checks on the worker transaction."""
    meta = job.request_meta or {}
    if "advisor_authority" not in meta:
        return
    authority = meta["advisor_authority"]
    from app.security.auth import AuthContext
    from app.security.advisor_write_commit import recheck_advisor_before_commit
    from app.models import GeoContentTask

    if (not isinstance(authority, dict) or authority.get("user_id") != job.created_by
            or authority.get("tenant_id") != job.tenant_id
            or type(authority.get("grant_id")) is not int
            or type(authority.get("expires_at")) not in {int, float}):
        deny(403, "ADVISOR_GRANT_REVOKED", "顾问作业授权无效，请重新选择客户")
    ctx = AuthContext(job.created_by, "", "顾问", job.tenant_id,
                      {"geo.assets": "edit", "geo.content": "edit"},
                      advisor_scope=AdvisorScope(frozenset({job.tenant_id}), job.tenant_id,
                                                 authority["grant_id"]))
    from app.security.advisor_write_publish import VARIANTS, PUSH_BATCH
    from app.security.advisor_write_operations import rules as operation_rules
    operation = authority.get("operation", GENERATE)
    all_rules = {**rules(), **operation_rules()}
    rule = all_rules.get(("POST", operation))
    if rule is None or operation not in {GENERATE, VARIANTS, PUSH_BATCH}:
        deny(403, "ADVISOR_ROUTE_UNAVAILABLE", "顾问作业操作未授权")
    body = authority.get("body", {})
    from app.security.advisor_write_routes import check_write_fields
    check_write_fields(rule, body)
    request = Request({"type": "http", "method": "POST", "path": operation.replace("{task_id}", str(job.ref_id)),
                       "headers": [], "query_string": f"tenant_id={job.tenant_id}".encode(),
                       "path_params": {"task_id": job.ref_id},
                       "route": SimpleNamespace(path=operation)})
    request.scope["geo_advisor_actor"] = (ctx.user_id, ctx.tenant_id)
    # Workers explicitly recheck before business commits. Do not install the
    # HTTP session hook on their failure-cleanup/status-only transactions.
    session.info["advisor_scoped_write"] = (ctx, request, body, rule, authority["expires_at"])
    from app.security.geo_advisor import check_manual_execution_scope
    await check_manual_execution_scope(session, ctx, rule)
    await recheck_advisor_before_commit(session, ctx)
    task = await session.get(GeoContentTask, job.ref_id)
    expected = "adapting" if operation == VARIANTS else "generating" if operation == GENERATE else None
    if task is None or (expected is not None and task.status != expected):
        deny(403, "ADVISOR_WRITE_STATE_FORBIDDEN", "当前任务状态不允许生成母稿")


def suggestion_day(now):
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return (start.astimezone(timezone.utc).replace(tzinfo=None),
            (start + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None))


async def reserve_suggestion(session, ctx, task):
    """Reuse terminal job records; serialize and commit BEFORE any AI call.

    Count accepted attempts, including heuristic fallback and provider failures.
    No pending work is queued for these reservation-only records.
    """
    if getattr(ctx, "advisor_scope", None) is None:
        return
    from app.models import GeoAsyncJob, Tenant

    await session.scalar(select(Tenant.id).where(Tenant.id == ctx.tenant_id).with_for_update())
    now = datetime.now(timezone.utc)
    start, end = suggestion_day(now)
    used = await session.scalar(select(func.count()).select_from(GeoAsyncJob).where(
        GeoAsyncJob.tenant_id == ctx.tenant_id, GeoAsyncJob.created_by == ctx.user_id,
        GeoAsyncJob.kind == SUGGEST_KIND,
        GeoAsyncJob.created_at >= start, GeoAsyncJob.created_at < end).execution_options(advisor_scope_control=True))
    if used >= 10:
        deny(429, "ADVISOR_SUGGEST_DAILY_LIMIT", QUOTA_MESSAGE)
    stamp = now.replace(tzinfo=None)
    session.add(GeoAsyncJob(tenant_id=ctx.tenant_id, created_by=ctx.user_id,
                kind=SUGGEST_KIND, status="succeeded", ref_type="content_task", ref_id=task.id,
                request_meta={"reservation_only": True}, result_meta={},
                created_at=stamp, started_at=stamp, finished_at=stamp))
    await session.commit()
