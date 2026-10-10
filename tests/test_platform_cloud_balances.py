import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import platform_balances as b, platform_cloud_balances as cloud
from app.api import platform_console, platform_balances as api
from app.platform_billing_observations import load_observations
from app.security.auth import AuthContext, require_auth


def settings(**values):
    defaults = dict(deepseek_api_key='', deepseek_base_url='https://api.deepseek.com',
        aliyun_balance_access_key_id='', aliyun_balance_access_key_secret='', aliyun_balance_security_token='',
        volcengine_balance_access_key_id='PUBLIC-FIXTURE-ID', volcengine_balance_access_key_secret='PRIVATE-FIXTURE-SECRET',
        tencent_balance_secret_id='PUBLIC-FIXTURE-ID', tencent_balance_secret_key='PRIVATE-FIXTURE-SECRET',
        qianfan_balance_access_key_id='PUBLIC-FIXTURE-ID', qianfan_balance_access_key_secret='PRIVATE-FIXTURE-SECRET')
    return SimpleNamespace(**{**defaults, **values})


def test_signatures_match_frozen_independent_official_sdk_vectors():
    # Cross-checked offline with volcengine 1.0.228, tencentcloud common 3.1.187,
    # bce-python-sdk 0.9.79. Public dummy keys; no SDK dependency at runtime.
    assert cloud.volcengine_headers('fixture-id', 'fixture-secret', '20261011T020304Z')['Authorization'].endswith(
        'Signature=e5a1cf443ea3da99bab5d3c84ebbf2e9dfa4e7c8e28be8223e4a13c98f3774c5')
    from datetime import datetime, timezone
    timestamp = int(datetime(2026, 10, 11, 2, 3, 4, tzinfo=timezone.utc).timestamp())
    assert cloud.tencent_headers('fixture-id', 'fixture-secret', timestamp)['Authorization'].endswith(
        'Signature=c8331de491ec12f3f8470f4b8616dd48e3077b4a54f7ec9fbaa40a71e3526e81')
    assert cloud.bce_authorization('fixture-id', 'fixture-secret', '2026-10-11T02:03:04Z').endswith(
        '/511dfa1ead61b401915f526dcd3b2a6bd291c2b5e69f9b51bbdb338d2336aa61')


@pytest.mark.parametrize('adapter,fields', [
    (cloud.volcengine, ('volcengine_balance_access_key_id', 'volcengine_balance_access_key_secret')),
    (cloud.tencent, ('tencent_balance_secret_id', 'tencent_balance_secret_key')),
    (cloud.qianfan, ('qianfan_balance_access_key_id', 'qianfan_balance_access_key_secret'))])
def test_dedicated_credentials_required_no_model_key_substitution(monkeypatch, adapter, fields):
    async def reject(*a, **kw):
        raise AssertionError('No transport without billing credentials')
    monkeypatch.setattr(b, 'json_request', reject)
    for field in fields:
        row = asyncio.run(adapter(settings(**{field: '', 'dashscope_api_key': 'MODEL-KEY'})))
        assert row['state'] == 'not_configured' and row['balances'] == []


def test_volcengine_account_identity_and_all_returned_funds(monkeypatch):
    calls = []
    async def request(*a, **kw):
        calls.append((a, kw))
        return {'ResponseMetadata': {}, 'Result': {'AccountID': 2131454985, 'AvailableBalance': '9.35',
            'CashBalance': '10.35', 'FreezeAmount': '1', 'CreditLimit': '0', 'ArrearsBalance': '0', 'secret': 'PRIVATE'}}, None
    monkeypatch.setattr(b, 'json_request', request)
    row = asyncio.run(cloud.volcengine(settings(volcengine_balance_account_id='2131454985')))
    assert row['billing_account_id'] == '2131454985'
    assert row['balances'][0] == {'currency': 'CNY', 'available': '9.35', 'cash': '10.35', 'credit': '0', 'frozen': '1', 'arrears': '0'}
    assert calls[0][0] == ('GET', 'https://open.volcengineapi.com/?Action=QueryBalanceAcct&Version=2022-01-01')
    assert 'cn-north-1/billing/request' in calls[0][1]['headers']['Authorization']
    assert 'PRIVATE' not in str(row)
    mismatch = asyncio.run(cloud.volcengine(settings(volcengine_balance_account_id='OTHER')))
    assert mismatch['state'] == 'account_mismatch' and not mismatch['balances']


