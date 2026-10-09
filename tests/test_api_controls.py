import asyncio
import json
import os
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import api_controls as controls, api_metering as meter


def test_budget_and_price_validation_rejects_unknown_and_invalid_fields():
    for value in (True, 'NaN', '-1', 'Infinity', '0.0000000000001'):
        with pytest.raises(ValueError): controls.decimal_value(value)
    assert controls.decimal_value('0') == '0'
    with pytest.raises(ValueError): controls.validate_value('provider', {'enabled': 1})
    with pytest.raises(ValueError): controls.validate_value('budget', {'daily_calls': 3})
    quote = {'unit':'tokens','input':'1','output':'2','max_input':1000000}
    amount, payload = controls.reservation(quote, {'json':{'messages':[{'role':'user','content':'你好'}]}})
    assert amount == Decimal('1.008192')
    assert payload['json']['max_tokens'] == 4096
    with pytest.raises(controls.ControlDenied): controls.reservation(None, {})
    with pytest.raises(controls.ControlDenied): controls.reservation(quote, {'json':{'messages':[], 'stream':True}})
    with pytest.raises(controls.ControlDenied): controls.replace_credential({}, 'old', 'new')
    day,month=controls.period_starts(datetime(2026,10,31,16,0,tzinfo=timezone.utc))
    assert day.isoformat()=='2026-11-01T00:00:00+08:00'
    assert day==month


