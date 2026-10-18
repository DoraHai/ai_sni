"""Object and assignment checks for SEO's scoped manual content writes.

These checks do not grant route or field access. The caller must first apply the
write rule and edit permissions, and recheck authorization before committing.
No ORM identity-map values or caller-supplied site can override stored ownership.
"""
import csv
import io
import json
from datetime import date

from fastapi import HTTPException
from sqlalchemy import or_, select
from starlette.datastructures import UploadFile

from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import (
    SeoAiOperation, SeoAutomationRun, SeoBrandAsset, SeoContentAsset, SeoKeywordAsset, SeoSiteAdvisorAssignment,
    SeoSitePage,
)
from app.models.seo_qa import SeoQaBatch, SeoQaFact
from app.models.seo_cockpit import SeoTask
from app.models.tenant import Tenant


# Deliberately limited to objects in the approved manual editing surface.
_MODELS = {
    "tenant_id": Tenant, "site_id": SeoSite, "fact_id": SeoQaFact,
    "asset_id": SeoBrandAsset, "content_id": SeoContentAsset,
    "keyword_id": SeoKeywordAsset, "page_id": SeoSitePage,
    "source_page_id": SeoSitePage,
}
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_FILE_ROWS = 2000
_MAX_REFERENCES = 10000
_MAX_DEPTH = 32


def _reject(status, code):
    raise HTTPException(status, {"code": code})


def _positive_id(value):
    if type(value) is int and 0 < value <= 2**63 - 1:
        return value
    if (isinstance(value, str) and value.isascii() and value.isdigit()
            and len(value) <= 19 and 0 < int(value) <= 2**63 - 1):
        return int(value)
    _reject(422, "ADVISOR_INVALID_OBJECT_ID")


def _id_key(key):
    """Recognize ambiguous/unknown IDs too, including plural array fields."""
    if key == "id" or key == "ids" or key.endswith(("_id", "_ids")):
        singular = key[:-1] if key.endswith("s") else key
        if singular not in _MODELS:
            _reject(403, "ADVISOR_OBJECT_UNAVAILABLE")
        return singular
    return None


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _references(value, refs, depth=0):
    if depth > _MAX_DEPTH:
        _reject(403, "ADVISOR_OBJECT_UNAVAILABLE")
    if isinstance(value, dict):
        for key, item in value.items():
            kind = _id_key(key)
            if kind is not None:
                if key.endswith("_ids"):
                    if not isinstance(item, list):
                        _reject(422, "ADVISOR_INVALID_OBJECT_ID")
                    for entry in item:
                        refs.append((kind, _positive_id(entry)))
                elif item is None and kind not in {"tenant_id", "site_id"}:
                    # Optional keyword/source-page removal is allowed by schemas.
                    continue
                else:
                    refs.append((kind, _positive_id(item)))
            else:
                _references(item, refs, depth + 1)
            if len(refs) > _MAX_REFERENCES:
                _reject(403, "ADVISOR_OBJECT_UNAVAILABLE")
    elif isinstance(value, list):
        for item in value:
            _references(item, refs, depth + 1)


async def _file_references(upload, refs):
    """Validate every row and restore the handler's file cursor on all exits.

    No upload route is currently allowlisted; this handles files defensively if
    a caller supplies multipart data. It does not authorize an import endpoint.
    """
    position = upload.file.tell()
    try:
        await upload.seek(0)
        raw = await upload.read(_MAX_FILE_BYTES + 1)
        if len(raw) > _MAX_FILE_BYTES:
            _reject(413, "ADVISOR_OBJECT_FILE_TOO_LARGE")
        try:
            source = raw.decode("utf-8-sig")
            name = (upload.filename or "").lower()
            if name.endswith(".json"):
                rows = json.loads(source, object_pairs_hook=_json_object)
                if isinstance(rows, dict):
                    rows = [rows]
                if not isinstance(rows, list):
                    raise ValueError()
            elif name.endswith(".csv"):
                reader = csv.DictReader(io.StringIO(source), strict=True)
                if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                    raise ValueError()
                for key in reader.fieldnames:
                    _id_key(key)
                rows = []
                for row in reader:
                    if None in row or None in row.values():
                        raise ValueError()
                    rows.append(row)
                    if len(rows) > _MAX_FILE_ROWS:
                        _reject(413, "ADVISOR_OBJECT_FILE_TOO_LARGE")
                # CSV plural references must be JSON arrays, never unchecked text.
                for row in rows:
                    for key in row:
                        if key.endswith("_ids"):
                            row[key] = json.loads(row[key])
                        elif row[key] == "" and key.endswith("_id") and key not in {"tenant_id", "site_id"}:
                            row[key] = None
            else:
                _reject(403, "ADVISOR_OBJECT_UNAVAILABLE")
            if len(rows) > _MAX_FILE_ROWS:
                _reject(413, "ADVISOR_OBJECT_FILE_TOO_LARGE")
            if not rows or any(not isinstance(row, dict) for row in rows):
                raise ValueError()
            _references(rows, refs)
        except (UnicodeError, ValueError, csv.Error, RecursionError):
            _reject(422, "ADVISOR_INVALID_OBJECT_FILE")
    finally:
        await upload.seek(position)