def test_tencent_real_balance_cents_negative_debt_and_credit_are_separate(monkeypatch):
    calls = []
    async def request(*a, **kw):
        calls.append((a, kw))
        return {'Response': {'Uin': 100052496461, 'Balance': 999999, 'RealBalance': -1,
            'CashAccountBalance': 2000, 'PresentAccountBalance': 300, 'CreditAmount': 100000,
            'RealCreditBalance': 99999, 'FreezeAmount': 100, 'OweAmount': 2201, 'PRIVATE': 'SECRET'}}, None
    monkeypatch.setattr(b, 'json_request', request)
    row = asyncio.run(cloud.tencent(settings(tencent_balance_account_uin='100052496461')))
    funds = row['balances'][0]
    assert funds['available'] == '-0.01' and funds['cash'] == '20' and funds['grant'] == '3'
    assert funds['credit'] == '1000' and funds['available_credit'] == '999.99' and funds['arrears'] == '22.01'
    assert calls[0][0] == ('POST', 'https://billing.tencentcloudapi.com/')
    assert calls[0][1]['content'] == b'{}'
    assert calls[0][1]['headers']['X-TC-Action'] == 'DescribeAccountBalance'
    assert 'PRIVATE' not in str(row)
    assert asyncio.run(cloud.tencent(settings(tencent_balance_account_uin='OTHER')))['state'] == 'account_mismatch'


def test_qianfan_zero_cash_is_available_not_baidu_advertising_balance(monkeypatch):
    calls = []
    async def request(*a, **kw):
        calls.append((a, kw)); return {'cashBalance': 0, 'SECRET': 'PRIVATE'}, None
    monkeypatch.setattr(b, 'json_request', request)
    row = asyncio.run(cloud.qianfan(settings()))
    assert row['balances'] == [{'currency': 'CNY', 'available': '0', 'cash': '0', 'balance_kind': 'cash'}]
    assert calls[0][0] == ('POST', 'https://billing.baidubce.com/v1/finance/cash/balance')
    assert '/host;x-bce-date/' in calls[0][1]['headers']['Authorization']
    assert 'PRIVATE' not in str(row)


@pytest.mark.parametrize('adapter,payload', [
    (cloud.volcengine, {'ResponseMetadata': {'Error': {'Code': 'AccessDenied', 'Message': 'PRIVATE'}}}),
    (cloud.tencent, {'Response': {'Error': {'Code': 'UnauthorizedOperation', 'Message': 'PRIVATE'}}}),
    (cloud.qianfan, {'code': 'AccessDenied', 'message': 'PRIVATE'})])
def test_supplier_error_is_sanitized_and_never_becomes_zero(monkeypatch, adapter, payload):
    async def request(*a, **kw): return payload, None
    monkeypatch.setattr(b, 'json_request', request)
    row = asyncio.run(adapter(settings()))
    assert row['state'] == 'permission_denied' and row['balances'] == [] and 'PRIVATE' not in str(row)


@pytest.mark.parametrize('adapter,payload', [
    (cloud.volcengine, {'ResponseMetadata': {}, 'Result': {'AccountID': 1}}),
    (cloud.tencent, {'Response': {'Uin': 1, 'Balance': 2000}}),
    (cloud.qianfan, {}),
    (cloud.qianfan, {'cashBalance': 'NaN'})])
def test_missing_or_malformed_balance_fails_instead_of_inferring(monkeypatch, adapter, payload):
    async def request(*a, **kw): return payload, None
    monkeypatch.setattr(b, 'json_request', request)
    with pytest.raises(ValueError): asyncio.run(adapter(settings()))


