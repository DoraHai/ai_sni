"""Durable, assisted content delivery. No AI or publication supplier is called here.

Reservations serialize on the existing site row; transitions serialize on the
task row. All new objects and the cycle cursor commit in the same transaction.
The worker replays facts, never replays a publication operation.
"""
from datetime import datetime, timedelta, timezone
import logging

from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.database import async_session_factory
from app.models.module_workspace import SeoSite
from app.models.seo import SeoContentAsset, SeoContentPublication, SeoSiteAdvisorAssignment
from app.models.seo_cockpit import SeoTask
from app.models.seo_page_capture import SeoPageCapture
from app.module_scope import seo_site_is_operational
from app.seo_service_plan import service_plan_is_paused

ACTION = "content_delivery"
METRIC = "seo.content.published_7d_count"
SCHEMA = "0105_seo_content_confirmations"
logger = logging.getLogger(__name__)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def plan_for(site):
    settings = site.site_settings if isinstance(site.site_settings, dict) else {}
    plan = settings.get("seo_service_plan")
    return plan if isinstance(plan, dict) else {}


async def schema_ready(session):
    return list((await session.execute(text("SELECT version_num FROM alembic_version"))).scalars()) == [SCHEMA]


async def published_count(session, site, now):
    return int(await session.scalar(select(func.count()).select_from(SeoContentAsset).where(
        SeoContentAsset.tenant_id == site.tenant_id, SeoContentAsset.site_id == site.id,
        SeoContentAsset.status == "published",
        SeoContentAsset.published_at > (now - timedelta(days=7)).replace(tzinfo=None),
        SeoContentAsset.published_at <= now.replace(tzinfo=None),
    )) or 0)


def transition(task, phase, now, *, waiting_for="advisor", blocker=None):
    params = dict(task.params or {})
    old = (params.get("phase"), params.get("blocker"))
    params.update(phase=phase, waiting_for=waiting_for, blocker=blocker)
    if old != (phase, blocker):
        history = list(params.get("history") or [])
        history.append({"phase": phase, "blocker": blocker, "at": now.isoformat(), "actor": "system"})
        params["history"] = history[-100:]
        params["history_truncated"] = bool(params.get("history_truncated") or len(history) > 100)
        params["phase_since"] = now.isoformat()
    # Internal reminder only; no message was sent to a customer or advisor.
    since = datetime.fromisoformat(params.get("phase_since") or now.isoformat())
    params["attention_due_at"] = (since + timedelta(days=2)).isoformat() if waiting_for else None
    params["attention_overdue"] = bool(waiting_for and now >= since + timedelta(days=2))
    params["notification_sent"] = False
    task.params = params
    task.updated_at = now


async def reserve_content_workflow(session, site, *, request_key, actor_id, now=None, scheduled=False):
    """Caller must hold site FOR UPDATE. Idempotency survives terminal tasks."""
    now = now or datetime.now(timezone.utc)
    scope = (SeoTask.tenant_id == site.tenant_id, SeoTask.site_id == site.id, SeoTask.action_type == ACTION)
    existing = await session.scalar(select(SeoTask).where(
        *scope, SeoTask.params["request_key"].as_string() == request_key,
    ).limit(1))
    if existing is not None:
        return existing, False
    plan = plan_for(site)
    if service_plan_is_paused(site):
        raise HTTPException(409, {"code": "service_plan_paused"})
    topics = plan.get("content_topics") or []
    if not topics or not plan.get("optimization_directions"):
        raise HTTPException(409, {"code": "service_plan_content_topics_required"})
    active = await session.scalar(select(SeoTask.id).where(*scope, SeoTask.status.in_(("open", "in_progress"))).limit(1))
    if active is not None:
        raise HTTPException(409, {"code": "content_workflow_already_active", "task_id": active})
    settings = dict(site.site_settings or {})
    cursor = dict(settings.get("seo_content_workflow_cursor") or {})
    sequence = int(cursor.get("sequence") or 0)
    topic = topics[sequence % len(topics)]
    content = SeoContentAsset(
        tenant_id=site.tenant_id, site_id=site.id, content_type="article", title=topic,
        outline="服务计划选题，待顾问补充资料并制作稿件。\n优化方向：" + "；".join(plan["optimization_directions"]),
        status="planned", version_count=1, created_by=None if scheduled else actor_id,
    )
    session.add(content)
    await session.flush()
    task = SeoTask(
        tenant_id=site.tenant_id, site_id=site.id, module="seo", action_type=ACTION,
        title=("内容交付 · " + topic)[:240], status="in_progress",
        created_by="cockpit" if scheduled else str(actor_id), assignee_role="seo_advisor",
        baseline={"metric_key": METRIC, "value": await published_count(session, site, now), "as_of": now.isoformat()},
        params={"request_key": request_key, "trigger": "scheduled" if scheduled else "advisor",
                "plan_revision": plan["revision"], "content_id": content.id,
                "assignment_advisor_id": actor_id, "triggered_by_user_id": None if scheduled else actor_id,
                "plan_topic": topic,
                "publication_policy": "advisor_uses_existing_distribution", "history": []},
        created_at=now, updated_at=now,
    )
    transition(task, "awaiting_draft", now)
    session.add(task)
    cursor.update(sequence=sequence + 1, last_reserved_at=now.isoformat(),
                  next_due_at=(now + timedelta(days=int(plan.get("content_interval_days") or 7))).isoformat())
    settings["seo_content_workflow_cursor"] = cursor
    site.site_settings = settings
    await session.flush()
    return task, True