async def _request_references(request, body):
    refs = []
    _references(dict(request.path_params), refs)
    for key, value in request.query_params.multi_items():
        kind = _id_key(key)
        if kind is not None:
            # Repeated query parameters are independently checked, never collapsed.
            refs.append((kind, _positive_id(value)))
    _references(body, refs)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type in {"multipart/form-data", "application/x-www-form-urlencoded"}:
        form = await request.form()
        for key, value in form.multi_items():
            if isinstance(value, UploadFile):
                await _file_references(value, refs)
            elif key.endswith("_ids"):
                try:
                    value = json.loads(value)
                except ValueError:
                    _reject(422, "ADVISOR_INVALID_OBJECT_ID")
                _references({key: value}, refs)
            else:
                _references({key: value}, refs)
    if len(refs) > _MAX_REFERENCES:
        _reject(403, "ADVISOR_OBJECT_UNAVAILABLE")
    return refs


async def _scope(session, ctx, request, body, rule, *, lock=False):
    if getattr(rule, "workflow", False):
        from app.security.seo_advisor_work import workflow_scope
        return await workflow_scope(session, ctx, request, body, rule, lock=lock)
    ctx.ensure_tenant(ctx.tenant_id)
    if rule.assignment != "site":
        _reject(403, "ADVISOR_OBJECT_UNAVAILABLE")
    refs = await _request_references(request, body)
    scopes = set()
    seen = set()
    # Include unchanged stored links: a partial PATCH cannot launder a bad link.
    index = 0
    while index < len(refs):
        kind, object_id = refs[index]
        index += 1
        if (kind, object_id) in seen:
            continue
        seen.add((kind, object_id))
        model = _MODELS[kind]
        table = model.__table__
        query = select(table).where(table.c.id == object_id)
        if lock:
            query = query.with_for_update(read=True)
        row = (await session.execute(query)).mappings().first()
        if row is None:
            _reject(404, "ADVISOR_OBJECT_NOT_FOUND")
        owner = row["id"] if kind == "tenant_id" else row["tenant_id"]
        ctx.ensure_tenant(owner)
        if kind == "tenant_id":
            continue
        site_id = row["id"] if kind == "site_id" else row["site_id"]
        if site_id is None:
            _reject(403, "ADVISOR_OBJECT_UNAVAILABLE")
        scopes.add(site_id)
        if kind != "site_id":
            refs.append(("site_id", site_id))
        if kind == "content_id":
            _references({key: row[key] for key in ("keyword_id", "keyword_ids", "source_page_id")
                         if row[key] is not None}, refs)
        elif kind in {"page_id", "source_page_id"} and row["target_keyword_id"] is not None:
            refs.append(("keyword_id", row["target_keyword_id"]))
        if len(refs) > _MAX_REFERENCES:
            _reject(403, "ADVISOR_OBJECT_UNAVAILABLE")
    if len(scopes) > 1:
        _reject(403, "ADVISOR_TENANT_NOT_GRANTED")
    if not scopes:
        _reject(403, "ADVISOR_ASSIGNMENT_REQUIRED")
    # Creation must use the same explicit site that the handler will persist.
    if request.method == "POST" and (
        not isinstance(body, dict) or body.get("site_id") is None
    ):
        _reject(403, "ADVISOR_ASSIGNMENT_REQUIRED")
    return scopes.pop()


async def check_write_objects(session, ctx, request, body: dict | list | None, rule) -> None:
    if not ctx.is_advisor:
        return
    await _scope(session, ctx, request, body, rule)


