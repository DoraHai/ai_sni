import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from app.geo.audit import GeoAuditError
from app.geo.publication_monitor import check_publication, initial_state, store_state, outcome, follow_up
from app.models import GeoActionTicket


def fixture():
    v = NS(id=2, article_version_id=3, title='Title', body_markdown='body', adapt_meta={'push_deliveries':{'key':{'state':'unknown'}}})
    pub = NS(id=4, published_url='https://example.com/a')
    content = NS(id=5,tenant_id=7)
    store_state(v,pub,initial_state(v))
    session = NS(scalar=AsyncMock(return_value=content), execute=AsyncMock(return_value=NS(first=lambda:(pub,v))), commit=AsyncMock())
    return v,pub,content,session


@pytest.mark.parametrize('kind', ['healthy','unreachable','mismatch','version_changed'])
def test_actual_fetch_classification_preserves_delivery_journal(kind):
    v,pub,content,s=fixture()
    fetch=AsyncMock(return_value=NS(html='html',final_url=pub.published_url))
    match={'observed_sha256':'real','expected_sha256':'expected'}
    if kind=='unreachable': fetch.side_effect=GeoAuditError('failed')
    if kind=='mismatch': match=HTTPException(409,'mismatch')
    if kind=='version_changed': v.body_markdown='edited'
    with patch('app.geo.publication_monitor.safe_fetch',fetch), \
         patch('app.geo.publication_monitor.match_publication',side_effect=match if isinstance(match,Exception) else None,return_value=match), \
         patch('app.geo.publication_monitor.follow_up',AsyncMock()):
        result=asyncio.run(check_publication(s,7,5,4))
    assert result['state']==kind
    assert v.adapt_meta['push_deliveries']['key']['state']=='unknown'
    assert s.commit.await_count==1
    assert fetch.await_count==(0 if kind=='version_changed' else 1)


def test_missing_tenant_task_cannot_fetch_or_read_publication():
    _,_,_,s=fixture();s.scalar.return_value=None
    with pytest.raises(HTTPException) as exc:
        asyncio.run(check_publication(s,8,5,4))
    assert exc.value.status_code==404 and s.execute.await_count==0


def test_repeat_click_uses_recent_result():
    v,pub,_,s=fixture()
    store_state(v,pub,{**initial_state(v),'checked_at':datetime.utcnow().isoformat()+'Z'})
    with patch('app.geo.publication_monitor.safe_fetch',AsyncMock()) as fetch:
        asyncio.run(check_publication(s,7,5,4))
    fetch.assert_not_awaited()


def test_failure_does_not_retimestamp_stale_matching_proof():
    state=outcome({'observed_sha256':'old','expected_sha256':'old','history':[{}]*40},'unreachable',datetime(2026,9,6))
    assert 'observed_sha256' not in state and len(state['history'])==30
    assert state['next_check_at']=='2026-09-06T01:00:00Z'


def test_first_failure_does_not_create_ticket_second_failure_does():
    _,p,c,_=fixture();added=[]
    s=NS(scalar=AsyncMock(return_value=None),add=added.append)
    asyncio.run(follow_up(s,c,p,{'state':'unreachable','failures':1}))
    assert not added
    asyncio.run(follow_up(s,c,p,{'state':'unreachable','failures':2}))
    assert len(added)==1 and added[0].status=='todo'


def test_recovery_closes_and_regression_reopens_same_ticket():
    _,p,c,_=fixture();row=GeoActionTicket(id=1,status='doing',owner_name='customer',progress={})
    s=NS(scalar=AsyncMock(return_value=row),add=lambda _:pytest.fail('duplicate'))
    asyncio.run(follow_up(s,c,p,{'state':'healthy','failures':0}))
    assert row.status=='done' and row.closed_at is not None
    asyncio.run(follow_up(s,c,p,{'state':'mismatch','failures':2}))
    assert row.status=='reopened' and row.closed_at is None and row.owner_name=='customer'


def test_recovered_ticket_requires_two_failures_to_reopen_and_preserves_closure_time():
    _,p,c,_=fixture();closed=datetime(2026,9,1)
    row=GeoActionTicket(id=1,status='done',closed_at=closed,progress={})
    s=NS(scalar=AsyncMock(return_value=row),add=lambda _:pytest.fail('duplicate'))
    asyncio.run(follow_up(s,c,p,{'state':'healthy','failures':0}))
    assert row.closed_at==closed
    asyncio.run(follow_up(s,c,p,{'state':'unreachable','failures':1}))
    assert row.status=='done' and row.closed_at==closed and row.last_verdict=='pending'
    asyncio.run(follow_up(s,c,p,{'state':'unreachable','failures':2}))
    assert row.status=='reopened' and row.closed_at is None


def test_timeout_is_recorded_as_unknown_availability_not_a_content_match():
    _,_,_,s=fixture()
    with patch('app.geo.publication_monitor.safe_fetch',AsyncMock(side_effect=TimeoutError)), \
         patch('app.geo.publication_monitor.follow_up',AsyncMock()):
        result=asyncio.run(check_publication(s,7,5,4))
    assert result['state']=='unreachable' and 'observed_sha256' not in result
    s.commit.assert_awaited_once()


def test_cancelled_fetch_does_not_commit_success_or_failure():
    v,p,_,s=fixture()
    old=dict(v.adapt_meta['publication_monitor'][str(p.id)])
    with patch('app.geo.publication_monitor.safe_fetch',AsyncMock(side_effect=asyncio.CancelledError)):
        with pytest.raises(asyncio.CancelledError):asyncio.run(check_publication(s,7,5,4))
    s.commit.assert_not_awaited()
    assert v.adapt_meta['publication_monitor'][str(p.id)]==old


def test_failed_worker_defers_without_fabricating_a_page_failure():
    from app.geo.publication_monitor import defer_monitor_failure
    v,p,_,s=fixture()
    old={**initial_state(v),'state':'healthy','checked_at':'2026-09-01T00:00:00Z','observed_sha256':'real-proof','failures':0}
    store_state(v,p,old)
    asyncio.run(defer_monitor_failure(s,7,5,4))
    result=v.adapt_meta['publication_monitor']['4']
    assert result['state']=='healthy' and result['failures']==0
    assert result['checked_at']==old['checked_at'] and result['observed_sha256']=='real-proof'
    assert result['last_error']['kind']=='check_incomplete' and result['next_check_at']
    s.commit.assert_awaited_once()


def test_monitor_cannot_be_manually_marked_complete():
    from app.geo.routes import patch_action_ticket,TicketUpdate
    row=NS(advice_code='monitor:v1:4')
    with patch('app.geo.routes._work_ticket_for_update',AsyncMock(return_value=row)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(patch_action_ticket(1,TicketUpdate(manual_pass=True),7,NS(ensure_tenant=lambda _:None),NS()))
    assert exc.value.status_code==409


def test_export_never_downgrades_published_variant_or_drops_monitor_state():
    from app.geo.content.routes import export_variant
    v,_,c,s=fixture();v.channel='website';v.status='published';c.status='published'
    v.adapt_meta['body_html']='<p>body</p>';s.refresh=AsyncMock()
    with patch('app.geo.content.routes._get_task',AsyncMock(return_value=c)), \
         patch('app.geo.content.routes._variants',AsyncMock(return_value=[v])), \
         patch('app.geo.content.routes._sync_task_pipeline',AsyncMock()):
        result=asyncio.run(export_variant(5,7,'website',NS(ensure_tenant=lambda _:None),s))
    assert result['status']=='published' and 'publication_monitor' in v.adapt_meta
    s.refresh.assert_awaited_once_with(c,with_for_update=True)
