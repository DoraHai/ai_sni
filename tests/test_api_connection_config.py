import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine

from app import api_controls as controls,api_connection_config as configs
from app.config import get_settings,get_server_settings


def test_connections_reject_infrastructure_secrets_cross_fields_and_nonofficial_targets():
    for target in ('http://api.deepseek.com','https://127.0.0.1/v1','https://api.deepseek.com@evil.test',
                   'https://api.deepseek.com/v1?api_key=secret','https://api.deepseek.com:444/v1'):
        with pytest.raises(ValueError):
            configs.validate_connection('connection:seo.deepseek',{'parameters':{'base_url':target},'secrets':{},'restore':False})
    for key,value in (('connection:seo.database',{}),('connection:seo.deepseek',{'parameters':{},'secrets':{'jwt_secret':'private'},'restore':False}),
                      ('connection:seo.deepseek',{'parameters':{'baidu_write_dry_run':False},'secrets':{},'restore':False})):
        with pytest.raises(ValueError):configs.validate_connection(key,value)
    value={'parameters':{'base_url':'https://api.deepseek.com/v1','model':'deepseek-chat'},'secrets':{'api_key':'test-key-value'},'restore':False}
    assert configs.validate_connection('connection:seo.deepseek',value)[0]['model']=='deepseek-chat'
    unsafe=get_server_settings().model_copy(update={'deepseek_base_url':'https://api.deepseek.com/v1?key=private-value'})
    assert configs.public_defaults(configs.CATALOG['seo.deepseek'],unsafe)['parameters']['base_url']==''


