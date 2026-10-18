"""Scope and cost checks for the one admitted advisor visibility action."""
from sqlalchemy import select

from app.models import GeoProject, GeoPrompt, GeoOptimizationUnit, Tenant, User
from app.security.advisor_scope import deny


class AdvisorVisibilityUnavailable(RuntimeError):
    pass


async def check_visibility_execution(session, run, prompt_ids, *, lock=False):
    """A queued advisor action retains its grant generation, not its JWT."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from sqlalchemy.orm import load_only
    from app.config import get_settings
    from app.models import User, Role
    from app.module_scope import ensure_module_access
    from app.security.advisor_scope import AdvisorScope, account_locked, active_grants, is_advisor, read_grants
    from app.security.auth import AuthContext
    from app.security.advisor_write_routes import VISIBILITY_RUN_RULE
    from app.security.geo_advisor import check_manual_execution_scope

    message = '顾问授权、项目分配或检测范围已变化，请重新发起检测'
    try:
        auth = (run.summary or {}).get('advisor_visibility_auth')
        if (not isinstance(auth, dict) or type(auth.get('user_id')) is not int
                or auth['user_id'] != run.created_by or auth.get('tenant_id') != run.tenant_id
                or type(auth.get('grant_id')) is not int or type(auth.get('auth_exp')) is not int
                or auth['auth_exp'] <= datetime.now(timezone.utc).timestamp()
                or not get_settings().advisor_scoped_content_writes_enabled):
            raise AdvisorVisibilityUnavailable(message)
        # Match the HTTP admission/commit lock order: tenant -> user -> role.
        # Starting a worker with the reverse order can deadlock a new request.
        if lock:
            await session.scalar(select(Tenant.id).where(Tenant.id == run.tenant_id).with_for_update())
        user_query = select(User).options(load_only(
            User.id, User.role_id, User.tenant_id, User.is_active, User.locked_until
        )).where(User.id == run.created_by).execution_options(populate_existing=True)
        if lock:
            user_query = user_query.with_for_update()
        user = await session.scalar(user_query)
        if user is None or not user.is_active or account_locked(user):
            raise AdvisorVisibilityUnavailable(message)
        role = await session.get(Role, user.role_id, populate_existing=True, with_for_update=lock)
        if not is_advisor(role) or any((role.permissions or {}).get(k) != 'edit'
                for k in ('geo.assets', 'geo.content')):
            raise AdvisorVisibilityUnavailable(message)
        grants = await active_grants(session, await read_grants(session, user.id))
        tenants = frozenset(g.tenant_id for g in grants)
        if user.tenant_id not in tenants or not any(
                g.id == auth['grant_id'] and g.tenant_id == run.tenant_id for g in grants):
            raise AdvisorVisibilityUnavailable(message)
        ctx = AuthContext(user.id, '', role.name, run.tenant_id, dict(role.permissions or {}),
            advisor_scope=AdvisorScope(tenants, run.tenant_id, auth['grant_id']))
        await ensure_module_access(session, ctx, run.tenant_id, 'geo')
        request = SimpleNamespace(state=SimpleNamespace(advisor_visibility_prompt_ids=list(prompt_ids)))
        await check_visibility_scope(session, ctx, request, lock=lock)
        if lock:
            await check_manual_execution_scope(session, ctx, VISIBILITY_RUN_RULE)
    except AdvisorVisibilityUnavailable:
        raise
    except Exception as exc:
        raise AdvisorVisibilityUnavailable(message) from exc


def record_visibility_execution(run, result):
    from app.security.advisor_write_audit import record
    auth = (run.summary or {}).get('advisor_visibility_auth')
    if not isinstance(auth, dict) or auth.get('user_id') != run.created_by:
        return
    record({'geo_advisor_actor': (run.created_by, run.tenant_id), 'method': 'POST',
            'path': '/api/v1/geo/visibility-patrol/runs', 'path_params': {'run_id': run.id}}, result)


async def check_visibility_scope(session, ctx, request, *, lock=True):
    """Freeze at most 20 active questions; revalidate that scope before commit.

    The tenant lock is also used by scheduler/settings/project binding writers.
    Unassigned, ambiguous and other-project questions never enter this run.
    """
    from app.geo.project_scope import binding, project_scope
    from app.geo.project_workflows import advisor_available, plan_for

    if lock:
        await session.scalar(select(Tenant.id).where(Tenant.id == ctx.tenant_id).with_for_update())
    project_query = select(GeoProject).where(GeoProject.tenant_id == ctx.tenant_id).order_by(
        GeoProject.id).execution_options(populate_existing=True)
    if lock:
        project_query = project_query.with_for_update()
    projects = list(await session.scalars(project_query))
    owned = set()
    for project in projects:
        plan = plan_for(project)
        if (project.status != "active" or type(plan.get("advisor_user_id")) is not int
                or plan["advisor_user_id"] != ctx.user_id):
            continue
        _, business_ids = await project_scope(session, ctx.tenant_id, project.id)
        for business_id in business_ids:
            if sum(business_id in binding(p)["business_ids"] for p in projects) != 1:
                deny(403, "ADVISOR_ASSIGNMENT_REQUIRED", "项目业务归属有冲突，请由管理员核对")
        owned.update(business_ids)
    actor = await session.get(User, ctx.user_id, populate_existing=True)
    if (not owned or actor is None
            or not await advisor_available(session, actor.tenant_id, ctx.user_id)):
        deny(403, "ADVISOR_ASSIGNMENT_REQUIRED", "当前客户没有分配给你的有效项目")
    units = select(GeoOptimizationUnit.id).where(
        GeoOptimizationUnit.tenant_id == ctx.tenant_id, GeoOptimizationUnit.business_id.in_(owned))
    query = select(GeoPrompt.id).where(GeoPrompt.tenant_id == ctx.tenant_id,
        GeoPrompt.unit_id.in_(units), GeoPrompt.status == "active")
    frozen = getattr(request.state, "advisor_visibility_prompt_ids", None)
    if frozen is None:
        frozen = list(await session.scalars(query.order_by(
            GeoPrompt.priority.desc(), GeoPrompt.id.desc()).limit(20)))
        if not frozen:
            deny(409, "ADVISOR_VISIBILITY_NO_PROMPTS", "已分配的项目没有可检测的有效问题")
        request.state.advisor_visibility_prompt_ids = frozen
    else:
        current = set(await session.scalars(query.where(GeoPrompt.id.in_(frozen))))
        if current != set(frozen):
            deny(403, "ADVISOR_ASSIGNMENT_REQUIRED", "检测问题的项目归属或状态已变化，请刷新后再试")


async def check_visibility_quota(session, ctx):
    # Caller retains the tenant row lock until the pending run is committed.
    from app.config import get_settings
    from app.geo.content.patrol import count_patrol_runs_today

    limit = 10
    used = await count_patrol_runs_today(session, ctx.tenant_id, created_by=ctx.user_id)
    if used >= limit:
        deny(429, "ADVISOR_VISIBILITY_DAILY_LIMIT",
             f"今天这个客户的 AI 可见度手动检测已用完 10 次（{used}/{limit}），明天再试；失败也计次")
