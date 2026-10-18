"""登录态鉴权 + 自定义角色菜单级 RBAC。

- 前端登录走 JWT（token 只存 user id，角色/权限每次请求从库读 → 改权限即时生效、无需重登）。
- 脚本/curl/调度走 admin API Key 兜底 = 超级管理员（所有菜单 edit）。
- 业务路由用 require_scoped_auth：按请求路径反查菜单键 + HTTP 方法定 view/edit，校验当前
  角色权限；并按 query 的 tenant_id 做单客户隔离（绑定了 tenant 的账号只能看该客户）。

⚠️ 部署：Nginx 反代 /api 不能注入 X-API-Key（否则全请求被当超管，角色控制失效）。
"""
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Query, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_metering import bind_identity, bind_tenant
from app.config import get_settings
from app.database import get_session
from app.module_scope import ensure_module_access
from app.models.role import Role
from app.models.user import User
from app.security.api_key import resolve_api_key
from app.security.sem_identity import ensure_sem_identity_access
from app.permissions import OPERATOR_PERMS, effective_role_permissions
from app.security.advisor_scope import (AdvisorScope, account_locked, active_grants, deny,
                                        is_advisor, read_grants)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

JWT_ALG = "HS256"
_READ_METHODS = ("GET", "HEAD", "OPTIONS")

# 这些路径会读取或操作 SEM 客户数据。客户与模块管理、授权入口和 SEO/GEO 路径故意不在
# 列表中，确保管理员仍能查看冲突并完成修复，同时不跨模块扩大影响。
_SEM_IDENTITY_GUARDED_PREFIXES = (
    "/api/v1/dashboard",
    "/api/v1/alerts",
    "/api/v1/customer-profile",
    "/api/v1/keywords",
    "/api/v1/structure",
    "/api/v1/suggestions",
    "/api/v1/expansion",
    "/api/v1/search-terms",
    "/api/v1/negative-words",
    "/api/v1/operation-records",
    "/api/v1/adjustment-verify",
    "/api/v1/leads",
    "/api/v1/assistant",
    "/api/v1/reports",
    "/api/v1/writeback",
    "/api/v1/manage",
    "/api/v1/ocpc",
    "/api/v1/onboarding-builder",
    "/api/v1/sem/assets/accounts",
    "/api/v1/admin/fetch-keyword-report",
    "/api/v1/admin/sync-keywords",
    "/api/v1/admin/refresh-keyword-workbench",
    "/api/v1/admin/sync-operation-records",
    "/api/v1/admin/sync-expansion",
    "/api/v1/admin/sync-url-words",
)


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except ValueError:
        return False


def _jwt_secret() -> str:
    s = get_settings()
    return s.jwt_secret or s.admin_api_key


def issue_token(user: User, *, switch_source_id: int | None = None,
                switch_group_id: str | None = None, root_source_id: int | None = None,
                auth_exp: int | None = None, advisor: bool = False,
                tenant_id: int | None = None, grant_id: int | None = None) -> str:
    """token 只放 user id + 过期（角色/权限运行时从库读，便于即时生效）。"""
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "exp": now + timedelta(hours=s.jwt_expire_hours),
               "iat": int(now.timestamp())}
    if advisor:
        expires = int((now + timedelta(hours=s.jwt_expire_hours)).timestamp())
        if tenant_id is None:
            payload.update(scope_kind="advisor_identity", aud="advisor-session", exp=expires)
        else:
            if (type(tenant_id) is not int or tenant_id <= 0 or type(grant_id) is not int
                    or grant_id <= 0 or type(auth_exp) is not int or auth_exp <= now.timestamp()):
                raise ValueError("无效的顾问客户会话")
            payload.update(scope_kind="advisor_tenant", aud="advisor-business", tid=tenant_id,
                           gid=grant_id, auth_exp=auth_exp, exp=min(expires, auth_exp))
    if switch_source_id is not None:
        if root_source_id is None or auth_exp is None or auth_exp <= now.timestamp():
            raise ValueError("切换会话缺少有效的原登录信息")
        payload.update(via="advisor_switch", src=switch_source_id, grp=switch_group_id,
                       root_src=root_source_id, auth_exp=auth_exp,
                       exp=min(int((now + timedelta(hours=2)).timestamp()), auth_exp))
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALG)


