"""登录态 + 当前用户（含菜单权限）+ 租户列表（多客户切换器数据源）。"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Role, Tenant, User
from app.permissions import ALL_EDIT, OPERATOR_PERMS
from app.security.auth import (
    AuthContext,
    hash_password,
    issue_token,
    require_auth,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])


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
    user = await session.scalar(select(User).where(User.username == req.username.strip()))
    # 用户不存在也走一次哈希校验，避免计时侧信道探测用户名
    ok = verify_password(req.password, user.password_hash if user else hash_password("x"))
    if user is None or not ok:
        logger.warning("登录失败: %s", req.username)
        raise HTTPException(401, "用户名或密码不正确")
    if not user.is_active:
        raise HTTPException(403, "账号已停用，请联系管理员")
    user.last_login_at = datetime.utcnow()
    await session.commit()
    return {"token": issue_token(user), "user": await _user_payload(user, session)}


@router.get("/me")
async def me(
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if ctx.user_id is None:  # API Key：未绑租户=超管；绑了租户=运营权限且锁客户
        perms = dict(ctx.permissions) if ctx.permissions else (
            ALL_EDIT if ctx.is_superadmin else dict(OPERATOR_PERMS)
        )
        return {
            "user": {
                "id": None,
                "username": ctx.username or "api-key",
                "display_name": ctx.role_name or "API Key",
                "role_id": None,
                "role_label": ctx.role_name or "API Key",
                "permissions": perms,
                "tenant_id": ctx.tenant_id,
            }
        }
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
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """多客户切换器数据。绑定了单客户的账号只回该客户；否则全部。"""
    cond = []
    if ctx.tenant_id is not None:
        cond.append(Tenant.id == ctx.tenant_id)
    tenants = (
        await session.scalars(select(Tenant).where(*cond).order_by(Tenant.id))
    ).all()
    return {"tenants": [{"id": t.id, "name": t.name} for t in tenants]}


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    brand_terms: list[str] | None = None
    industry: str | None = Field(None, max_length=100)
    admin_username: str | None = Field(None, min_length=2, max_length=50)
    admin_password: str | None = Field(None, min_length=8, max_length=100)
    admin_display_name: str | None = Field(None, max_length=50)


@router.post("/tenants")
async def create_tenant(
    req: CreateTenantRequest,
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """运维新建客户（名称 + 品牌词，可选同时建绑定该客户的管理员账号）。"""
    if not ctx.can_edit("settings.accounts"):
        raise HTTPException(403, "仅有账号与权限管理权的角色可新建客户")
    if ctx.tenant_id is not None:
        raise HTTPException(403, "绑定了单客户的账号不能新建客户")
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "客户名称不能为空")
    existing = await session.scalar(select(Tenant).where(Tenant.name == name))
    if existing is not None:
        raise HTTPException(409, f"客户「{name}」已存在")
    terms = []
    for t in req.brand_terms or []:
        tt = str(t).strip()
        if tt and tt not in terms:
            terms.append(tt)
    tenant = Tenant(
        name=name,
        brand_terms=terms[:30] or None,
        industry=(req.industry or "").strip() or None,
    )
    session.add(tenant)
    await session.flush()

    user_out = None
    if req.admin_username and req.admin_password:
        uname = req.admin_username.strip()
        if await session.scalar(select(User).where(User.username == uname)):
            raise HTTPException(409, f"用户名「{uname}」已存在")
        admin_role = await session.scalar(select(Role).where(Role.name == "管理员"))
        if admin_role is None:
            admin_role = await session.scalar(select(Role).order_by(Role.id.asc()))
        if admin_role is None:
            raise HTTPException(400, "系统尚未配置角色，无法同时创建账号")
        user = User(
            username=uname,
            display_name=(req.admin_display_name or "").strip() or uname,
            password_hash=hash_password(req.admin_password),
            role_id=admin_role.id,
            tenant_id=tenant.id,
        )
        session.add(user)
        await session.flush()
        user_out = {"id": user.id, "username": user.username, "tenant_id": tenant.id}

    await session.commit()
    await session.refresh(tenant)
    return {
        "tenant": {"id": tenant.id, "name": tenant.name, "brand_terms": tenant.brand_terms or []},
        "admin_user": user_out,
        "next_paths": {
            "onboarding": "/geo/onboarding",
            "accounts": "/settings/accounts",
        },
    }
