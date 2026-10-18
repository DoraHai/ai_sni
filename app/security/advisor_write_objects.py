"""Fail-closed object and project scope for GEO's manual content writes.

This module deliberately does not authorize routes, fields, grants or commits.
The write guard owns those checks and calls both public functions below.
"""
import csv
import io
import json
import re
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.security.advisor_scope import deny


_PREFIX = "/api/v1/geo"
_TASK_TEMPLATES = {
    _PREFIX + "/content-tasks/{task_id}",
    _PREFIX + "/content-tasks/{task_id}/facts",
    _PREFIX + "/content-tasks/{task_id}/article",
    _PREFIX + "/content-tasks/{task_id}/variants/{channel}",
}
_IMPORT_TEMPLATES = {
    _PREFIX + "/facts/import", _PREFIX + "/prompts/import",
    _PREFIX + "/prompts/import-csv",
}
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024


def _positive_id(value):
    # Keep this independent of the guard module to avoid a circular import
    # when the guard imports the two public write checks during integration.
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0:
        return int(value)
    deny(422, "ADVISOR_INVALID_OBJECT_ID", "客户和对象 ID 必须是正整数")


def _unavailable():
    deny(403, "ADVISOR_OBJECT_UNAVAILABLE", "此对象范围尚未开放")


def _assignment_required():
    deny(403, "ADVISOR_ASSIGNMENT_REQUIRED", "需要当前对象所属项目的有效顾问分配")


def _key(value):
    # Cover ID aliases even in flexible brief/meta/profile JSON dictionaries.
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value)).lower()


def _references(value):
    """Walk every nested object/list; unknown ID fields are never ignored."""
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = _key(raw_key)
            if key in {"id", "ids"} or key.endswith(("_id", "_ids")):
                singular = key[:-1] if key.endswith("ids") else key
                if key == "ids" or key.endswith("_ids"):
                    if not isinstance(item, list):
                        _unavailable()
                    if not item:
                        yield singular, None
                    for ident in item:
                        yield singular, ident
                else:
                    yield singular, item
            # An ID value containing an object is invalid, but still walked so
            # nested ID fields cannot disappear when a schema ignores extras.
            yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _unavailable()
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_json_object)
    except (ValueError, UnicodeError):
        _unavailable()


async def _upload_rows(upload):
    # Restore the exact cursor, so a subsequent handler reads the same bytes.
    position = upload.file.tell()
    try:
        await upload.seek(0)
        raw = await upload.read(_MAX_UPLOAD_BYTES + 1)
    finally:
        await upload.seek(position)
    if not raw or len(raw) > _MAX_UPLOAD_BYTES:
        _unavailable()
    name = (upload.filename or "").lower()
    if name.endswith(".json"):
        value = _json(raw)
        if not isinstance(value, (dict, list)):
            _unavailable()
        return value
    if not name.endswith(".csv"):
        _unavailable()
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        headers = reader.fieldnames
        if not headers or len({_key(h.strip()) for h in headers}) != len(headers):
            _unavailable()
        rows = []
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                _unavailable()
            parsed = {}
            for key, value in row.items():
                value = value.strip()
                # CSV may contain serialized JSON arrays or nested metadata.
                parsed[key.strip()] = _json(value) if value.startswith(("[", "{")) else value
            rows.append(parsed)
        if not rows:
            _unavailable()
        return rows
    except (UnicodeError, csv.Error):
        _unavailable()


async def _inputs(request, body):
    values = list(request.path_params.items()) + list(request.query_params.multi_items())
    # Preserve repeated query parameters instead of flattening them to a dict.
    refs = []
    for key, value in values:
        if _key(key).endswith("_ids"):
            value = _json(value) if isinstance(value, str) and value.startswith("[") else [value]
        refs.extend(_references({key: value}))
    refs.extend(_references(body))
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type in {"multipart/form-data", "application/x-www-form-urlencoded"}:
        form = await request.form()
        for key, value in form.multi_items():
            if isinstance(value, UploadFile):
                refs.extend(_references(await _upload_rows(value)))
            else:
                parsed = _json(value) if value.startswith(("[", "{")) else value
                refs.extend(_references({key: parsed}))
    return refs


