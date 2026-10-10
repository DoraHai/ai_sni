"""Fixed read-only billing calls; cloud credentials never reuse model keys.

Volcengine: /docs/6269/1223898 and /docs/6269/130258
Tencent: /document/api/555/20253 and /document/api/213/30654
Baidu: /doc/Finance/s/Skhtyytwu and /doc/Reference/s/njwvz1yfu
"""
from datetime import datetime, timezone
import hashlib
import hmac
from decimal import Decimal
from urllib.parse import quote
from app import platform_balances as b


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def mac(key, value):
    return hmac.new(key, value.encode(), hashlib.sha256).digest()


def volcengine_headers(key, secret, stamp):
    query = 'Action=QueryBalanceAcct&Version=2022-01-01'
    headers = {'host': 'open.volcengineapi.com', 'x-date': stamp,
               'x-content-sha256': sha('')}
    signed = ';'.join(sorted(headers))
    canonical = '\n'.join(['GET', '/', query,
        ''.join(k + ':' + headers[k] + '\n' for k in sorted(headers)), signed, sha('')])
    scope = stamp[:8] + '/cn-north-1/billing/request'
    signing = mac(mac(mac(mac(secret.encode(), stamp[:8]), 'cn-north-1'), 'billing'), 'request')
    signature = mac(signing, '\n'.join(['HMAC-SHA256', stamp, scope, sha(canonical)])).hex()
    headers['Authorization'] = f'HMAC-SHA256 Credential={key}/{scope}, SignedHeaders={signed}, Signature={signature}'
    return headers


def tencent_headers(key, secret, timestamp):
    # TC3 v3, fixed action, no region and no mutating finance:trade action.
    host, content_type, action = 'billing.tencentcloudapi.com', 'application/json', 'DescribeAccountBalance'
    canonical = '\n'.join(['POST', '/', '',
        f'content-type:{content_type}\nhost:{host}\n',
        'content-type;host', sha('{}')])
    date = datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y-%m-%d')
    scope = date + '/billing/tc3_request'
    signing = mac(mac(mac(('TC3' + secret).encode(), date), 'billing'), 'tc3_request')
    signature = mac(signing, '\n'.join(['TC3-HMAC-SHA256', str(timestamp), scope, sha(canonical)])).hex()
    return {'Host': host, 'Content-Type': content_type, 'X-TC-Action': action,
        'X-TC-Version': '2018-07-09', 'X-TC-Timestamp': str(timestamp),
        'Authorization': f'TC3-HMAC-SHA256 Credential={key}/{scope}, SignedHeaders=content-type;host, Signature={signature}'}


def bce_authorization(key, secret, stamp, method='POST', path='/v1/finance/cash/balance', headers=None):
    headers = headers or {'host': 'billing.baidubce.com', 'x-bce-date': stamp}
    signed = ';'.join(sorted(headers))
    canonical = '\n'.join([method, quote(path, safe='/~'), '', '\n'.join(
        quote(k.lower().strip(), safe='~') + ':' + quote(v.strip(), safe='~') for k, v in sorted(headers.items()))])
    prefix = f'bce-auth-v1/{key}/{stamp}/1800'
    signing = mac(secret.encode(), prefix).hex().encode()
    return prefix + '/' + signed + '/' + mac(signing, canonical).hex()


def failed(error, provider):
    return b.result(error, provider + '账务查询失败，请核对专用只读凭据、权限或稍后重试。')


