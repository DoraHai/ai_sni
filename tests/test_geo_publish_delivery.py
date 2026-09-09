import asyncio
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from fastapi import HTTPException
from app.geo.content.multi_push import (
    delivery_key,
    execute_single_push,
    record_revoked_inflight_delivery,
)
from app.geo.content.review import assert_review_approved, apply_decision
from app.geo.tenant_scope import GeoEntitlementUnavailable


def setup_case(review='approved'):
    task=NS(id=12,tenant_id=1,review_status=review)
    variant=NS(id=3,task_id=12,article_version_id=16,title='title',body_markdown='body',adapt_meta={})
    account=NS(id=4,channel_id=5,tenant_id=1,status='active',auth_type='webhook',credentials_encrypted='encrypted')
    channel=NS(id=5,tenant_id=1,enabled=True,publish_mode='auto_publish',channel_type='website')
    article=NS(id=16)
    session=NS(refresh=AsyncMock(),commit=AsyncMock(),rollback=AsyncMock(),
               flush=AsyncMock(),scalar=AsyncMock(return_value=object()))
    args=dict(task=task,variant=variant,account=account,channel_row=channel,article=article,mode='publish')
    return session,args


def patches(args,perform, *, entitlement=True):
    stack=ExitStack()
    stack.enter_context(patch('app.geo.content.routes._latest_article',AsyncMock(return_value=args['article'])))
    stack.enter_context(patch('app.geo.content.routes._build_rule_input',AsyncMock(return_value=None)))
    stack.enter_context(patch('app.geo.content.routes._ensure_tenant_exists',AsyncMock(return_value=NS(id=1,name='租户名'))))
    stack.enter_context(patch('app.geo.content.routes._brand_context_for_task',AsyncMock(return_value=('业务品牌',['业务品牌']))))
    stack.enter_context(patch('app.geo.content.gate.assert_can_publish',side_effect=lambda _,task,brand:assert_review_approved(task)))
    stack.enter_context(patch('app.geo.content.multi_push._perform_single_push',perform))
    stack.enter_context(patch('app.geo.content.multi_push.decrypt_credentials_json',return_value={'webhook_url':'https://example.com/publish'}))
    stack.enter_context(patch('app.geo.content.multi_push.asyncio.sleep',AsyncMock()))
    if entitlement:
        stack.enter_context(patch('app.geo.tenant_scope.ensure_geo_entitlement', AsyncMock()))
    return stack


def test_execution_gate_uses_current_business_brand_before_connector():
    session,args=setup_case();send=AsyncMock(return_value={'ok':True})
    gate=AsyncMock(return_value=('MAXXDRIVE',['MAXXDRIVE']))
    checked=[]
    def assert_gate(_,*,task,brand):
        assert_review_approved(task)
        checked.append(brand)
    with patches(args,send), \
         patch('app.geo.content.routes._brand_context_for_task',gate), \
         patch('app.geo.content.gate.assert_can_publish',side_effect=assert_gate):
        asyncio.run(execute_single_push(session,**args))
    assert checked == ['MAXXDRIVE','MAXXDRIVE']
    assert gate.await_count == 2
    send.assert_awaited_once()


def test_expired_geo_access_blocks_before_connector_or_reservation():
    session,args=setup_case();send=AsyncMock()
    session.scalar.return_value=None
    with patches(args,send,entitlement=False),pytest.raises(HTTPException) as error:
        asyncio.run(execute_single_push(session,**args))
    assert getattr(error.value, 'status_code', None) == 403
    send.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_brand_change_after_reservation_blocks_before_connector():
    session,args=setup_case();send=AsyncMock()
    brands=iter([('旧品牌',['旧品牌']),('新品牌',['新品牌'])])
    gate=AsyncMock(side_effect=lambda *_,**__: next(brands))
    def assert_gate(_,*,task,brand):
        assert_review_approved(task)
        if brand == '新品牌':
            raise ValueError('品牌标准未通过')
    with patches(args,send), \
         patch('app.geo.content.routes._brand_context_for_task',gate), \
         patch('app.geo.content.gate.assert_can_publish',side_effect=assert_gate), \
         pytest.raises(ValueError,match='品牌标准未通过'):
        asyncio.run(execute_single_push(session,**args))
    assert gate.await_count == 2
    send.assert_not_awaited()
    delivery=next(iter(args['variant'].adapt_meta['push_deliveries'].values()))
    assert delivery['state'] == 'failed'
    assert delivery['reason'] == 'publish_gate_changed_before_send'
    assert gate.await_args_list[1].kwargs['fresh'] is True


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


