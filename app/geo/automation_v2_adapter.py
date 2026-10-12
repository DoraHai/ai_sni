"""GEO-owned validation and ownership rules for shared automation v2.

The shared ledger deliberately knows nothing about GEO rows.  This adapter
builds hashes from live business inputs and treats every explicitly configured
visibility target as owned even after pause/end_project, so the legacy tenant
scheduler cannot take it back.
"""
from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import select, text

from app import automation_project_v2 as shared_v2
from app.automation_project_contract import ConfigurationV2
from app.geo.project_scope import binding, project_scope, prompt_ids_for_businesses
from app.geo.project_workflows import plan_for
from app.geo.project_workflows import advisor_available
from app.models import (GeoActionTicket, GeoAnswerSnapshot, GeoArticleVersion, GeoCompetitorAlias,
                        GeoChannelVariant, GeoContentTask, GeoFact,
                        GeoOptimizationBusiness, GeoProject, GeoPrompt, GeoPublication,
                        GeoTaskFact, GeoTrackingEngine,
                        GeoVisibilityPatrolSettings)
from app.models.user import User


VISIBILITY_OPERATION = "visibility_patrol"
PERIODIC_OPERATION = "periodic_workflow"
BRIEF_OPERATION = "content_brief_suggestion"
COMPETITOR_OPERATION = "competitor_report_draft"
MASTER_OPERATION = "content_master_draft"
VARIANT_OPERATION = "channel_variant_draft"
ONSITE_OPERATION = "onsite_ai"
OUTCOME_OPERATION = "outcome_review"
PUBLICATION_OPERATION = "publication_monitor"
SUPPORTED_OPERATIONS = frozenset({VISIBILITY_OPERATION, PERIODIC_OPERATION,
                                  BRIEF_OPERATION, COMPETITOR_OPERATION,
                                  MASTER_OPERATION, VARIANT_OPERATION,
                                  ONSITE_OPERATION, OUTCOME_OPERATION,
                                  PUBLICATION_OPERATION})
SOURCE_KINDS = ("tenant_patrol_settings", "project_prompt_set", "project_scope_registry")


def _settings_value(row: GeoVisibilityPatrolSettings) -> dict:
    return {
        "enabled": bool(row.enabled),
        "window_start_hour": int(row.window_start_hour),
        "window_end_hour": int(row.window_end_hour),
        "interval_hours": int(row.interval_hours),
        "auto_persist": bool(row.auto_persist),
        "prefer_real": bool(row.prefer_real),
        "prompt_limit": int(row.prompt_limit),
        "engine_keys": sorted(row.engine_keys or []),
    }


def _prompt_value(row: GeoPrompt) -> dict:
    return {
        "id": int(row.id), "unit_id": int(row.unit_id) if row.unit_id else None,
        "question": row.question, "language": row.language, "priority": int(row.priority),
        # tags contains system-derived mention markers written by patrol itself;
        # it is not a source input and must not invalidate the next engine.
        "demand_note": row.demand_note, "status": row.status,
        "source": row.source, "question_group": row.question_group, "market": row.market,
        "is_brand_probe": bool(row.is_brand_probe), "owner_user_id": row.owner_user_id,
    }


def _plan_value(project: GeoProject) -> dict:
    plan = plan_for(project)
    return {key: plan.get(key) for key in (
        "revision", "enabled", "status", "prompt_ids", "interval_days", "advisor_user_id"
    )}


def _scope_value(project: GeoProject) -> dict:
    value = binding(project)
    return {"revision": int(value["revision"]), "business_ids": sorted(value["business_ids"])}


