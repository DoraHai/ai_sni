"""GEO adapter for the shared advisor grant contract. No task dispatch rights."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.security.advisor_scope import AdvisorScope, active_grants, deny, is_advisor, read_grants


async def apply_claims(ctx, user, role, claims, session):
    advisor = is_advisor(role)
    admin = bool(role and role.is_system and role.name == "管理员") or ctx.can_edit("settings.accounts")
    if admin:
        if claims.get("scope_kind") is not None:
            deny(401, "ADVISOR_ROLE_CHANGED", "请重新登录")
        return
    try:
        rows = await read_grants(session, user.id)
    except HTTPException:
        if advisor or claims.get("scope_kind") is not None:
            raise
        # Code-first rollout: existing non-advisor behavior remains available.
        return
    if not advisor:
        if rows or claims.get("scope_kind") is not None:
            deny(403, "ADVISOR_ROLE_CHANGED", "顾问角色已变化，请管理员核对客户授权")
        return
    try:
        active = await active_grants(session, rows)
    except DBAPIError:
        deny(503, "ADVISOR_GRANTS_UNAVAILABLE", "顾问客户授权尚未就绪")
    scope = AdvisorScope(frozenset(g.tenant_id for g in active))
    ctx.tenant_id = None
    ctx.advisor_scope = scope
    ctx.auth_exp = claims.get("auth_exp", claims.get("exp"))
    if claims.get("scope_kind") == "advisor_tenant":
        tid, gid = claims.get("tid"), claims.get("gid")
        if type(tid) is not int or tid <= 0 or type(gid) is not int or gid <= 0:
            deny(401, "ADVISOR_INVALID_TOKEN", "无效的客户凭证")
        if not any(g.id == gid and g.tenant_id == tid for g in active):
            deny(401, "ADVISOR_GRANT_REVOKED", "客户授权已撤销，请重新选择客户")
        if user.tenant_id not in scope.tenant_ids:
            deny(403, "ADVISOR_DEFAULT_TENANT_INVALID", "默认客户与授权不一致")
        ctx.advisor_scope = AdvisorScope(scope.tenant_ids, tid, gid)
        ctx.tenant_id = tid


def positive_id(value):
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0:
        return int(value)
    deny(422, "ADVISOR_INVALID_OBJECT_ID", "客户和对象 ID 必须是正整数")


async def check_objects(session, ctx, request):
    """Resolve actual tenant owners, including secondary query filters."""
    from app.database import Base
    path = request.url.path
    owners = {
        "project_id": "geo_projects", "business_id": "geo_optimization_businesses",
        "unit_id": "geo_optimization_units", "prompt_id": "geo_prompts",
        "content_task_id": "geo_content_tasks", "snapshot_id": "geo_answer_snapshots",
        "patrol_run_id": "geo_visibility_patrol_runs", "job_id": "geo_async_jobs",
        "async_job_id": "geo_async_jobs", "period_id": "geo_optimization_periods",
        "audit_id": "geo_audit_runs", "ticket_id": "geo_action_tickets",
        "report_id": "geo_competitor_reports", "archive_id": "geo_deliverable_archives",
        "channel_id": "geo_publishing_channels", "account_id": "geo_channel_accounts",
        "placement_id": "geo_media_placements", "fact_id": "geo_facts",
        "run_id": "geo_visibility_patrol_runs",
        "task_id": "geo_action_tickets" if "/integration/tasks" in path else "geo_content_tasks",
    }
    values = list(request.path_params.items()) + list(request.query_params.multi_items())
    for scope_key in request.query_params.getlist("scope_key"):
        # Metric scope encodes an object ID, so treat it as another object input.
        from app.geo.content.daily_metrics import parse_scope_key
        parsed = parse_scope_key(scope_key)
        if parsed["level"] == "unknown":
            deny(422, "ADVISOR_INVALID_OBJECT_ID", "无效的指标范围")
        for key in ("business_id", "unit_id", "prompt_id"):
            if parsed[key] is not None:
                values.append((key, parsed[key]))
    for key, value in values:
        if key == "tenant_id":
            ctx.ensure_tenant(positive_id(value))
            continue
        # Pagination/assignment filters never authorize an object; existing SQL
        # remains constrained by the already verified tenant_id.
        if key in {"before_id", "after_id", "owner_user_id"}:
            continue
        if not key.endswith("_id"):
            continue
        if key == "ref_id":
            table_name = {"content_task": "geo_content_tasks"}.get(request.query_params.get("ref_type"))
        else:
            table_name = owners.get(key)
        table = Base.metadata.tables.get(table_name) if table_name else None
        if table is None or "tenant_id" not in table.c:
            deny(403, "ADVISOR_OBJECT_UNAVAILABLE", "此对象范围尚未开放")
        owner = await session.scalar(select(table.c.tenant_id).where(table.c.id == positive_id(value)))
        if owner is None:
            deny(404, "ADVISOR_OBJECT_NOT_FOUND", "对象不存在")
        ctx.ensure_tenant(owner)


async def guard_request(session, ctx, request, claims):
    if request is None:
        deny(403, "ADVISOR_ROUTE_UNAVAILABLE", "缺少请求范围")
    request.scope["geo_advisor_actor"] = (ctx.user_id, ctx.tenant_id)
    if claims.get("scope_kind") != "advisor_tenant":
        if not ctx.advisor_scope.tenant_ids:
            deny(403, "ADVISOR_NO_TENANT", "顾问尚未获准访问任何客户")
        deny(409, "ADVISOR_TENANT_SELECTION_REQUIRED", "请先切换客户")
    ctx.ensure_tenant(ctx.tenant_id)
    if request.method != "GET":
        await guard_scoped_write(session, ctx, request, claims)
        return
    from app.security.geo_advisor_routes import READ_ROUTES, STATIC_ROUTES
    route = request.scope.get("route")
    template = getattr(route, "path", request.url.path)
    if template not in READ_ROUTES:
        deny(403, "ADVISOR_ROUTE_UNAVAILABLE", "此顾问入口尚未开放")
    from app.security.auth import _required
    keys, edit = _required(request.url.path, request.method)
    if keys is None or not (ctx.can_edit(*keys) if edit else ctx.can_view(*keys)):
        deny(403, "ADVISOR_ROUTE_UNAVAILABLE", "当前角色无权访问此功能")
    await check_objects(session, ctx, request)
    from app.security.advisor_write_reads import check_read_assignment
    await check_read_assignment(session, ctx, request)
    if (template not in STATIC_ROUTES and template != "/api/v1/geo/tenants"
            and not request.query_params.getlist("tenant_id")):
        deny(403, "ADVISOR_TENANT_REQUIRED", "请求必须指定当前客户")
    from app.module_scope import ensure_module_access
    await ensure_module_access(session, ctx, ctx.tenant_id, "geo")

    request.scope["geo_advisor_delivery"] = (ctx.user_id, dict(claims), ctx.tenant_id, frozenset(keys))


async def check_scoped_write_objects(session, ctx, request, body, rule):
    from app.security.advisor_write_routes import VISIBILITY_RUN_RULE
    if rule == VISIBILITY_RUN_RULE:
        from app.security.advisor_visibility import check_visibility_scope
        await check_visibility_scope(session, ctx, request)
        await check_manual_execution_scope(session, ctx, rule)
        return
    # B owns this contract. An incomplete integration remains closed even if
    # someone enables the new flag before the object-policy module is merged.
    try:
        from app.security.advisor_write_objects import check_write_objects, ensure_advisor_assignment
    except ModuleNotFoundError as exc:
        if exc.name != "app.security.advisor_write_objects":
            raise
        deny(403, "ADVISOR_OBJECT_UNAVAILABLE", "受限写入对象核对尚未就绪")
    await check_write_objects(session, ctx, request, body, rule)
    await ensure_advisor_assignment(session, ctx, request, body, rule)
    await check_manual_execution_scope(session, ctx, rule)
    if rule.method == "DELETE":
        from app.security.advisor_write_delete import check_cascade_scope
        await check_cascade_scope(session, request, rule)


async def check_manual_execution_scope(session, ctx, rule):
    """Serialize operations with scheduling; running plans do not veto edits.

    The current policy permits advisor operations during patrols, periods and
    service plans. Keep the shared tenant lock and the independent exact route,
    project assignment and commit checks. This never authorizes plan settings.
    """
    from app.models import Tenant
    await session.scalar(select(Tenant.id).where(Tenant.id == ctx.tenant_id).with_for_update())


async def guard_scoped_write(session, ctx, request, claims):
    from app.config import get_settings
    from app.module_scope import ensure_module_access
    from app.security.advisor_write_routes import match_write_rule, check_write_fields
    from app.security.advisor_write_commit import bind_advisor_write_commit

    if not get_settings().advisor_scoped_content_writes_enabled:
        deny(403, "ADVISOR_HIGH_RISK_WRITES_DISABLED", "顾问任务和写入暂未开放")
    from app.security.advisor_import_preview import PREVIEW_ROUTES, guard_import_preview
    if (request.method, getattr(request.scope.get("route"), "path", None)) in PREVIEW_ROUTES:
        await guard_import_preview(session, ctx, request, claims)
        return
    rule = match_write_rule(request)
    if rule is None:
        deny(403, "ADVISOR_HIGH_RISK_WRITES_DISABLED", "此顾问写入入口尚未开放")
    if not request.query_params.getlist("tenant_id"):
        deny(403, "ADVISOR_TENANT_REQUIRED", "请求必须指定当前客户")
    try:
        from app.security.advisor_write_objects import check_write_objects
    except ModuleNotFoundError as exc:
        if exc.name != "app.security.advisor_write_objects":
            raise
        deny(403, "ADVISOR_OBJECT_UNAVAILABLE", "受限写入对象核对尚未就绪")
    # Resolve supplied object references even when an extra query key or an
    # opaque brief would otherwise fail the field policy first.
    await check_write_objects(session, ctx, request, {}, rule)
    from app.security.advisor_write_operations import rules as operation_rules, read_contract
    from app.security.advisor_write_ai import TASK_TEMPLATES, GENERATE, read_contract as ai_contract
    ai_body = await ai_contract(request, rule) if rule.template in TASK_TEMPLATES else None
    operation = rule in operation_rules().values()
    # Query switches are admitted only by an exact action contract.
    for key, value in (() if operation else request.query_params.multi_items()):
        if key == "project_id" and rule.method == "POST" and rule.template == "/api/v1/geo/optimization-businesses":
            positive_id(value)
            continue
        if key == "run_async" and rule.template == GENERATE:
            continue
        if key != "tenant_id":
            deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", "此查询字段未向顾问开放")
        ctx.ensure_tenant(positive_id(value))
    try:
        # Request.json() caches body bytes for the handler/dependency re-read.
        body = ai_body if ai_body is not None else (await read_contract(request, rule) if operation else await request.json())
    except (ValueError, UnicodeDecodeError):
        deny(403, "ADVISOR_WRITE_FIELD_FORBIDDEN", "顾问写入仅支持 JSON 对象")
    if isinstance(body, dict) and "brief" in body:
        await check_write_objects(session, ctx, request, {"brief": body["brief"]}, rule)
    check_write_fields(rule, body)
    if not all(ctx.can_edit(key) for key in rule.edit_all):
        deny(403, "ADVISOR_ROUTE_UNAVAILABLE", "当前角色无编辑权限")
    await ensure_module_access(session, ctx, ctx.tenant_id, "geo")
    await check_scoped_write_objects(session, ctx, request, body, rule)
    bind_advisor_write_commit(session, ctx, request, body, rule, claims)
    request.state.advisor_scoped_write = rule
    request.scope["geo_advisor_delivery"] = (ctx.user_id, dict(claims), ctx.tenant_id, frozenset(rule.edit_all))
