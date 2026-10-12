"""Enable actual native main API controls/metering with synthetic transport only."""
import json
import asyncio
from uuid import uuid4
import httpx
from sqlalchemy import text

async def install(sessions,root,module):
    from app import api_controls as controls,api_metering as meter,api_connection_config as configs
    from app.config import get_server_settings
    controls.async_session_factory=sessions;meter.async_session_factory=sessions
    async with sessions.begin() as db:
        connection=await db.connection();raw=await connection.get_raw_connection()
        for name in ('api_metering_schema.sql','api_controls_schema.sql'):
            ddl=(root/'scripts'/name).read_text(encoding='utf-8').replace('BEGIN;','').replace('COMMIT;','')
            await raw.driver_connection.execute(ddl)
        await configs.register_connections(db,module,get_server_settings())
    async with sessions() as db:
        await controls.mutate(db,actor_id=8,request_id=str(uuid4()),kind='connection',key='connection:'+module+'.deepseek',expected_revision=0,value={'parameters':{'enabled':True,'model':'deepseek-chat'},'secrets':{'api_key':'synthetic-'+module+'-key'},'restore':False})
    return controls,meter

class Provider:
    def __init__(self):self.mode='normal';self.calls=[];self.original=httpx.AsyncClient;self.on_call=None;self.entered=asyncio.Event()
    async def transport(self,request):
        body=json.loads(request.content);snap=json.loads(body['messages'][-1]['content']);self.calls.append({'snapshot':snap,'authorization':request.headers['authorization']})
        self.entered.set()
        assert 'tools' not in body and body['max_tokens']==1500
        if self.on_call:await self.on_call()
        if self.mode=='timeout':raise httpx.ReadTimeout('synthetic',request=request)
        if self.mode=='outer-timeout':await asyncio.sleep(1)
        if self.mode=='http-error':return httpx.Response(503,json={'error':'synthetic'})
        content='invalid JSON' if self.mode=='invalid' else json.dumps({'items':[{'queue_id':i['queue_id'],'at':i['earliest_at']} for i in snap['items']]})
        return httpx.Response(200,json={'id':'synthetic','choices':[{'message':{'content':content}}],'usage':{'prompt_tokens':100,'prompt_cache_hit_tokens':0,'completion_tokens':12}})
    def activate(self):httpx.AsyncClient=lambda **kwargs:self.original(transport=httpx.MockTransport(self.transport),**kwargs)
    def restore(self):httpx.AsyncClient=self.original