async def live_basis(session, tenant_id: int, project_id: int, operations=None) -> dict:
    """Return the exact server-owned inputs used by configure and execution."""
    requested_operations = set(operations or SUPPORTED_OPERATIONS)
    project, business_ids = await project_scope(session, tenant_id, project_id)
    settings = await session.scalar(select(GeoVisibilityPatrolSettings).where(
        GeoVisibilityPatrolSettings.tenant_id == tenant_id
    ).execution_options(populate_existing=True))
    if settings is None and VISIBILITY_OPERATION in requested_operations:
        raise HTTPException(409, {"code": "automation_patrol_settings_missing", "message": "请先配置 GEO 巡检"})
    prompt_ids = set(await prompt_ids_for_businesses(session, tenant_id, business_ids))
    selected = set(plan_for(project).get("prompt_ids") or [])
    prompts = list(await session.scalars(select(GeoPrompt).where(
        GeoPrompt.tenant_id == tenant_id,
        GeoPrompt.id.in_(prompt_ids & selected),
        GeoPrompt.status == "active",
    ).order_by(GeoPrompt.id).execution_options(populate_existing=True)))
    engines = list(await session.scalars(select(GeoTrackingEngine).where(
        GeoTrackingEngine.tenant_id == tenant_id,
        GeoTrackingEngine.enabled.is_(True),
    ).order_by(GeoTrackingEngine.sort_order, GeoTrackingEngine.id)
      .execution_options(populate_existing=True))) if VISIBILITY_OPERATION in requested_operations else []
    if (len(engines) > 10 or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", row.engine_key or "")
                                 for row in engines)):
        raise HTTPException(409, {"code": "automation_engine_registry_invalid",
                                  "message": "巡检引擎清单超限或包含无效标识"})
    plan_value = _plan_value(project)
    scope_value = _scope_value(project)
    prompt_set = {"prompt_ids": [int(row.id) for row in prompts]}
    sources = [
        {"kind": "project_prompt_set", "object_id": project_id,
         "revision": int(plan_value.get("revision") or 0), "sha256": shared_v2.fingerprint(prompt_set)},
        {"kind": "project_scope_registry", "object_id": project_id,
         "revision": int(scope_value["revision"]), "sha256": shared_v2.fingerprint(scope_value)},
    ]
    if VISIBILITY_OPERATION in requested_operations:
        sources.insert(0, {"kind": "tenant_patrol_settings", "object_id": tenant_id,
            "revision": 0, "sha256": shared_v2.fingerprint(_settings_value(settings))})
    visibility_targets = []
    for prompt in prompts:
        source_hash = shared_v2.fingerprint(_prompt_value(prompt))
        for engine in engines:
            visibility_targets.append({"operation": VISIBILITY_OPERATION, "object_type": "prompt",
                "object_id": int(prompt.id), "source_revision": 0,
                "source_hash": source_hash, "variant": engine.engine_key})
    periodic_targets = [{"operation": PERIODIC_OPERATION, "object_type": "project",
        "object_id": project_id, "source_revision": int(plan_value.get("revision") or 0),
        "source_hash": shared_v2.fingerprint({"plan": plan_value, "scope": scope_value}),
        "variant": None}]
    content_operations = {BRIEF_OPERATION, MASTER_OPERATION, VARIANT_OPERATION,
                          OUTCOME_OPERATION, PUBLICATION_OPERATION}
    needs_content = bool(requested_operations & content_operations)
    tasks = list(await session.scalars(select(GeoContentTask).where(
        GeoContentTask.tenant_id == tenant_id,
        GeoContentTask.business_id.in_(business_ids),
        GeoContentTask.status.notin_(("archived", "cancelled")),
    ).order_by(GeoContentTask.id).execution_options(populate_existing=True))) if needs_content else []
    businesses = ({row.id: row for row in await session.scalars(select(GeoOptimizationBusiness).where(
        GeoOptimizationBusiness.tenant_id == tenant_id,
        GeoOptimizationBusiness.id.in_(business_ids),
    ).execution_options(populate_existing=True))}
        if requested_operations & {BRIEF_OPERATION, MASTER_OPERATION} else {})
    prompt_map = {int(row.id): row for row in prompts}
    brief_targets = []
    master_targets = []
    task_ids = [int(row.id) for row in tasks]
    existing_article_task_ids = (set(await session.scalars(select(GeoArticleVersion.task_id).where(
        GeoArticleVersion.task_id.in_(task_ids)
    ).distinct())) if task_ids and requested_operations & {MASTER_OPERATION, VARIANT_OPERATION} else set())
    latest_articles = {}
    if task_ids and VARIANT_OPERATION in requested_operations:
        for article in await session.scalars(select(GeoArticleVersion).where(
            GeoArticleVersion.task_id.in_(task_ids)
        ).order_by(GeoArticleVersion.task_id, GeoArticleVersion.version_no.desc(),
                   GeoArticleVersion.id.desc()).execution_options(populate_existing=True)):
            latest_articles.setdefault(int(article.task_id), article)
    existing_variants = ({(int(row.task_id), str(row.channel).lower()) for row in await session.scalars(
        select(GeoChannelVariant).where(
            GeoChannelVariant.task_id.in_(task_ids)
        ).execution_options(populate_existing=True))}
        if task_ids and VARIANT_OPERATION in requested_operations else set())
    variant_targets = []
    reviewer_ids = {int(row.reviewed_by) for row in tasks
                    if isinstance(row.reviewed_by, int) and row.reviewed_by > 0}
    valid_reviewer_ids = (set(await session.scalars(select(User.id).where(
        User.id.in_(reviewer_ids), User.is_active.is_(True)
    ))) if reviewer_ids and VARIANT_OPERATION in requested_operations else set())
    for task in tasks:
        prompt = prompt_map.get(int(task.prompt_id))
        if prompt is None:
            continue
        business = businesses.get(task.business_id)
        source = {"task": {"id": int(task.id), "prompt_id": int(task.prompt_id),
                            "business_id": task.business_id, "title": task.title,
                            # status is an executor-owned queue/phase field.
                            "brief": task.brief or {}},
                  "prompt": _prompt_value(prompt),
                  "profile": (business.profile or {}) if business else {}}
        if BRIEF_OPERATION in requested_operations:
            brief_targets.append({"operation": BRIEF_OPERATION, "object_type": "content_task",
                "object_id": int(task.id), "source_revision": 0,
                "source_hash": shared_v2.fingerprint(source), "variant": None})
        if MASTER_OPERATION in requested_operations and int(task.id) not in existing_article_task_ids:
            facts = list((await session.execute(select(GeoFact, GeoTaskFact.sort_order).join(
                GeoTaskFact, GeoTaskFact.fact_id == GeoFact.id
            ).where(GeoTaskFact.task_id == task.id).order_by(
                GeoTaskFact.sort_order, GeoFact.id).execution_options(populate_existing=True))).all())
            fact_source = [{"id": int(fact.id), "title": fact.title,
                            "statement": fact.statement, "fact_type": fact.fact_type,
                            "source_name": fact.source_name, "source_url": fact.source_url,
                            "trust_level": fact.trust_level, "status": fact.status,
                            "expires_at": fact.expires_at.isoformat() if fact.expires_at else None,
                            "meta": fact.meta or {}, "sort_order": int(sort_order)}
                           for fact, sort_order in facts]
            master_targets.append({"operation": MASTER_OPERATION,
                "object_type": "content_task", "object_id": int(task.id),
                "source_revision": 0,
                "source_hash": shared_v2.fingerprint({**source, "facts": fact_source}),
                "variant": None})
        article = latest_articles.get(int(task.id)) if VARIANT_OPERATION in requested_operations else None
        channels = []
        if VARIANT_OPERATION in requested_operations:
            for raw in task.target_channels or []:
                channel = str(raw or "").strip().lower()
                if channel and channel not in channels:
                    channels.append(channel)
            if (len(channels) > 10 or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", row)
                                          for row in channels)):
                raise HTTPException(409, {"code": "automation_channel_registry_invalid",
                                          "message": "目标渠道超限或包含无效标识"})
        article_reviewed = bool(
            article is not None and task.review_status == "approved"
            and task.reviewed_at is not None
            and task.reviewed_by in valid_reviewer_ids
        )
        if article_reviewed:
            article_source = {"id": int(article.id), "version_no": int(article.version_no),
                              "kind": article.kind, "title": article.title,
                              "body_markdown": article.body_markdown,
                              "outline": article.outline or {}}
            for channel in channels:
                if (int(task.id), channel) not in existing_variants:
                    variant_targets.append({"operation": VARIANT_OPERATION,
                        "object_type": "content_task", "object_id": int(task.id),
                        "source_revision": int(article.version_no),
                        "source_hash": shared_v2.fingerprint(
                            {"task": source["task"], "article": article_source,
                             "channel": channel}), "variant": channel})
    snapshots = (list(await session.scalars(select(GeoAnswerSnapshot).where(
        GeoAnswerSnapshot.tenant_id == tenant_id,
        GeoAnswerSnapshot.prompt_id.in_(prompt_set["prompt_ids"]),
    ).order_by(GeoAnswerSnapshot.id).limit(501).execution_options(populate_existing=True)))
        if COMPETITOR_OPERATION in requested_operations else [])
    if len(snapshots) > 500:
        raise HTTPException(409, {"code": "automation_competitor_source_too_large",
                                  "message": "竞品证据超过单次安全上限，请先缩小项目问题范围"})
    snapshot_source = [{"id": int(row.id), "prompt_id": row.prompt_id,
                        "engine": row.engine,
                        "captured_at": row.captured_at.isoformat() if row.captured_at else None,
                        "competitors": row.competitors or [], "cited_urls": row.cited_urls or [],
                        "sample_mode": row.sample_mode, "simulated": bool(row.simulated)}
                       for row in snapshots]
    aliases = (list(await session.scalars(select(GeoCompetitorAlias).where(
        GeoCompetitorAlias.tenant_id == tenant_id,
    ).order_by(GeoCompetitorAlias.id).execution_options(populate_existing=True)))
        if COMPETITOR_OPERATION in requested_operations else [])
    competitor_targets = [{"operation": COMPETITOR_OPERATION,
        "object_type": "competitor_alias", "object_id": int(alias.id),
        "source_revision": 0,
        "source_hash": shared_v2.fingerprint({"alias": {"id": int(alias.id),
            "alias_name": alias.alias_name, "canonical_name": alias.canonical_name},
            "snapshots": snapshot_source}), "variant": None} for alias in aliases]
    onsite_targets = []
    if ONSITE_OPERATION in requested_operations:
        # Import lazily: the route module owns the public-source projection and
        # imports the async job registry during application boot.
        from app.geo.onsite_routes import PREFIX, _proposal_snapshot
        onsite_rows = list(await session.scalars(select(GeoActionTicket).where(
            GeoActionTicket.tenant_id == tenant_id,
            GeoActionTicket.advice_code.startswith(PREFIX),
            GeoActionTicket.progress["onsite"]["project_id"].as_integer() == project_id,
        ).order_by(GeoActionTicket.id).execution_options(populate_existing=True)))
        for row in onsite_rows:
            value = (row.progress or {}).get("onsite") or {}
            if value.get("phase") != "draft":
                continue
            snapshot = await _proposal_snapshot(session, project, row)
            onsite_targets.append({"operation": ONSITE_OPERATION,
                "object_type": "onsite_task", "object_id": int(row.id),
                "source_revision": int(value.get("revision") or 0),
                "source_hash": str(snapshot["source_hash"]), "variant": None})
    task_business = {int(row.id): int(row.business_id) if row.business_id else None for row in tasks}
    outcome_targets = []
    if OUTCOME_OPERATION in requested_operations:
        review_rows = list(await session.scalars(select(GeoActionTicket).where(
            GeoActionTicket.tenant_id == tenant_id,
            GeoActionTicket.advice_code.like("cockpit:v1:%"),
            GeoActionTicket.status.in_(("todo", "doing")),
        ).order_by(GeoActionTicket.id).execution_options(populate_existing=True)))
        for row in review_rows:
            params = (row.progress_first or {}).get("params") or {}
            content_task_id = params.get("content_task_id")
            try:
                content_task_id = int(content_task_id)
            except (TypeError, ValueError):
                continue
            if task_business.get(content_task_id) not in business_ids:
                continue
            stable = {"ticket_id": int(row.id), "content_task_id": content_task_id,
                      "params": params, "baseline_snapshot": row.baseline_snapshot or {},
                      "status": row.status}
            outcome_targets.append({"operation": OUTCOME_OPERATION,
                "object_type": "metric_task", "object_id": int(row.id),
                "source_revision": 0, "source_hash": shared_v2.fingerprint(stable),
                "variant": None})
    publication_targets = []
    if PUBLICATION_OPERATION in requested_operations and task_ids:
        rows = list((await session.execute(select(GeoPublication, GeoChannelVariant).join(
            GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id
        ).where(
            GeoChannelVariant.task_id.in_(task_ids),
            GeoPublication.status == "published",
            GeoPublication.published_url.is_not(None),
        ).order_by(GeoPublication.id).execution_options(populate_existing=True))).all())
        for publication, variant in rows:
            stable = {"publication": {"id": int(publication.id),
                        "variant_id": int(publication.variant_id),
                        "url": publication.published_url, "status": publication.status},
                      "variant": {"id": int(variant.id),
                        "task_id": int(variant.task_id),
                        "article_version_id": int(variant.article_version_id),
                        "fingerprint": shared_v2.fingerprint({
                            "title": variant.title, "body_markdown": variant.body_markdown})}}
            publication_targets.append({"operation": PUBLICATION_OPERATION,
                "object_type": "publication", "object_id": int(publication.id),
                "source_revision": int(variant.article_version_id),
                "source_hash": shared_v2.fingerprint(stable), "variant": None})
    return {"project": project, "settings": settings, "prompts": prompts, "engines": engines,
        "service_plan": {"revision": int(plan_value.get("revision") or 0),
                         "sha256": shared_v2.fingerprint(plan_value)},
        "source_bindings": sources,
        "targets_by_operation": {VISIBILITY_OPERATION: visibility_targets,
                                  PERIODIC_OPERATION: periodic_targets,
                                  BRIEF_OPERATION: brief_targets,
                                  COMPETITOR_OPERATION: competitor_targets,
                                  MASTER_OPERATION: master_targets,
                                  VARIANT_OPERATION: variant_targets,
                                  ONSITE_OPERATION: onsite_targets,
                                  OUTCOME_OPERATION: outcome_targets,
                                  PUBLICATION_OPERATION: publication_targets},
        "targets": visibility_targets}