@dataclass
class _Objects:
    businesses: set[int] = field(default_factory=set)
    projects: set[int] = field(default_factory=set)
    tasks: set[int] = field(default_factory=set)
    # An unscoped fact/prompt must not borrow scope from a sibling object.
    unscoped: bool = False


async def _resolve(session, ctx, request, body, rule):
    from app.models import (GeoArticleVersion, GeoChannelVariant, GeoContentTask,
                            GeoFact, GeoOptimizationBusiness, GeoOptimizationUnit,
                            GeoProject, GeoPrompt)

    ctx.ensure_tenant(ctx.tenant_id)
    template = getattr(request.scope.get("route"), "path", None)
    if template != rule.template:
        _unavailable()
    models = {
        "project_id": GeoProject, "business_id": GeoOptimizationBusiness,
        "unit_id": GeoOptimizationUnit, "prompt_id": GeoPrompt, "fact_id": GeoFact,
        "content_task_id": GeoContentTask, "article_id": GeoArticleVersion,
        "expected_article_id": GeoArticleVersion, "article_version_id": GeoArticleVersion,
        "variant_id": GeoChannelVariant,
    }
    from app.security.advisor_write_operations import task_templates
    from app.security.advisor_write_reads import TASK_READS
    task_routes = _TASK_TEMPLATES | task_templates() | TASK_READS
    if template in task_routes:
        models["task_id"] = GeoContentTask
    state = _Objects()
    seen = set()

    async def resolve(key, value):
        if key == "tenant_id":
            ctx.ensure_tenant(_positive_id(value))
            return
        model = models.get(key)
        if model is None:
            _unavailable()  # Includes unknown null/empty-array ID fields.
        if value is None:
            return
        ident = _positive_id(value)
        marker = (model, ident)
        if marker in seen:
            return
        seen.add(marker)
        stmt = select(model).where(model.id == ident).execution_options(populate_existing=True)
        if session.info.get("advisor_scoped_write"):
            # Commit-time validation retains ownership locks until the same
            # transaction commits, including parents without tenant columns.
            stmt = stmt.with_for_update()
        row = await session.scalar(stmt)
        if row is None:
            deny(404, "ADVISOR_OBJECT_NOT_FOUND", "对象不存在")
        if hasattr(row, "tenant_id"):
            ctx.ensure_tenant(row.tenant_id)
        if model is GeoProject:
            state.projects.add(ident)
        elif model is GeoOptimizationBusiness:
            state.businesses.add(ident)
        elif model is GeoOptimizationUnit:
            await resolve("business_id", row.business_id)
        elif model is GeoPrompt:
            if row.unit_id is None:
                state.unscoped = True
            else:
                await resolve("unit_id", row.unit_id)
        elif model is GeoFact:
            if row.business_id is None:
                state.unscoped = True
            else:
                await resolve("business_id", row.business_id)
        elif model is GeoContentTask:
            state.tasks.add(ident)
            await resolve("prompt_id", row.prompt_id)
            if row.business_id is not None:
                await resolve("business_id", row.business_id)
        else:
            # Articles and variants have no tenant column: their real owner is
            # the content task, never an action ticket with the same numeric ID.
            await resolve("content_task_id", row.task_id)
            if model is GeoChannelVariant:
                article = await session.scalar(select(GeoArticleVersion).where(
                    GeoArticleVersion.id == row.article_version_id).execution_options(populate_existing=True))
                if article is None:
                    deny(404, "ADVISOR_OBJECT_NOT_FOUND", "对象不存在")
                if article.task_id != row.task_id:
                    _unavailable()

    for key, value in await _inputs(request, body):
        await resolve(key, value)
    if template in task_routes:
        target = _positive_id(request.path_params["task_id"])
        if state.tasks != {target}:
            _unavailable()
        if template.endswith("/variants/{channel}"):
            variants = list(await session.scalars(select(GeoChannelVariant).where(
                GeoChannelVariant.task_id == target,
                GeoChannelVariant.channel == str(request.path_params["channel"]).strip().lower())))
            if not variants:
                deny(404, "ADVISOR_OBJECT_NOT_FOUND", "渠道稿不存在")
            for variant in variants:
                await resolve("variant_id", variant.id)
    return state


