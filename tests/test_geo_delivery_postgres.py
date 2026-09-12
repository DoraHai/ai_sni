"""Real PostgreSQL delivery locks; isolated structure-only schema, no external publish."""
import asyncio
import os
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from app.geo.content.delivery_recovery import DeliveryResolution, resolve_delivery
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models import (
    GeoChannelAccount,
    GeoChannelVariant,
    GeoContentTask,
    GeoOptimizationBusiness,
    GeoPublishingChannel,
)
from app.geo.content.multi_push import execute_single_push
from app.geo.tenant_scope import GeoEntitlementUnavailable


@pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires authorized PostgreSQL')
@pytest.mark.parametrize('scenario', ['same_account', 'different_accounts', 'ambiguous_response', 'recovery_during_send'])
def test_real_delivery_serialization(scenario):
    async def run():
        url=os.environ['GEO_TEST_POSTGRES_URL']; schema='geo_delivery_test_'+uuid4().hex
        admin=create_async_engine(url); engine=None; created=False
        tables=['tenants','tenant_modules','geo_content_tasks','geo_channel_variants','geo_channel_accounts','geo_publishing_channels','geo_article_versions']
        try:
            async with admin.begin() as c:
                await c.execute(text(f'CREATE SCHEMA {schema}'))
                for table in tables:
                    await c.execute(text(f'CREATE TABLE {schema}.{table} AS SELECT * FROM public.{table} WITH NO DATA'))
                await c.execute(text(f"INSERT INTO {schema}.tenants(id,name) VALUES(7,'测试租户')"))
                await c.execute(text(f"INSERT INTO {schema}.tenant_modules(tenant_id,module_code,status) VALUES(7,'geo','active')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_content_tasks(id,tenant_id,review_status,title,status) VALUES(12,7,'approved','title','ready')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_article_versions(id,task_id,version_no,title,body_markdown) VALUES(16,12,1,'title','body')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_channel_variants(id,task_id,article_version_id,channel,title,body_markdown,status,adapt_meta) VALUES(3,12,16,'website','title','body','draft','{{}}')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_publishing_channels(id,tenant_id,channel_type,publish_mode,enabled) VALUES(5,7,'website','auto_publish',true)"))
                for aid in [4,6]:
                    await c.execute(text(f"INSERT INTO {schema}.geo_channel_accounts(id,tenant_id,channel_id,auth_type,status,credentials_encrypted) VALUES(:id,7,5,'webhook','active','encrypted')"),{'id':aid})
            created=True
            engine=create_async_engine(url,connect_args={'server_settings':{'search_path':schema,'statement_timeout':'15000'}})
            sessions=async_sessionmaker(engine,expire_on_commit=False)
            entered, release, second_ready=asyncio.Event(),asyncio.Event(),asyncio.Event()
            pids={}; sends=[]
            async def send(session,**kw):
                sends.append(kw['account'].id)
                if len(sends)==1:
                    pids['first']=await session.scalar(text('SELECT pg_backend_pid()'))
                    entered.set();await asyncio.wait_for(release.wait(),10)
                    if scenario=='ambiguous_response':raise httpx.ReadTimeout('no response')
                return {'ok':True,'remote_url':'https://example.com/article','account_id':kw['account'].id}
            async def call(aid,second=False):
                if second:await entered.wait()
                async with sessions() as s:
                    task=await s.get(GeoContentTask,12);variant=await s.get(GeoChannelVariant,3)
                    account=await s.get(GeoChannelAccount,aid);channel=await s.get(GeoPublishingChannel,5)
                    if second:
                        pids['second']=await s.scalar(text('SELECT pg_backend_pid()'));second_ready.set()
                    try:
                        if second and scenario=='recovery_during_send':
                            from app.geo.content.multi_push import delivery_key
                            req=DeliveryResolution(tenant_id=7,action='allow_retry',note='Operator checked publication records',confirmed_not_published=True)
                            return await resolve_delivery(s,task=task,variant=variant,account=account,
                                key=delivery_key(task,variant,account,'publish'),req=req,user_id=9)
                        return await execute_single_push(s,task=task,variant=variant,account=account,channel_row=channel,mode='publish',article=None)
                    except (ValueError,HTTPException) as exc:return str(exc)
            with patch('app.geo.content.routes._build_rule_input',AsyncMock(return_value=None)), \
                 patch('app.geo.content.routes._ensure_tenant_exists',AsyncMock(return_value=object())), \
                 patch('app.geo.content.routes._brand_context_for_task',AsyncMock(return_value=('品牌',['品牌']))), \
                 patch('app.geo.content.gate.assert_can_publish'), \
                 patch('app.geo.content.multi_push.decrypt_credentials_json',return_value={'webhook_url':'https://example.com/publish'}), \
                 patch('app.geo.content.multi_push._perform_single_push',side_effect=send):
                a=asyncio.create_task(call(4));b=asyncio.create_task(call(6 if scenario=='different_accounts' else 4,True))
                try:
                    ready=asyncio.create_task(second_ready.wait())
                    done,_=await asyncio.wait((a,b,ready),timeout=10,return_when=asyncio.FIRST_COMPLETED)
                    if a in done or b in done:
                        failed=a if a in done else b
                        await failed
                        raise AssertionError('delivery worker exited before reaching the lock check')
                    if ready not in done:
                        raise TimeoutError('second delivery worker did not reach the lock check')
                    async with admin.connect() as c:
                        for _ in range(100):
                            blockers=await c.scalar(text('SELECT pg_blocking_pids(:pid)'),{'pid':pids['second']})
                            if pids['first'] in blockers:break
                            await asyncio.sleep(.05)
                        else:raise AssertionError('second sender did not wait on the task lock')
                    release.set();results=await asyncio.wait_for(asyncio.gather(a,b),15)
                finally:
                    release.set()
                    for worker in (a,b,ready):
                        if not worker.done():worker.cancel()
                    await asyncio.gather(a,b,ready,return_exceptions=True)
            async with sessions() as s:
                journal=(await s.get(GeoChannelVariant,3)).adapt_meta['push_deliveries']
                if scenario=='different_accounts':
                    assert sends==[4,6] and len(journal)==2
                    assert all(v['state']=='succeeded' for v in journal.values())
                elif scenario=='recovery_during_send':
                    assert sends==[4] and isinstance(results[1],str)
                    assert next(iter(journal.values()))['state']=='succeeded'
                elif scenario=='same_account':
                    assert sends==[4] and results[1]['deduplicated'] is True
                    assert next(iter(journal.values()))['state']=='succeeded'
                else:
                    assert sends==[4] and all(isinstance(r,str) for r in results)
                    assert next(iter(journal.values()))['state']=='unknown'
        finally:
            if engine:await engine.dispose()
            if created:
                async with admin.begin() as c:
                    for table in tables:await c.execute(text(f'DROP TABLE {schema}.{table}'))
                    await c.execute(text(f'DROP SCHEMA {schema}'))
            await admin.dispose()
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires authorized PostgreSQL')
def test_delivery_reloads_brand_after_reservation_commit():
    async def run():
        from app.geo.content import routes

        url=os.environ['GEO_TEST_POSTGRES_URL'];schema='geo_brand_delivery_'+uuid4().hex
        admin=create_async_engine(url);engine=None;created=False
        tables=['tenants','tenant_modules','geo_optimization_businesses','geo_content_tasks',
                'geo_channel_variants','geo_channel_accounts',
                'geo_publishing_channels','geo_article_versions']
        try:
            async with admin.begin() as c:
                await c.execute(text(f'CREATE SCHEMA {schema}'))
                for table in tables:
                    await c.execute(text(f'CREATE TABLE {schema}.{table} AS SELECT * FROM public.{table} WITH NO DATA'))
                await c.execute(text(f"INSERT INTO {schema}.tenants(id,name) VALUES(7,'租户名')"))
                await c.execute(text(f"INSERT INTO {schema}.tenant_modules(tenant_id,module_code,status) VALUES(7,'geo','active')"))
                await c.execute(text(f'''INSERT INTO {schema}.geo_optimization_businesses(id,tenant_id,name,profile,status,sort_order)
                    VALUES(20,7,'业务','{{"product_name":"旧品牌"}}','active',0)'''))
                await c.execute(text(f"INSERT INTO {schema}.geo_content_tasks(id,tenant_id,business_id,review_status,title,status) VALUES(12,7,20,'approved','title','ready')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_article_versions(id,task_id,version_no,title,body_markdown) VALUES(16,12,1,'title','body')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_channel_variants(id,task_id,article_version_id,channel,title,body_markdown,status,adapt_meta) VALUES(3,12,16,'website','title','body','draft','{{}}')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_publishing_channels(id,tenant_id,channel_type,publish_mode,enabled) VALUES(5,7,'website','auto_publish',true)"))
                await c.execute(text(f"INSERT INTO {schema}.geo_channel_accounts(id,tenant_id,channel_id,auth_type,status,credentials_encrypted) VALUES(4,7,5,'webhook','active','encrypted')"))
            created=True
            engine=create_async_engine(url,connect_args={'server_settings':{'search_path':schema,'statement_timeout':'15000'}})
            sessions=async_sessionmaker(engine,expire_on_commit=False)
            original=routes._brand_context_for_task;seen=[];send=AsyncMock()

            async def observe_brand(session,task,tenant,*,fresh=False):
                result=await original(session,task,tenant,fresh=fresh)
                seen.append((result[0],fresh))
                if len(seen)==1:
                    async with sessions() as other:
                        biz=await other.get(GeoOptimizationBusiness,20)
                        biz.profile={'product_name':'新品牌'}
                        await other.commit()
                return result

            def gate(_,*,task,brand,article_id):
                assert article_id == 16
                if brand=='新品牌':
                    raise ValueError('品牌标准未通过')

            async with sessions() as s:
                task=await s.get(GeoContentTask,12);variant=await s.get(GeoChannelVariant,3)
                account=await s.get(GeoChannelAccount,4);channel=await s.get(GeoPublishingChannel,5)
                with patch('app.geo.content.routes._brand_context_for_task',side_effect=observe_brand), \
                     patch('app.geo.content.routes._build_rule_input',AsyncMock(return_value=None)), \
                     patch('app.geo.content.gate.assert_can_publish',side_effect=gate), \
                     patch('app.geo.content.multi_push.decrypt_credentials_json',return_value={'webhook_url':'https://example.com/publish'}), \
                     patch('app.geo.content.multi_push._perform_single_push',send), \
                     pytest.raises(ValueError,match='品牌标准未通过'):
                    await execute_single_push(s,task=task,variant=variant,account=account,
                                              channel_row=channel,mode='publish',article=None)
            assert seen==[('旧品牌',False),('新品牌',True)]
            send.assert_not_awaited()
            async with sessions() as s:
                delivery=next(iter((await s.get(GeoChannelVariant,3)).adapt_meta['push_deliveries'].values()))
                assert delivery['state']=='failed'
                assert delivery['reason']=='publish_gate_changed_before_send'
        finally:
            if engine:await engine.dispose()
            if created:
                async with admin.begin() as c:
                    for table in tables:await c.execute(text(f'DROP TABLE {schema}.{table}'))
                    await c.execute(text(f'DROP SCHEMA {schema}'))
            await admin.dispose()
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires authorized PostgreSQL')
def test_revoked_social_send_rolls_back_credential_patch_and_persists_unknown_audit():
    async def run():
        url=os.environ['GEO_TEST_POSTGRES_URL'];schema='geo_revoked_delivery_'+uuid4().hex
        admin=create_async_engine(url);engine=None;created=False
        tables=['tenants','tenant_modules','geo_content_tasks','geo_channel_variants',
                'geo_channel_accounts','geo_publishing_channels','geo_article_versions',
                'geo_publications']
        try:
            async with admin.begin() as c:
                await c.execute(text(f'CREATE SCHEMA {schema}'))
                for table in tables:
                    await c.execute(text(f'CREATE TABLE {schema}.{table} AS SELECT * FROM public.{table} WITH NO DATA'))
                await c.execute(text(f"INSERT INTO {schema}.tenants(id,name) VALUES(7,'测试租户')"))
                await c.execute(text(f"INSERT INTO {schema}.tenant_modules(tenant_id,module_code,status) VALUES(7,'geo','active')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_content_tasks(id,tenant_id,review_status,title,status) VALUES(12,7,'approved','title','ready')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_article_versions(id,task_id,version_no,title,body_markdown) VALUES(16,12,1,'title','body')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_channel_variants(id,task_id,article_version_id,channel,title,body_markdown,status,adapt_meta) VALUES(3,12,16,'wechat','title','body','draft','{{}}')"))
                await c.execute(text(f"INSERT INTO {schema}.geo_publishing_channels(id,tenant_id,channel_type,name,publish_mode,enabled) VALUES(5,7,'wechat','WeChat test','auto_publish',true)"))
                await c.execute(text(f"INSERT INTO {schema}.geo_channel_accounts(id,tenant_id,channel_id,display_name,auth_type,status,credentials_encrypted) VALUES(4,7,5,'test account','oauth2','active','old-ciphertext')"))
            created=True
            engine=create_async_engine(url,connect_args={'server_settings':{'search_path':schema,'statement_timeout':'15000'}})
            sessions=async_sessionmaker(engine,expire_on_commit=False)
            entered=asyncio.Event();release=asyncio.Event()

            async def post_social(_credentials,_payload):
                entered.set();await asyncio.wait_for(release.wait(),10)
                return {'ok':True,'platform':'wechat','remote_url':'https://example.com/maybe-published',
                        'credential_patch':{'access_token':'rotated'},
                        'response':{'secret':'never-store'}}

            async def deliver():
                async with sessions() as s:
                    task=await s.get(GeoContentTask,12);variant=await s.get(GeoChannelVariant,3)
                    account=await s.get(GeoChannelAccount,4);channel=await s.get(GeoPublishingChannel,5)
                    return await execute_single_push(s,task=task,variant=variant,account=account,
                                                     channel_row=channel,mode='publish',article=None)

            credentials={'provider':'gateway','api_url':'https://example.com/push',
                         'access_token':'old','platform':'wechat'}
            with patch('app.geo.content.routes._build_rule_input',AsyncMock(return_value=None)), \
                 patch('app.geo.content.routes._ensure_tenant_exists',AsyncMock(return_value=object())), \
                 patch('app.geo.content.routes._brand_context_for_task',AsyncMock(return_value=('品牌',['品牌']))), \
                 patch('app.geo.content.gate.assert_can_publish'), \
                 patch('app.geo.content.multi_push.decrypt_credentials_json',return_value=credentials), \
                 patch('app.geo.content.multi_push.post_social',side_effect=post_social), \
                 patch('app.geo.content.ai_settings.encrypt_api_key',return_value='rotated-ciphertext'):
                worker=asyncio.create_task(deliver())
                await asyncio.wait_for(entered.wait(),5)
                async with sessions() as revoke:
                    await revoke.execute(text("UPDATE tenant_modules SET status='disabled' WHERE tenant_id=7 AND module_code='geo'"))
                    await revoke.commit()
                release.set()
                with pytest.raises(GeoEntitlementUnavailable):
                    await asyncio.wait_for(worker,10)

            async with sessions() as s:
                account=await s.get(GeoChannelAccount,4)
                variant=await s.get(GeoChannelVariant,3)
                delivery=next(iter(variant.adapt_meta['push_deliveries'].values()))
                assert account.credentials_encrypted=='old-ciphertext'
                assert delivery['state']=='unknown'
                assert delivery['reason']=='entitlement_revoked_after_send'
                assert delivery['manual_verification_required'] is True
                assert delivery['result']['remote_url']=='https://example.com/maybe-published'
                assert 'response' not in delivery['result'] and 'never-store' not in str(delivery)
                assert await s.scalar(text('SELECT count(*) FROM geo_publications'))==0
        finally:
            release.set()
            if engine:await engine.dispose()
            if created:
                async with admin.begin() as c:
                    for table in reversed(tables):await c.execute(text(f'DROP TABLE {schema}.{table}'))
                    await c.execute(text(f'DROP SCHEMA {schema}'))
            await admin.dispose()
    asyncio.run(run())