async def validate_configuration(session, tenant_id: int, project_id: int,
                                 configuration: ConfigurationV2, actor_id: int,
                                 *, current_targets: list[dict] | None = None) -> dict:
    if not set(configuration.operations) <= SUPPORTED_OPERATIONS:
        raise HTTPException(409, {"code": "automation_operation_not_supported", "message": "所选 GEO 操作尚未接入受控执行"})
    basis = await live_basis(session, tenant_id, project_id, configuration.operations)
    plan = plan_for(basis["project"])
    if (basis["project"].status != "active"
            or not plan.get("enabled") or plan.get("status") != "active"
            or int(plan.get("advisor_user_id") or 0) != actor_id
            or configuration.owner_user_id != actor_id
            or not await advisor_available(session, tenant_id, actor_id)):
        raise HTTPException(409, {"code": "automation_service_plan_changed", "message": "服务计划或顾问分配已变化"})
    expected_sources = basis["source_bindings"]
    expected_targets = [target for operation in configuration.operations
                        for target in basis["targets_by_operation"].get(operation, [])]
    if configuration.service_plan.model_dump(mode="json") != basis["service_plan"]:
        raise HTTPException(409, {"code": "automation_service_plan_changed", "message": "服务计划版本已变化，请刷新"})
    configured_sources = {
        (item.kind, int(item.object_id)): item.model_dump(mode="json")
        for item in configuration.source_bindings
    }
    live_sources = {(item["kind"], int(item["object_id"])): item for item in expected_sources}
    if configured_sources != live_sources:
        raise HTTPException(409, {"code": "automation_source_changed", "message": "项目问题或巡检配置已变化，请刷新"})
    requested = (current_targets if current_targets is not None else
                 [item.model_dump(mode="json") for item in configuration.targets])
    allowed = {(item["operation"], item["object_type"], item["object_id"], item["variant"],
                item["source_revision"], item["source_hash"]) for item in expected_targets}
    if not requested or any((item["operation"], item["object_type"], item["object_id"], item["variant"],
                             item["source_revision"], item["source_hash"]) not in allowed for item in requested):
        raise HTTPException(409, {"code": "automation_target_changed", "message": "执行目标已变化，请刷新"})
    return basis


