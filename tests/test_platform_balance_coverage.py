import asyncio
import json
import os
from types import SimpleNamespace
from contextlib import asynccontextmanager
import pytest
from app import platform_balance_coverage as coverage, platform_balances as b
from app.api import platform_balances as api
from app.api_connection_config import CATALOG, credential_id


def test_catalogue_includes_all_modules_products_and_unknown_service_configuration():
    rows = coverage.coverage_rows(SimpleNamespace(deepseek_api_key='PRIVATE', deepseek_base_url='https://api.deepseek.com'))['rows']
    assert set(r['connection_id'] for r in rows) == set(CATALOG)
    assert {r['module'] for r in rows} == {'sem', 'seo', 'geo'}
    assert next(r for r in rows if r['id'] == 'sem.deepseek')['configured'] is True
    assert all(r['configured'] is None for r in rows if r['module'] != 'sem')
    assert {r['capability'] for r in rows} >= {'direct', 'billing_authorization', 'package', 'quota', 'pending'}
    assert len([r for r in rows if r['connection_id'] == 'seo.chinaz']) == 14
    assert any('搜狗 PC' in r['name'] for r in rows)
    assert 'PRIVATE' not in str(rows)


def test_package_fallback_and_partial_configuration_are_not_fake_missing():
    records = [{'label':'connection:seo.chinaz', 'secret_status':{'api_key':True},'enabled':True,'seen_at':'2026-10-10'},
               {'label':'connection:geo.geo_kimi', 'secret_status':{'api_key':False},'enabled':False}]
    rows=coverage.coverage_rows(SimpleNamespace(),records,'available')['rows']
    assert all(r['configured'] is True for r in rows if r['connection_id']=='seo.chinaz')
    kimi=next(r for r in rows if r['id']=='geo.geo_kimi')
    assert kimi['configured'] is False and kimi['enabled'] is False
    assert kimi['configuration_source']=='service_registry'


@pytest.mark.parametrize('base',['http://api.moonshot.cn','https://proxy.example','https://api.moonshot.cn@proxy.example','https://api.moonshot.cn/?secret=1','https://api.moonshot.cn:444','https://api.moonshot.cn/redirect',None])
def test_kimi_never_sends_key_to_unverified_endpoint(monkeypatch,base):
    async def fail(*a,**kw):raise AssertionError('must not query')
    monkeypatch.setattr(b,'json_request',fail)
    assert asyncio.run(b.kimi(base,'PRIVATE'))['state']=='unsupported'


def test_kimi_real_zero_and_nonzero_error_codes(monkeypatch):
    calls=[]
    async def request(*a,**kw):
        calls.append((a,kw))
        return {'status':True,'code':0,'data':{'available_balance':0,'cash_balance':-1,'voucher_balance':0,'key':'PRIVATE'}},None
    monkeypatch.setattr(b,'json_request',request)
    row=asyncio.run(b.kimi('https://api.moonshot.cn/v1','fixture'))
    assert row['balances'][0]['available']=='0' and row['balances'][0]['cash']=='-1'
    assert calls[0][0]==('GET','https://api.moonshot.cn/v1/users/me/balance')
    assert 'PRIVATE' not in str(row)
    async def error(*a,**kw):return {'status':True,'code':123,'message':'PRIVATE','data':{'available_balance':100}},None
    monkeypatch.setattr(b,'json_request',error)
    row=asyncio.run(b.kimi('https://api.moonshot.cn/v1','fixture'))
    assert row['state']=='error' and row['balances']==[] and 'PRIVATE' not in str(row)