def test_configuration_failure_blocks_business_but_keeps_admin_recovery(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from app.api_metering import MeteringScopeMiddleware
    monkeypatch.setenv('API_CONTROLS_ENABLED','true')
    async def unavailable(module):raise controls.ControlDenied('must not leak internal data')
    monkeypatch.setattr(configs,'load_settings',unavailable)
    app=FastAPI()
    app.add_middleware(MeteringScopeMiddleware,module='seo')
    @app.get('/api/v1/work')
    @app.get('/api/v1/admin/console/snapshot')
    @app.get('/api/v1/auth/me')
    async def route():return {'ok':True}
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            blocked=await client.get('/api/v1/work')
            assert blocked.status_code==503 and 'internal data' not in blocked.text
            assert blocked.headers['cache-control']=='no-store'
            for path in ('/api/v1/auth/me','/api/v1/admin/console/snapshot'):
                assert (await client.get(path)).status_code==200
    asyncio.run(run())


def test_native_first_credentials_are_fresh_scoped_encrypted_audited_and_versioned(monkeypatch):
    raw=os.getenv('PLATFORM_CONSOLE_TEST_DATABASE_URL') or os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL')
    if not raw:pytest.skip('Explicit local test PostgreSQL URL required')
    url=make_url(raw)
    assert url.host in {'127.0.0.1','localhost'} and 'test' in url.database.lower()
    schema='connections_'+uuid4().hex
    monkeypatch.setenv('API_CONTROLS_ENABLED','true')
    monkeypatch.setenv('API_METERING_ENABLED','true')
    # The GEO release deliberately omits SEO-only DataForSEO settings. This
    # local fixture models registration by the actual SEO service.
    base=get_server_settings().model_copy(update={'deepseek_api_key':'','deepseek_model':'deepseek-chat',
        'seo_dataforseo_base_url':'https://api.dataforseo.com','seo_dataforseo_login':'',
        'seo_dataforseo_password':'','seo_dataforseo_enabled':False})
    monkeypatch.setattr('app.config.get_server_settings',lambda:base)
    async def run():
        setup=create_async_engine(raw)
        db=create_async_engine(raw,connect_args={'server_settings':{'search_path':schema}})
        factory=async_sessionmaker(db,expire_on_commit=False)
        monkeypatch.setattr(controls,'async_session_factory',factory)
        root=Path(__file__).parents[1]
        try:
            async with setup.begin() as c:await c.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with db.connect() as c:
                native=await c.get_raw_connection()
                await native.driver_connection.execute((root/'scripts/api_metering_schema.sql').read_text())
                await native.driver_connection.execute((root/'scripts/api_controls_schema.sql').read_text())
            async with factory() as s:
                for module in ('sem','seo','geo'):await configs.register_connections(s,module,base)
                await s.commit()
            async def provider_change(key,value,rev=0):
                async with factory() as s:return await controls.mutate(s,actor_id=10,request_id=str(uuid4()),kind='connection',key=key,expected_revision=rev,value=value)
            await provider_change('connection:seo.chinaz',{'parameters':{'enabled':True},
                'secrets':{'baidu_pc_top50_api_key':'private-pc-ranking-key'},'restore':False})
            await provider_change('connection:seo.chinaz',{'parameters':{},
                'secrets':{'baidu_mobile_top50_api_key':'private-mobile-ranking-key'},'restore':False},1)
            chinaz=await configs.load_settings('seo')
            assert chinaz.chinaz_baidu_pc_top50_api_key=='private-pc-ranking-key'
            assert chinaz.chinaz_baidu_mobile_top50_api_key=='private-mobile-ranking-key'
            await provider_change('connection:seo.dataforseo',{'parameters':{'enabled':True},
                'secrets':{'login':'private-login@example.test','password':'private-basic-password'},'restore':False})
            basic=await configs.load_settings('seo')
            assert basic.seo_dataforseo_login=='private-login@example.test' and basic.seo_dataforseo_password=='private-basic-password'
            async def change(value,rev=0,rid=None):
                async with factory() as s:return await controls.mutate(s,actor_id=10,request_id=rid or str(uuid4()),kind='connection',key='connection:seo.deepseek',expected_revision=rev,value=value)
            secret='first-private-key-value'
            value={'parameters':{'base_url':'https://api.deepseek.com/v1','model':'deepseek-reasoner'},'secrets':{'api_key':secret},'restore':False}
            rid=str(uuid4())
            outcome=await change(value,rid=rid)
            assert outcome['value']['secrets']=={'api_key':True}
            assert (await change(value,rid=rid))['replayed']
            with pytest.raises(controls.ControlConflict):await change({**value,'parameters':{'model':'other'}},rid=rid)
            first=await configs.load_settings('seo')
            assert first.deepseek_api_key==secret and first.deepseek_model=='deepseek-reasoner'
            assert (await configs.load_settings('geo')).deepseek_api_key==''
            assert base.deepseek_api_key=='' and get_settings().deepseek_api_key==''
            async with configs.runtime_scope('seo'):
                assert get_settings().deepseek_api_key==secret
            assert get_settings().deepseek_api_key==''
            # Same revision can be consumed once; no partial secret overwrite.
            values=[{'parameters':{'model':'race-'+str(i)},'secrets':{'api_key':'race-secret-'+str(i)},'restore':False} for i in range(2)]
            raced=await asyncio.gather(*(change(v,rev=1) for v in values),return_exceptions=True)
            assert sum(isinstance(r,controls.ControlConflict) for r in raced)==1
            fresh=await configs.load_settings('seo')
            assert fresh.deepseek_model in ('race-0','race-1')
            async with factory() as s:
                public=await controls.read_controls(s)
                ciphertext=await s.scalar(text('SELECT ciphertext FROM api_control_credentials WHERE id=:id'),{'id':configs.credential_id('seo.deepseek')})
                audit=(await s.execute(text('SELECT before_value,after_value FROM api_control_audit'))).all()
            serialized=json.dumps({'snapshot':public,'audit':[list(r) for r in audit]},default=str)
            assert secret not in serialized and 'race-secret' not in serialized and ciphertext not in serialized
            assert 'private-pc-ranking-key' not in serialized and 'private-mobile-ranking-key' not in serialized
            assert 'private-login@example.test' not in serialized and 'private-basic-password' not in serialized
            assert len(public['module_status'])==3
            connection=next(r for r in public['connections'] if r['id']=='seo.deepseek')
            assert connection['source']=='managed' and connection['secret_status']['api_key']
            await change({'parameters':{},'secrets':{},'restore':True},rev=2)
            restored=await configs.load_settings('seo')
            assert restored.deepseek_api_key=='' and restored.deepseek_model=='deepseek-chat'
            await change(value,rev=3)
            await change({'parameters':{'enabled':False},'secrets':{},'restore':False},rev=4)
            assert (await configs.load_settings('seo')).deepseek_api_key==''
        finally:
            await db.dispose()
            async with setup.begin() as c:await c.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await setup.dispose()
    asyncio.run(run())