@dataclass
class AuthContext:
    """当前访问者。api_key 兜底 = 超管（所有菜单 edit）。"""

    user_id: int | None
    username: str
    role_name: str
    tenant_id: int | None  # 绑定的单客户；None=全客户
    permissions: dict[str, str] = field(default_factory=dict)  # {菜单key: view|edit}
    is_superadmin: bool = False  # API Key 兜底
    advisor_scope: AdvisorScope | None = None
    auth_exp: int | None = None

    def can_view(self, *keys: str) -> bool:
        if self.is_superadmin:
            return True
        return any(self.permissions.get(k) in ("view", "edit") for k in keys)

    def can_edit(self, *keys: str) -> bool:
        if self.is_superadmin:
            return True
        return any(self.permissions.get(k) == "edit" for k in keys)

    def ensure_tenant(self, tenant_id: int) -> None:
        """绑定了单客户的账号只能访问该客户的数据。"""
        if self.advisor_scope is not None:
            self.advisor_scope.ensure_tenant(tenant_id)
        if self.tenant_id is not None and self.tenant_id != tenant_id:
            raise HTTPException(403, "无权访问该客户的数据")
        bind_tenant(tenant_id)


# ===== 请求路径 → 菜单键 + 是否写 的映射（后端真鉴权） =====
_KW_DETAIL_RE = re.compile(r"^/api/v1/keywords/\d+(/category)?$")