def test_revoked_social_send_rolls_back_credential_patch_then_records_unknown():
    session,args=setup_case();revoked=False
    args['variant'].channel='wechat'
    args['channel_row'].channel_type='wechat'
    args['channel_row'].name='WeChat test'
    args['account'].auth_type='oauth2'
    args['account'].display_name='test account'
    original_ciphertext=args['account'].credentials_encrypted
    async def ensure(_session,_tenant_id):
        if revoked:
            raise GeoEntitlementUnavailable()
    async def post_social(_credentials,_payload):
        nonlocal revoked
        revoked=True
        return {'ok':True,'platform':'wechat','remote_url':'https://example.com/maybe-published',
                'credential_patch':{'access_token':'rotated'},
                'response':{'secret':'never-store'}}
    async def rollback():
        args['account'].credentials_encrypted=original_ciphertext
    session.rollback.side_effect=rollback
    session.scalar.side_effect=[args['task'].id,args['variant']]
    with patch('app.geo.content.routes._latest_article',AsyncMock(return_value=args['article'])), \
         patch('app.geo.content.routes._build_rule_input',AsyncMock(return_value=None)), \
         patch('app.geo.content.routes._ensure_tenant_exists',AsyncMock(return_value=NS(id=1,name='租户名'))), \
         patch('app.geo.content.routes._brand_context_for_task',AsyncMock(return_value=('业务品牌',['业务品牌']))), \
         patch('app.geo.content.gate.assert_can_publish'), \
         patch('app.geo.content.multi_push.decrypt_credentials_json',return_value={
             'provider':'gateway','api_url':'https://example.com/push','access_token':'old'}), \
         patch('app.geo.content.multi_push.post_social',side_effect=post_social), \
         patch('app.geo.content.ai_settings.encrypt_api_key',return_value='rotated-ciphertext'), \
         patch('app.geo.tenant_scope.ensure_geo_entitlement',side_effect=ensure), \
         pytest.raises(GeoEntitlementUnavailable):
        asyncio.run(execute_single_push(session,**args))
    delivery=next(iter(args['variant'].adapt_meta['push_deliveries'].values()))
    assert delivery['state']=='unknown'
    assert delivery['reason']=='entitlement_revoked_after_send'
    assert delivery['manual_verification_required'] is True
    assert delivery['result']['remote_url']=='https://example.com/maybe-published'
    assert 'response' not in delivery['result'] and 'never-store' not in str(delivery)
    assert session.commit.await_count==2
    assert session.rollback.await_count==1
    assert args['account'].credentials_encrypted==original_ciphertext


def test_revoked_inflight_audit_does_not_overwrite_concurrent_recovery():
    key='delivery-key';resolved={'reservation_id':'new','state':'failed',
        'reason':'operator_confirmed_not_published','recovery_history':[{'action':'allow_retry'}]}
    variant=NS(id=3,task_id=12,adapt_meta={'push_deliveries':{key:resolved}})
    session=NS(rollback=AsyncMock(),scalar=AsyncMock(side_effect=[12,variant]),commit=AsyncMock())
    saved=asyncio.run(record_revoked_inflight_delivery(session,task_id=12,variant_id=3,
        key=key,reservation_id='old',account_id=4,mode='publish',article_id=16,attempt=1,
        result={'remote_url':'https://example.com/maybe'}))
    assert saved is False
    assert variant.adapt_meta['push_deliveries'][key]==resolved
    assert session.rollback.await_count==2
    session.commit.assert_not_awaited()


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


def test_recovery_revokes_reserved_sender_before_external_send():
    session,args=setup_case();send=AsyncMock();calls=0
    async def refresh(row,**kwargs):
        nonlocal calls
        if row is args['task']:
            calls+=1
            if calls==2:
                entry=next(iter(args['variant'].adapt_meta['push_deliveries'].values()))
                entry.update(state='failed',reason='operator_confirmed_not_published')
    session.refresh.side_effect=refresh
    with patches(args,send),pytest.raises(ValueError):asyncio.run(execute_single_push(session,**args))
    send.assert_not_awaited()
    assert next(iter(args['variant'].adapt_meta['push_deliveries'].values()))['reason']=='operator_confirmed_not_published'


def test_retry_keeps_operator_recovery_history():
    session,args=setup_case();send=AsyncMock(return_value={'ok':True})
    key=delivery_key(args['task'],args['variant'],args['account'],'publish')
    history=[{'action':'allow_retry','user_id':9,'note':'checked platform'}]
    args['variant'].adapt_meta={'push_deliveries':{key:{'state':'failed','recovery_history':history}}}
    with patches(args,send):asyncio.run(execute_single_push(session,**args))
    assert args['variant'].adapt_meta['push_deliveries'][key]['recovery_history']==history