async def check_write_objects(session, ctx, request, body: dict | list | None, rule) -> None:
    """Validate all supplied IDs and their parent owners, without mutations."""
    await _resolve(session, ctx, request, body, rule)


async def ensure_advisor_assignment(session, ctx, request, body, rule) -> None:
    """Every referenced business must belong to the same assigned active project."""
    from app.geo.project_scope import binding
    from app.geo.project_workflows import advisor_available, plan_for
    from app.models import GeoProject, GeoVisibilityPatrolSettings

    objects = await _resolve(session, ctx, request, body, rule)
    creating_business = request.method == "POST" and rule.template == _PREFIX + "/optimization-businesses"
    if (rule.assignment != "project" or objects.unscoped
            or (not objects.businesses and not objects.projects and not creating_business)):
        _assignment_required()
    creation_parent = {
        _PREFIX + "/facts": "business_id", _PREFIX + "/prompts": "unit_id",
        _PREFIX + "/optimization-units": "business_id",
        _PREFIX + "/content-tasks": "prompt_id",
        _PREFIX + "/content-imports/create-task": "prompt_id",
    }.get(rule.template)
    if request.method == "POST" and creation_parent:
        if not isinstance(body, dict) or body.get(creation_parent) is None:
            _assignment_required()
    for parent_key in ("business_id", "unit_id"):
        if isinstance(body, dict) and parent_key in body and body[parent_key] is None:
            _assignment_required()
    # Business creation binds the new row atomically in its handler. Imports do
    # not persist business/unit ownership and remain unavailable.
    if creating_business and (objects.businesses or len(request.query_params.getlist("project_id")) != 1
                              or len(objects.projects) != 1):
        _assignment_required()
    if rule.template in _IMPORT_TEMPLATES:
        _assignment_required()
    project_stmt = select(GeoProject).where(GeoProject.tenant_id == ctx.tenant_id).order_by(
        GeoProject.id).execution_options(populate_existing=True)
    if session.info.get("advisor_scoped_write"):
        project_stmt = project_stmt.with_for_update()
    projects = list(await session.scalars(project_stmt))
    scopes, plans = {}, {}
    for project in projects:
        try:
            scopes[project.id] = set(binding(project)["business_ids"])
            plans[project.id] = plan_for(project)
            if not isinstance(plans[project.id], dict):
                _assignment_required()
        except (HTTPException, AttributeError, TypeError, ValueError):
            _assignment_required()
    selected = set(objects.projects)
    for business_id in objects.businesses:
        owners = {p.id for p in projects if business_id in scopes[p.id]}
        if len(owners) != 1:
            _assignment_required()
        selected.update(owners)
    if len(selected) != 1:
        _assignment_required()
    project = next((p for p in projects if p.id in selected), None)
    plan = plans[project.id] if project else {}
    # Imports use the selected customer grant, checked by auth and again at
    # commit. The scheduler helper requires a native/default tenant binding,
    # which would incorrectly exclude another explicitly granted customer.
    # The HTTP guard and commit hook validate the selected grant, account and
    # permissions. Scheduler's default-tenant helper must not veto another
    # explicitly granted customer on an interactive advisor request.
    selected_import = getattr(ctx, "advisor_scope", None) is not None
    if (project is None or project.status != "active"
            or type(plan.get("advisor_user_id")) is not int
            or plan["advisor_user_id"] != ctx.user_id
            or (not selected_import and not await advisor_available(session, ctx.tenant_id, ctx.user_id))):
        _assignment_required()
    # A tenant-wide patrol dynamically consumes new prompts. Active project
    # cycles and generation can consume updated facts. Refuse these resources
    # while either execution chain is enabled rather than silently enrolling
    # manual preparation into background work.
    if rule.template in {_PREFIX + "/facts", _PREFIX + "/facts/{fact_id}",
                         _PREFIX + "/prompts", _PREFIX + "/prompts/{prompt_id}"}:
        patrol = await session.scalar(select(GeoVisibilityPatrolSettings.enabled).where(
            GeoVisibilityPatrolSettings.tenant_id == ctx.tenant_id))
        if patrol or any(p.get("enabled") for p in plans.values()):
            _unavailable()