def _required(path: str, method: str) -> tuple[set[str] | None, bool]:
    """返回 (可接受的菜单键集合 或 None=不限菜单, 是否需要 edit)。命中集合满足其一即可。"""
    edit = method not in _READ_METHODS
    p = path
    if p.startswith("/api/v1/admin/customers"):
        return {"settings.customers"}, True
    if p.startswith("/api/v1/sem/assets/accounts"):
        return {"sem.assets"}, edit
    if p.startswith("/api/v1/seo/sites"):
        return {"seo.assets"}, edit
    if p.startswith("/api/v1/geo/projects"):
        return {"geo.assets"}, edit

    if p.startswith("/api/v1/dashboard"):
        return {"monitor.dashboard"}, edit
    if p.startswith("/api/v1/alerts"):
        return {"monitor.alerts"}, edit
    if p.startswith("/api/v1/customer-profile"):
        return {"monitor.profile"}, edit
    if _KW_DETAIL_RE.match(p):
        # /keywords/{id} 详情下钻：任一盯盘/工作台可见即可；/category 改分级算工作台写
        if p.endswith("/category"):
            return {"optimize.keywords"}, edit
        return {"monitor.dashboard", "monitor.alerts", "optimize.keywords"}, edit
    if (
        p.startswith("/api/v1/keywords")
        or p.startswith("/api/v1/structure")
        or p.startswith("/api/v1/suggestions")
    ):
        return {"optimize.keywords"}, edit
    if p.startswith("/api/v1/expansion"):
        return {"optimize.expand"}, edit
    if p.startswith("/api/v1/search-terms"):
        return {"optimize.searchterms"}, edit
    if p.startswith("/api/v1/negative"):
        return {"optimize.negatives"}, edit
    if p.startswith("/api/v1/operation-records"):
        return {"verify.adjustments"}, edit
    if p.startswith("/api/v1/adjustment-verify"):
        return {"verify.pending"}, edit
    if p.startswith("/api/v1/leads"):
        return {"verify.leads"}, edit
    if p.startswith("/api/v1/assistant"):
        # 对话/记忆都算"使用助手"(读性质，非编辑配置)，view 即可，POST 也不要求 edit
        return {"assistant"}, False
    if p == "/api/v1/geo/tenants":
        # GEO 顶部客户切换器是所有 GEO 工作台的公共只读数据源。
        return {"geo.assets", "geo.content", "geo.diagnosis"}, False
    if p.startswith("/api/v1/geo/audits"):
        # 运行诊断、生成建议和资产都属于使用 GEO 工具，view 权限即可。
        return {"geo.diagnosis"}, False
    if (
        p.startswith("/api/v1/geo/prompts")
        or p.startswith("/api/v1/geo/facts")
        or p.startswith("/api/v1/geo/content-tasks")
        or p.startswith("/api/v1/geo/content-health")
        or p.startswith("/api/v1/geo/content-brief-catalog")
        or p.startswith("/api/v1/geo/content-stats")
        or p.startswith("/api/v1/geo/answer-snapshots")
        or p.startswith("/api/v1/geo/visibility-patrol")
        or p.startswith("/api/v1/geo/tracking-engines")
        or p.startswith("/api/v1/geo/media-placements")
        or p.startswith("/api/v1/geo/channel-profiles")
        or p.startswith("/api/v1/geo/publishing-channel-options")
        or p.startswith("/api/v1/geo/publishing-channels")
        or p.startswith("/api/v1/geo/channel-accounts")
        or p.startswith("/api/v1/geo/citation-insights")
        or p.startswith("/api/v1/geo/competitor-insights")
        or p.startswith("/api/v1/geo/evaluation-insights")
        or p.startswith("/api/v1/geo/visibility-period-diff")
        or p.startswith("/api/v1/geo/deliverables")
        or p.startswith("/api/v1/geo/optimization-businesses")
        or p.startswith("/api/v1/geo/optimization-units")
        or p.startswith("/api/v1/geo/daily-metrics")
        or p.startswith("/api/v1/geo/oauth/social")
        or p.startswith("/api/v1/geo/channel-accounts")
        or p.startswith("/api/v1/geo/ops-alerts")
        or p.startswith("/api/v1/geo/competitor-reports")
        or p.startswith("/api/v1/geo/onboarding")
        or p.startswith("/api/v1/geo/weekly-insights")
        or p.startswith("/api/v1/geo/topic-heat")
        or p.startswith("/api/v1/geo/ai-trends")
        or p.startswith("/api/v1/geo/ai-settings")
        or p.startswith("/api/v1/geo/channel-polish-prompts")
        or p.startswith("/api/v1/geo/gap-workbench")
        or p.startswith("/api/v1/geo/optimization-periods")
        or p.startswith("/api/v1/geo/metrics")
        or p.startswith("/api/v1/geo/metric-dictionary")
        or p.startswith("/api/v1/geo/competitor-aliases")
        or p.startswith("/api/v1/geo/competitor-reports")
        or p.startswith("/api/v1/geo/onboarding")
        or p.startswith("/api/v1/geo/async-jobs")
        or p.startswith("/api/v1/geo/monitoring-stance")
        or p.startswith("/api/v1/geo/attribution")
    ):
        return {"geo.content"}, edit
    if p.startswith("/api/v1/geo"):
        return {"geo.diagnosis"}, False
    if p.startswith("/api/v1/seo/overview"):
        return {"seo.dashboard"}, edit
    if p.startswith("/api/v1/seo/alerts"):
        return {"seo.alerts"}, edit
    if p.startswith("/api/v1/seo/keywords") or p.startswith("/api/v1/seo/rank"):
        return {"seo.keywords"}, edit
    if p.startswith("/api/v1/seo/content"):
        return {"seo.content"}, edit
    if p.startswith("/api/v1/seo/site"):
        return {"seo.site"}, edit
    if p.startswith("/api/v1/seo/internal-links") or p.startswith("/api/v1/seo/backlinks"):
        return {"seo.links"}, edit
    if p.startswith("/api/v1/seo/competitors"):
        return {"seo.competitors"}, edit
    if p.startswith("/api/v1/onboarding-builder"):
        # 生成草案可查看；执行草案即使处于演练模式也会落内部台账，必须有编辑权。
        return {"onboarding"}, p.endswith("/apply")
    if p == "/api/v1/oauth/baidu/authorize" and edit:
        # 普通接入由 onboarding 控制，客户定向重绑由 settings.customers 控制；
        # 具体是哪一种必须由 endpoint 根据请求体再次做最小权限校验。
        return {"onboarding", "settings.customers"}, True
    if p == "/api/v1/oauth/baidu/status" and not edit:
        return {"onboarding", "settings.customers"}, False
    if p.startswith("/api/v1/oauth/baidu"):
        # 查看授权状态需 view；发起/更新授权需 edit。
        return {"onboarding"}, edit
    if p == "/api/v1/writeback/mode":
        # 关键词页和效果验证页都需要读取当前租户的门禁摘要；任一只读权限即可。
        return {"optimize.keywords", "verify.adjustments"}, False
    if p.startswith("/api/v1/writeback"):
        # 回写台账（只读查询）归效果验证。回写动作本身走 /keywords/{id}/writeback（optimize.keywords edit）
        return {"verify.adjustments"}, edit
    if p.startswith("/api/v1/manage/account-budget"):
        return {"manage.account"}, edit
    if p.startswith("/api/v1/manage/adgroup"):
        return {"manage.adgroups"}, edit
    if p.startswith("/api/v1/manage"):
        return {"manage.campaigns"}, edit
    if p.startswith("/api/v1/ocpc"):
        return {"manage.ocpc"}, edit
    if p.startswith("/api/v1/reports"):
        return {"delivery.report"}, edit
    if p.startswith("/api/v1/users") or p.startswith("/api/v1/roles"):
        return {"settings.accounts"}, edit
    # admin 运维接口：归到相关菜单的 edit（操作员从对应页触发）
    if p.startswith("/api/v1/admin/sync-expansion") or p.startswith(
        "/api/v1/admin/sync-url-words"
    ):
        return {"optimize.expand"}, True
    if p.startswith("/api/v1/admin/sync-keywords") or p.startswith(
        "/api/v1/admin/refresh-keyword-workbench"
    ):
        return {"optimize.keywords"}, True
    if p.startswith("/api/v1/admin/sync-operation-records"):
        return {"verify.adjustments"}, True
    if p.startswith("/api/v1/admin"):
        return {"settings.accounts"}, True
    return None, edit  # 未登记路径（如 /auth/*）：不做菜单校验，仅需登录