def test_dataforseo_uses_only_free_user_data_and_requires_successful_task(monkeypatch):
    calls=[]
    async def request(*a,**kw):
        calls.append((a,kw))
        return {'status_code':20000,'tasks':[{'status_code':20000,'result':[{'login':'PRIVATE','money':{'balance':0,'total':100}}]}]},None
    monkeypatch.setattr(b,'json_request',request)
    row=asyncio.run(b.dataforseo('https://api.dataforseo.com/v3','fixture','password'))
    assert row['balances']==[{'currency':'USD','available':'0'}]
    assert calls[0][0]==('GET','https://api.dataforseo.com/v3/appendix/user_data')
    assert 'PRIVATE' not in str(row)
    assert asyncio.run(b.dataforseo('https://proxy.example','fixture','password'))['state']=='unsupported'
    async def error(*a,**kw):return {'status_code':20000,'tasks':[{'status_code':40102,'result':[{'money':{'balance':999}}]}]},None
    monkeypatch.setattr(b,'json_request',error)
    row=asyncio.run(b.dataforseo('https://api.dataforseo.com','fixture','password'))
    assert row['state']=='error' and row['balances']==[]


def test_unavailable_registry_does_not_hide_catalogue_or_guess_remote_credentials():
    @asynccontextmanager
    async def failed():raise RuntimeError('PRIVATE');yield
    view,managed=asyncio.run(coverage.load_coverage(SimpleNamespace(),failed))
    assert view['state']=='unavailable' and managed==[] and len(view['rows'])>30
    assert 'PRIVATE' not in str(view)


def test_native_registry_is_read_only_and_disabled_controls_never_decrypt(monkeypatch):
    from uuid import uuid4
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    raw=os.getenv('PLATFORM_CONSOLE_TEST_DATABASE_URL')
    if not raw:pytest.skip('Explicit isolated local PostgreSQL URL required')
    url=make_url(raw)
    assert url.host in ('127.0.0.1','localhost') and 'test' in url.database.lower()
    schema='coverage_test_'+uuid4().hex
    setup=create_async_engine(raw,poolclass=NullPool)
    scoped=create_async_engine(raw,poolclass=NullPool,connect_args={'server_settings':{'search_path':schema}})
    class ReadOnlySession(AsyncSession):
        async def execute(self,stmt,*args,**kw):
            if str(stmt).lstrip().startswith('SELECT'):
                assert (await super().execute(text('SHOW transaction_read_only'))).scalar()=='on'
            return await super().execute(stmt,*args,**kw)
    async def prepare():
        async with setup.begin() as c:await c.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with scoped.begin() as c:
            await c.execute(text('CREATE TABLE api_control_bindings(module text,label text,metadata jsonb,seen_at timestamptz,id varchar,host text)'))
            await c.execute(text('CREATE TABLE api_control_settings(key text,kind text,value jsonb)'))
            await c.execute(text('CREATE TABLE api_control_credentials(id varchar primary key,ciphertext text)'))
            for config_id,base,secrets in [('geo.geo_kimi','https://api.moonshot.cn/v1',{'api_key':'PRIVATE'}),('seo.dataforseo','https://api.dataforseo.com/v3',{'login':'PRIVATE','password':'PRIVATE'})]:
                await c.execute(text('INSERT INTO api_control_bindings(module,label,metadata,seen_at) VALUES(:module,:label,CAST(:meta AS jsonb),CURRENT_TIMESTAMP)'),
                    {'module':config_id.split('.')[0],'label':'connection:'+config_id,'meta':json.dumps({'parameters':{'base_url':base,'enabled':True},'secrets':{k:True for k in secrets}})})
                await c.execute(text("INSERT INTO api_control_settings VALUES(:key,'connection',CAST(:value AS jsonb))"),
                    {'key':'connection:'+config_id,'value':json.dumps({'parameters':{},'secrets':{k:True for k in secrets}})})
                await c.execute(text('INSERT INTO api_control_credentials VALUES(:id,:secret)'),{'id':credential_id(config_id),'secret':json.dumps(secrets)})
    async def cleanup():
        async with scoped.connect() as c:
            assert await c.scalar(text('SELECT count(*) FROM api_control_credentials')) in (2,3)
        await scoped.dispose()
        async with setup.begin() as c:await c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await setup.dispose()
    asyncio.run(prepare())
    decrypts=[]
    monkeypatch.setattr(coverage,'decrypt',lambda v:decrypts.append(1) or v)
    factory=async_sessionmaker(scoped,class_=ReadOnlySession,expire_on_commit=False)
    try:
        monkeypatch.setenv('API_CONTROLS_ENABLED','false')
        view,managed=asyncio.run(coverage.load_coverage(SimpleNamespace(),factory))
        assert view['state']=='available' and managed==[] and decrypts==[]
        assert next(r for r in view['rows'] if r['id']=='geo.geo_kimi')['configured'] is True
        monkeypatch.setenv('API_CONTROLS_ENABLED','true')
        view,managed=asyncio.run(coverage.load_coverage(SimpleNamespace(),factory))
        assert len(managed)==2 and len(decrypts)==2 and 'PRIVATE' not in str(view)
        async def disable():
            async with scoped.begin() as c:
                await c.execute(text("UPDATE api_control_settings SET value=CAST(:value AS jsonb) WHERE key='connection:geo.geo_kimi'"),
                    {'value':json.dumps({'parameters':{'enabled':False},'secrets':{}})})
        asyncio.run(disable())
        view,managed=asyncio.run(coverage.load_coverage(SimpleNamespace(),factory))
        assert [r['code'] for r in managed]==['dataforseo']
        assert next(r for r in view['rows'] if r['id']=='geo.geo_kimi')['enabled'] is False
        async def rotate():
            async with scoped.begin() as c:
                await c.execute(text("INSERT INTO api_control_bindings(module,label,id,host) VALUES('seo','dataforseo','rotated-fixture','api.dataforseo.com')"))
                await c.execute(text("INSERT INTO api_control_credentials VALUES('rotated-fixture','PRIVATE-ROTATION')"))
        asyncio.run(rotate())
        view,managed=asyncio.run(coverage.load_coverage(SimpleNamespace(),factory))
        assert managed==[] and 'PRIVATE' not in str(view)
    finally:asyncio.run(cleanup())


