"""Assisted project cycles on the existing ticket ledger, without paid side effects."""
from datetime import datetime, timedelta, timezone
import hashlib
import logging

from fastapi import HTTPException
from sqlalchemy import select

from app.database import async_session_factory
from app.geo.project_scope import binding, project_scope, prompt_ids_for_businesses
from app.geo.tenant_scope import ensure_geo_entitlement, ensure_geo_background_execution_allowed
from app.models import GeoActionTicket, GeoProject, GeoPrompt, Tenant
from app.models.user import User
from app.models.role import Role

PLAN_KEY = "geo_service_plan"
logger = logging.getLogger(__name__)


def plan_for(project):
    return (project.project_settings or {}).get(PLAN_KEY) or {"revision": 0, "enabled": False,
        "status": "paused", "prompt_ids": [], "interval_days": 7, "advisor_user_id": None}


async def advisor_available(session, tenant_id, user_id):
    user = await session.get(User, user_id, populate_existing=True) if user_id else None
    if user is None or not user.is_active or user.tenant_id not in {None, tenant_id}:
        return False
    role = await session.get(Role, user.role_id, populate_existing=True)
    perms = role.permissions if role else {}
    return perms.get("geo.content") == "edit" and perms.get("geo.assets") == "edit"


async def ensure_ticket_project(session, row, tenant_id, prompt_id, project_id=None, *, business_id=None):
    stored = ((row.progress or {}).get("project_workflow") or {}).get("project_id")
    if stored and project_id and stored != project_id:
        raise HTTPException(404, "待办不属于当前项目")
    project_id = stored or project_id
    if project_id is None:
        return
    project, business_ids = await project_scope(session, tenant_id, project_id)
    if project.status != "active" or (plan_for(project).get("revision") and plan_for(project).get("status") != "active"):
        raise HTTPException(409, "项目或服务计划已暂停")
    if (business_id is not None and business_id not in business_ids) or prompt_id not in await prompt_ids_for_businesses(session, tenant_id, business_ids):
        raise HTTPException(404, "目标问题不属于当前项目")