async def _build_context(user: User, session: AsyncSession, payload: dict | None = None) -> AuthContext:
    role = await session.get(Role, user.role_id, populate_existing=True)
    perms = (
        effective_role_permissions(role.name, role.is_system, role.permissions)
        if role else {}
    )
    advisor = is_advisor(role)
    rows = []
    # Trusted existing platform admins retain their branch. Fixed customers
    # retain their old bound restriction when the new table is not yet present.
    if advisor or not any(k.startswith("settings.") and v == "edit" for k, v in perms.items()):
        try:
            rows = await read_grants(session, user.id)
        except HTTPException:
            if advisor or user.tenant_id is None:
                raise
    scope = None
    tenant_id = user.tenant_id
    if advisor or rows:
        if not advisor:
            deny(403, "ADVISOR_ROLE_CHANGED", "顾问角色已变化，请管理员核对客户授权")
        active = await active_grants(session, rows)
        scope = AdvisorScope(frozenset(g.tenant_id for g in active))
        tenant_id = None
        claims = payload or {}
        kind = claims.get("scope_kind")
        if kind == "advisor_tenant":
            tid, gid = claims.get("tid"), claims.get("gid")
            if type(tid) is not int or tid <= 0 or type(gid) is not int or gid <= 0:
                deny(401, "ADVISOR_INVALID_TOKEN", "无效的客户凭证")
            grant = next((g for g in active if g.id == gid and g.tenant_id == tid), None)
            if grant is None:
                deny(401, "ADVISOR_GRANT_REVOKED", "客户授权已撤销，请重新选择客户")
            if user.tenant_id not in scope.tenant_ids:
                deny(403, "ADVISOR_DEFAULT_TENANT_INVALID", "默认客户与授权不一致，请管理员修复")
            scope = AdvisorScope(scope.tenant_ids, tid, gid)
            tenant_id = tid
        elif kind not in (None, "advisor_identity"):
            deny(401, "ADVISOR_INVALID_TOKEN", "无效的顾问凭证类型")
    elif payload and payload.get("scope_kind") is not None:
        deny(401, "ADVISOR_ROLE_CHANGED", "顾问角色已变化，请重新登录")
    return bind_identity(AuthContext(
        user_id=user.id,
        username=user.username,
        role_name=role.name if role else "?",
        tenant_id=tenant_id,
        permissions=perms,
        advisor_scope=scope,
        auth_exp=(payload or {}).get("auth_exp", (payload or {}).get("exp")),
    ))