def test_native_budget_races_prices_rotation_and_audit(monkeypatch):
    raw = os.getenv('PLATFORM_CONSOLE_TEST_DATABASE_URL') or os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL')
    if not raw: pytest.skip('Explicit local test PostgreSQL URL required')
    url = make_url(raw)
    assert url.host in {'127.0.0.1','localhost'} and 'test' in url.database.lower()
    schema = 'api_controls_' + uuid4().hex
    monkeypatch.setenv('API_METERING_ENABLED', 'true')
    monkeypatch.setenv('API_CONTROLS_ENABLED', 'true')
    monkeypatch.delenv('API_METERING_RATES_JSON', raising=False)
    sent = []
    async def provider(request):
        sent.append(request)
        await asyncio.sleep(.01)
        return httpx.Response(200,json={'usage':{'prompt_tokens':100,'completion_tokens':10,
                              'prompt_tokens_details':{'cached_tokens':0}}})
    def budget(**caps):
        return dict(daily_calls=None,monthly_calls=None,daily_cny=None,monthly_cny=None,warning_percent=80,**caps) if not caps else {
            **dict(daily_calls=None,monthly_calls=None,daily_cny=None,monthly_cny=None,warning_percent=80),**caps}
    async def run():
        setup = create_async_engine(raw)
        db = create_async_engine(raw, connect_args={'server_settings':{'search_path':schema}})
        factory = async_sessionmaker(db, expire_on_commit=False)
        root = Path(__file__).parents[1]
        try:
            async with setup.begin() as c: await c.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with db.connect() as c:
                native = await c.get_raw_connection()
                await native.driver_connection.execute((root/'scripts/api_metering_schema.sql').read_text())
                await native.driver_connection.execute((root/'scripts/api_controls_schema.sql').read_text())
            async with db.begin() as c:
                await c.execute(text('CREATE TABLE tenants(id bigint PRIMARY KEY)'))
                await c.execute(text('CREATE TABLE users(id bigint PRIMARY KEY)'))
                await c.execute(text('INSERT INTO tenants VALUES(1),(2)'))
                await c.execute(text('INSERT INTO users VALUES(10),(20)'))
            monkeypatch.setattr(meter, 'async_session_factory', factory)
            monkeypatch.setattr(controls, 'async_session_factory', factory)
            async def change(kind,key,value,rev=0,rid=None):
                async with factory() as session:
                    return await controls.mutate(session,actor_id=10,request_id=rid or str(uuid4()),kind=kind,key=key,expected_revision=rev,value=value)
            await change('budget','budget:tenant:1',budget(daily_calls=2))
            async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
                async def call(tid=1,uid=10,host='dashscope.aliyuncs.com'):
                    with meter.background_scope(tenant_id=tid,user_id=uid,module='seo',operation='test'):
                        return await meter.metered_request(client,'post','https://'+host+'/v1/chat/completions',
                            model='deepseek-v4-flash',api_key='old-secret',headers={'Authorization':'Bearer old-secret'},
                            json={'messages':[{'role':'user','content':'test'}]})
                outcomes = await asyncio.gather(*(call() for _ in range(6)),return_exceptions=True)
                assert sum(isinstance(x,controls.ControlDenied) for x in outcomes) == 4
                assert len(sent) == 2
                await call(2,20)
                assert len(sent) == 3
                await change('budget','budget:tenant:1',budget(),rev=1)
                # Nested account budget still applies after tenant budget removal.
                await change('budget','budget:user:10',budget(monthly_calls=2))
                with pytest.raises(controls.ControlDenied): await call(2,10)
                await change('budget','budget:user:10',budget(),rev=1)
                await change('budget','budget:global',budget(monthly_cny='2'))
                await call(2,20)
                with pytest.raises(controls.ControlDenied): await call(2,20,'unknown.test')
                # Register runtime binding; rotation affects exact key+host only.
                ident = controls.binding_id('dashscope.aliyuncs.com',meter.credential_ref('old-secret'))
                async with db.begin() as c:
                    await c.execute(text('''INSERT INTO api_control_bindings(id,module,label,host,model,configured,can_rotate)
                        VALUES(:id,'seo','dashscope','dashscope.aliyuncs.com','deepseek-v4-flash',true,true)'''),{'id':ident})
                rid = str(uuid4())
                result = await change('credential',ident,{'key':'new-private-secret'},rid=rid)
                assert result['value'] == {'overridden':True,'revision':1}
                async with db.connect() as c:
                    ciphertext=await c.scalar(text('SELECT ciphertext FROM api_control_credentials WHERE id=:id'), {'id':ident})
                    assert 'new-private-secret' not in ciphertext
                    assert controls.decrypt(ciphertext)=='new-private-secret'
                assert (await change('credential',ident,{'key':'new-private-secret'},rid=rid))['replayed']
                with pytest.raises(controls.ControlConflict): await change('credential',ident,{'key':'different-secret'},rid=rid)
                await call(2,20)
                assert sent[-1].headers['Authorization'] == 'Bearer new-private-secret'
                snapshot = None
                async with factory() as s: snapshot = await controls.read_controls(s)
                serialized = json.dumps(snapshot,default=str)
                assert 'new-private-secret' not in serialized and ciphertext not in serialized
                # Frozen price affects future attempts only, with atomic audit.
                await change('rate','rate:dashscope.aliyuncs.com:deepseek-v4-flash',
                             {'unit':'tokens','input':'3','output':'4','cached':'0.5','max_input':100000,'source':'test contract'})
                await call(2,20)
                async with db.connect() as c:
                    rows=(await c.execute(text('SELECT estimated_amount,pricing_version,reserved_amount FROM api_usage_events ORDER BY started_at,id'))).mappings().all()
                    assert rows[0]['estimated_amount'] == Decimal('0.00012')
                    assert rows[-1]['estimated_amount'] == Decimal('0.00034')
                    assert rows[-1]['pricing_version'].startswith('admin-')
                    assert rows[-1]['reserved_amount'] == Decimal('0.316384')
                # Pause/re-enable, optimistic conflicts, and fail closed on DB failure.
                await change('provider','provider:dashscope.aliyuncs.com',{'enabled':False})
                before=len(sent)
                with pytest.raises(controls.ControlDenied): await call(2,20)
                with pytest.raises(controls.ControlConflict): await change('provider','provider:dashscope.aliyuncs.com',{'enabled':True})
                assert len(sent)==before
                await change('provider','provider:dashscope.aliyuncs.com',{'enabled':True},rev=1)
                async with db.begin() as c:
                    await c.execute(text('UPDATE api_usage_events SET estimated_amount=NULL,reserved_amount=NULL WHERE id=(SELECT id FROM api_usage_events LIMIT 1)'))
                with pytest.raises(controls.ControlDenied): await call(2,20)
                async with db.begin() as c: await c.execute(text('DROP TABLE api_control_settings'))
                with pytest.raises(meter.MeteringUnavailable): await call(2,20)
                assert len(sent)==before
        finally:
            await db.dispose()
            async with setup.begin() as c: await c.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await setup.dispose()
    asyncio.run(run())