def test_route_deduplicates_same_managed_credentials_without_exposing_them(monkeypatch):
    from fastapi import Response
    settings=SimpleNamespace(deepseek_api_key='PRIVATE',deepseek_base_url='https://api.deepseek.com',
        aliyun_balance_access_key_id='',aliyun_balance_access_key_secret='',aliyun_balance_security_token='')
    view=coverage.coverage_rows(settings)
    managed=[{'id':'geo.geo_deepseek','code':'geo_deepseek','base_url':'https://api.deepseek.com','secrets':{'api_key':'PRIVATE'},'module':'geo','name':'DeepSeek'},
             {'id':'seo.deepseek','code':'deepseek','base_url':'https://api.deepseek.com','secrets':{'api_key':'PRIVATE'},'module':'seo','name':'DeepSeek'}]
    async def load(*a):return view,managed
    @asynccontextmanager
    async def failed():raise RuntimeError();yield
    calls=[]
    async def query(key,factory,refresh):calls.append(1);return b.result('available',balances=[{'currency':'CNY','available':'0'}])
    monkeypatch.setattr(api,'get_settings',lambda:settings)
    monkeypatch.setattr(api,'load_coverage',load)
    monkeypatch.setattr(api,'async_session_factory',failed)
    monkeypatch.setattr(b,'query_cached',query)
    monkeypatch.setenv('API_CONTROLS_ENABLED','false')
    data=asyncio.run(api.read_balances(Response(),provider=None,account_id=None,after_id=0))
    assert len(calls)==2
    assert [r['balance_row_id'] for r in data['coverage']['rows'] if r['id'] in {'geo.geo_deepseek','seo.deepseek'}]==['deepseek','deepseek']
    assert 'PRIVATE' not in str(data)
