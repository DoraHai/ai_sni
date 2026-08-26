"""百度服务商 OAuth：前端发起、公开回调、授权账户列表。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.oauth import (
    BaiduOAuthError,
    create_authorization_url,
    exchange_auth_code,
    fetch_authorized_accounts,
    oauth_callback_url,
    oauth_is_configured,
    persist_authorization,
    verify_callback_signature,
)
from app.config import get_settings
from app.database import async_session_factory, get_session
from app.models import BaiduAccount, BaiduOAuthGrant, Tenant
from app.module_scope import get_tenant_module
from app.scheduler import INITIAL_KEYWORD_HISTORY_DAYS, refresh_keyword_workbench_snapshot
from app.security.auth import AuthContext, require_scoped_auth
from app.sem_asset_sync import public_sync_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/oauth/baidu", tags=["百度 OAuth"])
callback_router = APIRouter(tags=["百度 OAuth 回调"])
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class AuthorizationRequest(BaseModel):
    tenant_id: int = Field(..., gt=0)
    return_path: str = Field("/onboarding", max_length=300)
    bind_to_tenant: bool = False


def _ensure_can_bind(ctx: AuthContext, tenant_id: int) -> None:
    ctx.ensure_tenant(tenant_id)
    if not ctx.can_edit("onboarding"):
        raise HTTPException(403, "当前角色只有查看权限，不能绑定百度推广账户。")


def _ensure_can_rebind(ctx: AuthContext) -> None:
    if not ctx.can_edit("settings.customers"):
        raise HTTPException(403, "只有客户与模块管理员可以重新绑定账户归属。")


@router.get("/status")
async def oauth_status(
    tenant_id: int = Query(..., gt=0),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    await get_tenant_module(session, tenant_id, "sem")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")

    rows = (
        await session.execute(
            select(BaiduAccount, BaiduOAuthGrant)
            .outerjoin(
                BaiduOAuthGrant, BaiduOAuthGrant.id == BaiduAccount.oauth_grant_id
            )
            .where(
                BaiduAccount.tenant_id == tenant_id,
                BaiduAccount.status != "archived",
            )
            .order_by(BaiduAccount.status, BaiduAccount.baidu_username)
        )
    ).all()
    accounts = []
    for account, grant in rows:
        accounts.append(
            {
                "id": account.id,
                "username": account.baidu_username,
                "ucid": account.baidu_ucid,
                "status": account.status,
                "auth_mode": account.auth_mode,
                "account_role": account.account_role,
                "authorization_name": grant.master_name if grant else None,
                "authorization_type": grant.account_type if grant else None,
                "authorized_at": (
                    account.authorized_at.isoformat() if account.authorized_at else None
                ),
                "token_expires_at": account.expires_at.isoformat(),
                "refresh_expires_at": (
                    account.refresh_expires_at.isoformat()
                    if account.refresh_expires_at
                    else None
                ),
                "last_synced_at": (
                    account.last_synced_at.isoformat()
                    if account.last_synced_at
                    else None
                ),
                "sync_status": account.sync_status,
                "last_sync_error": public_sync_error(account.last_sync_error),
            }
        )
    return {
        "configured": oauth_is_configured(),
        "callback_url": oauth_callback_url(),
        "tenant_id": tenant_id,
        "tenant_name": tenant.name,
        "accounts": accounts,
    }


@router.post("/authorize")
async def authorize(
    req: AuthorizationRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if req.bind_to_tenant:
        ctx.ensure_tenant(req.tenant_id)
        _ensure_can_rebind(ctx)
    else:
        _ensure_can_bind(ctx, req.tenant_id)
    if await session.get(Tenant, req.tenant_id) is None:
        raise HTTPException(404, "客户不存在")
    # 无论普通接入还是客户定向重绑，都不能给未开通/已停用 SEM 的客户建立推广账户。
    await get_tenant_module(session, req.tenant_id, "sem")
    try:
        url = await create_authorization_url(
            session,
            tenant_id=req.tenant_id,
            requested_by_user_id=ctx.user_id,
            return_path=req.return_path,
            bind_to_tenant=req.bind_to_tenant,
        )
    except BaiduOAuthError as exc:
        raise HTTPException(503, exc.message) from exc
    return {"authorize_url": url}


def _result_redirect(
    return_path: str = "/onboarding",
    *,
    status: str,
    code: str | None = None,
    accounts: int | None = None,
    tenant_id: int | None = None,
) -> RedirectResponse:
    settings = get_settings()
    path = return_path if return_path.startswith("/") else "/onboarding"
    parsed = urlsplit(path)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["baidu_auth"] = status
    if code:
        query["code"] = code
    if accounts is not None:
        query["accounts"] = str(accounts)
    if tenant_id is not None:
        query["tenant_id"] = str(tenant_id)
    path_with_query = urlunsplit(("", "", parsed.path, urlencode(query), ""))
    return RedirectResponse(
        f"{settings.app_base_url.rstrip('/')}{path_with_query}", status_code=303
    )


async def _initial_sync(account_ids: list[int]) -> None:
    """授权落库后的后台首同步；失败不影响授权结果，15分钟任务还会继续重试。"""
    async with async_session_factory() as session:
        for account_id in account_ids:
            account = await session.get(BaiduAccount, account_id)
            if account is None or account.status != "active":
                continue
            tenant = await session.get(Tenant, account.tenant_id)
            if tenant is None:
                continue
            try:
                today = datetime.now(_SHANGHAI_TZ).date()
                await refresh_keyword_workbench_snapshot(
                    session,
                    tenant,
                    account,
                    today,
                    report_start_date=today
                    - timedelta(days=INITIAL_KEYWORD_HISTORY_DAYS - 1),
                )
            except Exception:  # noqa: BLE001
                await session.rollback()
                logger.exception(
                    "百度 OAuth 首次同步失败 tenant=%s account=%s",
                    tenant.id,
                    account_id,
                )


@callback_router.get("/api/oauth/baidu/callback")
async def callback(
    background_tasks: BackgroundTasks,
    appId: str = Query(..., min_length=1),
    authCode: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    userId: int = Query(..., gt=0),
    timestamp: str = Query(..., min_length=1),
    signature: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    settings = get_settings()
    if appId != settings.baidu_app_id:
        logger.warning("百度 OAuth 回调 appId 不匹配")
        return _result_redirect(status="error", code="invalid_app")

    signed_params = {
        "appId": appId,
        "authCode": authCode,
        "state": state,
        "timestamp": timestamp,
        "userId": str(userId),
    }
    try:
        if not verify_callback_signature(signed_params, signature):
            logger.warning("百度 OAuth 回调验签失败")
            return _result_redirect(status="error", code="invalid_signature")

        # 验签通过后再消费一次性 state，防止伪造请求耗掉合法 state。
        from app.baidu.oauth import consume_oauth_state

        state_row = await consume_oauth_state(session, state)
        try:
            await get_tenant_module(session, state_row.tenant_id, "sem")
        except HTTPException as exc:
            raise BaiduOAuthError(
                "sem_module_unavailable",
                "授权期间目标客户的 SEM 模块已停用，本次绑定已安全终止。",
            ) from exc
        token_data = await exchange_auth_code(auth_code=authCode, user_id=userId)
        master, oauth_accounts = await fetch_authorized_accounts(
            open_id=str(token_data.get("openId") or ""),
            access_token=str(token_data.get("accessToken") or ""),
            user_id=userId,
        )
        _, accounts, account_tenants = await persist_authorization(
            session,
            oauth_user_id=userId,
            token_data=token_data,
            master=master,
            accounts=oauth_accounts,
            target_tenant_id=(state_row.tenant_id if state_row.bind_to_tenant else None),
        )
        account_ids = [account.id for account in accounts]
        background_tasks.add_task(_initial_sync, account_ids)
        logger.info(
            "百度 OAuth 授权成功 initiated_from_tenant=%s linked_tenants=%s account_count=%s",
            state_row.tenant_id,
            [tenant.id for tenant in account_tenants],
            len(accounts),
        )
        return _result_redirect(
            state_row.return_path,
            status="success",
            accounts=len(accounts),
            tenant_id=account_tenants[0].id,
        )
    except BaiduOAuthError as exc:
        await session.rollback()
        logger.warning("百度 OAuth 回调失败 code=%s", exc.code)
        return _result_redirect(status="error", code=exc.code)
    except Exception:  # noqa: BLE001
        await session.rollback()
        logger.exception("百度 OAuth 回调处理异常")
        return _result_redirect(status="error", code="internal_error")