async def require_auth(
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
    header_key: str | None = Security(_api_key_header),
    key: str | None = Query(None, description="旧版 API Key 查询参数；需服务端显式开启"),
    session: AsyncSession = Depends(get_session),
    request: Request = None,
) -> AuthContext:
    # 1) JWT（前端登录态）
    if bearer and bearer.credentials:
        try:
            # Verify signature/time first, then explicitly validate the audience
            # for every new scope; legacy non-advisor tokens have no audience.
            payload = jwt.decode(bearer.credentials, _jwt_secret(), algorithms=[JWT_ALG],
                                 options={"verify_aud": False})
            kind = payload.get("scope_kind")
            expected = {"advisor_identity": "advisor-session", "advisor_tenant": "advisor-business"}
            if kind is not None:
                if kind not in expected:
                    raise jwt.InvalidTokenError()
                payload = jwt.decode(bearer.credentials, _jwt_secret(), algorithms=[JWT_ALG],
                                     audience=expected[kind], options={"require": ["exp", "iat", "sub", "aud"]})
                if type(payload["exp"]) is not int or type(payload["iat"]) is not int:
                    raise jwt.InvalidTokenError()
                if kind == "advisor_tenant" and (type(payload.get("auth_exp")) is not int
                        or payload["exp"] > payload["auth_exp"]):
                    raise jwt.InvalidTokenError()
            elif "aud" in payload:
                raise jwt.InvalidTokenError()
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "登录已过期，请重新登录")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "登录凭证无效，请重新登录")
        try:
            sub = payload["sub"]
            if not isinstance(sub, str) or not sub.isascii() or not sub.isdecimal() or int(sub) <= 0:
                raise ValueError()
            user_id = int(sub)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(401, "登录凭证无效，请重新登录")
        user = await session.get(User, user_id, populate_existing=True)
        if user is None or not user.is_active or account_locked(user):
            raise HTTPException(401, "账号不存在或已停用")
        from app.security.advisor_switch import validate_switch_claims
        await validate_switch_claims(session, payload, user)
        ctx = await _build_context(user, session, payload)
        if ctx.advisor_scope is not None:
            from app.security.advisor_request import guard_advisor_request
            await guard_advisor_request(session, ctx, request, payload)
        return ctx

    # 2) admin API Key 兜底（curl / 冒烟 / 调度）
    settings = get_settings()
    provided = resolve_api_key(header_key, key)
    if provided and secrets.compare_digest(provided, settings.admin_api_key):
        # 未绑租户 = 运维超管（curl / 冒烟）。绑了租户则降为该客户运营，不再绕过 RBAC。
        bound = getattr(settings, "admin_api_key_tenant_id", None)
        if bound is not None:
            return bind_identity(AuthContext(
                user_id=None,
                username="api-key",
                role_name="租户运维密钥",
                tenant_id=int(bound),
                permissions=dict(OPERATOR_PERMS),
                is_superadmin=False,
            ))
        return bind_identity(AuthContext(
            user_id=None,
            username="api-key",
            role_name="超级管理员",
            tenant_id=None,
            is_superadmin=True,
        ))

    raise HTTPException(401, "未登录。请先登录，或通过 X-API-Key 提供管理密钥。")


async def require_scoped_auth(
    request: Request,
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    """业务路由统一鉴权：菜单权限（view/edit）+ 单客户隔离。"""
    keys, need_edit = _required(request.url.path, request.method)
    if keys is not None:
        ok = ctx.can_edit(*keys) if need_edit else ctx.can_view(*keys)
        if not ok:
            verb = "编辑" if need_edit else "访问"
            raise HTTPException(403, f"当前角色无权{verb}此功能")
    tenant_id_values: list[object] = []
    query_tid = request.query_params.get("tenant_id")
    path_tid = request.path_params.get("tenant_id")
    if query_tid is not None:
        tenant_id_values.extend(request.query_params.getlist("tenant_id"))
    if path_tid is not None:
        tenant_id_values.append(path_tid)
    if request.method not in _READ_METHODS:
        try:
            payload = await request.json()
        except (ValueError, RuntimeError):
            payload = None
        if isinstance(payload, dict) and "tenant_id" in payload:
            tenant_id_values.append(payload["tenant_id"])

    parsed_tenant_ids: list[int] = []
    for tid in tenant_id_values:
        if isinstance(tid, bool) or tid is None:
            raise HTTPException(422, "tenant_id 必须是整数")
        if isinstance(tid, float):
            if not tid.is_integer():
                raise HTTPException(422, "tenant_id 必须是整数")
            parsed_tenant_ids.append(int(tid))
        elif isinstance(tid, int):
            parsed_tenant_ids.append(tid)
        elif isinstance(tid, str) and tid.strip().lstrip("-").isdigit():
            parsed_tenant_ids.append(int(tid.strip()))
        else:
            raise HTTPException(422, "tenant_id 必须是整数")

    if len(set(parsed_tenant_ids)) > 1:
        raise HTTPException(422, "请求中的 tenant_id 不一致")
    if parsed_tenant_ids:
        tenant_id = parsed_tenant_ids[0]
        ctx.ensure_tenant(tenant_id)
        if request.url.path.startswith(_SEM_IDENTITY_GUARDED_PREFIXES):
            await ensure_module_access(session, ctx, tenant_id, "sem")
            await ensure_sem_identity_access(session, tenant_id)
    return ctx


async def require_admin(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    """全局账号/角色管理：仅未绑定客户的账号管理员可访问。"""
    if ctx.tenant_id is not None:
        raise HTTPException(403, "单客户账号不能管理全局账号与角色")
    if not ctx.can_edit("settings.accounts"):
        raise HTTPException(403, "仅有账号与权限管理权的角色可执行此操作")
    return ctx
