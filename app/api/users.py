"""账号管理（账号与权限页 · 账号 tab）。需 settings.accounts edit。

角色由 role_id 指向 roles 表（自定义角色）；tenant_id = 限定单客户（可选，独立于角色）。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Role, Tenant, User
from app.security.auth import AuthContext, hash_password, require_admin

router = APIRouter(
    prefix="/api/v1/users",
    tags=["账号管理"],
    dependencies=[Depends(require_admin)],
)


def _payload(u: User, role_names: dict[int, str], tenant_names: dict[int, str]) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "role_id": u.role_id,
        "role_label": role_names.get(u.role_id, "?"),
        "tenant_id": u.tenant_id,
        "tenant_name": tenant_names.get(u.tenant_id),
        "is_active": u.is_active,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.get("")
async def list_users(session: AsyncSession = Depends(get_session)) -> dict:
    users = (await session.scalars(select(User).order_by(User.id))).all()
    role_names = {r.id: r.name for r in (await session.scalars(select(Role))).all()}
    tenant_names = {t.id: t.name for t in (await session.scalars(select(Tenant))).all()}
    return {
        "users": [_payload(u, role_names, tenant_names) for u in users],
        "role_options": [{"id": rid, "label": name} for rid, name in role_names.items()],
    }


async def _check_tenant(session: AsyncSession, tenant_id: int | None) -> None:
    if tenant_id is not None and await session.get(Tenant, tenant_id) is None:
        raise HTTPException(404, "绑定的客户不存在")


async def _check_role(session: AsyncSession, role_id: int) -> None:
    if await session.get(Role, role_id) is None:
        raise HTTPException(404, "指定的角色不存在")


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=8, max_length=100)
    display_name: str | None = Field(None, max_length=50)
    role_id: int
    tenant_id: int | None = None  # 可选：限定单客户


@router.post("")
async def create_user(
    req: CreateUserRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    await _check_role(session, req.role_id)
    await _check_tenant(session, req.tenant_id)
    if await session.scalar(select(User).where(User.username == req.username.strip())):
        raise HTTPException(409, "用户名已存在")
    user = User(
        username=req.username.strip(),
        display_name=req.display_name,
        password_hash=hash_password(req.password),
        role_id=req.role_id,
        tenant_id=req.tenant_id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return {"status": "ok", "id": user.id}


class UpdateUserRequest(BaseModel):
    is_active: bool | None = None
    role_id: int | None = None
    tenant_id: int | None = None
    clear_tenant: bool = False  # True=解除单客户绑定（改回全客户）
    display_name: str | None = Field(None, max_length=50)
    new_password: str | None = Field(None, min_length=8, max_length=100)


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    req: UpdateUserRequest,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_admin),
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    if req.is_active is False and user.id == ctx.user_id:
        raise HTTPException(400, "不能停用自己的账号")
    if req.role_id is not None:
        await _check_role(session, req.role_id)
        user.role_id = req.role_id
    if req.clear_tenant:
        user.tenant_id = None
    elif req.tenant_id is not None:
        await _check_tenant(session, req.tenant_id)
        user.tenant_id = req.tenant_id
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.new_password:
        user.password_hash = hash_password(req.new_password)
    await session.commit()
    return {"status": "ok"}
