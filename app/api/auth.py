"""登录态 + 当前用户（含菜单权限）+ 租户列表（多客户切换器数据源）。"""
import logging
import ipaddress
import jwt
from functools import wraps
from uuid import UUID, uuid4
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models import BaiduAccount, Role, Tenant, TenantModule, User
from app.models.advisor_account import AdvisorAccountLink, AdvisorAccountSwitchAudit
from app.permissions import ALL_EDIT, OPERATOR_PERMS, effective_role_permissions
from app.module_scope import list_module_tenants, module_is_available
from app.security.auth import (
    AuthContext,
    hash_password,
    issue_token,
    _jwt_secret,
    JWT_ALG,
    require_auth,
    require_admin,
    verify_password,
)
from app.security.sem_identity import (
    load_sem_identity_states,
    public_sem_identity_state,
)
from app.security.advisor_scope import is_advisor, deny, account_locked, read_grants, active_grants
from app.security.advisor_management import TenantId
from app.security.advisor_session import admit_selection

logger = logging.getLogger(__name__)

def _raise_missing_link_schema(exc: DBAPIError) -> None:
    if getattr(exc.orig, "sqlstate", None) == "42P01" or getattr(exc.orig, "pgcode", None) == "42P01":
        raise HTTPException(503, "顾问关联表尚未就绪") from exc
    raise exc