async def owned_visibility_prompt_ids(session, tenant_id: int) -> set[int]:
    """Return claimed prompts; partial/unreadable registry raises and fails closed."""
    installed = await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM information_schema.tables
        WHERE table_schema=current_schema() AND table_name='automation_projects')"""))
    if not installed:
        return set()
    await shared_v2.require_schema(session)
    rows = list((await session.execute(text("""SELECT scope_id,configuration FROM automation_projects
        WHERE module='geo' AND tenant_id=:tenant_id
          AND configuration->>'contract_version'='2'
          AND configuration->'operations' ? :operation"""),
        {"tenant_id": tenant_id, "operation": VISIBILITY_OPERATION})).mappings())
    owners: dict[int, set[int]] = {}
    for row in rows:
        config = ConfigurationV2.model_validate(row["configuration"])
        project_prompts = {int(target.object_id) for target in config.targets
                           if target.operation == VISIBILITY_OPERATION
                           and target.object_type == "prompt"}
        for prompt_id in project_prompts:
            owners.setdefault(prompt_id, set()).add(int(row["scope_id"]))
    duplicates = [prompt_id for prompt_id, scope_ids in owners.items() if len(scope_ids) > 1]
    if duplicates:
        raise HTTPException(409, {"code": "automation_target_ownership_conflict",
                                  "message": "同一巡检问题被多个项目接管"})
    return set(owners)


async def owned_target_ids(session, tenant_id: int, operation: str,
                           object_type: str) -> set[int]:
    """Return durable v2 ownership for a typed target, including paused/ended projects."""
    installed = await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM information_schema.tables
        WHERE table_schema=current_schema() AND table_name='automation_projects')"""))
    if not installed:
        return set()
    await shared_v2.require_schema(session)
    rows = list((await session.execute(text("""SELECT scope_id,configuration FROM automation_projects
        WHERE module='geo' AND tenant_id=:tenant_id
          AND configuration->>'contract_version'='2'
          AND configuration->'operations' ? :operation"""),
        {"tenant_id": tenant_id, "operation": operation})).mappings())
    owners: dict[int, set[int]] = {}
    for row in rows:
        config = ConfigurationV2.model_validate(row["configuration"])
        for target in config.targets:
            if target.operation == operation and target.object_type == object_type:
                owners.setdefault(int(target.object_id), set()).add(int(row["scope_id"]))
    duplicates = [ident for ident, scopes in owners.items() if len(scopes) > 1]
    if duplicates:
        raise HTTPException(409, {"code": "automation_target_ownership_conflict",
                                  "message": "同一执行目标被多个项目接管"})
    return set(owners)


