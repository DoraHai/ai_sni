"""Scope and cost checks for the one admitted advisor visibility action."""
from sqlalchemy import select

from app.models import GeoProject, GeoPrompt, GeoOptimizationUnit, Tenant
from app.security.advisor_scope import deny


async def check_visibility_scope(session, ctx, request):
    """Freeze at most 20 active questions; revalidate that scope before commit.

    The tenant lock is also used by scheduler/settings/project binding writers.
    Unassigned, ambiguous and other-project questions never enter this run.
    """
    from app.geo.project_scope import binding, project_scope
    from app.geo.project_workflows import advisor_available, plan_for

    await session.scalar(select(Tenant.id).where(Tenant.id == ctx.tenant_id).with_for_update())
    projects = list(await session.scalars(select(GeoProject).where(
        GeoProject.tenant_id == ctx.tenant_id).order_by(GeoProject.id)
        .with_for_update().execution_options(populate_existing=True)))
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
    if not owned or not await advisor_available(session, ctx.tenant_id, ctx.user_id):
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