def _link_schema_guard(fn):
    @wraps(fn)
    async def guarded(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except DBAPIError as exc:
            _raise_missing_link_schema(exc)
    return guarded


def _audit_ip(request):
    if not request or not request.client:
        return None
    peer = request.client.host
    if peer in {"127.0.0.1", "::1"}:
        real = request.headers.get("x-real-ip")
        if real:
            try:
                return str(ipaddress.ip_address(real))
            except ValueError:
                pass
    return peer


def _audit(request, *, action, actor, source, target, group, status="success", reason=None):
    return AdvisorAccountSwitchAudit(
        action=action, actor_user_id=actor, from_user_id=source, to_user_id=target,
        group_id=group, status=status, reason=reason,
        ip_address=_audit_ip(request),
        user_agent=request.headers.get("user-agent", "")[:512] if request else None,
        created_at=datetime.now(timezone.utc),
    )

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


async def _user_payload(u: User, session: AsyncSession, *, advisor_identity: bool = False) -> dict:
    role = await session.get(Role, u.role_id)
    result = {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "role_id": u.role_id,
        "role_label": role.name if role else "?",
        "permissions": (role.permissions or {}) if role else {},  # 前端按它渲染菜单/按钮
        "tenant_id": u.tenant_id,
    }
    if advisor_identity and is_advisor(role):
        result.update(is_advisor=True, tenant_id=None, default_tenant_id=u.tenant_id,
                      permissions=effective_role_permissions(role.name, role.is_system, role.permissions))
    return result


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
    role = await session.get(Role, user.role_id)
    return {"token": issue_token(user, advisor=is_advisor(role)),
            "user": await _user_payload(user, session, advisor_identity=is_advisor(role))}


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
    result = await _user_payload(user, session)
    if ctx.advisor_scope is not None:
        result.update(tenant_id=ctx.tenant_id, is_advisor=True,
                      default_tenant_id=user.tenant_id, permissions=ctx.permissions)
    return {"user": result}


async def _eligible_advisor(session: AsyncSession, user: User | None) -> bool:
    if user is None or not user.is_active or user.tenant_id is None:
        return False
    role = await session.get(Role, user.role_id)
    permissions = effective_role_permissions(role.name, role.is_system, role.permissions) if role else {}
    if any(key.startswith("settings.") and level == "edit" for key, level in permissions.items()):
        return False
    return (
        permissions.get("seo.site") == "edit" and permissions.get("seo.content") == "edit"
    ) or (
        permissions.get("geo.assets") == "edit" and permissions.get("geo.content") == "edit"
    )


class AccountLinkRequest(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=20)
    group_id: UUID | None = None


async def _require_named_account_admin(session: AsyncSession, ctx: AuthContext) -> None:
    if ctx.user_id is None:
        raise HTTPException(403, "需要实名平台管理员")
    admin = await session.get(User, ctx.user_id, with_for_update=True)
    role = await session.get(Role, admin.role_id) if admin else None
    permissions = effective_role_permissions(role.name, role.is_system, role.permissions) if role else {}
    if not admin or not admin.is_active or admin.tenant_id is not None or permissions.get("settings.accounts") != "edit":
        raise HTTPException(403, "平台管理员权限已变化")


@router.post("/account-links")
@_link_schema_guard
async def link_advisor_accounts(
    req: AccountLinkRequest,
    ctx: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    request: Request = None,
) -> dict:
    """A named platform administrator creates or extends an explicit advisor group."""
    if not get_settings().advisor_legacy_account_switch_enabled:
        deny(410, "LEGACY_ADVISOR_SWITCH_DISABLED", "旧账号关联与切换已关闭")
    if ctx.user_id is None or len(set(req.user_ids)) != len(req.user_ids):
        raise HTTPException(403, "需要实名平台管理员且账号不得重复")
    if req.group_id is None and len(req.user_ids) < 2:
        raise HTTPException(400, "新关联组至少需要两个账号")
    from app.security.platform_admin import acquire_platform_admin_lock
    await acquire_platform_admin_lock(session)
    await _require_named_account_admin(session, ctx)
    existing = list(await session.scalars(select(AdvisorAccountLink).where(
        AdvisorAccountLink.group_id == req.group_id
    ))) if req.group_id else []
    if req.group_id and not existing:
        raise HTTPException(404, "关联组不存在")
    users = []
    for user_id in [*(link.user_id for link in existing), *req.user_ids]:
        user = await session.get(User, user_id, with_for_update=True)
        if not await _eligible_advisor(session, user):
            raise HTTPException(403, "关联组只允许已启用的单租户顾问账号")
        users.append(user)
    if len({user.tenant_id for user in users}) != len(users):
        raise HTTPException(403, "关联组内每个账号必须属于不同客户")
    for user_id in req.user_ids:
        if await session.get(AdvisorAccountLink, user_id):
            raise HTTPException(409, "账号已有关联组")
    group_id = req.group_id or uuid4()
    for user_id in req.user_ids:
        user = next(u for u in users if u.id == user_id)
        session.add(AdvisorAccountLink(user_id=user_id, group_id=group_id,
                                       tenant_id=user.tenant_id, created_by=ctx.user_id))
        session.add(_audit(request, action="link", actor=ctx.user_id, source=ctx.user_id,
                           target=user_id, group=group_id,
                           reason="extend" if req.group_id else "create"))
    await session.commit()
    return {"group_id": str(group_id), "user_ids": [user.id for user in users]}


@router.delete("/account-links/{user_id}")
@_link_schema_guard
async def unlink_advisor_account(
    user_id: int,
    ctx: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    request: Request = None,
) -> dict:
    if not get_settings().advisor_legacy_account_switch_enabled:
        deny(410, "LEGACY_ADVISOR_SWITCH_DISABLED", "旧账号关联与切换已关闭")
    if ctx.user_id is None:
        raise HTTPException(403, "需要实名平台管理员")
    from app.security.platform_admin import acquire_platform_admin_lock
    await acquire_platform_admin_lock(session)
    await _require_named_account_admin(session, ctx)
    link = await session.get(AdvisorAccountLink, user_id)
    if link is None:
        raise HTTPException(404, "账号未关联")
    await session.delete(link)
    session.add(_audit(request, action="unlink", actor=ctx.user_id, source=ctx.user_id,
                       target=user_id, group=link.group_id, reason="admin_unlink"))
    remaining = list(await session.scalars(select(AdvisorAccountLink).where(
        AdvisorAccountLink.group_id == link.group_id, AdvisorAccountLink.user_id != user_id
    )))
    if len(remaining) == 1:
        await session.delete(remaining[0])
        session.add(_audit(request, action="unlink", actor=ctx.user_id, source=ctx.user_id,
                           target=remaining[0].user_id, group=link.group_id, reason="group_dissolved"))
    await session.commit()
    return {"status": "ok"}


@router.get("/linked-accounts")
async def linked_accounts(
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not get_settings().advisor_legacy_account_switch_enabled:
        return {"accounts": []}
    if ctx.user_id is None:
        raise HTTPException(403, "需要实名顾问账号")
    current = await session.get(User, ctx.user_id)
    if not await _eligible_advisor(session, current):
        return {"accounts": []}
    try:
        link = await session.get(AdvisorAccountLink, ctx.user_id)
    except DBAPIError as exc:
        _raise_missing_link_schema(exc)
    if link is None:
        return {"accounts": []}
    if link.tenant_id != current.tenant_id:
        return {"accounts": []}
    others = list(await session.scalars(select(User).join(
        AdvisorAccountLink, AdvisorAccountLink.user_id == User.id
    ).where(AdvisorAccountLink.group_id == link.group_id, User.id != ctx.user_id).order_by(User.id)))
    accounts = []
    for user in others:
        if (not await _eligible_advisor(session, user) or user.tenant_id == current.tenant_id
                or (user.locked_until is not None and user.locked_until > datetime.now(timezone.utc).replace(tzinfo=None))):
            continue
        target_link = await session.get(AdvisorAccountLink, user.id)
        if not target_link or target_link.tenant_id != user.tenant_id:
            continue
        tenant = await session.get(Tenant, user.tenant_id)
        if tenant:
            accounts.append({"id": user.id, "display_name": user.display_name or user.username,
                             "customer_name": tenant.name})
    return {"accounts": accounts}


class SwitchAccountRequest(BaseModel):
    target_user_id: int = Field(gt=0)


@router.post("/switch-account")
async def switch_account(
    req: SwitchAccountRequest,
    request: Request,
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not get_settings().advisor_legacy_account_switch_enabled:
        deny(410, "LEGACY_ADVISOR_SWITCH_DISABLED", "旧账号关联与切换已关闭")
    if ctx.user_id is None:
        raise HTTPException(403, "需要实名顾问账号")
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "需要有效的登录凭证")
    try:
        claims = jwt.decode(authorization[7:].strip(), _jwt_secret(), algorithms=[JWT_ALG])
        if claims.get("sub") != str(ctx.user_id):
            raise ValueError("会话账号不匹配")
        auth_exp = claims.get("auth_exp", claims["exp"])
        root_source_id = claims.get("root_src", ctx.user_id)
        if type(auth_exp) is not int or type(root_source_id) is not int:
            raise ValueError("登录来源无效")
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(401, "登录凭证无效，请重新登录") from exc
    source = await session.get(User, ctx.user_id)
    if not await _eligible_advisor(session, source):
        raise HTTPException(403, "当前账号无顾问切换资格")
    try:
        source_link = await session.get(AdvisorAccountLink, ctx.user_id)
    except DBAPIError as exc:
        _raise_missing_link_schema(exc)
    if not source_link or source_link.tenant_id != source.tenant_id:
        raise HTTPException(403, "当前账号没有有效关联组")
    # Serialize attempts per source, without contending with account administration.
    await session.execute(select(func.pg_advisory_xact_lock(
        func.hashtextextended("advisor_switch:" + str(ctx.user_id), 0))))
    source = await session.get(User, ctx.user_id, with_for_update={"read": True}, populate_existing=True)
    link = await session.scalar(select(AdvisorAccountLink).where(
        AdvisorAccountLink.user_id == ctx.user_id).with_for_update(read=True))
    if not await _eligible_advisor(session, source) or not link or link.tenant_id != source.tenant_id:
        raise HTTPException(403, "当前账号没有有效关联组")
    now = datetime.now(timezone.utc)
    async def deny_switch(message: str, reason: str):
        session.add(_audit(request, action="switch", actor=ctx.user_id, source=ctx.user_id,
                           target=req.target_user_id, group=link.group_id,
                           status="denied", reason=reason))
        await session.commit()
        raise HTTPException(403, message)
    recent = await session.scalar(select(func.count()).select_from(AdvisorAccountSwitchAudit).where(
        AdvisorAccountSwitchAudit.from_user_id == ctx.user_id,
        AdvisorAccountSwitchAudit.action == "switch",
        AdvisorAccountSwitchAudit.created_at >= now - timedelta(minutes=1)))
    if (recent or 0) >= 10:
        raise HTTPException(429, "切换过于频繁，请稍后重试")
    target_link = await session.scalar(select(AdvisorAccountLink).where(
        AdvisorAccountLink.user_id == req.target_user_id).with_for_update(read=True))
    if not target_link or link.group_id != target_link.group_id or source.id == req.target_user_id:
        await deny_switch("目标账号不在当前关联组", "not_linked")
    target = await session.get(User, req.target_user_id, with_for_update={"read": True}, populate_existing=True)
    locked = target and target.locked_until and target.locked_until > now.replace(tzinfo=None)
    if (not await _eligible_advisor(session, target) or target.tenant_id == source.tenant_id
            or target_link.tenant_id != target.tenant_id or locked):
        await deny_switch("目标账号不具备有效顾问资格", "target_ineligible")
    try:
        target_token = issue_token(target, switch_source_id=source.id,
                                   switch_group_id=str(link.group_id),
                                   root_source_id=root_source_id, auth_exp=auth_exp)
    except ValueError as exc:
        raise HTTPException(401, "原登录会话已到期，请重新登录") from exc
    session.add(_audit(request, action="switch", actor=ctx.user_id, source=source.id,
                       target=target.id, group=link.group_id))
    await session.commit()
    logger.info("advisor_account_switch from_user_id=%s to_user_id=%s at=%s",
                source.id, target.id, now.isoformat())
    return {"token": target_token,
            "user": await _user_payload(target, session)}


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
    if ctx.advisor_scope is not None:
        from app.models.advisor_tenant_grant import AdvisorTenantGrant
        if module:
            if not ctx.can_view(*_MODULE_PERMISSION_KEYS[module]):
                raise HTTPException(403, "当前账号无权访问该模块的客户列表")
            tenants = await list_module_tenants(session, ctx, module)
        else:
            tenants = list((await session.scalars(select(Tenant).join(
                AdvisorTenantGrant, AdvisorTenantGrant.tenant_id == Tenant.id
            ).where(AdvisorTenantGrant.user_id == ctx.user_id,
                    AdvisorTenantGrant.revoked_at.is_(None)).order_by(Tenant.id))).all())
        return {"module": module, "tenants": [{"id": t.id, "name": t.name} for t in tenants]}
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


class SelectTenantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: TenantId


def _selection_audit(fn):
    @wraps(fn)
    async def audited(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except HTTPException as error:
            req, ctx = kwargs.get("req"), kwargs.get("ctx")
            code = error.detail.get("code") if isinstance(error.detail, dict) else "selection_denied"
            logger.info("advisor_tenant_selection actor_user_id=%s tenant_id=%s status=denied reason=%s",
                        getattr(ctx, "user_id", None), getattr(req, "tenant_id", None), code)
            raise
    return audited


@router.post("/select-tenant")
@_selection_audit
async def select_tenant(
    req: SelectTenantRequest,
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not get_settings().advisor_multi_tenant_enabled:
        deny(404, "ADVISOR_MULTI_TENANT_DISABLED", "顾问多客户功能尚未开放")
    if ctx.user_id is None or ctx.advisor_scope is None:
        deny(403, "ADVISOR_IDENTITY_REQUIRED", "仅顾问本人可以切换客户")
    admit_selection(ctx.user_id)
    # Serialize with grant saves. The identity/session expiry comes from the
    # verified token, never from the selection body or a refreshed TTL.
    user = await session.get(User, ctx.user_id, with_for_update=True, populate_existing=True)
    role = await session.get(Role, user.role_id, populate_existing=True) if user else None
    if not user or not user.is_active or account_locked(user) or not is_advisor(role):
        deny(401, "ADVISOR_ROLE_CHANGED", "账号或顾问资格已变化，请重新登录")
    rows = await read_grants(session, user.id)
    active = await active_grants(session, rows)
    if not active:
        deny(403, "ADVISOR_NO_TENANT", "顾问尚未获准访问任何客户")
    # A business credential revoked since require_auth must not act as an
    # identity credential while waiting for this users row lock.
    if ctx.advisor_scope.grant_id is not None and not any(
            g.id == ctx.advisor_scope.grant_id and g.tenant_id == ctx.tenant_id for g in active):
        deny(401, "ADVISOR_GRANT_REVOKED", "客户授权已撤销，请重新选择客户")
    grant = next((g for g in active if g.tenant_id == req.tenant_id), None)
    if grant is None:
        deny(403, "ADVISOR_TENANT_NOT_GRANTED", "顾问只能访问勾选的客户")
    if user.tenant_id not in {g.tenant_id for g in active}:
        deny(403, "ADVISOR_DEFAULT_TENANT_INVALID", "默认客户与授权不一致，请管理员修复")
    perms = effective_role_permissions(role.name, role.is_system, role.permissions)
    modules = list((await session.scalars(select(TenantModule).where(
        TenantModule.tenant_id == req.tenant_id))).all())
    if not any(module_is_available(m) and any(perms.get(k) in ("view", "edit")
            for k in _MODULE_PERMISSION_KEYS.get(m.module_code, ())) for m in modules):
        deny(403, "ADVISOR_TENANT_MODULE_UNAVAILABLE", "该客户没有当前角色可用的模块")
    if type(ctx.auth_exp) is not int or ctx.auth_exp <= datetime.now(timezone.utc).timestamp():
        deny(401, "ADVISOR_SESSION_EXPIRED", "原登录会话已到期，请重新登录")
    access_token = issue_token(user, advisor=True, tenant_id=req.tenant_id,
                               grant_id=grant.id, auth_exp=ctx.auth_exp)
    tenant = await session.get(Tenant, req.tenant_id)
    expires_at = jwt.decode(access_token, _jwt_secret(), algorithms=[JWT_ALG],
                            audience="advisor-business")["exp"]
    await session.commit()
    logger.info("advisor_tenant_selection actor_user_id=%s tenant_id=%s grant_id=%s status=success",
                user.id, req.tenant_id, grant.id)
    return {"access_token": access_token, "token_type": "bearer", "tenant_id": req.tenant_id,
            "tenant_name": tenant.name, "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat()}


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
    "seo": (
        "seo.assets", "seo.dashboard", "seo.alerts", "seo.keywords",
        "seo.content", "seo.site", "seo.links", "seo.competitors",
    ),
    "geo": ("geo.assets", "geo.content", "geo.diagnosis"),
}


@router.get("/modules")
async def list_my_modules(
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Modules visible in the signed-in user's workspace and module switcher."""
    if ctx.advisor_scope is not None:
        ctx.ensure_tenant(ctx.tenant_id)
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