async def legacy_prompt_ids(session, tenant_id: int, limit: int) -> list[int]:
    owned = await owned_visibility_prompt_ids(session, tenant_id)
    rows = list(await session.scalars(select(GeoPrompt.id).where(
        GeoPrompt.tenant_id == tenant_id, GeoPrompt.status == "active",
        GeoPrompt.id.not_in(owned) if owned else text("TRUE"),
    ).order_by(GeoPrompt.priority.desc(), GeoPrompt.id.desc()).limit(max(1, min(limit, 50)))))
    return [int(value) for value in rows]


async def provider_fee_receipt(session, *, tenant_id: int, job_ref: str) -> tuple[str, list[str]]:
    """Return recorded only when the existing usage ledger has reviewable cost."""
    columns = set((await session.execute(text("""SELECT column_name FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name='api_usage_events'"""))).scalars())
    required = {"id", "tenant_id", "module", "job_ref", "state", "estimated_amount"}
    if not required <= columns:
        return "unknown_charge", []
    try:
        from app.api_usage_review_basis import accounted_amount
        amount = await accounted_amount(session)
    except RuntimeError:
        return "unknown_charge", []
    rows = list((await session.execute(text(
        "SELECT id,state," + amount + " AS amount FROM api_usage_events "
        "WHERE tenant_id=:tenant AND module='geo' AND job_ref=:job ORDER BY id LIMIT 21"
    ), {"tenant": tenant_id, "job": job_ref})).mappings())
    known = (bool(rows) and len(rows) <= 20
             and all(row["state"] in {"succeeded", "error"}
                     and row["amount"] is not None for row in rows))
    return ("recorded" if known else "unknown_charge"), [
        f"api_event:{row['id']}" for row in rows[:20]
    ]


def aggregate_step_fee(step: dict | None) -> str:
    """Derive settlement cost only from durable per-call receipts."""
    provider_calls = [call for call in (step or {}).get("calls", [])
                      if call.get("kind") == "provider"]
    if not provider_calls:
        return "not_called"
    if all(call.get("fee_state") == "recorded" for call in provider_calls):
        return "recorded"
    return "unknown_charge"
