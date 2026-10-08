"""One opt-in draft attempt per content workflow, using the existing assist API.

Task claims commit before provider work. Recovery only reads the corresponding
durable AI operation; it never starts a second supplier request for a claim.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging

from fastapi import HTTPException
from sqlalchemy import select

from app.database import async_session_factory
from app.models.module_workspace import SeoSite
from app.models.role import Role
from app.models.user import User
from app.models.seo import SeoAiOperation, SeoContentAsset, SeoKeywordAsset, SeoSiteAdvisorAssignment
from app.models.seo_cockpit import SeoTask
from app.models.seo_qa import SeoQaFact
from app.module_scope import seo_site_is_operational
from app.security.auth import AuthContext
from app.seo_ai_operations import LEASE, request_fingerprint, retained_result
from app.seo_content_workflow import ACTION, plan_for, schema_ready, transition, utc
from app.seo_qa import answer_checks, fact_is_current
from app.seo_service_plan import service_plan_is_paused

logger = logging.getLogger(__name__)


def blocked(code):
    return HTTPException(409, {"code": code})


async def selected_material(session, site, plan):
    fact_ids = sorted(set(plan.get("content_ai_fact_ids") or []))
    keyword_ids = sorted(set(plan.get("content_ai_keyword_ids") or []))
    if not 1 <= len(fact_ids) <= 20 or not 1 <= len(keyword_ids) <= 5:
        raise blocked("ai_draft_material_and_keywords_required")
    facts = list(await session.scalars(select(SeoQaFact).where(
        SeoQaFact.tenant_id == site.tenant_id, SeoQaFact.site_id == site.id,
        SeoQaFact.id.in_(fact_ids),
    ).order_by(SeoQaFact.id)))
    if len(facts) != len(fact_ids) or any(not fact_is_current(fact) for fact in facts):
        raise blocked("ai_draft_material_missing_or_expired")
    if any(not (fact.statement or "").strip() or not (fact.source_name or "").strip() for fact in facts):
        raise blocked("ai_draft_material_provenance_required")
    snapshots = [{"id": f.id, "version": f.version, "title": f.title, "statement": f.statement,
                  "source_name": f.source_name, "source_url": f.source_url} for f in facts]
    if len(json.dumps(snapshots, ensure_ascii=False)) > 50000:
        raise blocked("ai_draft_material_limit_50000")
    keywords = list(await session.scalars(select(SeoKeywordAsset).where(
        SeoKeywordAsset.tenant_id == site.tenant_id, SeoKeywordAsset.site_id == site.id,
        SeoKeywordAsset.id.in_(keyword_ids), SeoKeywordAsset.status == "active",
    ).order_by(SeoKeywordAsset.id)))
    if len(keywords) != len(keyword_ids) or any(not k.keyword.strip() for k in keywords):
        raise blocked("ai_draft_keywords_missing_or_inactive")
    return {"facts": snapshots, "keywords": [{"id": k.id, "keyword": k.keyword} for k in keywords]}


def source_fingerprint(content):
    return request_fingerprint({key: getattr(content, key) for key in (
        "title", "outline", "draft", "humanized_content", "source_text", "version_count",
        "status", "keyword_id", "keyword_ids", "source_page_id", "content_type")})


def state_for(task):
    return dict((task.params or {}).get("ai_draft") or {})


def save_state(task, state):
    task.params = {**task.params, "ai_draft": state}


def attention(task, reason, *, checks=None):
    now = datetime.now(timezone.utc)
    save_state(task, {**state_for(task), "status": "needs_attention", "reason": reason,
                     "finished_at": now.isoformat(), "quality_checks": checks or []})
    transition(task, "ai_draft_needs_attention", now, blocker=reason)


async def locked_context(session, task_id):
    """Assignment -> site -> task -> content, consistently with the write API."""
    if not await schema_ready(session):
        return None
    hint = await session.get(SeoTask, task_id)
    if not hint or hint.action_type != ACTION:
        return None
    tenant_id, site_id = hint.tenant_id, hint.site_id
    site = await session.get(SeoSite, site_id)
    if not site or site.tenant_id != tenant_id:
        return None
    authorizer = plan_for(site).get("content_ai_authorized_by")
    assignment = await session.scalar(select(SeoSiteAdvisorAssignment).where(
        SeoSiteAdvisorAssignment.tenant_id == tenant_id, SeoSiteAdvisorAssignment.site_id == site_id,
        SeoSiteAdvisorAssignment.advisor_user_id == authorizer, SeoSiteAdvisorAssignment.active.is_(True),
    ).with_for_update().execution_options(populate_existing=True)) if authorizer else None
    site = await session.get(SeoSite, site_id, with_for_update=True, populate_existing=True)
    task = await session.get(SeoTask, task_id, with_for_update=True, populate_existing=True)
    if not site or not task or (task.tenant_id, task.site_id, task.action_type) != (tenant_id, site_id, ACTION):
        return None
    if task.status not in {"open", "in_progress"}:
        return None
    plan = plan_for(site)
    reason = None
    if plan.get("content_ai_enabled") is not True:
        reason = "ai_draft_disabled"
    elif service_plan_is_paused(site):
        reason = "service_plan_paused"
    elif not await seo_site_is_operational(session, tenant_id, site_id):
        reason = "site_or_module_not_operational"
    elif not assignment or plan.get("content_ai_authorized_by") != authorizer:
        reason = "ai_draft_authorization_revoked"
    ctx = None
    if reason is None:
        user = await session.get(User, authorizer, populate_existing=True)
        role = await session.get(Role, user.role_id, populate_existing=True) if user else None
        if not user or not user.is_active or user.tenant_id not in {None, tenant_id} or not role:
            reason = "ai_draft_authorization_revoked"
        else:
            ctx = AuthContext(user.id, user.username, role.name, user.tenant_id, dict(role.permissions or {}))
            if not (ctx.can_edit("seo.content") and ctx.can_edit("seo.site") and ctx.can_view("seo.keywords")):
                reason = "ai_draft_authorization_revoked"
    content = await session.get(SeoContentAsset, task.params.get("content_id"), with_for_update=True, populate_existing=True)
    if not content or (content.tenant_id, content.site_id) != (tenant_id, site_id):
        reason = "content_missing_or_out_of_scope"
    return site, task, content, ctx, reason


async def validate_claim(session, site, content, claim):
    plan = plan_for(site)
    if (plan.get("revision"), plan.get("content_ai_authorized_by")) != (claim["plan_revision"], claim["authorized_by"]):
        raise blocked("ai_draft_plan_changed")
    if source_fingerprint(content) != claim["source_hash"]:
        raise blocked("ai_draft_content_changed")
    material = await selected_material(session, site, plan)
    if request_fingerprint(material) != claim["material_hash"]:
        raise blocked("ai_draft_material_changed")
    return material


async def persist_result(task_id, result=None, error=None):
    """Also used after restart; never invokes assist or refunds successful work."""
    from app.api.seo import _sanitize_content_html
    async with async_session_factory() as session:
        scope = await locked_context(session, task_id)
        if scope is None:
            return
        site, task, content, ctx, reason = scope
        claim = state_for(task)
        if claim.get("status") != "claimed":
            return
        try:
            if reason:
                raise blocked(reason)
            material = await validate_claim(session, site, content, claim)
            operation = await session.scalar(select(SeoAiOperation).where(
                SeoAiOperation.tenant_id == site.tenant_id,
                SeoAiOperation.request_key == claim["request_id"],
            ))
            if operation and (operation.request_hash, operation.actor, operation.kind, operation.site_id) != (
                claim["request_hash"], str(claim["authorized_by"]), "content_assist", site.id,
            ):
                raise blocked("ai_draft_operation_mismatch")
            # A committed result wins over a lost HTTP/worker response.
            if operation and operation.status == "succeeded":
                result = retained_result(operation)
            elif error:
                raise blocked(error)
            elif operation and operation.status == "refunded":
                raise blocked("ai_draft_operation_refunded")
            else:
                if datetime.now(timezone.utc) > utc(datetime.fromisoformat(claim["claimed_at"])) + LEASE + timedelta(minutes=1):
                    raise blocked("ai_draft_outcome_unknown")
                return
            if not isinstance(result, dict) or not operation or operation.status != "succeeded":
                raise blocked("ai_draft_result_unavailable")
            if (claim.get("generation_route") is None or result.get("generation_route") != claim["generation_route"]
                    or result.get("provider") != "deepseek" or result.get("model") != claim["generation_route"]["model"]):
                raise blocked("ai_draft_provider_evidence_missing")
            if result.get("response_model") and not result["response_model"].lower().startswith("deepseek"):
                raise blocked("ai_draft_provider_model_mismatch")
            body = _sanitize_content_html(str(result.get("content") or ""))
            title, outline = str(result.get("title") or "").strip(), str(result.get("outline") or "").strip()
            checks = answer_checks(body, material["facts"])
            if not title or len(title) > 300 or not outline or len(outline) > 20000 or len(body) > 80000:
                checks.append("生成内容为空或超过稿件字段限制")
            if checks:
                attention(task, "ai_draft_quality_review_required", checks=checks)
            else:
                content.title, content.outline, content.draft = title, outline, body
                content.source_text = json.dumps(material["facts"], ensure_ascii=False)
                content.keyword_ids = [k["id"] for k in material["keywords"]]
                content.keyword_id = content.keyword_ids[0]
                content.status = "drafting"
                content.version_count = (content.version_count or 1) + 1
                content.review_submitted_by = content.review_submitted_at = None
                content.reviewed_by = content.reviewed_at = content.review_note = None
                save_state(task, {**claim, "status": "succeeded", "reason": None,
                    "provider": result["provider"], "model": result["model"], "response_model": result.get("response_model"),
                    "operation_id": operation.id, "generated_by": "system", "saved_version": content.version_count,
                    "finished_at": datetime.now(timezone.utc).isoformat(), "fact_snapshots": material["facts"],
                    "quality_checks": [], "meaning": "draft_only_not_reviewed_or_confirmed"})
                transition(task, "awaiting_internal_review", datetime.now(timezone.utc))
        except HTTPException as exc:
            attention(task, exc.detail.get("code", "ai_draft_needs_attention") if isinstance(exc.detail, dict) else "ai_draft_needs_attention")
        await session.commit()


async def execute_content_draft(task_id):
    from app.api.seo import SeoContentAssistRequest, _assist_seo_content, _seo_draft_route, _seo_assist_request_payload
    request = ctx = None
    async with async_session_factory() as session:
        scope = await locked_context(session, task_id)
        if scope is None:
            return
        site, task, content, ctx, reason = scope
        claim = state_for(task)
        if claim.get("status") in {"succeeded", "needs_attention"}:
            return
        if not claim:
            if reason == "ai_draft_disabled":
                return
            try:
                if reason:
                    raise blocked(reason)
                if content.status not in {"planned", "drafting"} or (content.draft or "").strip() or (content.humanized_content or "").strip() or content.source_page_id:
                    return
                material = await selected_material(session, site, plan_for(site))
                generation_route = _seo_draft_route(plan_for(site))
                request = SeoContentAssistRequest(
                    tenant_id=site.tenant_id, site_id=site.id, action="generate", mode="original",
                    request_id=f"workflow_{task.id}_draft_v1", title=content.title,
                    keyword_ids=[k["id"] for k in material["keywords"]],
                    source_text=json.dumps(material["facts"], ensure_ascii=False),
                    instruction="仅依据所选事实资料撰写本选题。每项事实用 [F编号] 标明出处；不能从关键词、标题或客户简介推断产品参数、案例或效果。资料不足时明确写待补充，交顾问处理。输出是待人工审核的草稿。",
                )
                claim = {"status": "claimed", "request_id": request.request_id,
                    "request_hash": request_fingerprint(_seo_assist_request_payload(request, generation_route)),
                    "generation_route": generation_route,
                    "source_hash": source_fingerprint(content), "material_hash": request_fingerprint(material),
                    "plan_revision": plan_for(site)["revision"], "authorized_by": ctx.user_id,
                    "claimed_at": datetime.now(timezone.utc).isoformat(), "trigger": "system",
                    "source_version": content.version_count or 1}
                save_state(task, claim)
                transition(task, "ai_draft_in_progress", datetime.now(timezone.utc), waiting_for="system")
            except HTTPException as exc:
                attention(task, exc.detail["code"])
            await session.commit()
    if request is None:
        await persist_result(task_id)
        return
    # Recheck after the committed claim, immediately before any quota/provider work.
    async with async_session_factory() as session:
        scope = await locked_context(session, task_id)
        if scope is None:
            return
        site, task, content, ctx, reason = scope
        try:
            if reason:
                raise blocked(reason)
            await validate_claim(session, site, content, claim)
        except HTTPException as exc:
            attention(task, exc.detail["code"])
            await session.commit()
            return
        await session.commit()
    error = None
    try:
        async with async_session_factory() as session:
            await _assist_seo_content(request, session, ctx, generation_route=claim["generation_route"])
    except HTTPException as exc:
        error = (exc.detail.get("code") if isinstance(exc.detail, dict) else None) or {429: "ai_draft_quota_exceeded", 503: "ai_draft_provider_unavailable"}.get(exc.status_code, "ai_draft_generation_failed")
    except asyncio.CancelledError:
        # The durable claim/operation is reconciled on the next run.
        raise
    except Exception:
        # Provider errors may include submitted material; persist only a stable code.
        error = "ai_draft_generation_failed"
        logger.warning("SEO automatic draft needs attention: task_id=%s", task_id)
    await persist_result(task_id, error=error)