async def save_plan(session, tenant_id, project_id, values, expected_revision, actor_id):
    await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    project = await session.get(GeoProject, project_id, with_for_update=True, populate_existing=True)
    if project is None or project.tenant_id != tenant_id:
        raise HTTPException(404, "GEO 项目不存在")
    current = plan_for(project)
    if current["revision"] != expected_revision:
        raise HTTPException(409, "服务计划已更新，请重新读取")
    _, business_ids = await project_scope(session, tenant_id, project_id)
    ids = set(await prompt_ids_for_businesses(session, tenant_id, business_ids))
    selected = sorted(set(values["prompt_ids"]))
    if not set(selected) <= ids:
        raise HTTPException(404, "计划问题不属于当前项目")
    if values["enabled"] and (not selected or not await advisor_available(session, tenant_id, values["advisor_user_id"])):
        raise HTTPException(409, "开启周期任务需要项目问题和有效顾问分配")
    result = {**values, "prompt_ids": selected, "revision": current["revision"] + 1,
        "updated_by": actor_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    project.project_settings = {**(project.project_settings or {}), PLAN_KEY: result}
    await session.flush()
    return result


def phase_state(ticket, plan, now):
    phase = plan["next_step"]
    old = (ticket.progress or {}).get("project_workflow") or {}
    if old.get("phase") != phase:
        sequence = int(old.get("sequence") or 0) + 1
        history = [*(old.get("history") or []), {"phase": phase, "at": now.isoformat()}][-50:]
        state = {**old, "phase": phase, "sequence": sequence, "phase_since": now.isoformat(), "history": history,
                 "notice_id": hashlib.sha256(f"{ticket.id}:{sequence}:{phase}".encode()).hexdigest(), "seen_by": {}}
    else:
        state = dict(old)
    due = datetime.fromisoformat(state["phase_since"]) + timedelta(days=2)
    state.update(waiting_for="advisor", due_at=due.isoformat(), overdue=now >= due,
                 delivery_channel="in_app", external_notification_sent=False)
    return state


async def refresh_project(project_id, *, session_factory=None, now=None):
    from app.geo.routes import build_ticket_execution_plan
    from app.geo.execution_plan import ticket_prompt_id
    factory = session_factory or async_session_factory
    now = now or datetime.now(timezone.utc)
    async with factory() as session:
        seed = await session.get(GeoProject, project_id)
        if seed is None:
            return
        tenant_id = seed.tenant_id
        ensure_geo_background_execution_allowed(tenant_id)
        await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
        project = await session.get(GeoProject, project_id, with_for_update=True, populate_existing=True)
        if project is None:
            return
        settings = dict(project.project_settings or {})
        plan = plan_for(project)
        if project.status != "active" or not plan.get("enabled") or plan.get("status") != "active":
            return
        await ensure_geo_entitlement(session, tenant_id)
        if not await advisor_available(session, tenant_id, plan.get("advisor_user_id")):
            settings["geo_workflow_blocker"] = "advisor_assignment_unavailable"
            project.project_settings = settings
            await session.commit()
            return
        _, business_ids = await project_scope(session, tenant_id, project_id)
        ids = set(await prompt_ids_for_businesses(session, tenant_id, business_ids))
        if not set(plan["prompt_ids"]) <= ids:
            settings["geo_workflow_blocker"] = "project_scope_changed"
            project.project_settings = settings
            await session.commit()
            return
        cursors = dict(settings.get("geo_workflow_cursors") or {})
        for prompt_id in plan["prompt_ids"]:
            prompt = await session.get(GeoPrompt, prompt_id)
            if prompt is None or prompt.status != "active" or prompt.is_brand_probe:
                continue
            code = f"workqueue:v1:prompt-{prompt_id}"
            tickets = list(await session.scalars(select(GeoActionTicket).where(
                GeoActionTicket.tenant_id == tenant_id, GeoActionTicket.advice_code == code,
                GeoActionTicket.status.in_(("todo", "doing", "reopened"))).order_by(GeoActionTicket.id).with_for_update()))
            cursor = cursors.get(str(prompt_id)) or {}
            if not tickets and (not cursor.get("next_due_at") or datetime.fromisoformat(cursor["next_due_at"]) <= now):
                ticket = GeoActionTicket(tenant_id=tenant_id, advice_code=code,
                    title=("项目周期优化 · " + prompt.question)[:300], action="保留修改前证据，按事实制作内容，审核发布后同题复测。",
                    status="todo", priority="medium", acceptance_type="manual", created_by=None,
                    progress={"project_workflow": {"project_id": project.id, "scope_revision": binding(project)["revision"],
                        "plan_revision": plan["revision"], "advisor_user_id": plan["advisor_user_id"]}})
                session.add(ticket)
                await session.flush()
                tickets = [ticket]
                cursors[str(prompt_id)] = {"ticket_id": ticket.id, "next_due_at": (now + timedelta(days=plan["interval_days"])).isoformat()}
            for ticket in tickets:
                previous = (ticket.progress or {}).get("project_workflow") or {}
                if previous.get("project_id") not in {None, project.id}:
                    settings["geo_workflow_blocker"] = "existing_ticket_project_conflict"
                    continue
                execution = await build_ticket_execution_plan(session, ticket, tenant_id, project_id=project.id)
                state = phase_state(ticket, execution, now)
                state.update(project_id=project.id, scope_revision=binding(project)["revision"], plan_revision=plan["revision"],
                             advisor_user_id=plan["advisor_user_id"])
                ticket.progress = {**(ticket.progress or {}), "project_workflow": state}
                ticket.due_date = datetime.fromisoformat(state["due_at"]).date()
        settings["geo_workflow_cursors"] = cursors
        # Clear only a previous configuration blocker after validating this tick.
        if settings.get("geo_workflow_blocker") in {"advisor_assignment_unavailable", "project_scope_changed"}:
            settings.pop("geo_workflow_blocker", None)
        project.project_settings = settings
        await session.commit()


async def run_project_workflows():
    cursor = 0
    while True:
        async with async_session_factory() as session:
            ids = list(await session.scalars(select(GeoProject.id).where(GeoProject.id > cursor,
                GeoProject.status == "active", GeoProject.project_settings[PLAN_KEY]["enabled"].as_boolean().is_(True))
                .order_by(GeoProject.id).limit(100)))
        if not ids:
            return
        for project_id in ids:
            try:
                await refresh_project(project_id)
            except Exception:
                logger.exception("GEO project workflow failed project_id=%s", project_id)
        cursor = ids[-1]