async def volcengine(settings):
    key = getattr(settings, 'volcengine_balance_access_key_id', '')
    secret = getattr(settings, 'volcengine_balance_access_key_secret', '')
    if not key or not secret:
        return b.result('not_configured', '火山引擎账务只读 IAM 凭据待配置；方舟模型 Key 不能代替账务凭据。')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    data, error = await b.json_request('GET', 'https://open.volcengineapi.com/?Action=QueryBalanceAcct&Version=2022-01-01',
        headers=volcengine_headers(key, secret, stamp))
    if error:
        return failed(error, '火山引擎')
    metadata = data.get('ResponseMetadata')
    if not isinstance(metadata, dict):
        raise ValueError('invalid metadata')
    if metadata.get('Error'):
        code = (metadata['Error'].get('Code') if isinstance(metadata['Error'], dict) else '')
        return failed('permission_denied' if code in ('AccessDenied', 'Unauthorized', 'InvalidAuthorization', 'SignatureDoesNotMatch', 'InvalidAccessKey') else 'error', '火山引擎')
    info = data.get('Result')
    if not isinstance(info, dict) or type(info.get('AccountID')) is not int or info['AccountID'] <= 0:
        raise ValueError('invalid account')
    expected = getattr(settings, 'volcengine_balance_account_id', '')
    if expected and expected != str(info['AccountID']):
        return b.result('account_mismatch', '返回的火山引擎账务账号与配置不一致，未展示余额。')
    return {**b.result('available', '火山引擎账户可用余额，覆盖该账户全部云服务；并非豆包专属额度。', [{
        'currency': 'CNY', 'available': b.amount(info.get('AvailableBalance')),
        'cash': b.optional_amount(info.get('CashBalance')), 'credit': b.optional_amount(info.get('CreditLimit')),
        'frozen': b.optional_amount(info.get('FreezeAmount')), 'arrears': b.optional_amount(info.get('ArrearsBalance'))}]),
        'billing_account_id': str(info['AccountID'])}


async def tencent(settings):
    key, secret = getattr(settings, 'tencent_balance_secret_id', ''), getattr(settings, 'tencent_balance_secret_key', '')
    if not key or not secret:
        return b.result('not_configured', '腾讯云账务只读子用户凭据待配置；余额需单独授权 finance:DescribeAccountBalance。')
    data, error = await b.json_request('POST', 'https://billing.tencentcloudapi.com/',
        headers=tencent_headers(key, secret, int(datetime.now(timezone.utc).timestamp())), content=b'{}')
    if error:
        return failed(error, '腾讯云')
    info = data.get('Response')
    if not isinstance(info, dict):
        raise ValueError('invalid response')
    if info.get('Error'):
        code = info['Error'].get('Code', '') if isinstance(info['Error'], dict) else ''
        return failed('permission_denied' if code.startswith(('AuthFailure', 'UnauthorizedOperation')) else 'rate_limited' if code.startswith('RequestLimitExceeded') else 'error', '腾讯云')
    if type(info.get('Uin')) is not int or info['Uin'] <= 0:
        raise ValueError('invalid account')
    expected = getattr(settings, 'tencent_balance_account_uin', '')
    if expected and expected != str(info['Uin']):
        return b.result('account_mismatch', '返回的腾讯云账务账号与配置不一致，未展示余额。')
    cents = lambda field: None if info.get(field) is None else format(Decimal(b.amount(info[field])) / 100, 'f')
    available = cents('RealBalance')
    if available is None:
        raise ValueError('missing real balance')
    return {**b.result('available', '腾讯云账户真实可用余额，单位已从分转换为元；同一账户的混元等服务共享余额。', [{
        'currency': 'CNY', 'available': available, 'cash': cents('CashAccountBalance'),
        'grant': cents('PresentAccountBalance'), 'income': cents('IncomeIntoAccountBalance'),
        'credit': cents('CreditAmount'), 'available_credit': cents('RealCreditBalance'),
        'frozen': cents('FreezeAmount'), 'arrears': cents('OweAmount')}]), 'billing_account_id': str(info['Uin'])}


async def qianfan(settings):
    key, secret = getattr(settings, 'qianfan_balance_access_key_id', ''), getattr(settings, 'qianfan_balance_access_key_secret', '')
    if not key or not secret:
        return b.result('not_configured', '百度智能云财务只读 AK/SK 待配置；千帆模型 Key 不能代替账务凭据。')
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    headers = {'Host': 'billing.baidubce.com', 'x-bce-date': stamp, 'Content-Type': 'application/json; charset=utf-8',
               'Authorization': bce_authorization(key, secret, stamp)}
    data, error = await b.json_request('POST', 'https://billing.baidubce.com/v1/finance/cash/balance', headers=headers, content=b'{}')
    if error:
        return failed(error, '百度智能云')
    if data.get('code'):
        return failed('permission_denied' if data['code'] in ('AccessDenied', 'InvalidAccessKeyId', 'SignatureDoesNotMatch') else 'error', '百度智能云')
    cash = b.amount(data.get('cashBalance'))
    return b.result('available', '百度智能云接口返回现金账户余额；其他赠额、代金券或资源包未由此接口返回，区别于百度推广账户。',
                    [{'currency': 'CNY', 'available': cash, 'cash': cash, 'balance_kind': 'cash'}])
