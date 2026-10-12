"""Actual central JWT router -> SEO writer. Human checks are synthetic, no platform."""
import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.schema import CreateTable

from app.config import get_settings
from app.models.seo import SeoContentPublication, SeoPublishAttempt
from app.models.seo_page_capture import SeoPageCapture
from test_seo_distribution_broker_postgres import (shared, no_platform_http, environment,
    request, setup_task, exchange, receipt, SCOPE, EVIDENCE)

pytestmark=pytest.mark.skipif(os.getenv('SEO_DISTRIBUTION_INTEGRATION')!='true',reason='explicit local integration opt-in')
URL='https://mp.weixin.qq.com/s/synthetic-public-result'


@pytest.fixture(autouse=True)
def captures(monkeypatch):
    monkeypatch.setattr(get_settings(),'seo_page_capture_enabled',True)


async def schema(sessions,ledger=True):
    async with sessions.begin() as db:
        for model in (SeoContentPublication,SeoPublishAttempt,SeoPageCapture):
            await db.execute(CreateTable(model.__table__,include_foreign_key_constraints=[]))
    if ledger: await ledger_schema(sessions)


async def ledger_schema(sessions):
    async with sessions.begin() as db:
        conn=await db.connection();raw=await conn.get_raw_connection()
        await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/seo_distribution_results_schema.sql').read_text())


async def published(client,headers,admin):
    device,task,payload=await setup_task(client,headers,admin,'publish')
    await request(client,'POST','/account-policy',admin,json={'binding_id':payload['binding_id'],'expected_revision':0,
        'enabled':True,'timezone':'Asia/Shanghai','min_interval_seconds':0,'daily_limit':100,
        'windows':[{'start':0,'end':1440}],'request_id':str(uuid4())})
    dispatched=(await exchange(client,device))['tasks'][0]
    report={**receipt(dispatched),'code':'HUMAN_PUBLISHED','evidence':'human-reported','publicUrl':URL}
    ack=await exchange(client,device,[report])
    assert ack['receiptAcks'][0]['status']=='succeeded'
    return device,task


def check(task,**changes):
    return {**SCOPE,'task_id':task['id'],'mode':'human','expected_public_url':URL,
        'confirm_public_access':True,'confirm_target_account':True,'confirm_approved_content':True,
        'request_id':str(uuid4()),**changes}


async def count(db,table):
    assert table in {'seo_content_publications','seo_publish_attempts','seo_page_captures',
        'distribution_tasks','distribution_publication_checks','seo_distribution_result_events'}
    return await db.scalar(text('SELECT count(*) FROM '+table))


@pytest.mark.parametrize('state',['running','paused','ended'])
def test_actual_verified_writeback_native_capture_and_whitelist(shared,state):
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            await schema(sessions)
            device,task=await published(client,headers,admin)
            if state!='running':
                await request(client,'POST','/control',headers,json={**SCOPE,
                    'action':'pause' if state=='paused' else 'end','expected_revision':1,'request_id':str(uuid4())})
            payload=check(task)
            first=await request(client,'POST','/publication-check',headers,json=payload)
            native=first['publication']['writeback']
            assert native['state']=='written',native
            assert set(native['result'])=={'module','publication_id','monitor_state','verification','idempotent'}
            assert native['result']['module']=='seo' and native['result']['monitor_state']=='pending'
            assert native['result']['verification']=='human-verified'
            assert await request(client,'POST','/publication-check',headers,json=payload)==first
            further=await asyncio.gather(*(request(client,'POST','/publication-check',headers,json=check(task)) for _ in range(3)))
            assert all(r['publication']['writeback']['state']=='written' for r in further)
            view=await request(client,'GET','/tasks',headers,params=SCOPE)
            assert view['items'][0]['publication']['writeback']['result']==native['result']
            serialized=str(view)
            for secret in ('selection article body',device['credential'],'content_digest','external_account_id'):
                assert secret not in serialized
            async with sessions() as db:
                assert await count(db,'seo_content_publications')==1
                assert await count(db,'seo_publish_attempts')==1
                assert await count(db,'seo_page_captures')==1
                assert await count(db,'seo_distribution_result_events')==1
                publication=await db.get(SeoContentPublication,native['result']['publication_id'])
                assert publication.page_url==URL and publication.variant_id==60 and publication.status=='published'
                assert publication.link_discovery['search_engine_indexed'] is None
                capture=(await db.execute(text('SELECT relation_type,relation_id,status FROM seo_page_captures'))).one()
                assert capture==('publication',publication.id,'pending')
            EVIDENCE.append({'case':'actual-native-result','project_state':state,'verification':'human-verified',
                'native_publications':1,'page_checks':1,'page_state':'pending','indexed':None})
    asyncio.run(scenario())


