import asyncio
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from app.geo.content.multi_push import execute_single_push, delivery_key
from app.geo.content.review import assert_review_approved, apply_decision


def setup_case(review='approved'):
    task=NS(id=12,tenant_id=1,review_status=review)
    variant=NS(id=3,task_id=12,article_version_id=16,title='title',body_markdown='body',adapt_meta={})
    account=NS(id=4,channel_id=5,tenant_id=1,status='active',auth_type='webhook',credentials_encrypted='encrypted')
    channel=NS(id=5,tenant_id=1,enabled=True,publish_mode='auto_publish',channel_type='website')
    article=NS(id=16)
    session=NS(refresh=AsyncMock(),commit=AsyncMock())
    args=dict(task=task,variant=variant,account=account,channel_row=channel,article=article,mode='publish')
    return session,args


def patches(args,perform):
    stack=ExitStack()
    stack.enter_context(patch('app.geo.content.routes._latest_article',AsyncMock(return_value=args['article'])))
    stack.enter_context(patch('app.geo.content.routes._build_rule_input',AsyncMock(return_value=None)))
    stack.enter_context(patch('app.geo.content.gate.assert_can_publish',side_effect=lambda _,task:assert_review_approved(task)))
    stack.enter_context(patch('app.geo.content.multi_push._perform_single_push',perform))
    stack.enter_context(patch('app.geo.content.multi_push.decrypt_credentials_json',return_value={'webhook_url':'https://example.com/publish'}))
    stack.enter_context(patch('app.geo.content.multi_push.asyncio.sleep',AsyncMock()))
    return stack


def test_success_is_reserved_before_send_and_reused_on_repeat():
    session,args=setup_case()
    async def perform(*a,**kw):
        session.commit.assert_awaited_once()
        assert next(iter(args['variant'].adapt_meta['push_deliveries'].values()))['state']=='sending'
        return {'ok':True,'remote_url':'https://example.com/article','response':{'token':'never-store'}}
    send=AsyncMock(side_effect=perform)
    with patches(args,send):
        first=asyncio.run(execute_single_push(session,**args))
        second=asyncio.run(execute_single_push(session,**args))
    assert second['deduplicated'] is True and send.await_count==1
    assert 'response' not in first and 'never-store' not in str(args['variant'].adapt_meta)


@pytest.mark.parametrize('review',['none','pending','rejected'])
def test_unapproved_never_reaches_connector(review):
    session,args=setup_case(review); send=AsyncMock()
    with patches(args,send),pytest.raises(ValueError):asyncio.run(execute_single_push(session,**args))
    send.assert_not_awaited();session.commit.assert_not_awaited()


def test_connection_failure_retries_then_succeeds():
    session,args=setup_case()
    send=AsyncMock(side_effect=[httpx.ConnectTimeout('connect'),httpx.ConnectError('connect'),{'ok':True}])
    with patches(args,send):asyncio.run(execute_single_push(session,**args))
    assert send.await_count==3
    assert next(iter(args['variant'].adapt_meta['push_deliveries'].values()))['attempts']==3


def test_response_timeout_is_durable_unknown_and_blocks_resend():
    session,args=setup_case();send=AsyncMock(side_effect=httpx.ReadTimeout('ambiguous'))
    with patches(args,send):
        for _ in range(2):
            with pytest.raises(ValueError):asyncio.run(execute_single_push(session,**args))
    assert send.await_count==1
    assert next(iter(args['variant'].adapt_meta['push_deliveries'].values()))['state']=='unknown'


def test_safe_failure_stops_after_three_attempts():
    session,args=setup_case();send=AsyncMock(side_effect=httpx.ConnectError('connect'))
    with patches(args,send),pytest.raises(ValueError):asyncio.run(execute_single_push(session,**args))
    assert send.await_count==3
    assert next(iter(args['variant'].adapt_meta['push_deliveries'].values()))['state']=='failed'


def test_durable_inflight_reservation_blocks_second_sender():
    session,args=setup_case();send=AsyncMock()
    key=delivery_key(args['task'],args['variant'],args['account'],'publish')
    args['variant'].adapt_meta={'push_deliveries':{key:{'state':'sending'}}}
    with patches(args,send),pytest.raises(ValueError):asyncio.run(execute_single_push(session,**args))
    send.assert_not_awaited()


def test_approval_changed_after_reservation_aborts_without_send():
    session,args=setup_case();send=AsyncMock()
    calls=0
    async def refresh(row,**kwargs):
        nonlocal calls
        if row is args['task']:
            calls+=1
            if calls==2:row.review_status='none'
    session.refresh.side_effect=refresh
    with patches(args,send),pytest.raises(ValueError):asyncio.run(execute_single_push(session,**args))
    send.assert_not_awaited()


def test_api_key_cannot_supply_anonymous_human_approval():
    with pytest.raises(ValueError):apply_decision(NS(review_status='pending'),decision='approved',note='ok',reviewer_id=None)


def test_delivery_identity_distinguishes_mode_account_and_content():
    _,args=setup_case();t,v,a=args['task'],args['variant'],args['account']
    key=delivery_key(t,v,a,'publish')
    assert delivery_key(t,v,a,'draft')!=key
    a.id+=1;assert delivery_key(t,v,a,'publish')!=key
    a.id-=1;v.body_markdown='changed';assert delivery_key(t,v,a,'publish')!=key


def test_sibling_reservation_is_preserved_when_result_is_saved():
    session,args=setup_case()
    async def send(*a,**kw):
        meta=args['variant'].adapt_meta
        meta['push_deliveries']['sibling']={'state':'sending','account_id':99}
        return {'ok':True}
    with patches(args,AsyncMock(side_effect=send)):
        asyncio.run(execute_single_push(session,**args))
    assert args['variant'].adapt_meta['push_deliveries']['sibling']['state']=='sending'
