"""百度商业开发者中心 OAuth 2.0 服务商接入。

官方文档：
  - 授权页：https://u.baidu.com/oauth/page/index
  - 换 Token：https://u.baidu.com/oauth/accessToken
  - 刷新 Token：https://u.baidu.com/oauth/refreshToken
  - 授权账户：https://u.baidu.com/oauth/getUserInfo

注意：百度回调签名不是标准 OAuth 算法，必须按官方 Java 示例使用
AES-CBC/NoPadding、全零 IV、secretKey 前 16 字节。
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import BaiduAccount, BaiduOAuthGrant, BaiduOAuthState, Tenant, TenantModule
from app.security.crypto import decrypt, encrypt

logger = logging.getLogger(__name__)

_DEFAULT_ACCESS_SECONDS = 24 * 60 * 60
_DEFAULT_REFRESH_SECONDS = 30 * 24 * 60 * 60
_REFRESH_AHEAD = timedelta(hours=2)
_MAX_SUB_ACCOUNT_PAGES = 100


class BaiduOAuthError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class OAuthAccount:
    ucid: int
    username: str
    role: str


def oauth_callback_url() -> str:
    settings = get_settings()
    if settings.baidu_oauth_callback_url.strip():
        return settings.baidu_oauth_callback_url.strip()
    return f"{settings.app_base_url.rstrip('/')}/api/oauth/baidu/callback"


def oauth_is_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.baidu_app_id.strip()
        and settings.baidu_secret_key.strip()
        and settings.baidu_oauth_scope.strip()
        and oauth_callback_url().startswith(("https://", "http://"))
    )


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _safe_return_path(path: str | None) -> str:
    value = (path or "/onboarding").strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/onboarding"
    return value[:300]


async def create_authorization_url(
    session: AsyncSession,
    *,
    tenant_id: int,
    requested_by_user_id: int | None,
    return_path: str = "/onboarding",
) -> str:
    settings = get_settings()
    if not oauth_is_configured():
        raise BaiduOAuthError(
            "not_configured",
            "百度 OAuth 尚未配置，请先设置应用 App ID、SecretKey 和授权链接中的 scope。",
        )

    raw_state = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    session.add(
        BaiduOAuthState(
            state_hash=_state_hash(raw_state),
            tenant_id=tenant_id,
            requested_by_user_id=requested_by_user_id,
            return_path=_safe_return_path(return_path),
            expires_at=now + timedelta(minutes=settings.baidu_oauth_state_ttl_minutes),
        )
    )
    await session.commit()

    query = urlencode(
        {
            "platformId": settings.baidu_oauth_platform_id,
            "appId": settings.baidu_app_id,
            "scope": settings.baidu_oauth_scope,
            "state": raw_state,
            "callback": oauth_callback_url(),
        }
    )
    return f"{settings.baidu_oauth_base_url.rstrip('/')}/oauth/page/index?{query}"


def _signature_payload(params: dict[str, str]) -> bytes:
    ordered = {
        key: params[key]
        for key in sorted(("appId", "authCode", "state", "timestamp", "userId"))
    }
    raw_json = json.dumps(
        ordered, ensure_ascii=False, separators=(",", ":"), sort_keys=False
    )
    return base64.b64encode(raw_json.encode("utf-8"))


def calculate_callback_signature(
    params: dict[str, str], secret_key: str
) -> str:
    """复刻百度 Java demo 的 AES-CBC/NoPadding + 零填充 + 大写十六进制。"""
    key = secret_key[:16].encode("utf-8")
    if len(key) != 16:
        raise BaiduOAuthError("invalid_secret", "百度应用 SecretKey 长度不正确")
    payload = _signature_payload(params)
    padded_len = ((len(payload) + 15) // 16) * 16
    padded = payload.ljust(padded_len, b"\0")
    cipher = Cipher(algorithms.AES(key), modes.CBC(b"\0" * 16))
    encryptor = cipher.encryptor()
    return (encryptor.update(padded) + encryptor.finalize()).hex().upper()


def verify_callback_signature(params: dict[str, str], signature: str) -> bool:
    expected = calculate_callback_signature(params, get_settings().baidu_secret_key)
    return secrets.compare_digest(expected.lower(), signature.strip().lower())


async def consume_oauth_state(
    session: AsyncSession, raw_state: str
) -> BaiduOAuthState:
    row = await session.scalar(
        select(BaiduOAuthState)
        .where(BaiduOAuthState.state_hash == _state_hash(raw_state))
        .with_for_update()
    )
    now = datetime.utcnow()
    if row is None or row.consumed_at is not None or row.expires_at <= now:
        raise BaiduOAuthError(
            "invalid_state", "授权请求已失效，请返回 SEM 平台重新发起授权。"
        )
    row.consumed_at = now
    await session.commit()
    return row


async def _post_oauth(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.baidu_oauth_base_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json;charset:utf-8"},
            )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("百度 OAuth 请求失败 path=%s type=%s", path, type(exc).__name__)
        raise BaiduOAuthError("oauth_upstream", "百度授权服务暂时不可用，请稍后重试。") from exc
    if body.get("code") != 0 or not isinstance(body.get("data"), dict):
        logger.warning(
            "百度 OAuth 业务失败 path=%s code=%s message=%s",
            path,
            body.get("code"),
            body.get("message"),
        )
        raise BaiduOAuthError(
            "oauth_rejected", body.get("message") or "百度未接受本次授权请求。"
        )
    return body["data"]


async def exchange_auth_code(*, auth_code: str, user_id: int) -> dict[str, Any]:
    settings = get_settings()
    return await _post_oauth(
        "/oauth/accessToken",
        {
            "appId": settings.baidu_app_id,
            "authCode": auth_code,
            "secretKey": settings.baidu_secret_key,
            "grantType": "auth_code",
            "userId": user_id,
        },
    )


async def fetch_authorized_accounts(
    *, open_id: str, access_token: str, user_id: int
) -> tuple[dict[str, Any], list[OAuthAccount]]:
    """获取授权主体和全部子账户；超管/代理商按最多 500 条分页。"""
    all_sub_accounts: dict[int, OAuthAccount] = {}
    master: dict[str, Any] | None = None
    cursor = 1

    for _ in range(_MAX_SUB_ACCOUNT_PAGES):
        data = await _post_oauth(
            "/oauth/getUserInfo",
            {
                "openId": open_id,
                "accessToken": access_token,
                "userId": user_id,
                "needSubList": True,
                "pageSize": 500,
                "lastPageMaxUcId": cursor,
            },
        )
        if master is None:
            master = {
                "master_ucid": int(data.get("masterUid") or user_id),
                "master_name": str(data.get("masterName") or user_id),
                "account_type": int(data.get("userAcctType") or 1),
            }
        page = data.get("subUserList") or []
        page_ids: list[int] = []
        for item in page:
            ucid = int(item.get("ucId") or 0)
            username = str(item.get("ucName") or "").strip()
            if ucid and username:
                page_ids.append(ucid)
                all_sub_accounts[ucid] = OAuthAccount(
                    ucid=ucid, username=username, role="subaccount"
                )
        if not data.get("hasNext"):
            break
        if not page_ids:
            raise BaiduOAuthError(
                "invalid_account_page", "百度返回的子账户分页数据不完整，请重新授权。"
            )
        cursor = max(page_ids)
    else:
        raise BaiduOAuthError(
            "too_many_account_pages", "授权账户数量过多，请联系平台管理员处理。"
        )

    assert master is not None
    accounts = list(all_sub_accounts.values())
    if not accounts:
        accounts = [
            OAuthAccount(
                ucid=master["master_ucid"],
                username=master["master_name"],
                role="standalone",
            )
        ]
    return master, accounts


def _expiry_from_token_data(
    data: dict[str, Any],
) -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    try:
        access_seconds = max(60, int(data.get("expiresIn") or _DEFAULT_ACCESS_SECONDS))
    except (TypeError, ValueError):
        access_seconds = _DEFAULT_ACCESS_SECONDS
    try:
        refresh_seconds = max(
            60, int(data.get("refreshExpiresIn") or _DEFAULT_REFRESH_SECONDS)
        )
    except (TypeError, ValueError):
        refresh_seconds = _DEFAULT_REFRESH_SECONDS
    return now + timedelta(seconds=access_seconds), now + timedelta(
        seconds=refresh_seconds
    )


async def persist_authorization(
    session: AsyncSession,
    *,
    oauth_user_id: int,
    token_data: dict[str, Any],
    master: dict[str, Any],
    accounts: list[OAuthAccount],
) -> tuple[BaiduOAuthGrant, list[BaiduAccount], list[Tenant]]:
    """保存授权，并确保每个百度推广账户拥有独立客户。

    账户归属只按百度 UCID 创建/复用 Tenant，不使用发起授权前选中的客户，
    避免把新账号误绑到当前客户。
    """
    settings = get_settings()
    access_token = str(token_data.get("accessToken") or "")
    refresh_token = str(token_data.get("refreshToken") or "")
    open_id = str(token_data.get("openId") or "")
    if not access_token or not refresh_token or not open_id:
        raise BaiduOAuthError(
            "incomplete_token", "百度返回的授权令牌信息不完整，请重新授权。"
        )
    expires_at, refresh_expires_at = _expiry_from_token_data(token_data)
    encrypted_access = encrypt(access_token)
    encrypted_refresh = encrypt(refresh_token)
    now = datetime.utcnow()

    linked_tenants: list[Tenant] = []
    for account in accounts:
        tenant = await session.scalar(
            select(Tenant).where(Tenant.baidu_ucid == account.ucid)
        )
        if tenant is None:
            tenant = Tenant(
                name=account.username[:100],
                baidu_ucid=account.ucid,
                strategy="lead",
                brand_terms=[account.username],
            )
            session.add(tenant)
            await session.flush()
        linked_tenants.append(tenant)

    if not linked_tenants:
        raise BaiduOAuthError("no_accounts", "百度未返回可授权的推广账户。")
    primary_tenant = linked_tenants[0]

    # OAuth 是 SEM 首次接入入口。新账户会自动创建独立客户，因此也必须同时
    # 开通对应的 SEM 工作区，否则模块客户选择器会把已授权账户隐藏起来。
    # 使用唯一约束 + ON CONFLICT 保证重复授权和并发回调不会产生重复记录；
    # 已存在但被业务侧停用的模块不会被 OAuth 擅自重新启用。
    await session.execute(
        insert(TenantModule)
        .values(
            [
                {
                    "tenant_id": tenant_id,
                    "module_code": "sem",
                    "status": "active",
                }
                for tenant_id in sorted({tenant.id for tenant in linked_tenants})
            ]
        )
        .on_conflict_do_nothing(constraint="uq_tenant_module_code")
    )

    grant = await session.scalar(
        select(BaiduOAuthGrant)
        .where(
            BaiduOAuthGrant.app_id == settings.baidu_app_id,
            BaiduOAuthGrant.oauth_user_id == oauth_user_id,
        )
        .order_by(BaiduOAuthGrant.updated_at.desc(), BaiduOAuthGrant.id.desc())
        .limit(1)
    )
    if grant is None:
        grant = BaiduOAuthGrant(
            tenant_id=primary_tenant.id,
            app_id=settings.baidu_app_id,
            oauth_user_id=oauth_user_id,
            open_id=open_id,
            master_ucid=master["master_ucid"],
            master_name=master["master_name"],
            account_type=master["account_type"],
            access_token_encrypted=encrypted_access,
            refresh_token_encrypted=encrypted_refresh,
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
            status="active",
            authorized_at=now,
        )
        session.add(grant)
        await session.flush()
    else:
        grant.tenant_id = primary_tenant.id
        grant.open_id = open_id
        grant.master_ucid = master["master_ucid"]
        grant.master_name = master["master_name"]
        grant.account_type = master["account_type"]
        grant.access_token_encrypted = encrypted_access
        grant.refresh_token_encrypted = encrypted_refresh
        grant.expires_at = expires_at
        grant.refresh_expires_at = refresh_expires_at
        grant.status = "active"
        grant.authorized_at = now

    linked: list[BaiduAccount] = []
    active_ucids = {account.ucid for account in accounts}
    for account, account_tenant in zip(accounts, linked_tenants, strict=True):
        oauth_rows = (
            await session.scalars(
                select(BaiduAccount)
                .where(
                    BaiduAccount.baidu_ucid == account.ucid,
                    BaiduAccount.auth_mode == "oauth",
                )
                .order_by(BaiduAccount.updated_at.desc(), BaiduAccount.id.desc())
            )
        ).all()
        row = oauth_rows[0] if oauth_rows else None
        # 旧逻辑可能把同一 UCID 重复绑到多个客户；保留最新一条，其余停用。
        for duplicate in oauth_rows[1:]:
            duplicate.status = "inactive"
        if row is None:
            row = BaiduAccount(
                tenant_id=account_tenant.id,
                baidu_username=account.username,
                baidu_ucid=account.ucid,
                access_token_encrypted=encrypted_access,
                refresh_token_encrypted=encrypted_refresh,
                expires_at=expires_at,
                oauth_grant_id=grant.id,
                account_role=account.role,
                refresh_expires_at=refresh_expires_at,
                authorized_at=now,
                auth_mode="oauth",
                status="active",
                sync_status="pending",
            )
            session.add(row)
        else:
            row.tenant_id = account_tenant.id
            row.baidu_username = account.username
            row.access_token_encrypted = encrypted_access
            row.refresh_token_encrypted = encrypted_refresh
            row.expires_at = expires_at
            row.oauth_grant_id = grant.id
            row.account_role = account.role
            row.refresh_expires_at = refresh_expires_at
            row.authorized_at = now
            row.auth_mode = "oauth"
            row.status = "active"
            row.sync_status = "pending"
            row.last_sync_error = None
        linked.append(row)

    await session.execute(
        update(BaiduAccount)
        .where(
            BaiduAccount.oauth_grant_id == grant.id,
            BaiduAccount.baidu_ucid.not_in(active_ucids),
        )
        .values(status="inactive")
    )
    await session.commit()
    return grant, linked, linked_tenants


async def refresh_grant(
    session: AsyncSession, grant: BaiduOAuthGrant
) -> bool:
    now = datetime.utcnow()
    if grant.refresh_expires_at <= now:
        grant.status = "reauthorization_required"
        await session.execute(
            update(BaiduAccount)
            .where(BaiduAccount.oauth_grant_id == grant.id)
            .values(status="reauthorization_required")
        )
        await session.commit()
        return False

    data = await _post_oauth(
        "/oauth/refreshToken",
        {
            "appId": grant.app_id,
            "refreshToken": decrypt(grant.refresh_token_encrypted),
            "secretKey": get_settings().baidu_secret_key,
            "userId": grant.oauth_user_id,
        },
    )
    access_token = str(data.get("accessToken") or "")
    refresh_token = str(data.get("refreshToken") or "")
    if not access_token or not refresh_token:
        raise BaiduOAuthError(
            "incomplete_refresh", "百度返回的刷新令牌信息不完整。"
        )
    expires_at, refresh_expires_at = _expiry_from_token_data(data)
    encrypted_access = encrypt(access_token)
    encrypted_refresh = encrypt(refresh_token)
    grant.access_token_encrypted = encrypted_access
    grant.refresh_token_encrypted = encrypted_refresh
    grant.expires_at = expires_at
    grant.refresh_expires_at = refresh_expires_at
    grant.status = "active"
    await session.execute(
        update(BaiduAccount)
        .where(BaiduAccount.oauth_grant_id == grant.id)
        .values(
            access_token_encrypted=encrypted_access,
            refresh_token_encrypted=encrypted_refresh,
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
            status="active",
        )
    )
    await session.commit()
    return True


async def refresh_expiring_oauth_grants(session: AsyncSession) -> dict[str, int]:
    now = datetime.utcnow()
    grants = (
        await session.scalars(
            select(BaiduOAuthGrant).where(
                BaiduOAuthGrant.status == "active",
                BaiduOAuthGrant.expires_at <= now + _REFRESH_AHEAD,
            )
        )
    ).all()
    result = {"checked": len(grants), "refreshed": 0, "failed": 0}
    for grant in grants:
        try:
            if await refresh_grant(session, grant):
                result["refreshed"] += 1
        except Exception:  # noqa: BLE001
            result["failed"] += 1
            await session.rollback()
            logger.exception("百度 OAuth Token 刷新失败 grant_id=%s", grant.id)
    return result
