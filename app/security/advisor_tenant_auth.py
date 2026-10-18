"""Per-request grant validation for the independent SEO API.

The module deliberately exposes no grant administration or task dispatch API.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.models.advisor_tenant_grant import AdvisorTenantGrant
from app.models.tenant import Tenant
from app.security.advisor_seo_scope import is_advisor_role

SESSION_ROUTES = frozenset({
    ("GET", "/api/v1/auth/me"), ("GET", "/api/v1/auth/tenants"),
    ("POST", "/api/v1/auth/select-tenant"), ("PATCH", "/api/v1/auth/password"),
    ("GET", "/api/v1/auth/linked-accounts"),
})


def reject(status, code):
    raise HTTPException(status, {"code": code})


def positive_id(value):
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) > 0:
        return int(value)
    reject(401, "ADVISOR_INVALID_TOKEN")


async def apply_advisor_claims(ctx, user, role, payload, session):
    advisor = is_advisor_role(role)
    # Existing platform admin behavior has priority over historic restrictions.
    if (role and role.is_system and role.name == "管理员") or ctx.can_edit("settings.accounts"):
        if payload.get("scope_kind") is not None:
            reject(401, "ADVISOR_INVALID_TOKEN")
        return ctx
    try:
        # A savepoint keeps a missing-table query from poisoning a non-advisor's
        # ordinary transaction during the code-first rollout.
        async with session.begin_nested():
            grants = list(await session.scalars(select(AdvisorTenantGrant).where(
                AdvisorTenantGrant.user_id == user.id).execution_options(populate_existing=True)))
    except SQLAlchemyError:
        if advisor or payload.get("scope_kind") is not None:
            reject(503, "ADVISOR_GRANTS_UNAVAILABLE")
        return ctx  # COMMON-2: ordinary non-advisors keep their existing scope.
    if not advisor:
        if grants or payload.get("scope_kind") is not None:
            reject(403, "ADVISOR_ROLE_CHANGED")
        return ctx
    ctx.is_advisor = True
    ctx.scope_kind = payload.get("scope_kind")
    active = {g.id: g for g in grants if g.revoked_at is None}
    ctx.advisor_tenant_ids = frozenset(g.tenant_id for g in active.values())
    ctx.tenant_id = None  # Never use users.tenant_id as a business fallback.
    scope = ctx.scope_kind
    if scope == "advisor_identity":
        if payload.get("aud") != "advisor-session" or type(payload.get("exp")) is not int:
            reject(401, "ADVISOR_INVALID_TOKEN")
        ctx.auth_exp = payload["exp"]
        return ctx
    if scope != "advisor_tenant":
        reject(409, "ADVISOR_TENANT_SELECTION_REQUIRED")
    if payload.get("aud") != "advisor-business":
        reject(401, "ADVISOR_INVALID_TOKEN")
    tid, gid = positive_id(payload.get("tid")), positive_id(payload.get("gid"))
    exp, auth_exp = payload.get("exp"), payload.get("auth_exp")
    if (type(exp) is not int or type(auth_exp) is not int or exp > auth_exp
            or auth_exp <= datetime.now(timezone.utc).timestamp()):
        reject(401, "ADVISOR_INVALID_TOKEN")
    grant = active.get(gid)
    if grant is None or grant.tenant_id != tid:
        reject(401, "ADVISOR_GRANT_REVOKED")
    if not ctx.advisor_tenant_ids:
        reject(403, "ADVISOR_NO_TENANT")
    if user.tenant_id not in ctx.advisor_tenant_ids:
        reject(403, "ADVISOR_DEFAULT_TENANT_INVALID")
    if await session.get(Tenant, tid, populate_existing=True) is None:
        reject(403, "ADVISOR_TENANT_NOT_GRANTED")
    ctx.tenant_id, ctx.grant_id, ctx.auth_exp = tid, gid, auth_exp
    return ctx


async def enforce_advisor_request(request, ctx, session):
    """Runs even on routes depending only on require_auth, before any handler."""
    if not ctx.is_advisor:
        return
    route = (request.method, request.url.path)
    if route in SESSION_ROUTES:
        return
    if ctx.scope_kind != "advisor_tenant":
        if not ctx.advisor_tenant_ids:
            reject(403, "ADVISOR_NO_TENANT")
        reject(409, "ADVISOR_TENANT_SELECTION_REQUIRED")
    ctx.ensure_tenant(ctx.tenant_id)
    # Persisted jobs do not yet bind a grant generation. Do not dispatch writes,
    # exports, publishing, supplier calls or streaming work for advisors.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        reject(403, "ADVISOR_HIGH_RISK_WRITES_DISABLED")
    from app.security.auth import _required, enforce_scoped_request
    keys, _ = _required(request.url.path, request.method)
    if keys is None:
        reject(403, "ADVISOR_ROUTE_UNAVAILABLE")
    # All SEO business reads require an explicit tenant parameter.
    if request.url.path.startswith("/api/v1/seo"):
        if (not request.query_params.getlist("tenant_id")
                and "tenant_id" not in request.path_params):
            reject(403, "ADVISOR_TENANT_REQUIRED")
        from app.module_scope import ensure_module_access
        await ensure_module_access(session, ctx, ctx.tenant_id, "seo")
    else:
        # GEO has its own production unit. Unknown business areas remain closed
        # here until their object/task matrix is reviewed in that branch.
        reject(403, "ADVISOR_ROUTE_UNAVAILABLE")
    await enforce_scoped_request(request, ctx)
    await check_seo_objects(request, ctx, session)


async def check_seo_objects(request, ctx, session):
    """Resolve actual owners rather than trusting a caller's extra tenant_id."""
    from app.database import Base
    owners = {
        "site_id": "seo_sites", "keyword_id": "seo_keyword_assets",
        "content_id": "seo_content_assets", "page_id": "seo_site_pages",
        "source_page_id": "seo_site_pages", "capture_id": "seo_page_captures",
        "task_id": "seo_tasks", "batch_id": "seo_qa_batches",
        "operation_id": "seo_ai_operations", "publication_id": "seo_content_publications",
        "variant_id": "seo_distribution_variants", "question_id": "seo_questions",
        "placement_id": "seo_qa_placements", "run_id": "seo_automation_runs",
        "connection_id": "seo_distribution_connections", "asset_id": "seo_brand_assets",
        "result_id": "seo_serp_results", "assignment_id": "seo_site_advisor_assignments",
        "conversation_id": "seo_content_conversations",
    }
    values = list(request.path_params.items())
    values.extend((key, value) for key, value in request.query_params.multi_items()
                  if key.endswith("_id"))
    for key, value in values:
        if not key.endswith("_id") or key == "tenant_id":
            continue
        if key in {"before_id", "message_id"}:
            messages = Base.metadata.tables["seo_content_messages"]
            conversations = Base.metadata.tables["seo_content_conversations"]
            try:
                message_id = int(value)
            except (TypeError, ValueError):
                reject(422, "ADVISOR_INVALID_OBJECT_ID")
            owner = await session.scalar(select(conversations.c.tenant_id).join(
                messages, messages.c.conversation_id == conversations.c.id).where(messages.c.id == message_id))
            if owner is None:
                reject(404, "ADVISOR_OBJECT_NOT_FOUND")
            ctx.ensure_tenant(owner)
            continue
        table_name = owners.get(key)
        if table_name is None or table_name not in Base.metadata.tables:
            reject(403, "ADVISOR_OBJECT_UNAVAILABLE")
        table = Base.metadata.tables[table_name]
        if table.c.id.type.python_type is int:
            try:
                value = int(value)
            except (TypeError, ValueError):
                reject(422, "ADVISOR_INVALID_OBJECT_ID")
        owner = await session.scalar(select(table.c.tenant_id).where(table.c.id == value))
        if owner is None:
            reject(404, "ADVISOR_OBJECT_NOT_FOUND")
        ctx.ensure_tenant(owner)
