"""自定义角色管理（账号与权限页 · 角色 tab）。需 settings.accounts edit。

权限点 = 菜单（app/permissions.py），每个角色对每个菜单授 view/edit。内置角色不可删；
受信任的内置「管理员」不可移除两项平台管理编辑权。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Role, User
from app.permissions import (
    ADMIN_ROLE_NAME,
    MENUS,
    effective_role_permissions,
    has_full_platform_admin,
    normalize_permissions,
)
from app.security.auth import AuthContext, require_admin

router = APIRouter(
    prefix="/api/v1/roles",
    tags=["角色管理"],
    dependencies=[Depends(require_admin)],
)

def _payload(r: Role, user_counts: dict[int, int]) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "permissions": effective_role_permissions(r.name, r.is_system, r.permissions),
        "is_system": r.is_system,
        "user_count": user_counts.get(r.id, 0),
    }


@router.get("")
async def list_roles(session: AsyncSession = Depends(get_session)) -> dict:
    roles = (await session.scalars(select(Role).order_by(Role.id))).all()
    counts = {
        rid: int(n)
        for rid, n in (
            await session.execute(select(User.role_id, func.count()).group_by(User.role_id))
        ).all()
    }
    return {
        "roles": [_payload(r, counts) for r in roles],
        "menus": MENUS,  # 前端权限矩阵渲染用
    }


class RoleRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str | None = Field(None, max_length=200)
    permissions: dict = Field(default_factory=dict)  # {菜单key: view|edit}


@router.post("")
async def create_role(req: RoleRequest, session: AsyncSession = Depends(get_session)) -> dict:
    name = req.name.strip()
    if await session.scalar(select(Role).where(Role.name == name)):
        raise HTTPException(409, "角色名已存在")
    role = Role(
        name=name,
        description=req.description,
        permissions=normalize_permissions(req.permissions),
        is_system=False,
    )
    session.add(role)
    await session.commit()
    await session.refresh(role)
    return {"status": "ok", "id": role.id}


class UpdateRoleRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=50)
    description: str | None = Field(None, max_length=200)
    permissions: dict | None = None


@router.patch("/{role_id}")
async def update_role(
    role_id: int,
    req: UpdateRoleRequest,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_admin),
) -> dict:
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(404, "角色不存在")
    if req.name is not None and req.name.strip() != role.name:
        if role.is_system:
            raise HTTPException(400, "内置角色不可改名")
        if await session.scalar(select(Role).where(Role.name == req.name.strip())):
            raise HTTPException(409, "角色名已存在")
        role.name = req.name.strip()
    if req.description is not None:
        role.description = req.description
    if req.permissions is not None:
        perms = normalize_permissions(req.permissions)
        trusted_admin = role.is_system and role.name == ADMIN_ROLE_NAME
        if trusted_admin and not has_full_platform_admin(perms):
            raise HTTPException(400, "内置管理员必须保留客户与账号两项平台管理编辑权")

        current = effective_role_permissions(role.name, role.is_system, role.permissions)
        actor = await session.get(User, ctx.user_id) if ctx.user_id is not None else None
        if actor is not None and actor.role_id == role.id and perms.get("settings.accounts") != "edit":
            raise HTTPException(400, "不能移除当前账号管理角色所需的账号编辑权")
        if (
            actor is not None
            and actor.role_id == role.id
            and has_full_platform_admin(current)
            and not has_full_platform_admin(perms)
        ):
            raise HTTPException(400, "不能让当前账号失去平台管理能力")

        if has_full_platform_admin(current) and not has_full_platform_admin(perms):
            roles = list((await session.scalars(select(Role))).all())
            full_role_ids = {
                item.id
                for item in roles
                if item.id != role.id
                and has_full_platform_admin(
                    effective_role_permissions(item.name, item.is_system, item.permissions)
                )
            }
            has_other = False
            if full_role_ids:
                has_other = bool(
                    await session.scalar(
                        select(func.count())
                        .select_from(User)
                        .where(
                            User.role_id.in_(full_role_ids),
                            User.is_active.is_(True),
                            User.tenant_id.is_(None),
                        )
                    )
                )
            if not has_other:
                raise HTTPException(400, "不能移除最后一个平台管理员角色的完整权限")
        role.permissions = perms
    await session.commit()
    return {"status": "ok"}


@router.delete("/{role_id}")
async def delete_role(role_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(404, "角色不存在")
    if role.is_system:
        raise HTTPException(400, "内置角色不可删除")
    n = await session.scalar(
        select(func.count()).select_from(User).where(User.role_id == role_id)
    )
    if n:
        raise HTTPException(400, f"该角色下还有 {n} 个账号，请先改派后再删除")
    await session.delete(role)
    await session.commit()
    return {"status": "ok"}