async def ensure_advisor_assignment(session, ctx, request, body, rule) -> None:
    if not ctx.is_advisor:
        return
    site_id = await _scope(session, ctx, request, body, rule)
    if ctx.user_id is None:
        _reject(403, "ADVISOR_ASSIGNMENT_REQUIRED")
    # A fresh SQL read avoids an already-loaded assignment masking revocation.
    assignment = await session.scalar(select(SeoSiteAdvisorAssignment.id).where(
        SeoSiteAdvisorAssignment.tenant_id == ctx.tenant_id,
        SeoSiteAdvisorAssignment.site_id == site_id,
        SeoSiteAdvisorAssignment.advisor_user_id == ctx.user_id,
        SeoSiteAdvisorAssignment.active.is_(True),
    ))
    if assignment is None:
        _reject(403, "ADVISOR_ASSIGNMENT_REQUIRED")


async def lock_manual_write_scope(session, ctx, request, body, rule):
    """Hold assignment -> site locks, matching plan writers and schedulers.

    A manual edit is admitted only in a provably paused scope with no unfinished
    system work. Do not pause, cancel, or authorize any existing execution.
    """
    if getattr(rule, "workflow", False):
        from app.security.seo_advisor_work import lock_workflow_scope
        return await lock_workflow_scope(session, ctx, request, body, rule)
    site_id = await _scope(session, ctx, request, body, rule)
    assignments = list((await session.execute(select(SeoSiteAdvisorAssignment.__table__).where(
        SeoSiteAdvisorAssignment.tenant_id == ctx.tenant_id,
        SeoSiteAdvisorAssignment.site_id == site_id,
    ).order_by(SeoSiteAdvisorAssignment.id).with_for_update())).mappings())
    if not any(row['advisor_user_id'] == ctx.user_id and row['active'] for row in assignments):
        _reject(403, "ADVISOR_ASSIGNMENT_REQUIRED")
    site = (await session.execute(select(SeoSite.__table__).where(
        SeoSite.id == site_id, SeoSite.tenant_id == ctx.tenant_id).with_for_update())).mappings().first()
    if site is None:
        _reject(403, "ADVISOR_TENANT_NOT_GRANTED")
    module = (await session.execute(select(TenantModule.__table__).where(
        TenantModule.id == site['tenant_module_id'], TenantModule.tenant_id == ctx.tenant_id,
        TenantModule.module_code == 'seo').with_for_update(read=True))).mappings().first()
    if (site['status'] != 'active' or module is None or module['status'] not in {'active', 'trial'}
            or (module['expires_at'] is not None and module['expires_at'] < date.today())):
        _reject(403, "ADVISOR_OBJECT_UNAVAILABLE")
    settings = site['site_settings']
    plan = settings.get('seo_service_plan') if isinstance(settings, dict) else None
    if (not isinstance(plan, dict) or plan.get('status') != 'paused'
            or any(value for key, value in plan.items()
                   if key.endswith('_enabled'))):
        _reject(403, "ADVISOR_AUTOMATIC_CONSUMER_ACTIVE")
    task = await session.scalar(select(SeoTask.id).where(
        SeoTask.tenant_id == ctx.tenant_id, SeoTask.site_id == site_id,
        SeoTask.status.in_(['open', 'in_progress']),
        or_(SeoTask.assignee_role == 'system', SeoTask.action_type.in_([
            'content_delivery', 'site_diagnosis', 'ranking_followup', 'monthly_report',
        ])),
    ).limit(1))
    if task is not None:
        _reject(403, "ADVISOR_AUTOMATIC_CONSUMER_ACTIVE")
    for model, states in ((SeoQaBatch, ['queued', 'running']),
                          (SeoAiOperation, ['running']), (SeoAutomationRun, ['running'])):
        query = select(model.id, model.status).where(
            model.tenant_id == ctx.tenant_id,
            or_(model.site_id == site_id, model.site_id.is_(None)),
        ).order_by(model.id)
        # QA resume/retry locks its batch, while creation locks the site.
        # Include paused/finished batches so requeue cannot race this edit.
        if model is SeoQaBatch:
            query = query.with_for_update(read=True)
        else:
            query = query.where(model.status.in_(states))
        rows = (await session.execute(query)).all()
        if any(row.status in states for row in rows):
            _reject(403, "ADVISOR_AUTOMATIC_CONSUMER_ACTIVE")
    # Lock freshly read linked objects as well; scope cannot migrate before commit.
    await _scope(session, ctx, request, body, rule, lock=True)