async def advance_content_workflow(session, site, task, *, now=None, publication_id=None):
    """Caller holds site and task locks; returns a durable capture ID to dispatch."""
    from app.api.seo import _content_confirmation_status, _latest_content_confirmation
    from app.api.seo_page_captures import _deadline, _publication_url, reserve_publication_page_capture

    now = now or datetime.now(timezone.utc)
    if task.status in {"done", "cancelled"}:
        return None
    if service_plan_is_paused(site):
        transition(task, "paused", now, waiting_for=None, blocker="service_plan_paused")
        return None
    content = await session.get(SeoContentAsset, task.params["content_id"], with_for_update=True)
    if not content or content.tenant_id != site.tenant_id or content.site_id != site.id:
        transition(task, "needs_attention", now, blocker="content_missing_or_out_of_scope")
        return None
    if not (content.humanized_content or content.draft or "").strip():
        transition(task, "awaiting_draft", now)
        return None
    if content.status not in {"ready", "published"}:
        transition(task, "awaiting_internal_review", now)
        return None
    confirmation = await _latest_content_confirmation(session, content)
    confirmation_state = _content_confirmation_status(content, confirmation)
    if confirmation_state != "approved":
        transition(task, "awaiting_confirmation", now, waiting_for="customer_or_advisor",
                   blocker="confirmation_" + confirmation_state)
        return None
    publications = list(await session.scalars(select(SeoContentPublication).where(
        SeoContentPublication.tenant_id == site.tenant_id,
        SeoContentPublication.content_asset_id == content.id,
        SeoContentPublication.source_version == (content.version_count or 1),
    ).order_by(SeoContentPublication.id)))
    selected_id = publication_id or task.params.get("publication_id")
    selected = next((p for p in publications if p.id == selected_id), None) if selected_id else None
    if publication_id and selected is None:
        raise HTTPException(409, {"code": "publication_scope_or_version_mismatch"})
    if selected is None:
        if not publications:
            transition(task, "awaiting_publication", now, blocker="advisor_channel_selection_required")
            return None
        if len(publications) != 1:
            transition(task, "awaiting_publication_selection", now, blocker="multiple_publications")
            return None
        selected = publications[0]
    task.params = {**task.params, "publication_id": selected.id, "source_version": selected.source_version,
                   "confirmation_id": confirmation.id}
    if selected.status != "published":
        phase = "awaiting_manual_publication" if selected.status in {"manual_required", "draft_created", "preparing"} else "publication_needs_check"
        transition(task, phase, now, blocker=selected.status)
        return None
    if not selected.page_url or not selected.published_at:
        transition(task, "publication_needs_check", now, blocker="publication_evidence_missing")
        return None
    capture = await session.scalar(select(SeoPageCapture).where(
        SeoPageCapture.tenant_id == site.tenant_id, SeoPageCapture.site_id == site.id,
        SeoPageCapture.relation_type == "publication", SeoPageCapture.relation_id == selected.id,
        SeoPageCapture.source_url == selected.page_url,
        SeoPageCapture.captured_at >= utc(selected.published_at),
    ).order_by(SeoPageCapture.id.desc()).limit(1))
    if capture is None:
        capture, reason = await reserve_publication_page_capture(
            session, tenant_id=site.tenant_id, site_id=site.id,
            publication_id=selected.id, page_url=selected.page_url,
        )
        if capture is None:
            transition(task, "page_evidence_needs_attention", now, blocker=reason)
            return None
    task.params = {**task.params, "capture_id": capture.id}
    if (_publication_url(capture.source_url) != _publication_url(selected.page_url)
            or utc(capture.captured_at) < utc(selected.published_at)):
        transition(task, "page_evidence_needs_attention", now, blocker="capture_predates_publication")
        return None
    # A pending row is safe to dispatch after restart; a stale running row
    # may already have contacted a supplier and needs explicit retry instead.
    if capture.status == "running" and utc(capture.captured_at) < _deadline():
        capture.status, capture.error_code = "failed", "timeout"
    if capture.status in {"pending", "running"}:
        transition(task, "awaiting_page_evidence", now, waiting_for="system")
        return capture.id if capture.status == "pending" else None
    if capture.status != "succeeded" or capture.source != "auto" or not capture.sha256 or not capture.storage_key or not capture.http_status or not 200 <= capture.http_status < 300:
        transition(task, "page_evidence_needs_attention", now, blocker=capture.error_code or "automatic_page_evidence_required")
        return None
    before, after = task.baseline["value"], await published_count(session, site, now)
    if (content.status != "published" or not content.published_at
            or utc(content.published_at) < utc(task.created_at)
            or not now - timedelta(days=7) < utc(content.published_at) <= now
            or utc(selected.published_at) < utc(task.created_at) or after <= before):
        transition(task, "page_evidence_ready", now, blocker="published_metric_growth_not_verified")
        return None
    task.completion_evidence = {
        "metric_key": METRIC, "before": before, "after": after, "change_abs": after - before,
        "as_of": now.isoformat(), "source": {"content_id": content.id, "publication_id": selected.id,
        "source_version": selected.source_version, "confirmation_id": confirmation.id,
        "page_url": selected.page_url, "published_at": selected.published_at.isoformat(),
        "capture_id": capture.id, "captured_at": capture.captured_at.isoformat(), "sha256": capture.sha256},
        "meaning": "publication_and_page_evidence_only", "seo_effect": "not_evaluated",
        "snapshot_url": f"/api/v1/seo/metrics/snapshot?tenant_id={site.tenant_id}&site_id={site.id}",
    }
    task.status = "done"
    transition(task, "completed_with_page_evidence", now, waiting_for=None)
    return None