def test_withdrawn_native_review_blocks_writeback(shared):
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            await schema(sessions)
            _,task=await published(client,headers,admin)
            async with sessions.begin() as db:
                await db.execute(text("UPDATE seo_distribution_variants SET status='draft' WHERE id=60"))
            response=await request(client,'POST','/publication-check',headers,json=check(task))
            assert response['publication']['writeback']['state']=='blocked'
            async with sessions() as db:
                assert await count(db,'seo_content_publications')==await count(db,'seo_page_captures')==0
            EVIDENCE.append({'case':'actual-native-withdrawn-review','state':'blocked','native_publications':0})
    asyncio.run(scenario())


def test_missing_native_schema_pending_then_explicit_write_only_retry(shared):
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            await schema(sessions,ledger=False)
            device,task=await published(client,headers,admin)
            response=await request(client,'POST','/publication-check',headers,json=check(task))
            outbox=response['publication']['writeback']
            assert outbox['state']=='pending' and outbox['result'] is None
            async with sessions() as db:
                assert await count(db,'seo_content_publications')==await count(db,'seo_page_captures')==0
            await ledger_schema(sessions)
            retry={**SCOPE,'task_id':task['id'],'event_id':outbox['event_id'],'request_id':str(uuid4())}
            done=await request(client,'POST','/publication-writeback',headers,json=retry)
            assert done['publication']['writeback']['state']=='written',done
            assert await request(client,'POST','/publication-writeback',headers,json=retry)==done
            assert (await exchange(client,device))['tasks']==[]
            async with sessions() as db:
                assert await count(db,'seo_content_publications')==await count(db,'seo_page_captures')==1
                assert await count(db,'distribution_tasks')==await count(db,'distribution_publication_checks')==1
            EVIDENCE.append({'case':'actual-native-schema-recovery','before':'pending','after':'written',
                'new_platform_tasks':0,'native_publications':1,'page_checks':1})
    asyncio.run(scenario())


def test_native_scope_three_checks_and_unconfirmed_receipt_rejected(shared):
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            await schema(sessions)
            _,task=await published(client,headers,admin)
            for field in ('confirm_public_access','confirm_target_account','confirm_approved_content'):
                await request(client,'POST','/publication-check',headers,expected=422,json=check(task,**{field:False}))
            await request(client,'POST','/publication-check',admin,expected=403,json=check(task))
            for scope in ({**SCOPE,'tenant_id':9},{**SCOPE,'scope_id':99}):
                for method,path in [('GET','/tasks'),('POST','/publication-check')]:
                    params={'params':scope} if method=='GET' else {'json':check(task,**scope)}
                    response=await client.request(method,'/api/distribution/v1'+path,headers=headers,**params)
                    assert response.status_code in {403,404}
            await request(client,'POST','/publication-check',headers,expected=422,json=check(task,body='client-body'))
            async with sessions.begin() as db:
                await db.execute(text("UPDATE distribution_tasks SET status='unknown' WHERE id=:id"),{'id':task['id']})
            await request(client,'POST','/publication-check',headers,expected=409,json=check(task))
            async with sessions() as db: assert await count(db,'seo_content_publications')==0
            EVIDENCE.append({'case':'actual-native-negative-scope-and-unconfirmed','native_publications':0})
    asyncio.run(scenario())


