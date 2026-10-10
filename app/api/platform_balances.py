"""Superadmin balance reads work even when API controls schema is absent."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, text
from app.config import get_settings
from app.api_connection_config import runtime_scope
from app.database import async_session_factory
from app.models import BaiduAccount, Tenant
from app import platform_balances as balances

router = APIRouter()


# Included by platform_console.router, which requires global console admin.
@router.get('/balances')
async def read_balances(response: Response, provider: Literal['deepseek', 'aliyun', 'baidu'] | None = None,
                        account_id: int | None = Query(None, gt=0), refresh: bool = False,
                        after_id: int = Query(0, ge=0)):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Authorization'
    if account_id is not None and provider != 'baidu':
        raise HTTPException(422, '指定账户仅适用于百度推广余额查询')
    try:
        async with runtime_scope('sem'):
            settings = get_settings()
    except Exception:
        raise HTTPException(503, '平台余额凭据暂时无法读取，请稍后重试') from None
    accounts = []
    accounts_available = True
    if provider in (None, 'baidu'):
        try:
            async with asyncio.timeout(5), async_session_factory() as session:
                await session.execute(text('SET TRANSACTION READ ONLY'))
                stmt = select(BaiduAccount.id, BaiduAccount.tenant_id, BaiduAccount.baidu_username,
                              BaiduAccount.access_token_encrypted, Tenant.name).join(Tenant, Tenant.id == BaiduAccount.tenant_id).where(BaiduAccount.status == 'active', BaiduAccount.id > after_id).order_by(BaiduAccount.id).limit(11)
                if account_id is not None:
                    stmt = stmt.where(BaiduAccount.id == account_id)
                raw = (await session.execute(stmt)).all()
                accounts = [{'id': r[0], 'tenant_id': r[1], 'username': r[2], 'token': r[3], 'tenant_name': r[4]} for r in raw]
        except Exception:
            accounts_available = False
            if provider == 'baidu':
                raise HTTPException(503, '推广账户清单暂时无法读取，请稍后重试') from None
        if account_id is not None and not accounts:
            raise HTTPException(404, '未找到有效推广账户')
    next_after_id = accounts[9]['id'] if len(accounts) > 10 else None
    jobs = []
    identities = []
    if provider in (None, 'deepseek'):
        identities.append({'id': 'deepseek', 'provider': 'deepseek', 'name': 'DeepSeek 官方账户', 'tenant_id': None, 'source': 'provider_api'})
        jobs.append(balances.query_cached('deepseek:'+settings.deepseek_base_url+':'+settings.deepseek_api_key, lambda: balances.deepseek(settings), refresh))
    if provider in (None, 'aliyun'):
        identities.append({'id': 'aliyun', 'provider': 'aliyun', 'name': '阿里云账户（含百炼）', 'tenant_id': None, 'source': 'provider_api'})
        jobs.append(balances.query_cached('aliyun:'+settings.aliyun_balance_access_key_id+':'+settings.aliyun_balance_access_key_secret+':'+settings.aliyun_balance_security_token, lambda: balances.aliyun(settings), refresh))
    for account in accounts[:10]:
        identities.append({'id': 'baidu:'+str(account['id']), 'provider': 'baidu', 'account_id': account['id'],
                           'tenant_id': account['tenant_id'], 'name': account['username'], 'tenant_name': account['tenant_name'], 'source': 'provider_api'})
        jobs.append(balances.query_cached('baidu:'+str(account['id'])+':'+str(account['tenant_id'])+':'+account['username']+':'+account['token'], lambda a=account: balances.baidu(a), refresh))
    rows = await asyncio.gather(*jobs)
    if not accounts_available:
        identities.append({'id': 'baidu', 'provider': 'baidu', 'name': '百度推广账户', 'source': 'provider_api', 'tenant_id': None})
        rows.append(balances.result('unavailable', '推广账户清单读取失败，余额未知。'))
    rows = [balances.with_warnings(row, settings) for row in rows]
    return {'schema': 1, 'state': 'available', 'generated_at': datetime.now(timezone.utc).isoformat(),
            'rows': [{**identity, **row} for identity, row in zip(identities, rows)],
            'next_after_id': next_after_id, 'cache_seconds': balances.CACHE_SECONDS,
            'refresh_cooldown_seconds': balances.COOLDOWN_SECONDS}
