"""登录态 + 当前用户（含菜单权限）+ 租户列表（多客户切换器数据源）。"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models import BaiduAccount, Role, Tenant, TenantModule, User
from app.permissions import ALL_EDIT
from app.module_scope import list_module_tenants, module_is_available
from app.security.auth import (
    AuthContext,
    hash_password,
    issue_token,
    require_auth,
    verify_password,
)
from app.security.sem_identity import (
    load_sem_identity_states,
    public_sem_identity_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])


def _sem_account_payload(account: BaiduAccount) -> dict:
    return {
        "id": account.id,
        "username": account.baidu_username,
        "ucid": str(account.baidu_ucid),
        "auth_mode": account.auth_mode,
        "status": account.status,
        "sync_status": account.sync_status,
        "last_synced_at": (
            account.last_synced_at.isoformat() if account.last_synced_at else None
        ),
    }


async def _user_payload(u: User, session: AsyncSession) -> dict:
    role = await session.get(Role, u.role_id)
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "role_id": u.role_id,
        "role_label": role.name if role else "?",
        "permissions": (role.permissions or {}) if role else {},  # 前端按它渲染菜单/按钮
        "tenant_id": u.tenant_id,
    }


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


@router.post("/login")
async def login(req: LoginRequest, session: AsyncSession = Depends(get_session)) -> dict:
    settings = get_settings()
    now = datetime.utcnow()
    username = req.username.strip()
    # 行锁保证多个 worker 同时收到失败请求时不会丢失计数。
    user = await session.scalar(
        select(User).where(User.username == username).with_for_update()
    )
    # 用户不存在也走一次哈希校验，避免计时侧信道探测用户名
    ok = verify_password(req.password, user.password_hash if user else hash_password("x"))
    if user is not None and user.locked_until is not None and user.locked_until > now:
        logger.warning("登录被临时锁定账号拒绝: %s", username)
        raise HTTPException(401, "用户名或密码不正确")
    if user is None or not ok:
        if user is not None:
            window = timedelta(minutes=settings.login_failure_window_minutes)
            if user.last_failed_login_at is None or now - user.last_failed_login_at > window:
                user.failed_login_attempts = 0
            user.failed_login_attempts += 1
            user.last_failed_login_at = now
            if user.failed_login_attempts >= settings.login_max_failed_attempts:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                logger.warning("账号因连续登录失败被临时锁定: %s", username)
            await session.commit()
        logger.warning("登录失败: %s", username)
        raise HTTPException(401, "用户名或密码不正确")
    if not user.is_active:
        raise HTTPException(403, "账号已停用，请联系管理员")
    user.failed_login_attempts = 0
    user.last_failed_login_at = None
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    await session.commit()
    return {"token": issue_token(user), "user": await _user_payload(user, session)}


@router.get("/me")
async def me(
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if ctx.user_id is None:  # API Key 兜底访问者 = 超管，给全权限
        return {"user": {"id": None, "username": "api-key", "display_name": "API Key",
                         "role_id": None, "role_label": "超级管理员",
                         "permissions": ALL_EDIT, "tenant_id": None}}
    user = await session.get(User, ctx.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "账号不存在或已停用")
    return {"user": await _user_payload(user, session)}


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=100, description="至少 8 位")


@router.patch("/password")
async def change_password(
    req: ChangePasswordRequest,
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if ctx.user_id is None:
        raise HTTPException(400, "API Key 访问者没有密码可改")
    user = await session.get(User, ctx.user_id)
    if user is None or not verify_password(req.old_password, user.password_hash):
        raise HTTPException(403, "原密码不正确")
    user.password_hash = hash_password(req.new_password)
    await session.commit()
    return {"status": "ok"}


@router.get("/tenants")
async def list_tenants(
    module: str | None = Query(None, pattern="^(sem|seo|geo)$"),
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """多客户切换器数据。绑定了单客户的账号只回该客户；否则全部。"""
    if module:
        if not ctx.can_view(*_MODULE_PERMISSION_KEYS[module]):
            raise HTTPException(403, "当前账号无权访问该模块的客户列表")
        tenants = await list_module_tenants(session, ctx, module)
    else:
        cond = []
        if ctx.tenant_id is not None:
            cond.append(Tenant.id == ctx.tenant_id)
        tenants = list(
            (await session.scalars(select(Tenant).where(*cond).order_by(Tenant.id))).all()
        )
    include_sem_context = module == "sem" or (
        module is None and ctx.can_view("settings.customers")
    )
    tenant_ids = [tenant.id for tenant in tenants]
    accounts = (
        list(
            (
                await session.scalars(
                    select(BaiduAccount)
                    .where(
                        BaiduAccount.tenant_id.in_(tenant_ids),
                        BaiduAccount.status != "archived",
                    )
                    .order_by(BaiduAccount.tenant_id, BaiduAccount.id)
                )
            ).all()
        )
        if tenant_ids and include_sem_context
        else []
    )
    accounts_by_tenant: dict[int, list[dict]] = {}
    for account in accounts:
        accounts_by_tenant.setdefault(account.tenant_id, []).append(
            _sem_account_payload(account)
        )
    identity_states = await load_sem_identity_states(
        session, tenant_ids, tenant_accounts=accounts
    )
    return {
        "module": module,
        "tenants": [
            {
                "id": tenant.id,
                "name": tenant.name,
                **(
                    {
                        "sem_identity": public_sem_identity_state(identity_states.get(tenant.id)),
                        "sem_accounts": (
                            []
                            if identity_states.get(tenant.id, {}).get("status") == "blocked"
                            else accounts_by_tenant.get(tenant.id, [])
                        ),
                    }
                    if include_sem_context
                    else {}
                ),
            }
            for tenant in tenants
        ],
    }


_MODULE_PERMISSION_KEYS = {
    "sem": (
        "sem.assets", "assistant", "onboarding",
        "monitor.dashboard", "monitor.alerts", "monitor.profile",
        "optimize.expand", "optimize.keywords", "optimize.searchterms",
        "optimize.negatives", "verify.adjustments", "verify.pending",
        "verify.leads", "manage.account", "manage.campaigns",
        "manage.adgroups", "manage.ocpc", "delivery.report",
        "settings.customers",
    ),
    "seo": ("seo.assets", "seo.dashboard", "seo.keywords", "seo.content", "seo.site"),
    "geo": ("geo.assets", "geo.content", "geo.diagnosis"),
}


@router.get("/modules")
async def list_my_modules(
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Modules visible in the signed-in user's workspace and module switcher."""
    rows_by_code: dict[str, TenantModule] = {}
    if ctx.tenant_id is not None:
        rows = list(
            (
                await session.scalars(
                    select(TenantModule).where(TenantModule.tenant_id == ctx.tenant_id)
                )
            ).all()
        )
        rows_by_code = {row.module_code: row for row in rows}

    modules = []
    for code in ("sem", "seo", "geo"):
        permitted = ctx.can_view(*_MODULE_PERMISSION_KEYS[code])
        if ctx.tenant_id is not None:
            row = rows_by_code.get(code)
            available = bool(row and module_is_available(row) and permitted)
            modules.append(
                {
                    "module_code": code,
                    "status": row.status if row else "not_opened",
                    "available": available,
                    "expires_at": row.expires_at.isoformat() if row and row.expires_at else None,
                    "tenant_count": 1 if available else 0,
                }
            )
            continue

        tenants = await list_module_tenants(session, ctx, code)
        modules.append(
            {
                "module_code": code,
                "status": "active" if permitted else "no_permission",
                "available": permitted,
                "expires_at": None,
                "tenant_count": len(tenants),
            }
        )
    return {"tenant_id": ctx.tenant_id, "modules": modules}
