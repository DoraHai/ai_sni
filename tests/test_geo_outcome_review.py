import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from app.geo.outcome_review import assess_outcome, update_outcome_review
from app.geo.integration import completion_evidence
from test_geo_integration import task, state, metric_map, MENTIONS


@pytest.mark.parametrize('value,expected', [(0,'needs_review'),(12,'target_met')])
def test_review_uses_same_comparability_rules_without_auto_completing_task(value, expected):
    row=task();current=state();metric_map(current)[MENTIONS]['value']=value
    with patch('app.geo.outcome_review.snapshot',AsyncMock(side_effect=[current,row.baseline_snapshot])):
        result=asyncio.run(assess_outcome(NS(),row))
    assert result['state']==expected and row.status=='doing' and not row.progress
    if value==0:
        with pytest.raises(HTTPException):completion_evidence(row,current)


@pytest.mark.parametrize('change', ['missing','cohort','baseline_corrected','not_published'])
def test_unknown_or_incomparable_data_cannot_be_called_no_improvement(change):
    row=task();current=state();fresh=deepcopy(row.baseline_snapshot)
    if change=='missing':metric_map(current)[MENTIONS]['value']=None
    if change=='cohort':current['cohort']=[]
    if change=='baseline_corrected':fresh['sample_ids']=[999]
    if change=='not_published':row.progress_first['params']['content_task_id']=12
    with patch('app.geo.outcome_review.snapshot',AsyncMock(side_effect=[current,fresh])):
        with pytest.raises(HTTPException):asyncio.run(assess_outcome(NS(),row))


def test_missing_data_stores_waiting_and_does_not_create_work():
    row=task();row.progress_first['params']['content_task_id']=12
    s=NS(scalar=AsyncMock(side_effect=[row,None]),commit=AsyncMock(),add=lambda _:pytest.fail('must not create'))
    with patch('app.geo.outcome_review.assess_outcome',AsyncMock(side_effect=HTTPException(409,'not enough data'))):
        asyncio.run(update_outcome_review(s,10))
    assert row.progress['outcome_review']['state']=='waiting' and row.status=='doing'


def test_review_completion_requires_recorded_conclusion():
    from app.geo.routes import patch_action_ticket, TicketUpdate
    with patch('app.geo.routes._work_ticket_for_update',AsyncMock(return_value=NS(advice_code='review:v1:10'))):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(patch_action_ticket(1,TicketUpdate(manual_pass=True),7,NS(ensure_tenant=lambda _:None),NS()))
    assert exc.value.status_code==400


def test_repeated_review_reuses_ticket_and_same_week_does_not_reopen_finished_review():
    row=task();row.progress_first['params']['content_task_id']=12
    current=state();metric_map(current)[MENTIONS]['value']=0
    evidence=completion_evidence(row,current,{'first_verified_at':'2026-08-23T15:00:00Z'},require_target=False)
    assessment={'state':'needs_review','evidence':evidence}
    follow=NS(progress={'outcome_review':assessment},status='done')
    s=NS(scalar=AsyncMock(side_effect=[row,follow]),commit=AsyncMock(),add=lambda _:pytest.fail('duplicate'))
    with patch('app.geo.outcome_review.assess_outcome',AsyncMock(return_value=assessment)):
        asyncio.run(update_outcome_review(s,10))
    assert follow.status=='done' and row.status=='doing'


@pytest.mark.parametrize('new_state',['waiting','target_met'])
def test_later_observation_updates_existing_review_without_erasing_history_or_auto_closing(new_state):
    row=task();row.progress_first['params']['content_task_id']=12
    historical={'state':'needs_review','evidence':{'after':{'as_of':'2026-08-31'}}}
    follow=NS(progress={'outcome_review':historical},status='doing',evidence=[{'note':'customer plan'}])
    assessment={'state':new_state,'reason':'data missing'}
    s=NS(scalar=AsyncMock(side_effect=[row,follow]),commit=AsyncMock(),add=lambda _:pytest.fail('duplicate'))
    with patch('app.geo.outcome_review.assess_outcome',AsyncMock(return_value=assessment)):
        asyncio.run(update_outcome_review(s,10))
    assert follow.progress['current_outcome_review']==assessment
    assert follow.progress['outcome_review']==historical and follow.status=='doing'
    assert follow.evidence==[{'note':'customer plan'}] and row.status=='doing'
    assert ('待观察' if new_state=='waiting' else '已达目标') in follow.last_note
