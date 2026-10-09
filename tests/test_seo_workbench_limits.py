"""Real PostgreSQL races; every test uses a disposable schema in the opt-in test DB."""
import asyncio
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text, select

from test_seo_ai_operations import database
from app.models.seo import SeoAiOperation
from app.seo_ai_operations import SeoAiReplay, settle_seo_ai_operation, claim_seo_ai_operation
from app.seo_workbench_limits import claim_workbench_chat
from app.seo_usage_limits import WORKBENCH_CHAT_RESOURCE, workbench_user_resource

pytestmark=pytest.mark.skipif(not os.getenv('SEO_USAGE_TEST_DATABASE_URL'),reason='requires isolated PostgreSQL')


def limits(**overrides):
    return SimpleNamespace(**{'seo_workbench_chat_requests_per_tenant_per_day':100,
        'seo_workbench_chat_requests_per_user_per_day':30,'seo_workbench_chat_requests_per_user_per_minute':5,
        'seo_workbench_chat_concurrent_per_tenant':3,**overrides})


async def claim(session,*,actor='7',tenant=1,key=None,settings=None,payload=None):
    return await claim_workbench_chat(session,tenant,request_key=key or str(uuid4()),
        payload=payload or {'site_id':9},actor=actor,settings=settings or limits())


async def usage(sessions,tenant=1):
    async with sessions() as session:
        config=await session.scalar(text('SELECT module_settings FROM tenant_modules WHERE tenant_id=:tenant'),{'tenant':tenant})
        return config.get('seo_daily_usage') or {}


def test_concurrent_requests_across_sessions_and_sites_admit_only_one_per_user():
    async def scenario():
        async with database() as (sessions,_):
            async def start(i):
                async with sessions() as session:
                    try:return await claim(session,payload={'site_id':i})
                    except HTTPException as exc:assert exc.detail['code']=='assistant_user_busy'
            receipts=[r for r in await asyncio.gather(*(start(i) for i in range(20))) if r]
            assert len(receipts)==1
            counters=await usage(sessions)
            assert counters[WORKBENCH_CHAT_RESOURCE]==counters[workbench_user_resource('7')]==1
            assert counters.get('ai_requests',0)==0
            async with sessions() as session:
                await settle_seo_ai_operation(session,1,receipts[0]['operation_id'],result={'answer':'完成'})
    asyncio.run(scenario())


def test_tenant_concurrency_cap_and_independent_customer():
    async def scenario():
        async with database() as (sessions,_):
            async def start(i):
                async with sessions() as session:
                    try:return await claim(session,actor=str(i))
                    except HTTPException as exc:assert exc.detail['code']=='assistant_workspace_busy'
            assert len([r for r in await asyncio.gather(*(start(i) for i in range(12))) if r])==3
            async with sessions() as session:await claim(session,tenant=2,actor='7')
            assert (await usage(sessions,2))[WORKBENCH_CHAT_RESOURCE]==1
    asyncio.run(scenario())


@pytest.mark.parametrize('limited_by,code',[('user','assistant_user_daily_limit'),('tenant','assistant_tenant_daily_limit')])
def test_separate_daily_limits_recovery_and_original_seo_budget(limited_by,code):
    async def scenario():
        async with database() as (sessions,_):
            settings=limits(**{f'seo_workbench_chat_requests_per_{limited_by}_per_day':1})
            key=str(uuid4());result={'answer':'缓存回答'}
            async with sessions() as session:
                original=await claim_seo_ai_operation(session,1,request_key='draft',payload={},actor='7',kind='draft',limit=1)
                await settle_seo_ai_operation(session,1,original['operation_id'],result={'title':'稿件'})
                receipt=await claim(session,key=key,settings=settings)
                await settle_seo_ai_operation(session,1,receipt['operation_id'],result=result)
            async with sessions() as session:
                with pytest.raises(SeoAiReplay) as replay:await claim(session,key=key,settings=settings)
                assert replay.value.result==result
            async with sessions() as session:
                with pytest.raises(HTTPException) as exc:await claim(session,actor='8' if limited_by=='tenant' else '7',settings=settings)
                assert exc.value.detail['code']==code
                assert int(exc.value.headers['Retry-After'])>0
            counters=await usage(sessions)
            assert counters['ai_requests']==counters[WORKBENCH_CHAT_RESOURCE]==1
    asyncio.run(scenario())


def test_failed_calls_refund_both_daily_budgets_but_do_not_reset_frequency():
    async def scenario():
        async with database() as (sessions,_):
            last=None
            for _ in range(5):
                async with sessions() as session:
                    last=await claim(session)
                    await settle_seo_ai_operation(session,1,last['operation_id'])
                    await settle_seo_ai_operation(session,1,last['operation_id'])
            counters=await usage(sessions)
            assert counters[WORKBENCH_CHAT_RESOURCE]==counters[workbench_user_resource('7')]==0
            async with sessions() as session:
                with pytest.raises(HTTPException) as exc:await claim(session)
                assert exc.value.detail['code']=='assistant_rate_limited'
            async with sessions() as session:await claim(session,actor='8')
    asyncio.run(scenario())


def test_expired_lease_releases_concurrency_and_day_rollover_does_not_refund_new_day():
    async def scenario():
        async with database() as (sessions,_):
            async with sessions() as session:
                first=await claim(session)
                row=await session.get(SeoAiOperation,first['operation_id']);row.expires_at=datetime.utcnow()-timedelta(seconds=1)
                await session.commit()
            async with sessions() as session:second=await claim(session)
            assert (await usage(sessions))[WORKBENCH_CHAT_RESOURCE]==1
            async with sessions() as session:
                row=await session.get(SeoAiOperation,first['operation_id']);assert row.status=='refunded'
                row=await session.get(SeoAiOperation,second['operation_id']);row.charged_on='2000-01-01'
                await session.commit();await settle_seo_ai_operation(session,1,second['operation_id'])
            assert (await usage(sessions))[WORKBENCH_CHAT_RESOURCE]==1
    asyncio.run(scenario())


def test_old_chat_result_replays_without_new_charge_and_changed_site_is_rejected():
    async def scenario():
        async with database() as (sessions,_):
            key=str(uuid4());result={'answer':'旧结果'}
            async with sessions() as session:
                old=await claim_seo_ai_operation(session,1,request_key=key,payload={'site_id':9},actor='7',kind='workbench_chat',limit=100)
                await settle_seo_ai_operation(session,1,old['operation_id'],result=result)
            async with sessions() as session:
                with pytest.raises(SeoAiReplay) as replay:await claim(session,key=key)
                assert replay.value.result==result
            async with sessions() as session:
                with pytest.raises(HTTPException) as exc:await claim(session,key=key,payload={'site_id':10})
                assert exc.value.detail['code']=='request_conflict'
            counters=await usage(sessions)
            assert counters['ai_requests']==1 and counters.get(WORKBENCH_CHAT_RESOURCE,0)==0
    asyncio.run(scenario())
