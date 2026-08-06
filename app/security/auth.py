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

from app.config import get_settings
from app.database import get_session
from app.models.role import Role
from app.models.user import User

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

JWT_ALG = "HS256"
_READ_METHODS = ("GET", "HEAD", "OPTIONS")


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


def issue_token(user: User) -> str:
    """token 只放 user id + 过期（角色/权限运行时从库读，便于即时生效）。"""
    s = get_settings()
    payload = {
        "sub": str(user.id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=s.jwt_expire_hours),
    }
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
        if self.tenant_id is not None and self.tenant_id != tenant_id:
            raise HTTPException(403, "无权访问该客户的数据")


# ===== 请求路径 → 菜单键 + 是否写 的映射（后端真鉴权） =====
_KW_DETAIL_RE = re.compile(r"^/api/v1/keywords/\d+(/category)?$")


def _required(path: str, method: str) -> tuple[set[str] | None, bool]:
    """返回 (可接受的菜单键集合 或 None=不限菜单, 是否需要 edit)。命中集合满足其一即可。"""
    edit = method not in _READ_METHODS
    p = path

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
    ):
        return {"geo.content"}, edit
    if p.startswith("/api/v1/geo"):
        return {"geo.diagnosis"}, False
    if p.startswith("/api/v1/onboarding-builder"):
        # 智能搭建默认演练写入，仍归首次接入；真实写入由后端 dry-run 开关兜底。
        return {"onboarding"}, False
    if p.startswith("/api/v1/writeback"):
        # 回写台账（只读查询）归效果验证。回写动作本身走 /keywords/{id}/writeback（optimize.keywords edit）
        return {"verify.adjustments"}, edit
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


async def _build_context(user: User, session: AsyncSession) -> AuthContext:
    role = await session.get(Role, user.role_id)
    perms = dict(role.permissions or {}) if role else {}
    return AuthContext(
        user_id=user.id,
        username=user.username,
        role_name=role.name if role else "?",
        tenant_id=user.tenant_id,
        permissions=perms,
    )


async def require_auth(
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
    header_key: str | None = Security(_api_key_header),
    key: str | None = Query(None, description="API Key，与 X-API-Key 等价（脚本用）"),
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    # 1) JWT（前端登录态）
    if bearer and bearer.credentials:
        try:
            payload = jwt.decode(bearer.credentials, _jwt_secret(), algorithms=[JWT_ALG])
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "登录已过期，请重新登录")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "登录凭证无效，请重新登录")
        user = await session.get(User, int(payload["sub"]))
        if user is None or not user.is_active:
            raise HTTPException(401, "账号不存在或已停用")
        return await _build_context(user, session)

    # 2) admin API Key 兜底（curl / 冒烟 / 调度）= 超管
    provided = header_key or key
    if provided and secrets.compare_digest(provided, get_settings().admin_api_key):
        return AuthContext(
            user_id=None, username="api-key", role_name="超级管理员",
            tenant_id=None, is_superadmin=True,
        )

    raise HTTPException(401, "未登录。请先登录，或通过 X-API-Key 提供管理密钥。")


async def require_scoped_auth(
    request: Request,
    ctx: AuthContext = Depends(require_auth),
) -> AuthContext:
    """业务路由统一鉴权：菜单权限（view/edit）+ 单客户隔离。"""
    keys, need_edit = _required(request.url.path, request.method)
    if keys is not None:
        ok = ctx.can_edit(*keys) if need_edit else ctx.can_view(*keys)
        if not ok:
            verb = "编辑" if need_edit else "访问"
            raise HTTPException(403, f"当前角色无权{verb}此功能")
    tid = request.query_params.get("tenant_id")
    if tid and tid.lstrip("-").isdigit():
        ctx.ensure_tenant(int(tid))
    return ctx


async def require_admin(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    """账号/角色管理：需 settings.accounts edit。"""
    if not ctx.can_edit("settings.accounts"):
        raise HTTPException(403, "仅有账号与权限管理权的角色可执行此操作")
    return ctx