@pytest.mark.parametrize('evidence_source',['auto','manual'])
def test_actual_live_monitor_pending_to_captured_without_mutating_initial_snapshot(shared,monkeypatch,evidence_source):
    from app.api import seo_page_captures as native
    from app import seo_publication_monitor as jobs
    from test_seo_publication_monitor_postgres import Renderer
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            await schema(sessions)
            _,task=await published(client,headers,admin)
            created=await request(client,'POST','/publication-check',headers,json=check(task))
            original=created['publication']['writeback']['result']
            query={**SCOPE,'task_id':task['id']}
            renderer=Renderer()
            monkeypatch.setattr(native,'async_session_factory',sessions)
            monkeypatch.setattr(jobs,'async_session_factory',sessions)
            monkeypatch.setattr(native,'_capture_service',lambda:renderer)
            monkeypatch.setattr(get_settings(),'seo_scheduler_enabled',True)
            monkeypatch.setattr(get_settings(),'seo_external_actions_enabled',True)
            pending=await request(client,'GET','/publication-monitor',headers,params=query)
            assert pending['monitor']['state']=='pending' and renderer.calls==0
            if evidence_source=='auto':
                await native.execute_page_capture(pending['monitor']['evidence_id'])
            else:
                async with sessions.begin() as db:
                    db.add(SeoPageCapture(tenant_id=4,site_id=2,relation_type='publication',relation_id=original['publication_id'],
                        source_url=URL,status='succeeded',source='manual',uploaded_by=7,uploaded_at=datetime.now(timezone.utc),
                        captured_at=datetime.now(timezone.utc)+timedelta(seconds=1),sha256='b'*64,storage_key='b'*32+'.png',
                        warnings={},redirect_chain=[],viewport_width=800,viewport_height=600))
            # Later article edits do not invalidate a factual historical screenshot.
            async with sessions.begin() as db: await db.execute(text("UPDATE seo_distribution_variants SET status='draft' WHERE id=60"))
            live=await request(client,'GET','/publication-monitor',headers,params=query)
            value=live['monitor']
            assert value['state']=='captured' and value['evidence_source']==evidence_source and value['observed_at']
            assert set(value)=={'module','publication_id','basis','state','evidence_source','observed_at','next_check_at','evidence_id','code'}
            assert value['basis']=='page-capture' and value['publication_id']==original['publication_id']
            assert URL not in str(live) and 'storage_key' not in str(live) and 'selection article body' not in str(live)
            assert renderer.calls==(1 if evidence_source=='auto' else 0)
            async with sessions() as db:
                result=await db.scalar(text('SELECT result FROM distribution_publication_writebacks WHERE task_id=:id'),{'id':task['id']})
                assert result==original and result['monitor_state']=='pending'
                assert await count(db,'seo_content_publications')==await count(db,'distribution_tasks')==1
            EVIDENCE.append({'case':'actual-live-monitor','evidence_source':evidence_source,'state':'captured',
                'initial_snapshot':'pending','readonly_get_started_worker':False,'real_platform':False})
    asyncio.run(scenario())


def test_actual_live_monitor_current_scope_and_revoked_jwt_authority(shared):
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            await schema(sessions)
            _,task=await published(client,headers,admin)
            await request(client,'POST','/publication-check',headers,json=check(task))
            query={**SCOPE,'task_id':task['id']}
            assert (await request(client,'GET','/publication-monitor',headers,params=query))['monitor']['state']=='pending'
            await request(client,'GET','/publication-monitor',admin,expected=403,params=query)
            await request(client,'GET','/publication-monitor',headers,expected=403,params={**query,'tenant_id':9})
            async with sessions.begin() as db:
                await db.execute(text('UPDATE seo_site_advisor_assignments SET active=false WHERE id=3'))
            await request(client,'GET','/publication-monitor',headers,expected=403,params=query)
            async with sessions() as db:
                assert await count(db,'seo_page_captures')==1
                assert await db.scalar(text('SELECT status FROM seo_page_captures'))=='pending'
            EVIDENCE.append({'case':'actual-live-monitor-scope','revoked_identity_status':403,'readonly_get_started_worker':False})
    asyncio.run(scenario())
