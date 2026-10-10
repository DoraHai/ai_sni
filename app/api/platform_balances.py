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
from app import platform_cloud_balances as cloud_balances
from app.platform_billing_observations import load_observations
from app.platform_balance_coverage import load_coverage, query_managed

router = APIRouter()


# Included by platform_console.router, which requires global console admin.
@router.get('/balances')
async def read_balances(response: Response, provider: Literal['deepseek', 'aliyun', 'baidu', 'volcengine', 'tencent', 'qianfan', 'kimi', 'dataforseo'] | None = None,
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
    coverage, managed = await load_coverage(settings, async_session_factory) if provider is None else (None, [])
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
    cloud_specs = (
        ('volcengine', '火山引擎账户（含豆包）', cloud_balances.volcengine,
         ('volcengine_balance_access_key_id', 'volcengine_balance_access_key_secret', 'volcengine_balance_account_id')),
        ('tencent', '腾讯云账户（含混元）', cloud_balances.tencent,
         ('tencent_balance_secret_id', 'tencent_balance_secret_key', 'tencent_balance_account_uin')),
        ('qianfan', '百度智能云账户（含千帆）', cloud_balances.qianfan,
         ('qianfan_balance_access_key_id', 'qianfan_balance_access_key_secret')),
    )
    for code, name, adapter, fields in cloud_specs:
        if provider in (None, code):
            identities.append({'id': code, 'provider': code, 'name': name, 'tenant_id': None, 'source': 'provider_api'})
            cache_key = code + ':' + '\0'.join(getattr(settings, field, '') for field in fields)
            jobs.append(balances.query_cached(cache_key, lambda fn=adapter: fn(settings), refresh))
    async def direct_kimi():
        key = getattr(settings, 'kimi_balance_api_key', '')
        return await balances.kimi('https://api.moonshot.cn/v1', key) if key else balances.result('not_configured', 'Kimi 官方余额查询凭据待配置。')
    async def direct_dataforseo():
        login, password = getattr(settings, 'dataforseo_balance_login', ''), getattr(settings, 'dataforseo_balance_password', '')
        return await balances.dataforseo('https://api.dataforseo.com/v3', login, password) if login and password else balances.result('not_configured', 'DataForSEO 只读账户查询凭据待配置。')
    for code, name, adapter, fields in (
        ('kimi', 'Kimi 官方账户', direct_kimi, ('kimi_balance_api_key',)),
        ('dataforseo', 'DataForSEO 官方账户', direct_dataforseo, ('dataforseo_balance_login', 'dataforseo_balance_password'))):
        if provider in (None, code):
            managed_code = 'geo_kimi' if code == 'kimi' else code
            if provider is None and any(item['code'] == managed_code for item in managed) and not all(getattr(settings, field, '') for field in fields):
                continue
            identities.append({'id': code, 'provider': code, 'name': name, 'tenant_id': None, 'source': 'provider_api'})
            jobs.append(balances.query_cached(code + ':' + '\0'.join(getattr(settings, field, '') for field in fields), adapter, refresh))
    if coverage:
        for row in coverage['rows']:
            code = row['connection_id'].split('.', 1)[1]
            row['balance_row_id'] = {'dashscope': 'aliyun', 'geo_qwen': 'aliyun', 'geo_doubao': 'volcengine',
                'geo_hunyuan': 'tencent', 'geo_qianfan': 'qianfan', 'geo_kimi': 'kimi', 'dataforseo': 'dataforseo'}.get(code, row['balance_row_id'])
            if code in {'dashscope', 'geo_qwen', 'geo_doubao', 'geo_hunyuan', 'geo_qianfan'}:
                row['billing_link_state'] = 'account_to_verify'
                row['note'] += ' 下方结果为平台所配置账务账号；该模型连接的实际扣费归属仍需核对，不按连接累计金额。'
            if code == 'tencent_wsa':
                row['note'] += ' 如需查询，须先确认产品开通及其实际扣费账户；不得据同属腾讯云自动认定共享账号。'
    managed_refs = {}
    # Reused credentials are one query result; different credentials do not
    # prove different supplier billing accounts. No total money is computed.
    if provider is None:
        import hashlib
        for item in managed:
            key = item['code'] + ':' + str(item['base_url']) + ':' + '\0'.join(item['secrets'].values())
            if item['code'] in {'deepseek', 'geo_deepseek'}:
                key = 'deepseek:' + str(item['base_url']) + ':' + item['secrets']['api_key']
            fingerprint = hashlib.sha256(key.encode()).hexdigest()
            if item['code'] in {'deepseek', 'geo_deepseek'} and item['base_url'] == settings.deepseek_base_url and item['secrets']['api_key'] == settings.deepseek_api_key:
                row_id = 'deepseek'
            elif item['code'] == 'geo_kimi' and balances.official_base(item['base_url'], 'api.moonshot.cn') and item['secrets']['api_key'] == getattr(settings, 'kimi_balance_api_key', ''):
                row_id = 'kimi'
            elif item['code'] == 'dataforseo' and balances.official_base(item['base_url'], 'api.dataforseo.com') and item['secrets']['login'] == getattr(settings, 'dataforseo_balance_login', '') and item['secrets']['password'] == getattr(settings, 'dataforseo_balance_password', ''):
                row_id = 'dataforseo'
            elif fingerprint in managed_refs:
                row_id = managed_refs[fingerprint]
            else:
                row_id = 'connection:' + item['id']
                identities.append({'id': row_id, 'provider': item['code'], 'name': item['name'],
                    'module': item['module'], 'tenant_id': None, 'source': 'managed_provider_api'})
                jobs.append(balances.query_cached(key, lambda i=item: query_managed(i), refresh))
            managed_refs[fingerprint] = row_id
            for row in coverage['rows']:
                if row['connection_id'] == item['id']:
                    row['balance_row_id'] = row_id
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
            'coverage': coverage,
            'observations': load_observations(settings),
            'next_after_id': next_after_id, 'cache_seconds': balances.CACHE_SECONDS,
            'refresh_cooldown_seconds': balances.COOLDOWN_SECONDS}
