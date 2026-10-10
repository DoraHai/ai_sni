import asyncio
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import platform_balances as b
from app.api import platform_console, platform_balances as api
from app.security.auth import AuthContext, require_auth


def settings(**values):
    return SimpleNamespace(deepseek_api_key='fixture-key', deepseek_base_url='https://api.deepseek.com',
        aliyun_balance_access_key_id='fixture-id', aliyun_balance_access_key_secret='fixture-secret',
        aliyun_balance_security_token='', **values)


def test_rpc_canonical_fixture_cross_checked_with_node_hmac():
    params={'Version':'2019-09-10','AccessKeyId':'testid','Action':'DescribeRegions','Format':'XML',
        'SignatureMethod':'HMAC-SHA1','SignatureNonce':'3ee8c1b8-83d3-44af-a94f-4e0ad82fd6cf',
        'SignatureVersion':'1.0','Timestamp':'2019-08-23T12:46:24Z'}
    assert b.rpc_signature(params,'testsecret','GET') == 'u5GLRDKD9xTcL8TpK+1XvnDlVx8='


def test_deepseek_strict_balances_and_credentials(monkeypatch):
    calls=[]
    async def request(method,url,**kwargs):
        calls.append((method,url,kwargs))
        return {'is_available':True,'balance_infos':[{'currency':'CNY','total_balance':'0','granted_balance':'0','topped_up_balance':'0'}],'secret':'private'},None
    monkeypatch.setattr(b,'json_request',request)
    row=asyncio.run(b.deepseek(settings()))
    assert row['balances'][0]['available']=='0'
    assert row['sufficient'] is True
    assert 'fixture' not in str(row) and 'private' not in str(row)
    assert calls[0][0:2]==('GET','https://api.deepseek.com/user/balance')
    s=settings();s.deepseek_base_url='https://proxy.example/'
    assert asyncio.run(b.deepseek(s))['state']=='unsupported'
    s.deepseek_api_key=''
    assert asyncio.run(b.deepseek(s))['state']=='not_configured'
    assert len(calls)==1


def test_aliyun_signing_uses_post_body_and_never_exposes_provider_errors(monkeypatch):
    calls=[]
    async def request(method,url,**kwargs):
        calls.append((method,url,kwargs))
        return {'Success':True,'Data':{'AvailableAmount':'1,234.50','AvailableCashAmount':'1200','CreditAmount':'34.50','Currency':'CNY'}},None
    monkeypatch.setattr(b,'json_request',request)
    row=asyncio.run(b.aliyun(settings()))
    assert row['balances'][0]['available']=='1234.50'
    assert calls[0][0:2]==('POST','https://business.aliyuncs.com/')
    assert calls[0][2]['data']['Action']=='QueryAccountBalance'
    assert 'fixture' not in str(row)
    async def failed(*a,**kw):return {'Success':False,'Code':'Forbidden','Message':'private-secret'},None
    monkeypatch.setattr(b,'json_request',failed)
    row=asyncio.run(b.aliyun(settings()))
    assert row['state']=='permission_denied' and 'private-secret' not in str(row)
    s=settings();s.aliyun_balance_access_key_secret=''
    assert asyncio.run(b.aliyun(s))['state']=='not_configured'


@pytest.mark.parametrize('raw',[None,True,'NaN','Infinity','bad',{},'1e99'])
def test_invalid_amount_never_becomes_zero(raw):
    with pytest.raises(ValueError):b.amount(raw)


def test_cached_queries_coalesce_and_manual_refresh_bypasses_old_cache(monkeypatch):
    async def run():
        b._cache.clear();b._locks.clear();calls=[]
        async def request():calls.append(1);await asyncio.sleep(.01);return b.result('available',balances=[{'currency':'CNY','available':'9'}])
        rows=await asyncio.gather(*[b.query_cached('test',request) for _ in range(3)])
        assert len(calls)==1 and rows[1]['cached'] is True
        assert (await b.query_cached('test',request,True))['cached'] is True
        key=next(iter(b._cache));stamp,row=b._cache[key];b._cache[key]=(stamp-6,row)
        assert (await b.query_cached('test',request,True))['cached'] is False
        assert len(calls)==2
        async def fail():raise RuntimeError('private-provider-key')
        row=await b.query_cached('bad',fail)
        assert row['state']=='error' and row['balances']==[] and 'private' not in str(row)
    asyncio.run(run())


