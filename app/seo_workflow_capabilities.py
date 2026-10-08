"""Read-only trigger preflight, shared with the locked reservation paths."""
from sqlalchemy import func, select

from app.models.seo import SeoKeywordAsset
from app.models.seo_cockpit import SeoTask
from app.module_scope import seo_site_is_operational
from app.seo_content_workflow import ACTION, plan_for, schema_ready
from app.seo_service_plan import service_plan_is_paused

ACTIONS = {"content": ACTION, "website": "site_diagnosis",
           "monitoring": "ranking_followup", "report": "monthly_report"}


async def new_workflow_blocker(session, site, kind):
    if service_plan_is_paused(site):
        return "service_plan_paused"
    plan = plan_for(site)
    if not plan.get("revision"):
        return "service_plan_required"
    if await session.scalar(select(SeoTask.id).where(
        SeoTask.tenant_id == site.tenant_id, SeoTask.site_id == site.id,
        SeoTask.action_type == ACTIONS[kind], SeoTask.status.in_(("open", "in_progress")),
    ).limit(1)) is not None:
        return "content_workflow_already_active" if kind == "content" else "service_workflow_already_active"
    if kind == "content" and (not plan.get("content_topics") or not plan.get("optimization_directions")):
        return "service_plan_content_topics_required"
    if kind == "monitoring":
        count = int(await session.scalar(select(func.count()).select_from(SeoKeywordAsset).where(
            SeoKeywordAsset.tenant_id == site.tenant_id, SeoKeywordAsset.site_id == site.id,
            SeoKeywordAsset.status == "active",
        )) or 0)
        if not count:
            return "keyword_inventory_required"
        if count > 200:
            return "monitoring_keyword_limit_200"
    return None


async def trigger_capabilities(session, ctx, site):
    from app.api.seo import _site_advisor_assignment
    if not await schema_ready(session):
        common = "content_workflow_schema_unavailable"
    elif ctx.user_id is None:
        common = "authenticated_user_required"
    elif not (ctx.can_edit("seo.content") and ctx.can_edit("seo.site")):
        common = "content_and_site_edit_permissions_required"
    elif not await _site_advisor_assignment(session, site.tenant_id, site.id, ctx.user_id, schema_ready=True):
        common = "active_site_advisor_assignment_required"
    elif not await seo_site_is_operational(session, site.tenant_id, site.id):
        common = "site_or_module_not_operational"
    else:
        common = None
    result = {}
    for kind in ACTIONS:
        reason = common
        if reason is None and kind == "monitoring" and not ctx.can_edit("seo.keywords"):
            reason = "keyword_edit_permission_required"
        if reason is None:
            reason = await new_workflow_blocker(session, site, kind)
        result[kind] = {
            "allowed": reason is None, "reason": reason,
            "method": "POST", "endpoint": "/api/v1/seo/workbench/" + (
                "service-plan/run" if kind == "content" else "service-cycles/run"),
            "kind": None if kind == "content" else kind,
            "expected_revision": int(plan_for(site).get("revision") or 0),
            "request_id_format": "uuid", "meaning": "new_execution_only",
        }
    return result
