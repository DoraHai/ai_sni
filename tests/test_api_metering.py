import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import api_metering as meter
from app.api_cost_summary import read_api_costs


@pytest.mark.parametrize('usage,expected',[
    ({'prompt_tokens':100,'completion_tokens':20,'prompt_tokens_details':{'cached_tokens':30}},(100,30,20)),
    ({'prompt_tokens':100,'completion_tokens':20,'prompt_cache_hit_tokens':0},(100,0,20)),
    ({'prompt_tokens':100,'completion_tokens':20},(100,None,20)),
    ({'prompt_tokens':100,'completion_tokens':20,'prompt_tokens_details':{'cached_tokens':101}},(100,None,20)),
    ({'prompt_tokens':True,'completion_tokens':20},(None,None,20)),
    ({'prompt_tokens':-1},(None,None,None)),
])
def test_provider_usage_is_checked(usage,expected):
    assert meter.extract_usage({'usage':usage})==expected


def test_estimates_use_exact_model_cache_prices_and_version(monkeypatch):
    monkeypatch.delenv('API_METERING_RATES_JSON',raising=False)
    quote=meter.quote_rate('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions','deepseek-v4-flash')
    assert meter.estimate(quote,1000,0,500)==Decimal('0.002')
    assert meter.estimate(quote,1000,500,500) is None
    assert meter.estimate(quote,None,None,500) is None
    assert meter.quote_rate('https://dashscope-intl.aliyuncs.com/v1','deepseek-v4-flash') is None
    assert meter.quote_rate('https://dashscope.aliyuncs.com/v1','different-model') is None
    monkeypatch.setenv('API_METERING_RATES_JSON',json.dumps([{'host':'provider.test','model':'model','input':'2','output':'4','cached':'.2','version':'contract-v1'}]))
    quote=meter.quote_rate('https://provider.test/v1','model')
    assert meter.estimate(quote,1000,500,500)==Decimal('0.0031')


@pytest.mark.parametrize('value',['{','{}', '[{"host":"provider.test","model":"m","input":"NaN","output":"2","version":"v1"}]'])
def test_bad_rate_config_does_not_allow_an_unmetered_call(monkeypatch,value):
    monkeypatch.setenv('API_METERING_RATES_JSON',value)
    with pytest.raises(meter.MeteringUnavailable):
        meter.quote_rate('https://provider.test/v1','m')


def test_scope_isolation_jobs_and_denied_tenant():
    from app.security.auth import AuthContext
    from fastapi import HTTPException
    async def task(tid,uid):
        token=meter.scope.set(meter.MeterScope(module='seo'))
        try:
            ctx=AuthContext(uid,'test','role',tid)
            meter.bind_identity(ctx)
            ctx.ensure_tenant(tid)
            with pytest.raises(HTTPException): ctx.ensure_tenant(tid+1)
            assert meter.scope.get().tenant_id==tid
            await asyncio.sleep(.01)
            assert (meter.scope.get().tenant_id,meter.scope.get().user_id)==(tid,uid)
            with meter.background_scope(tenant_id=99,module='geo',operation='job',job_ref='job:7'):
                assert meter.scope.get().user_id is None
                assert meter.scope.get().tenant_id==99
            assert meter.scope.get().user_id==uid
        finally: meter.scope.reset(token)
    async def run(): await asyncio.gather(task(1,10),task(2,20))
    asyncio.run(run())
    assert meter.scope.get()==meter.MeterScope()


def test_native_attempts_survive_business_failure_and_block_on_ledger_failure(monkeypatch):
    raw=os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL') or os.getenv('PLATFORM_CONSOLE_TEST_DATABASE_URL')
    if not raw: pytest.skip('Explicit local test PostgreSQL URL required')
    url=make_url(raw)
    assert url.host in {'127.0.0.1','localhost'} and 'test' in url.database.lower()
    schema='api_meter_'+uuid4().hex
    monkeypatch.setenv('API_METERING_ENABLED','true')
    monkeypatch.delenv('API_METERING_RATES_JSON',raising=False)
    calls=[]
    async def provider(request):
        calls.append(request)
        if request.url.path.endswith('/timeout'): raise httpx.ReadTimeout('private URL and key',request=request)
        if request.url.path.endswith('/error'): return httpx.Response(429,json={'private':'SECRET'})
        if request.url.path.endswith('/missing'): return httpx.Response(200,json={'choices':[]})
        return httpx.Response(200,json={'id':'req-1','private':'SECRET',
            'usage':{'prompt_tokens':1000,'completion_tokens':500,'prompt_tokens_details':{'cached_tokens':0}},
            'choices':[{'message':{'content':'not valid business JSON'}}]})
    async def run():
        setup=create_async_engine(raw)
        db=create_async_engine(raw,connect_args={'server_settings':{'search_path':schema}})
        try:
            async with setup.begin() as c: await c.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with db.connect() as c:
                native=await c.get_raw_connection()
                ddl=(Path(__file__).parents[1]/'scripts/api_metering_schema.sql').read_text(encoding='utf-8')
                await native.driver_connection.execute(ddl)
            monkeypatch.setattr(meter,'async_session_factory',async_sessionmaker(db,expire_on_commit=False))
            async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
                async def paid(tid,uid):
                    with meter.background_scope(tenant_id=tid,user_id=uid,module='geo',operation='draft'):
                        return await meter.metered_request(client,'post','https://dashscope.aliyuncs.com/v1/ok?key=SECRET',api_key='SECRET',model='deepseek-v4-flash',json={'private':'SECRET'})
                # Concurrent independent attempts, including a retry for one user.
                await asyncio.gather(paid(1,10),paid(2,20),paid(1,10))
                with meter.background_scope(tenant_id=1,module='geo',operation='scheduled'):
                    for path in ('error','missing','timeout'):
                        try: await meter.metered_request(client,'post','https://dashscope.aliyuncs.com/v1/'+path,model='deepseek-v4-flash')
                        except httpx.ReadTimeout: pass
                async with db.begin() as business:
                    await business.execute(text('SELECT 1'))
                    await business.rollback()
                async with db.connect() as c:
                    rows=(await c.execute(text('SELECT * FROM api_usage_events ORDER BY tenant_id,user_id'))).mappings().all()
                    assert len(rows)==6
                    assert sum(r['estimated_amount'] or 0 for r in rows)==Decimal('.006')
                    assert sorted(r['user_id'] for r in rows if r['user_id'] is not None)==[10,10,20]
                    assert {'succeeded','error','unknown'} <= {r['state'] for r in rows}
                    assert 'SECRET' not in str(rows)
                    assert all('?' not in r['endpoint'] for r in rows)
                async with async_sessionmaker(db)() as session:
                    await session.execute(text('SET TRANSACTION READ ONLY'))
                    summary=await read_api_costs(session)
                    assert summary['calls']==6 and summary['unpriced']==3
                    assert summary['estimated_amount'] is None
                    assert Decimal(summary['known_amount'])==Decimal('.006')
                    assert len(summary['user_totals'])==3
                    assert summary['actual_amount'] is None
                # The schema is taken away to simulate accounting outage.
                async with db.begin() as c: await c.execute(text('DROP TABLE api_usage_events'))
                with pytest.raises(meter.MeteringUnavailable): await paid(1,10)
                assert len(calls)==6, 'A provider call must not occur without a committed reservation'
        finally:
            await db.dispose()
            async with setup.begin() as c: await c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await setup.dispose()
    asyncio.run(run())