async def process_site(site_id):
    """Fresh transaction per site, no provider calls while DB locks are held."""
    capture_ids = []
    async with async_session_factory() as session:
        if not await schema_ready(session):
            return
        # Same lock order as service-plan writes: assignment, then site.
        advisor = await session.scalar(select(SeoSiteAdvisorAssignment).where(
            SeoSiteAdvisorAssignment.site_id == site_id, SeoSiteAdvisorAssignment.active.is_(True),
        ).order_by(SeoSiteAdvisorAssignment.id).limit(1).with_for_update())
        site = await session.get(SeoSite, site_id, with_for_update=True)
        if not site or not advisor or advisor.tenant_id != site.tenant_id:
            return
        if not await seo_site_is_operational(session, site.tenant_id, site.id):
            return
        now = datetime.now(timezone.utc)
        active = list(await session.scalars(select(SeoTask).where(
            SeoTask.tenant_id == site.tenant_id, SeoTask.site_id == site.id,
            SeoTask.action_type == ACTION, SeoTask.status.in_(("open", "in_progress")),
        ).order_by(SeoTask.id).with_for_update()))
        for task in active:
            capture_id = await advance_content_workflow(session, site, task, now=now)
            if capture_id:
                capture_ids.append(capture_id)
        plan = plan_for(site)
        if not active and not service_plan_is_paused(site) and plan.get("content_cycle_enabled") is True:
            cursor = (site.site_settings or {}).get("seo_content_workflow_cursor") or {}
            due = datetime.fromisoformat(cursor["next_due_at"]) if cursor.get("next_due_at") else now
            if now >= utc(due) and plan.get("content_topics") and plan.get("optimization_directions"):
                await reserve_content_workflow(session, site,
                    request_key=f"cycle:{int(cursor.get('sequence') or 0) + 1}",
                    actor_id=advisor.advisor_user_id, now=now, scheduled=True)
        await session.commit()
    from app.api.seo_page_captures import execute_page_capture
    for capture_id in capture_ids:
        await execute_page_capture(capture_id)


async def run_content_workflows():
    """Keyset pages prevent low-ID waiting tasks starving later sites."""
    cursor = 0
    while True:
        async with async_session_factory() as session:
            if not await schema_ready(session):
                return
            site_ids = list(await session.scalars(select(SeoSite.id).where(
                SeoSite.id > cursor, SeoSite.status == "active",
            ).order_by(SeoSite.id).limit(100)))
        if not site_ids:
            return
        for site_id in site_ids:
            try:
                await process_site(site_id)
            except Exception:
                # A broken rollback/connection is isolated by the session context.
                logger.exception("SEO content workflow failed: site_id=%s", site_id)
        cursor = site_ids[-1]
