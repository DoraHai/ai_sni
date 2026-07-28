"""自定义角色管理（账号与权限页 · 角色 tab）。需 settings.accounts edit。

权限点 = 菜单（app/permissions.py），每个角色对每个菜单授 view/edit。内置角色不可删；
「管理员」不可移除 settings.accounts edit（防锁死管理入口）。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Role, User
from app.permissions import MENUS, normalize_permissions
from app.security.auth import require_admin

router = APIRouter(
    prefix="/api/v1/roles",
    tags=["角色管理"],
    dependencies=[Depends(require_admin)],
)

ADMIN_ROLE = "管理员"


def _payload(r: Role, user_counts: dict[int, int]) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "permissions": r.permissions or {},
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
    role_id: int, req: UpdateRoleRequest, session: AsyncSession = Depends(get_session)
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
        # 防锁死：管理员角色必须保留账号与权限的编辑权
        if role.name == ADMIN_ROLE and perms.get("settings.accounts") != "edit":
            raise HTTPException(400, "「管理员」角色必须保留账号与权限的编辑权")
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
