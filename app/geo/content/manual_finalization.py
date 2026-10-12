"""Explicit advisor finalization of stored channel drafts, never publication."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select

from app.geo.content.export_view import export_revision
from app.geo.content.review import apply_submit, invalidate_review, is_tenant_customer_reviewer
from app.models import GeoChannelVariant, GeoContentTask

KEY = "manual_finalization"
CHANNELS = {"wechat"}


def problem(code, message, status=409):
    return HTTPException(status, {"code": code, "message": message})


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str).encode()).hexdigest()


def master_digest(article):
    return digest([article.id, article.version_no, article.title, article.body_markdown,
        article.outline, article.author_name])


def content_digest(variant):
    return digest([variant.channel, variant.title, variant.body_markdown])


def asset_digest(assets):
    return digest([{"order": row.sort_order, "type": row.media_type,
        "sha256": hashlib.sha256(bytes(row.content_bytes or b"")).hexdigest()}
        for row in assets])


def current_variants(variants):
    latest = {}
    for row in variants:
        stamp = row.updated_at.replace(tzinfo=timezone.utc).timestamp() if row.updated_at else 0
        prior = latest.get(row.channel)
        if prior is None or (stamp, row.id) > prior[0]:
            latest[row.channel] = ((stamp, row.id), row)
    return [value[1] for value in latest.values()]


def record_valid(task, article, variant, *, allow_pending=False, scope_id=None):
    meta = variant.adapt_meta if isinstance(variant.adapt_meta, dict) else {}
    rec = meta.get(KEY)
    if rec is None:
        return meta.get("engine") != "manual_channel_finalization_v1"
    if not isinstance(rec, dict) or article is None:
        return False
    if (rec.get("version") != 1 or rec.get("source") != "manual"
            or type(rec.get("finalized_by")) is not int or rec["finalized_by"] <= 0
            or rec.get("tenant_id") != task.tenant_id
            or (scope_id is not None and rec.get("scope_id") != scope_id)
            or rec.get("master_digest") != master_digest(article)
            or variant.channel not in CHANNELS
            or rec.get("content_digest") != content_digest(variant)
            or rec.get("rendered_digest") != digest(meta.get("body_html"))):
        return False
    if rec.get("state") == "awaiting-review":
        return allow_pending and task.review_status in {"none", "pending"}
    binding = rec.get("customer_review")
    return (rec.get("state") == "approved" and task.review_status == "approved"
        and isinstance(binding, dict) and binding.get("reviewed_by") == task.reviewed_by
        and task.reviewed_at is not None and binding.get("reviewed_at") == task.reviewed_at.isoformat())


def assert_record_current(task, article, variant, facts, assets, scope_id):
    meta = variant.adapt_meta if isinstance(variant.adapt_meta, dict) else {}
    if KEY not in meta and meta.get("engine") != "manual_channel_finalization_v1":
        return
    rec = meta.get(KEY) or {}
    if (not record_valid(task, article, variant, scope_id=scope_id)
            or rec.get("facts_digest") != digest(facts)
            or rec.get("assets_digest") != asset_digest(assets)):
        raise problem("geo_distribution_manual_finalization_invalid", "人工定版已失效，请顾问重新核对定版并提交客户审核")


async def _context(session, actor, tenant_id, scope_id, task_id, channel):
    from app.geo.distribution_sources import authorize_scope
    from app.geo.project_scope import project_scope, prompt_ids_for_businesses
    from app.geo.content.routes import _latest_article, _task_facts, _fact_dicts
    if channel not in CHANNELS:
        raise problem("geo_manual_channel_unsupported", "此渠道尚未提供人工定版", 422)
    if type(actor) is not int or actor <= 0:
        raise problem("geo_manual_actor_required", "人工定版需要当前实名顾问", 403)
    await authorize_scope(session, actor, tenant_id, scope_id)
    _, business_ids = await project_scope(session, tenant_id, scope_id)
    prompts = await prompt_ids_for_businesses(session, tenant_id, business_ids)
    task = await session.get(GeoContentTask, task_id, populate_existing=True, with_for_update=True)
    if (task is None or task.tenant_id != tenant_id or task.business_id not in business_ids
            or task.prompt_id not in prompts):
        raise problem("geo_manual_scope_forbidden", "稿件不属于当前顾问项目", 403)
    if task.status in {"generating", "adapting", "archived", "cancelled"}:
        raise problem("geo_manual_task_unavailable", "当前任务不能定版")
    variant = await session.scalar(select(GeoChannelVariant).where(
        GeoChannelVariant.task_id == task_id, GeoChannelVariant.channel == channel).order_by(
            GeoChannelVariant.updated_at.desc().nullslast(), GeoChannelVariant.id.desc()).limit(1)
        .with_for_update().execution_options(populate_existing=True))
    article = await _latest_article(session, task_id, fresh=True)
    if variant is None or article is None:
        raise problem("geo_manual_version_stale", "缺少当前母稿或渠道稿，请刷新")
    if variant.status not in {"draft", "exported"}:
        raise problem("geo_manual_variant_unavailable", "仅未发布的完成渠道稿可以定版")
    facts = _fact_dicts(await _task_facts(session, task_id, fresh=True))
    assets = []
    revision = digest([export_revision(variant, article.id), master_digest(article), digest(facts), asset_digest(assets)])
    return task, article, variant, facts, assets, revision


async def quality_issues(session, task, article, variant, facts, assets):
    from app.geo.content.routes import _build_rule_input, _brand_context_for_task, _ensure_tenant_exists
    from app.geo.content.channel_polish import assess_article_quality
    from app.geo.content.channel_polish_defaults import default_min_body_chars
    from app.geo.content.channel_profiles import get_profile
    from app.geo.content.brand_geo import markdown_brand_validation
    from app.geo.content.draft_lint import lint_draft, lint_summary
    from app.geo.content.gate import assert_can_publish, PublishGateError
    tenant = await _ensure_tenant_exists(session, task.tenant_id, fresh=True)
    brand, _ = await _brand_context_for_task(session, task, tenant, fresh=True)
    ri = await _build_rule_input(session, task, article, fresh=True, refresh_citations=False)
    issues = []
    profile = get_profile(variant.channel)
    if not profile or not variant.title.strip() or len(variant.title) > profile.title_max:
        issues.append("标题为空或超过当前平台标题上限")
    for title, body, data in ((article.title, article.body_markdown, ri),
            (variant.title, variant.body_markdown, replace(ri, title=variant.title, body_markdown=variant.body_markdown))):
        issues.extend(assess_article_quality(body, min_chars=default_min_body_chars(variant.channel),
            channel=variant.channel, brand=brand, facts=facts))
        if not markdown_brand_validation(brand=brand, title=title, body_markdown=body).get("passed"):
            issues.append("当前品牌开篇/结论标准未通过")
        if not lint_summary(lint_draft(body, facts=facts)).get("blocks_ready"):
            issues.append("当前内容存在尚未核验的高风险表述")
        try:
            # Customer approval is a later step. All content/rules/lint checks
            # remain real; no approved task proxy is used to grant permission.
            assert_can_publish(data, task=None)
        except PublishGateError as exc:
            issues.append(str(exc))
    return list(dict.fromkeys(issues))[:24]


async def preview(session, actor, tenant, scope, task_id, channel):
    task, article, variant, facts, assets, revision = await _context(session, actor, tenant, scope, task_id, channel)
    issues = await quality_issues(session, task, article, variant, facts, assets)
    return {"variant_id": variant.id, "article_id": article.id, "revision": revision,
        "export_revision": export_revision(variant, article.id), "source": "manual",
        "requires_master_rebase": variant.article_version_id != article.id,
        "quality_passed": not issues, "issues": issues, "publishing_authorized": False}


async def finalize(session, actor, tenant, task_id, channel, req):
    task, article, variant, facts, assets, revision = await _context(session, actor, tenant, req.scope_id, task_id, channel)
    replay = await session.scalar(select(GeoChannelVariant).where(
        GeoChannelVariant.task_id == task_id, GeoChannelVariant.channel == channel,
        GeoChannelVariant.adapt_meta[KEY]["request_id"].astext == str(req.request_id)))
    if replay is not None:
        rec = (replay.adapt_meta or {}).get(KEY) or {}
        if (replay.id != variant.id or rec.get("snapshot_revision") != req.expected_revision
                or rec.get("finalized_by") != actor or rec.get("scope_id") != req.scope_id
                or rec.get("source_variant_id") != req.expected_variant_id
                or article.id != req.expected_article_id
                or not record_valid(task, article, replay, allow_pending=True, scope_id=req.scope_id)
                or rec.get("facts_digest") != digest(facts)):
            raise problem("geo_manual_request_conflict", "定版请求已被处理或当前版本已变化")
        return replay, True
    if (variant.id != req.expected_variant_id or article.id != req.expected_article_id
            or revision != req.expected_revision):
        raise problem("geo_manual_version_stale", "正文、事实、素材或母稿版本已变化，请重新核对")
    issues = await quality_issues(session, task, article, variant, facts, assets)
    if issues:
        raise problem("geo_manual_quality_blocked", "真实内容检查未通过：" + "；".join(issues[:6]))
    from app.geo.content.md_to_html import markdown_to_publish_html, html_to_plain, ensure_comparison_table_hint
    now = datetime.utcnow()
    updated = max(now, variant.updated_at + timedelta(microseconds=1)) if variant.updated_at else now
    html = markdown_to_publish_html(variant.body_markdown, wrap_article=True)
    rec = {"version": 1, "source": "manual", "state": "awaiting-review",
        "tenant_id": tenant, "scope_id": req.scope_id, "source_variant_id": variant.id,
        "source_article_id": variant.article_version_id,
        "request_id": str(req.request_id), "snapshot_revision": revision,
        "finalized_by": actor, "finalized_at": now.isoformat() + "Z",
        "master_digest": master_digest(article), "content_digest": content_digest(variant),
        "rendered_digest": digest(html),
        "facts_digest": digest(facts), "assets_digest": asset_digest(assets),
        "confirmations": req.model_dump(include={"confirm_title_body", "confirm_layout",
            "confirm_facts", "confirm_brand_author", "confirm_platform"}), "customer_review": None}
    result = GeoChannelVariant(task_id=task.id, article_version_id=article.id, channel=variant.channel,
        title=variant.title, body_markdown=variant.body_markdown, status="draft", export_format="html",
        created_at=now, updated_at=updated, adapt_meta={"engine": "manual_channel_finalization_v1",
            "polish": "manual", "quality": "publish_ready", "publishable": True,
            "fallback": False, "delivery": "html_publish_ready", "body_html": html,
            "body_plain": html_to_plain(html), "has_table": ensure_comparison_table_hint(variant.body_markdown),
            "article_standard": "full_article_v2", KEY: rec})
    session.add(result)
    await session.flush()
    invalidate_review(task)
    apply_submit(task, submitter_id=actor, note="顾问人工渠道定版，要求客户重新审核当前版本")
    return result, False


async def bind_customer_review(session, task, ctx, decision):
    from app.geo.content.routes import _latest_article, _variants, _task_facts, _fact_dicts
    article = await _latest_article(session, task.id, fresh=True)
    variants = current_variants(await _variants(session, task.id, fresh=True))
    facts = _fact_dicts(await _task_facts(session, task.id, fresh=True))
    pending = [v for v in variants if isinstance(v.adapt_meta, dict)
        and isinstance(v.adapt_meta.get(KEY), dict) and v.adapt_meta[KEY].get("state") == "awaiting-review"]
    if pending and not is_tenant_customer_reviewer(ctx):
        raise problem("geo_manual_customer_review_required", "人工定版必须由该客户实名账号重新审核", 403)
    for variant in variants:
        meta = dict(variant.adapt_meta or {})
        rec = meta.get(KEY)
        if not isinstance(rec, dict): continue
        rec = dict(rec)
        if decision == "rejected":
            rec["state"] = "invalidated"
            meta.update(publishable=False, quality="adapted_draft_not_publishable", delivery="html_preview_only")
        elif rec.get("state") == "awaiting-review":
            if (rec.get("master_digest") != master_digest(article)
                    or rec.get("content_digest") != content_digest(variant)
                    or rec.get("facts_digest") != digest(facts)
                    or rec.get("rendered_digest") != digest(meta.get("body_html"))):
                raise problem("geo_manual_version_stale", "人工定版版本已变化，请顾问重新定版")
            rec["state"] = "approved"
            rec["customer_review"] = {"reviewed_by": task.reviewed_by,
                "reviewed_at": task.reviewed_at.isoformat()}
        meta[KEY] = rec
        variant.adapt_meta = meta