def test_route_rejects_unauthorized_before_any_query_and_reads_without_schema(monkeypatch):
    app=FastAPI();app.include_router(platform_console.router)
    calls=[]
    async def query(*args,**kw):calls.append(1);return b.result('available',balances=[{'currency':'CNY','available':'3'}])
    monkeypatch.setattr(b,'query_cached',query);monkeypatch.setattr(api,'get_settings',settings)
    monkeypatch.setenv('API_CONTROLS_ENABLED','false')
    admin=lambda tenant=None:AuthContext(7,'test','管理员',tenant,{'settings.accounts':'edit','settings.customers':'edit'})
    with TestClient(app) as c:
        assert c.get('/api/v1/admin/console/balances?provider=deepseek').status_code==401
        app.dependency_overrides[require_auth]=lambda:admin(1)
        assert c.get('/api/v1/admin/console/balances?provider=deepseek').status_code==403
        assert not calls
        app.dependency_overrides[require_auth]=lambda:admin()
        r=c.get('/api/v1/admin/console/balances?provider=deepseek&refresh=true')
        assert r.status_code==200
        assert r.json()['rows'][0]['balances'][0]['available']=='3'
        assert r.headers['cache-control']=='private, no-store'
        assert r.headers['vary']=='Authorization'
        assert c.get('/api/v1/admin/console/balances?provider=deepseek&account_id=1').status_code==422
        assert c.get('/api/v1/admin/console/balances?provider=evil').status_code==422
        assert c.get('/api/v1/admin/console/balances?after_id=-1').status_code==422


def test_low_balance_warning_distinguishes_unknown_from_real_zero():
    row=b.with_warnings(b.result('available',balances=[{'currency':'CNY','available':'0'}]),settings())
    assert row['warning']=='low' and row['balances'][0]['warning_threshold']=='100'
    assert b.with_warnings(b.result('error'),settings())['warning']=='unknown'
    assert b.with_warnings(b.result('available',balances=[{'currency':'CNY','available':'1000'}]),settings())['warning']=='normal'
    assert b.with_warnings(b.result('available',balances=[{'currency':'JPY','available':'1000'}]),settings())['warning']=='unknown'


def test_baidu_adapter_only_uses_get_account_info_and_missing_balance_is_unknown(monkeypatch):
    from app.baidu import client as bc
    from app.baidu.services.account import AccountService
    from app.security import crypto
    calls=[]
    monkeypatch.setattr(crypto,'decrypt',lambda v:'fixture-token')
    monkeypatch.setattr(bc,'BaiduAPIClient',lambda **kw:object())
    async def read(self,fields):calls.append(fields);return {'data':[{'balance':0}]}
    monkeypatch.setattr(AccountService,'get_account_info',read)
    account={'id':1,'tenant_id':2,'username':'account','token':'encrypted'}
    row=asyncio.run(b.baidu(account))
    assert row['balances'][0]['available']=='0' and calls==[['balance']]
    assert 'fixture-token' not in str(row)
    async def empty(self,fields):return {'data':{}}
    monkeypatch.setattr(AccountService,'get_account_info',empty)
    with pytest.raises(ValueError):asyncio.run(b.baidu(account))


def test_balance_account_projection_paginates_and_excludes_secrets(monkeypatch):
    from contextlib import asynccontextmanager
    class Rows:
        def all(self):return [(i,2,'account'+str(i),'encrypted-secret','customer') for i in range(1,12)]
    class Session:
        async def execute(self,stmt):return Rows()
    @asynccontextmanager
    async def factory():yield Session()
    monkeypatch.setattr(api,'async_session_factory',factory)
    monkeypatch.setattr(api,'get_settings',settings)
    monkeypatch.setenv('API_CONTROLS_ENABLED','false')
    calls=[]
    async def query(key,fn,refresh):calls.append(key);return b.result('available',balances=[{'currency':'CNY','available':'3'}])
    monkeypatch.setattr(b,'query_cached',query)
    row=asyncio.run(api.read_balances(__import__('fastapi').Response(),provider='baidu',account_id=None,refresh=False,after_id=0))
    assert len(row['rows'])==10 and row['next_after_id']==10
    assert 'encrypted-secret' not in str(row) and 'token' not in str(row)
    assert row['rows'][0]['account_id']==1 and row['rows'][0]['tenant_id']==2
    assert len(calls)==10


def test_http_adapter_blocks_redirects_and_bounds_raw_responses(monkeypatch):
    import httpx
    original=httpx.AsyncClient
    for status,body,expected in [(401,b'private', 'permission_denied'),(403,b'private','permission_denied'),(429,b'private','rate_limited'),(302,b'private','error'),(500,b'private','error'),(200,b'{"balance":0}',None)]:
        def make_client(**kwargs):
            assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
            return original(**kwargs,transport=httpx.MockTransport(lambda request:httpx.Response(status,content=body)))
        monkeypatch.setattr(httpx,'AsyncClient',make_client)
        data,error=asyncio.run(b.json_request('GET','https://api.deepseek.com/user/balance'))
        assert error==expected
        if error:assert data is None
    def oversized(**kwargs):return original(**kwargs,transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'x'*65537)))
    monkeypatch.setattr(httpx,'AsyncClient',oversized)
    with pytest.raises(ValueError):asyncio.run(b.json_request('GET','https://api.deepseek.com/user/balance'))


def test_timeout_does_not_reuse_last_success():
    async def run():
        async def timeout():raise TimeoutError('private')
        row=await b.query_cached('timeout-fixture',timeout,True)
        assert row['state']=='timeout' and row['balances']==[] and 'private' not in str(row)
    asyncio.run(run())