async def control_checks(sessions,module,root):
    from app.distribution_planning_gateway import suggest,GatewayFailure
    controls,meter=await install(sessions,root,module);provider=Provider();provider.activate()
    from app import api_connection_config as configs
    from app.config import get_server_settings
    inherited=get_server_settings().model_copy(update={'deepseek_api_key':'synthetic-wrong-module-key'})
    inherited_token=configs.current_settings.set(inherited)
    snap={'tenant_id':4,'actor_id':7,'module':module,'scope_id':2,'items':[]};checks=[]
    async def change(kind,key,value,revision=0):
        async with sessions() as db:await controls.mutate(db,actor_id=8,request_id=str(uuid4()),kind=kind,key=key,expected_revision=revision,value=value)
    budget={'daily_calls':None,'monthly_calls':None,'daily_cny':None,'monthly_cny':None,'warning_percent':80,'max_concurrent':1}
    try:
        await change('rate','rate:api.deepseek.com:deepseek-chat',{'unit':'tokens','source':'synthetic isolated acceptance price','input':'1','output':'2','cached':None,'max_input':10000})
        await change('budget','budget:tenant:4',{**budget,'daily_cny':'1'})
        job=uuid4();assert await suggest(snap,job)=={'items':[]};checks.append('enabled-controls-admitted-and-metered')
        assert provider.calls[-1]['authorization']=='Bearer synthetic-'+module+'-key'
        assert configs.current_settings.get() is inherited;checks.append('module-context-isolated-and-restored')
        await change('provider','provider:api.deepseek.com',{'enabled':False})
        try:await suggest(snap,uuid4())
        except controls.ControlDenied as e:assert e.code=='api_provider_disabled'
        else:raise AssertionError('disabled provider sent')
        assert len(provider.calls)==1;checks.append('provider-disabled-no-http')
        await change('provider','provider:api.deepseek.com',{'enabled':True},1)
        await change('budget','budget:tenant:4',{**budget,'daily_calls':1},1)
        try:await suggest(snap,uuid4())
        except controls.ControlDenied as e:assert e.code=='api_budget_exhausted'
        else:raise AssertionError('exhausted budget sent')
        assert len(provider.calls)==1;checks.append('budget-exhausted-no-http')
        await change('budget','budget:tenant:4',budget,2)
        await change('connection','connection:'+module+'.deepseek',{'parameters':{'enabled':False},'secrets':{},'restore':False},1)
        try:await suggest(snap,uuid4())
        except GatewayFailure as e:assert e.code=='AI_NOT_CONFIGURED'
        else:raise AssertionError('disabled connection sent')
        assert len(provider.calls)==1;checks.append('connection-disabled-no-http')
        await change('connection','connection:'+module+'.deepseek',{'parameters':{'enabled':True},'secrets':{},'restore':False},2)
        for mode in ('invalid','http-error','timeout'):
            provider.mode=mode
            try:await suggest(snap,uuid4())
            except (GatewayFailure,httpx.HTTPError):pass
            else:raise AssertionError('failure accepted')
        checks+=['invalid-json-metered','http-failure-metered','timeout-unknown-metered']
        # Unknown charges/concurrency cannot be silently freed.
        try:await suggest(snap,uuid4())
        except controls.ControlDenied as e:assert e.code=='api_concurrency_limit'
        else:raise AssertionError('unknown call did not hold concurrency')
        assert len(provider.calls)==4;checks.append('unknown-attempt-blocks-new-admission')
        async with sessions() as db:
            events=(await db.execute(text('SELECT * FROM api_usage_events ORDER BY started_at'))).mappings().all()
            assert len(events)==4 and [e['state'] for e in events]==['succeeded','succeeded','error','unknown']
            assert all(e['tenant_id']==4 and e['user_id']==7 and e['module']==module and e['operation']=='distribution_planning' and e['job_ref'] for e in events)
            assert events[0]['reserved_amount'] is not None and events[0]['estimated_amount'] is not None
        original_write=meter._write
        async def broken_settlement(sql,params):
            if sql.lstrip().startswith('UPDATE api_usage_events'):raise meter.MeteringUnavailable('synthetic settlement failure')
            return await original_write(sql,params)
        meter._write=broken_settlement;provider.mode='normal'
        try:
            try:await suggest({**snap,'tenant_id':5},uuid4())
            except meter.MeteringUnavailable as e:assert e.provider_attempted
            else:raise AssertionError('failed settlement accepted')
        finally:meter._write=original_write
        async with sessions() as db:
            assert await db.scalar(text("SELECT count(*) FROM api_usage_events WHERE tenant_id=5 AND state='requested'"))==1
        checks.append('post-http-metering-failure-retains-durable-attempt')
        provider.mode='outer-timeout';provider.entered.clear()
        attempt=asyncio.create_task(suggest({**snap,'tenant_id':6},uuid4()))
        await asyncio.wait_for(provider.entered.wait(),5)
        try:await asyncio.wait_for(attempt,.01)
        except TimeoutError:pass
        else:raise AssertionError('outer timeout not cancelled')
        async with sessions() as db:assert await db.scalar(text("SELECT count(*) FROM api_usage_events WHERE tenant_id=6 AND state='unknown'"))==1
        checks.append('outer-cancel-after-admission-persists-unknown')
        settled=asyncio.Event()
        async def delayed_settlement(sql,params):
            if sql.lstrip().startswith('UPDATE api_usage_events'):
                settled.set();await asyncio.sleep(1)
            return await original_write(sql,params)
        meter._write=delayed_settlement;provider.mode='normal'
        try:
            attempt=asyncio.create_task(suggest({**snap,'tenant_id':7},uuid4()))
            await asyncio.wait_for(settled.wait(),5)
            try:await asyncio.wait_for(attempt,.01)
            except TimeoutError:pass
            else:raise AssertionError('settlement not cancelled')
        finally:meter._write=original_write
        async with sessions() as db:assert await db.scalar(text("SELECT count(*) FROM api_usage_events WHERE tenant_id=7 AND state='requested'"))==1
        checks.append('post-response-settlement-cancel-retains-requested-attempt')
        assert get_server_settings().baidu_write_dry_run is True
        checks.append('sem-money-dry-run-preserved')
        return checks
    finally:
        configs.current_settings.reset(inherited_token)
        provider.restore()
