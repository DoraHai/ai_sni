"""SEM request boundary. Unreviewed advisor actions remain closed."""
import re

from sqlalchemy import select

from app.models import BaiduAccount, Keyword, Campaign, Adgroup
from app.module_scope import ensure_module_access
from app.security.advisor_scope import deny


SESSION_ROUTES = frozenset({
    ("GET", "/api/v1/auth/me"), ("GET", "/api/v1/auth/tenants"),
    ("POST", "/api/v1/auth/select-tenant"), ("PATCH", "/api/v1/auth/password"),
    ("GET", "/api/v1/auth/linked-accounts"),
    ("POST", "/api/v1/auth/switch-account"),
})

# Exact reviewed read routes; a future route does not become advisor-accessible
# merely by sharing a prefix or adding a query tenant_id.
SEM_READ_ROUTES = re.compile(
    r"/api/v1/(?:keywords(?:/export|/cockpit(?:/[0-9]+)?|/[0-9]+)?"
    r"|reports/(?:analysis(?:/export)?|monthly(?:/export|/available-months)?)"
    r"|manage/(?:region-options|account-budget|campaigns|adgroups)"
    r"|structure/(?:campaigns|adgroups)"
    r"|writeback(?:/mode|/approvals|/queue)?"
    r"|dashboard|alerts|customer-profile|suggestions|search-terms|negative-words"
    r"|operation-records|adjustment-verify|leads)"
)


def tenant_values(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "tenant_id":
                yield item
            else:
                yield from tenant_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from tenant_values(item)


def positive_id(value):
    if type(value) is int and 0 < value <= 2**63 - 1:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and 0 < int(value) <= 2**63 - 1:
        return int(value)
    deny(422, "ADVISOR_INVALID_TENANT", "客户和对象 ID 必须是正整数")


async def guard_advisor_request(session, ctx, request, payload):
    if request is None:
        deny(409, "ADVISOR_TENANT_SELECTION_REQUIRED", "顾问请求必须提供明确会话路径")
    path = request.url.path.rstrip("/")
    method = request.method
    scope = ctx.advisor_scope
    if (method, path) in SESSION_ROUTES:
        return
    scope.ensure_tenant(scope.tenant_id)
    if payload.get("scope_kind") != "advisor_tenant":
        deny(409, "ADVISOR_TENANT_SELECTION_REQUIRED", "请先切换客户")
    # Every duplicate and nested tenant assertion is checked, even when the
    # handler uses only the final query argument.
    values = request.query_params.getlist("tenant_id")
    values += list(tenant_values(request.path_params))
    if method not in ("GET", "HEAD", "OPTIONS"):
        try:
            values += list(tenant_values(await request.json()))
        except (ValueError, RuntimeError):
            pass
    for value in values:
        scope.ensure_tenant(positive_id(value))
    if method not in ("GET", "HEAD"):
        # No new task columns or unreviewed final-side-effect serialization.
        # The separate high-risk flag is deliberately insufficient to enable
        # endpoints whose grant binding has not yet been reviewed.
        deny(403, "ADVISOR_HIGH_RISK_WRITES_DISABLED", "顾问写入和后台任务尚未开放")
    if path == "/api/v1/auth/modules":
        return
    if SEM_READ_ROUTES.fullmatch(path) is None:
        deny(403, "ADVISOR_ROUTE_NOT_AVAILABLE", "此功能尚未开放顾问客户访问")
    from app.security.auth import _required
    keys, edit = _required(path, method)
    if keys is None or not (ctx.can_edit(*keys) if edit else ctx.can_view(*keys)):
        deny(403, "ADVISOR_MENU_FORBIDDEN", "当前角色无权访问此功能")
    if not values and path != "/api/v1/manage/region-options":
        deny(403, "ADVISOR_TENANT_NOT_GRANTED", "业务请求必须指定当前客户")
    await ensure_module_access(session, ctx, scope.tenant_id, "sem")
    # Natural Baidu object IDs are tenant-qualified, unlike local row PKs.
    objects = [("baidu_account_id", BaiduAccount, BaiduAccount.id),
               ("campaign_id", Campaign, Campaign.campaign_id),
               ("adgroup_id", Adgroup, Adgroup.adgroup_id),
               ("keyword_id", Keyword, Keyword.keyword_id)]
    for name, model, column in objects:
        ids = request.query_params.getlist(name)
        if name in request.path_params:
            ids.append(request.path_params[name])
        for raw in ids:
            ident = positive_id(raw)
            owner = await session.scalar(select(model.tenant_id).where(
                column == ident, model.tenant_id == scope.tenant_id))
            if owner is None:
                deny(403, "ADVISOR_TENANT_NOT_GRANTED", "对象不属于当前客户")
            ctx.ensure_tenant(owner)
