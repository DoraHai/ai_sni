"""Fixed, read-only supplier balance adapters. No model generation or DDL.

DeepSeek: https://api-docs.deepseek.com/api/get-user-balance
Aliyun: https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-queryaccountbalance
RPC signing: https://www.alibabacloud.com/help/en/ros/signature-method
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import hmac
import time
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit
from uuid import uuid4
import httpx

CACHE_SECONDS = 60
COOLDOWN_SECONDS = 5
_slots = asyncio.Semaphore(4)
_cache = OrderedDict()
_locks = {}


def amount(value):
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('missing amount')
    try:
        parsed = Decimal(str(value).replace(',', ''))
        if not parsed.is_finite() or abs(parsed) > Decimal('1000000000000'):
            raise ValueError('invalid amount')
        return format(parsed, 'f')
    except InvalidOperation:
        raise ValueError('invalid amount') from None


def optional_amount(value):
    return None if value is None else amount(value)


def result(state, note='', balances=None):
    return {'state': state, 'note': note, 'balances': balances or [],
            'queried_at': datetime.now(timezone.utc).isoformat(), 'cached': False}


async def json_request(method, url, **kwargs):
    async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
        async with client.stream(method, url, **kwargs) as response:
            if response.status_code in (401, 403):
                return None, 'permission_denied'
            if response.status_code == 429:
                return None, 'rate_limited'
            if response.status_code != 200:
                return None, 'error'
            raw = bytearray()
            async for part in response.aiter_bytes():
                raw.extend(part)
                if len(raw) > 65536:
                    raise ValueError('oversized response')
            import json
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('invalid response')
            return data, None


async def deepseek(settings):
    key = settings.deepseek_api_key
    if not key:
        return result('not_configured', '尚未配置 DeepSeek 官方接口凭据；百炼上的 DeepSeek 模型不代表官方账户。')
    base = urlsplit(settings.deepseek_base_url)
    if base.scheme != 'https' or base.hostname != 'api.deepseek.com' or base.port not in (None, 443) or base.username or base.password:
        return result('unsupported', '当前 DeepSeek 使用其他接入点，不能用该凭据查询官方账户。')
    data, error = await json_request('GET', 'https://api.deepseek.com/user/balance',
                                    headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    if error:
        return result(error, 'DeepSeek 余额查询失败，请核对授权或稍后重试。')
    infos = data.get('balance_infos')
    if not isinstance(infos, list) or not infos or len(infos) > 10 or type(data.get('is_available')) is not bool:
        raise ValueError('invalid balance')
    balances = []
    for row in infos:
        if row.get('currency') not in ('CNY', 'USD'):
            raise ValueError('invalid currency')
        balances.append({'currency': row['currency'], 'available': amount(row.get('total_balance')),
                         'cash': optional_amount(row.get('topped_up_balance')), 'grant': optional_amount(row.get('granted_balance'))})
    return {**result('available', 'DeepSeek 官方账户可用余额（含未到期赠额）。', balances),
            'sufficient': data['is_available']}


def rpc_signature(params, secret, method='POST'):
    encode = lambda value: quote(str(value), safe='~')
    canonical = '&'.join(encode(k) + '=' + encode(v) for k, v in sorted(params.items()))
    payload = method + '&%2F&' + encode(canonical)
    return base64.b64encode(hmac.new((secret + '&').encode(), payload.encode(), hashlib.sha1).digest()).decode()


async def aliyun(settings):
    key, secret = settings.aliyun_balance_access_key_id, settings.aliyun_balance_access_key_secret
    if not key or not secret:
        return result('not_configured', '需配置阿里云费用查询只读 AccessKey；百炼模型 API Key 无法查询账户余额。')
    params = {'Action': 'QueryAccountBalance', 'Version': '2017-12-14', 'Format': 'JSON',
              'AccessKeyId': key, 'SignatureMethod': 'HMAC-SHA1', 'SignatureVersion': '1.0',
              'SignatureNonce': str(uuid4()), 'Timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    if settings.aliyun_balance_security_token:
        params['SecurityToken'] = settings.aliyun_balance_security_token
    params['Signature'] = rpc_signature(params, secret)
    data, error = await json_request('POST', 'https://business.aliyuncs.com/', data=params)
    if error:
        return result(error, '阿里云账户余额查询失败，请核对只读授权或稍后重试。')
    if data.get('Success') is not True:
        return result('permission_denied' if data.get('Code') in ('Forbidden', 'Forbidden.RAM', 'InvalidAccessKeyId.NotFound', 'SignatureDoesNotMatch') else 'error',
                      '阿里云费用查询未成功，请核对凭据及费用查询权限。')
    info = data.get('Data')
    if not isinstance(info, dict) or info.get('Currency') not in ('CNY', 'USD', 'JPY'):
        raise ValueError('invalid balance')
    return result('available', '阿里云账户余额，覆盖该账户全部云服务；并非百炼专属额度。',
                  [{'currency': info['Currency'], 'available': amount(info.get('AvailableAmount')),
                    'cash': optional_amount(info.get('AvailableCashAmount')), 'credit': optional_amount(info.get('CreditAmount'))}])


async def baidu(account):
    from app.baidu.client import BaiduAPIClient
    from app.baidu.services.account import AccountService
    from app.security.crypto import decrypt
    client = BaiduAPIClient(username=account['username'], access_token=decrypt(account['token']),
                           tenant_id=account['tenant_id'], baidu_account_id=account['id'], timeout=5)
    data = await AccountService(client).get_account_info(['balance'])
    info = data.get('data')
    if isinstance(info, list):
        info = info[0] if info else None
    if not isinstance(info, dict):
        raise ValueError('invalid balance')
    return result('available', '百度推广账户实时查询。', [{'currency': 'CNY', 'available': amount(info.get('balance'))}])


async def query_cached(cache_key, factory, refresh=False):
    # Secrets enter only a one-way internal fingerprint; never response/logs.
    key = hashlib.sha256(cache_key.encode()).hexdigest()
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            cached = _cache.get(key)
            if cached and time.monotonic() - cached[0] < (COOLDOWN_SECONDS if refresh else CACHE_SECONDS):
                return {**cached[1], 'cached': True}
            try:
                async with asyncio.timeout(8), _slots:
                    row = await factory()
            except TimeoutError:
                row = result('timeout', '余额查询超时，未取得最新余额。')
            except Exception:
                row = result('error', '余额暂时无法查询，未取得最新余额。')
            _cache[key] = (time.monotonic(), row)
            _cache.move_to_end(key)
            while len(_cache) > 128:
                _cache.popitem(last=False)
            return dict(row)
    finally:
        # Keep an active lock shared by waiters; prune when quiescent.
        if not lock.locked() and not getattr(lock, '_waiters', None):
            _locks.pop(key, None)


def with_warnings(row, settings):
    thresholds = {'CNY': amount(getattr(settings, 'platform_balance_warning_cny', 100)),
                  'USD': amount(getattr(settings, 'platform_balance_warning_usd', 10))}
    low = row.get('sufficient') is False
    measured = False
    values = []
    for value in row['balances']:
        threshold = thresholds.get(value['currency'])
        warning = 'unknown'
        if row['state'] == 'available' and threshold is not None:
            measured = True
            warning = 'low' if Decimal(value['available']) <= Decimal(threshold) else 'normal'
            low = low or warning == 'low'
        values.append({**value, 'warning': warning, 'warning_threshold': threshold})
    return {**row, 'balances': values, 'warning': 'low' if low else 'normal' if measured else 'unknown'}
