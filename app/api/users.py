"""账号管理（账号与权限页 · 账号 tab）。需 settings.accounts edit。

角色由 role_id 指向 roles 表（自定义角色）；tenant_id = 限定单客户（可选，独立于角色）。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.config import get_settings
from app.models import Role, Tenant, User
from app.permissions import PLATFORM_ADMIN_KEYS, effective_role_permissions
from app.security.auth import AuthContext, hash_password, require_admin
from app.platform_operations import audit_business
from app.security.advisor_scope import is_advisor, deny, read_grants, active_grants
from app.security.advisor_management import (TenantId, grants_version, lock_named_admin,
                                            save_grants, validate_tenants)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/users",
    tags=["账号管理"],
    dependencies=[Depends(require_admin)],
)


def _audit_state(user):
    return {key: getattr(user, key) for key in ('id', 'username', 'display_name', 'role_id', 'tenant_id', 'is_active')}


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


async def _account_payload(session, user, role, tenant_names, rows=None):
    advisor = is_advisor(role)
    unavailable = False
    if advisor and rows is None:
        try:
            rows = await read_grants(session, user.id)
        except HTTPException as error:
            if error.status_code != 503:
                raise
            # This is a named/admin-only account projection, never a business
            # authorization fallback. No writable version is issued until the
            # grant table is readable; grant mutation paths still fail closed.
            unavailable = True
    active = await active_grants(session, rows or []) if advisor else []
    result = _payload(user, {user.role_id: role.name if role else "?"}, tenant_names)
    result.update(is_advisor=advisor, tenant_ids=sorted(g.tenant_id for g in active),
                  default_tenant_id=user.tenant_id,
                  grants_version=grants_version(user.tenant_id, rows or []) if advisor and not unavailable else None)
    if unavailable:
        result.update(grants_available=False, grants_error_code="ADVISOR_GRANTS_UNAVAILABLE")
    return result


def _require_multi_tenant():
    if not get_settings().advisor_multi_tenant_enabled:
        deny(422, "ADVISOR_MULTI_TENANT_DISABLED", "顾问多客户功能尚未开放")


@router.get("")
async def list_users(session: AsyncSession = Depends(get_session)) -> dict:
    users = (await session.scalars(select(User).order_by(User.id))).all()
    roles = {r.id: r for r in (await session.scalars(select(Role))).all()}
    role_names = {rid: r.name for rid, r in roles.items()}
    tenant_names = {t.id: t.name for t in (await session.scalars(select(Tenant))).all()}
    return {
        "users": [await _account_payload(session, u, roles.get(u.role_id), tenant_names) for u in users],
        "role_options": [{"id": rid, "label": name} for rid, name in role_names.items()],
        "tenant_options": [
            {"id": tenant_id, "name": name}
            for tenant_id, name in tenant_names.items()
        ],
    }


@router.get("/{user_id}")
async def get_user(user_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    role = await session.get(Role, user.role_id)
    tenant_names = {t.id: t.name for t in (await session.scalars(select(Tenant))).all()}
    return await _account_payload(session, user, role, tenant_names)


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
    tenant_ids: list[TenantId] | None = Field(None, max_length=1000)
    default_tenant_id: TenantId | None = None


@router.post("")
async def create_user(
    req: CreateUserRequest, session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_admin),
) -> dict:
    await _check_role(session, req.role_id)
    role = await session.get(Role, req.role_id)
    advisor = is_advisor(role)
    supplied = bool(req.model_fields_set & {"tenant_ids", "default_tenant_id"})
    if supplied and not advisor:
        deny(422, "TENANT_IDS_ONLY_FOR_ADVISOR", "只有顾问账号可以设置多个客户")
    ids = None
    if advisor:
        _require_multi_tenant()
        await lock_named_admin(session, ctx)
        if not req.tenant_ids:
            deny(422, "ADVISOR_TENANTS_REQUIRED", "至少勾选 1 个客户")
        default_id = req.default_tenant_id if req.default_tenant_id is not None else req.tenant_ids[0]
        ids = await validate_tenants(session, req.tenant_ids, default_id, role)
        if req.tenant_id is not None and req.tenant_id != default_id:
            deny(422, "ADVISOR_DEFAULT_TENANT_INVALID", "默认客户字段不一致")
    else:
        default_id = req.tenant_id
        await _check_tenant(session, req.tenant_id)
    if await session.scalar(select(User).where(User.username == req.username.strip())):
        raise HTTPException(409, "用户名已存在")
    user = User(
        username=req.username.strip(),
        display_name=req.display_name,
        password_hash=hash_password(req.password),
        role_id=req.role_id,
        tenant_id=default_id,
    )
    session.add(user)
    await session.flush()
    rows = await save_grants(session, user, ids, default_id, ctx.user_id, []) if advisor else []
    created_state = _audit_state(user)
    if advisor:
        created_state["tenant_ids"] = ids
    await audit_business(session, ctx, 'user:' + str(user.id), 'user.create', None, created_state)
    await session.commit()
    await session.refresh(user)
    if advisor:
        logger.info("advisor_grants_created actor_user_id=%s user_id=%s tenant_ids=%s", ctx.user_id, user.id, ids)
    return {"status": "ok", **await _account_payload(session, user, role, {}, rows)}


class UpdateUserRequest(BaseModel):
    is_active: bool | None = None
    role_id: int | None = None
    tenant_id: int | None = None
    clear_tenant: bool = False  # True=解除单客户绑定（改回全客户）
    display_name: str | None = Field(None, max_length=50)
    new_password: str | None = Field(None, min_length=8, max_length=100)
    tenant_ids: list[TenantId] | None = Field(None, max_length=1000)
    default_tenant_id: TenantId | None = None
    expected_grants_version: str | None = Field(None, max_length=64)


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    req: UpdateUserRequest,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_admin),
) -> dict:
    supplied = bool(req.model_fields_set & {"tenant_ids", "default_tenant_id"})
    if supplied:
        user = await lock_named_admin(session, ctx, user_id)
    else:
        user = await session.get(User, user_id, with_for_update=True, populate_existing=True)
    if user is None:
        raise HTTPException(404, "用户不存在")
    if req.is_active is False and user.id == ctx.user_id:
        raise HTTPException(400, "不能停用自己的账号")
    before = _audit_state(user)
    old_role = await session.get(Role, user.role_id)
    new_role = await session.get(Role, req.role_id) if req.role_id is not None else old_role
    if is_advisor(old_role) and req.clear_tenant:
        deny(422, "ADVISOR_CLEAR_TENANT_FORBIDDEN", "顾问不能通过清空默认客户获得全部客户")
    if is_advisor(old_role) != is_advisor(new_role):
        deny(409, "ADVISOR_ROLE_CHANGE_FROZEN", "顾问角色转换已冻结，请先核对客户授权")
    advisor = is_advisor(new_role)
    if supplied and not advisor:
        deny(422, "TENANT_IDS_ONLY_FOR_ADVISOR", "只有顾问账号可以设置多个客户")
    if advisor and "tenant_id" in req.model_fields_set and not supplied:
        deny(422, "ADVISOR_TENANT_IDS_REQUIRED", "请使用顾问客户名单和默认客户字段")
    rows = None
    if advisor and supplied:
        _require_multi_tenant()
        if req.expected_grants_version is None:
            deny(428, "ADVISOR_GRANTS_VERSION_REQUIRED", "请刷新账号后再保存客户名单")
        rows = await read_grants(session, user.id)
        if req.expected_grants_version != grants_version(user.tenant_id, rows):
            deny(409, "ADVISOR_GRANTS_CONFLICT", "该账号的客户已被别人修改，请刷新后再改")
        ids = req.tenant_ids if "tenant_ids" in req.model_fields_set else [g.tenant_id for g in rows if g.revoked_at is None]
        if not ids:
            deny(422, "ADVISOR_TENANTS_REQUIRED", "至少勾选 1 个客户")
        default_id = req.default_tenant_id if "default_tenant_id" in req.model_fields_set else user.tenant_id
        if "default_tenant_id" not in req.model_fields_set and default_id not in ids:
            deny(422, "ADVISOR_DEFAULT_TENANT_REQUIRED", "取消默认客户时请同时选择新的默认客户")
        ids = await validate_tenants(session, ids, default_id, new_role)
        if req.tenant_id is not None and req.tenant_id != default_id:
            deny(422, "ADVISOR_DEFAULT_TENANT_INVALID", "默认客户字段不一致")
        before["tenant_ids"] = sorted(g.tenant_id for g in rows if g.revoked_at is None)
        rows = await save_grants(session, user, ids, default_id, ctx.user_id, rows)
    if req.role_id is not None:
        await _check_role(session, req.role_id)
        user.role_id = req.role_id
    if req.clear_tenant:
        user.tenant_id = None
    elif req.tenant_id is not None and not advisor:
        await _check_tenant(session, req.tenant_id)
        user.tenant_id = req.tenant_id
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.new_password:
        user.password_hash = hash_password(req.new_password)
    after = _audit_state(user)
    if advisor and supplied:
        after["tenant_ids"] = ids
    if req.new_password:
        after['password_changed'] = True
    await audit_business(session, ctx, 'user:' + str(user.id), 'user.update', before, after)
    await session.commit()
    if advisor and supplied:
        logger.info("advisor_grants_updated actor_user_id=%s user_id=%s tenant_ids=%s default_tenant_id=%s",
                    ctx.user_id, user.id, ids, user.tenant_id)
    return {"status": "ok", **await _account_payload(session, user, new_role, {}, rows)}


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_admin),
) -> dict:
    user = await session.get(User, user_id, with_for_update=True)
    if user is None:
        raise HTTPException(404, "用户不存在")
    if user.id == ctx.user_id:
        raise HTTPException(400, "不能删除自己的账号")
    role = await session.get(Role, user.role_id)
    permissions = effective_role_permissions(role.name, role.is_system, role.permissions) if role else {}
    if user.tenant_id is None and all(permissions.get(key) == "edit" for key in PLATFORM_ADMIN_KEYS):
        raise HTTPException(400, "不能删除超级管理员账号")
    before = _audit_state(user)
    user.is_active = False
    await audit_business(session, ctx, 'user:' + str(user.id), 'user.delete', before, _audit_state(user))
    await session.commit()
    logger.info("account_deactivated actor_user_id=%s target_user_id=%s", ctx.user_id, user_id)
    return {"status": "ok"}


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=100)


@router.patch("/{user_id}/password")
async def reset_user_password(
    user_id: int,
    req: ResetPasswordRequest,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_admin),
) -> dict:
    """Admin-only password reset; existing sessions retain their normal expiry."""
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(404, "用户不存在")
    user.password_hash = hash_password(req.new_password)
    await audit_business(session, ctx, 'user:' + str(user.id), 'user.password', None, {'password_changed': True})
    await session.commit()
    return {"status": "ok"}