def test_user_observations_have_correct_remaining_fraction_and_dated_source():
    row = load_observations(settings())
    assert row['state'] == 'available' and row['verified_on'] == '2026-10-11'
    assert len(row['packages']) == 9 and len(row['reported_balances']) == 4
    packages = {p['id']: p for p in row['packages']}
    for code in ('baidu_mobile_top50', 'baidu_pc_top50', 'bid_domains'):
        assert packages[code]['quota_warning'] == 'normal'
    assert packages['baidu_pc_ranking']['remaining'] == 36877
    assert {p['id'] for p in row['packages'] if p['quota_warning'] == 'exhausted'} == {'360_pc_ranking', 'baidu_mobile_ranking'}
    assert row['package_account']['balance'] == '0'
    assert row['services'][0]['state'] == 'not_opened'
    assert 'queried_at' not in row  # Never stamp file data with today's query time.


@pytest.mark.parametrize('mutation', ['invalid_total', 'duplicate', 'future', 'large', 'secret'])
def test_invalid_observations_fail_independently_and_never_expose_raw_file(tmp_path, mutation):
    from pathlib import Path
    data = json.loads((Path(__file__).parent.parent / 'config/platform_billing_observations.json').read_text(encoding='utf-8'))
    if mutation == 'invalid_total': data['packages'][0]['used'] = 0
    if mutation == 'duplicate': data['packages'].append(data['packages'][0])
    if mutation == 'future': data['verified_on'] = '2099-01-01'
    if mutation == 'secret': data['unexpected_key'] = 'PRIVATE'
    path = tmp_path / 'observations.json'
    path.write_text('PRIVATE' * 10000 if mutation == 'large' else json.dumps(data), encoding='utf-8')
    row = load_observations(settings(platform_billing_observations_path=str(path)))
    assert 'PRIVATE' not in str(row) and str(path) not in str(row)
    assert row['state'] == ('available' if mutation == 'secret' else 'unavailable')


def test_global_admin_only_cloud_routes_without_database_or_controls(monkeypatch):
    app = FastAPI(); app.include_router(platform_console.router)
    monkeypatch.setattr(api, 'get_settings', settings)
    monkeypatch.setenv('API_CONTROLS_ENABLED', 'false')
    @asynccontextmanager
    async def reject_db(): raise AssertionError('Cloud-only route must not use DB'); yield
    monkeypatch.setattr(api, 'async_session_factory', reject_db)
    calls = []
    async def query(key, factory, refresh):
        calls.append(key)
        return b.result('available', balances=[{'currency': 'CNY', 'available': '0'}])
    monkeypatch.setattr(b, 'query_cached', query)
    with TestClient(app) as client:
        assert client.get('/api/v1/admin/console/balances?provider=tencent').status_code == 401
        app.dependency_overrides[require_auth] = lambda: AuthContext(7, 'bound', 'user', 1, {'settings.accounts': 'edit', 'settings.customers': 'edit'})
        assert client.get('/api/v1/admin/console/balances?provider=tencent').status_code == 403
        assert not calls
        app.dependency_overrides[require_auth] = lambda: AuthContext(7, 'admin', 'user', None, {'settings.accounts': 'edit', 'settings.customers': 'edit'})
        for provider in ('volcengine', 'tencent', 'qianfan', 'kimi', 'dataforseo'):
            response = client.get('/api/v1/admin/console/balances', params={'provider': provider, 'refresh': 'true'})
            assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
            assert response.headers['vary'] == 'Authorization'
            assert response.json()['rows'][0]['provider'] == provider
            assert 'PRIVATE' not in response.text and 'PUBLIC-FIXTURE' not in response.text
        assert client.get('/api/v1/admin/console/balances?provider=tencent&account_id=1').status_code == 422


def test_live_query_failure_preserves_only_separate_historical_observation(monkeypatch):
    from fastapi import Response
    monkeypatch.setattr(api, 'get_settings', settings)
    monkeypatch.setenv('API_CONTROLS_ENABLED', 'false')
    async def query(*a, **kw): return b.result('permission_denied')
    monkeypatch.setattr(b, 'query_cached', query)
    row = asyncio.run(api.read_balances(Response(), provider='tencent', account_id=None, after_id=0))
    assert row['rows'][0]['balances'] == [] and row['rows'][0]['warning'] == 'unknown'
    history = next(r for r in row['observations']['reported_balances'] if r['provider'] == 'tencent')
    assert history['amount'] == '20.00'
