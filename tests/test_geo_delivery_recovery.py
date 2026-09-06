import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from app.geo.content.delivery_recovery import DeliveryResolution, resolve_delivery, delivery_items
from app.geo.content.multi_push import delivery_key


def case(**overrides):
    task = NS(id=12, tenant_id=1, review_status='approved')
    variant = NS(id=3, task_id=12, article_version_id=16, title='测试文章',
                 channel='website', body_markdown='这是需要在网站实际出现的段落内容。' * 40, adapt_meta={})
    account = NS(id=4, tenant_id=1)
    key = delivery_key(task, variant, account, 'publish')
    entry = dict(state='unknown', account_id=4, mode='publish', article_id=16, updated_at='2026-01-01T00:00:00')
    entry.update(overrides)
    variant.adapt_meta = {'keep': True, 'push_deliveries': {key: entry}}
    return dict(session=NS(refresh=AsyncMock(), commit=AsyncMock()), task=task,
                variant=variant, account=account, key=key, user_id=9)


def request(action='allow_retry', **kw):
    return DeliveryResolution(tenant_id=1, action=action, note='已进入渠道后台逐项核对相应文章记录', **kw)


def run(args, req, fetch=None):
    with patch('app.geo.content.routes._latest_article', AsyncMock(return_value=NS(id=16))), \
         patch('app.geo.content.routes._write_publication', AsyncMock()) as write, \
         patch('app.geo.content.delivery_recovery.safe_fetch', fetch or AsyncMock()):
        result = asyncio.run(resolve_delivery(**args, req=req))
        return result, write


def test_allow_retry_is_explicit_audited_and_does_not_publish():
    args = case(); fetch = AsyncMock()
    result, write = run(args, request(confirmed_not_published=True), fetch)
    assert result['state'] == 'failed'
    entry = args['variant'].adapt_meta['push_deliveries'][args['key']]
    assert entry['recovery_history'][0]['user_id'] == 9
    assert args['variant'].adapt_meta['keep'] is True
    fetch.assert_not_awaited(); write.assert_not_awaited()
    args['session'].commit.assert_awaited_once()


@pytest.mark.parametrize('kind', ['anonymous', 'unchecked', 'fresh_send', 'wrong_tenant', 'wrong_version', 'unapproved', 'resolved'])
def test_unsafe_recovery_never_changes_state(kind):
    args = case(); req = request(confirmed_not_published=kind != 'unchecked')
    entry = args['variant'].adapt_meta['push_deliveries'][args['key']]
    if kind == 'anonymous': args['user_id'] = None
    if kind == 'fresh_send': entry.update(state='sending', updated_at=datetime.now(timezone.utc).isoformat())
    if kind == 'wrong_tenant': args['account'].tenant_id = 2
    if kind == 'wrong_version': args['variant'].article_version_id = 17
    if kind == 'unapproved': args['task'].review_status = 'pending'
    if kind == 'resolved': entry['state'] = 'succeeded'
    with pytest.raises(HTTPException): run(args, req)
    args['session'].commit.assert_not_awaited()


def test_verified_publication_requires_real_body_and_records_hashes():
    args = case(); v = args['variant']
    html = f'<h1>{v.title}</h1><p>{v.body_markdown}</p>'
    fetch = AsyncMock(return_value=NS(html=html, final_url='https://example.com/article'))
    result, write = run(args, request('confirm_published', published_url='https://example.com/article'), fetch)
    assert result['state'] == 'succeeded'
    write.assert_awaited_once()
    event = v.adapt_meta['push_deliveries'][args['key']]['recovery_history'][0]
    assert len(event['evidence']['observed_sha256']) == 64
    assert 'completion_evidence' not in result


def test_matching_title_alone_does_not_confirm_publication():
    args = case()
    fetch = AsyncMock(return_value=NS(html='<h1>测试文章</h1>', final_url='https://example.com/article'))
    with pytest.raises(HTTPException):
        run(args, request('confirm_published', published_url='https://example.com/article'), fetch)
    args['session'].commit.assert_not_awaited()


def test_list_exposes_no_connector_result_or_reservation():
    args = case(result={'response': 'secret'}, reservation_id='private')
    rows = delivery_items([args['variant']])
    assert 'secret' not in str(rows) and 'reservation_id' not in str(rows)


def availability(args, **kw):
    from app.geo.content.delivery_recovery import recovery_availability
    return recovery_availability(**{k:v for k,v in args.items() if k != 'session'},
        article=NS(id=16), entry=args['variant'].adapt_meta['push_deliveries'][args['key']], **kw)


@pytest.mark.parametrize('seconds,allowed', [(599,False),(600,True)])
def test_recovery_availability_uses_exact_wait_boundary(seconds,allowed):
    from datetime import timedelta
    start=datetime(2026,9,6,tzinfo=timezone.utc)
    args=case(state='sending',updated_at=start.isoformat())
    result=availability(args,now=start+timedelta(seconds=seconds))
    assert result['can_allow_retry'] is allowed
    assert result['available_at']=='2026-09-06T00:10:00+00:00'
    assert bool(result['blocked_reason']) is not allowed


@pytest.mark.parametrize('kind', ['anonymous','changed_body','unapproved','missing_account','bad_time','resolved','limit'])
def test_list_recovery_options_fail_closed_for_blocked_records(kind):
    args=case()
    entry=args['variant'].adapt_meta['push_deliveries'][args['key']]
    if kind=='anonymous':args['user_id']=None
    if kind=='changed_body':args['variant'].body_markdown+='a change'
    if kind=='unapproved':args['task'].review_status='pending'
    if kind=='missing_account':args['account']=None
    if kind=='bad_time':entry.update(state='sending',updated_at=12345)
    if kind=='resolved':entry['state']='succeeded'
    if kind=='limit':entry['recovery_history']=[{}]*100
    result=availability(args)
    assert not result['can_confirm_published'] and not result['can_allow_retry']
    assert result['blocked_reason']


def test_draft_recovery_never_offers_confirm_published():
    args=case(mode='draft')
    old=args['key'];args['key']=delivery_key(args['task'],args['variant'],args['account'],'draft')
    journal=args['variant'].adapt_meta['push_deliveries'];journal[args['key']]=journal.pop(old)
    result=availability(args)
    assert result['can_allow_retry'] and not result['can_confirm_published']


def test_delivery_list_adds_availability_without_mutating_journal():
    from app.geo.content.routes import list_task_deliveries
    args=case();variant=args['variant'];session=args['session']
    import copy
    before=copy.deepcopy(variant.adapt_meta)
    session.scalars=AsyncMock(return_value=[args['account']])
    with patch('app.geo.content.routes._get_task',AsyncMock(return_value=args['task'])), \
         patch('app.geo.content.routes._variants',AsyncMock(return_value=[variant])), \
         patch('app.geo.content.routes._latest_article',AsyncMock(return_value=NS(id=16))):
        result=asyncio.run(list_task_deliveries(12,1,NS(user_id=9,ensure_tenant=lambda _:None),session))
    assert result['actionable_count']==1 and result['blocked_count']==0
    assert result['items'][0]['can_confirm_published']
    assert variant.adapt_meta==before
    session.commit.assert_not_awaited()
