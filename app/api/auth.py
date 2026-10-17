"""登录态 + 当前用户（含菜单权限）+ 租户列表（多客户切换器数据源）。"""
import logging
import ipaddress
import jwt
from functools import wraps
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models import BaiduAccount, Role, Tenant, TenantModule, User
from app.models.advisor_account import AdvisorAccountLink, AdvisorAccountSwitchAudit
from app.permissions import ALL_EDIT, effective_role_permissions
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
    async def deny(message: str, reason: str):
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
        await deny("目标账号不在当前关联组", "not_linked")
    target = await session.get(User, req.target_user_id, with_for_update={"read": True}, populate_existing=True)
    locked = target and target.locked_until and target.locked_until > now.replace(tzinfo=None)
    if (not await _eligible_advisor(session, target) or target.tenant_id == source.tenant_id
            or target_link.tenant_id != target.tenant_id or locked):
        await deny("目标账号不具备有效顾问资格", "target_ineligible")
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
