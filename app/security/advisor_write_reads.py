"""Project filters shared by the core advisor lists and object reads."""
from sqlalchemy import select

TASK_READS = frozenset("/api/v1/geo/content-tasks/{task_id}" + suffix for suffix in (
    "", "/deliveries", "/export", "/impact", "/publication-monitor", "/push-targets"))


async def assigned_scope(session, ctx):
    from app.geo.project_scope import binding
    from app.geo.project_workflows import plan_for
    from app.models import GeoProject
    projects = list(await session.scalars(select(GeoProject).where(
        GeoProject.tenant_id == ctx.tenant_id).execution_options(populate_existing=True)))
    scopes = {p.id: set(binding(p)["business_ids"]) for p in projects}
    owned = {p.id for p in projects if p.status == "active"
             and type(plan_for(p).get("advisor_user_id")) is int
             and plan_for(p)["advisor_user_id"] == ctx.user_id}
    businesses = {b for pid in owned for b in scopes[pid]
                  if sum(b in ids for ids in scopes.values()) == 1}
    return owned, businesses


async def filter_query(session, ctx, stmt, model):
    if getattr(ctx, "advisor_scope", None) is None:
        return stmt
    from app.models import GeoProject, GeoOptimizationBusiness, GeoOptimizationUnit, GeoPrompt
    projects, businesses = await assigned_scope(session, ctx)
    if model is GeoProject:
        return stmt.where(model.id.in_(projects))
    if model is GeoOptimizationBusiness:
        return stmt.where(model.id.in_(businesses))
    if model is GeoPrompt:
        return stmt.where(model.unit_id.in_(select(GeoOptimizationUnit.id).where(
            GeoOptimizationUnit.tenant_id == ctx.tenant_id,
            GeoOptimizationUnit.business_id.in_(businesses))))
    return stmt.where(model.business_id.in_(businesses))


async def check_read_assignment(session, ctx, request):
    from app.security.advisor_write_objects import ensure_advisor_assignment
    from app.security.advisor_write_routes import WriteRule
    path = getattr(request.scope.get("route"), "path", None)
    core = TASK_READS | {"/api/v1/geo/projects/{project_id}/executions",
                        "/api/v1/geo/optimization-businesses/{business_id}/dashboard"}
    if path in core:
        rule = WriteRule("GET", path, frozenset(), frozenset(), (), "project")
        await ensure_advisor_assignment(session, ctx, request, {}, rule)
