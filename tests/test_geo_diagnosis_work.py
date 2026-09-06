import asyncio
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException
from app.geo.diagnosis_work import diagnosis_work_plan


def case(code='robots'):
    ticket=NS(id=4,audit_id=2,tenant_id=7,advice_code=code,baseline_snapshot={'passed':False,'evidence':'原始记录'},
              action='修复对应配置',acceptance_type='auto',acceptance_check='finding.passed:'+code,acceptance_desc='重新抓取后通过')
    audit=NS(id=2,tenant_id=7,findings=[{'code':code,'evidence':'后来重新生成的说明'}],
             url='https://example.com/page',final_url=None,created_at=datetime(2026,9,6),page_title='页面')
    return ticket,audit


def test_plan_preserves_original_evidence_and_actual_page():
    ticket,audit=case()
    result=diagnosis_work_plan(ticket,audit)
    assert result['source_evidence']=='原始记录'
    assert result['page_url']=='https://example.com/page'
    assert result['suggested_role']=='网站维护人员'
    assert '修复对应配置' in result['steps'][1]
    assert '重抓验收' in result['steps'][-1]
    assert '不等于' in result['outcome_note']


@pytest.mark.parametrize('url',['javascript:alert(1)','https://user:password@example.com','https://[broken'])
def test_plan_never_exposes_unsafe_or_credential_bearing_links(url):
    ticket,audit=case();audit.url=url
    assert diagnosis_work_plan(ticket,audit)['page_url'] is None


def test_cross_customer_audit_is_rejected():
    ticket,audit=case();audit.tenant_id=8
    with pytest.raises(HTTPException):diagnosis_work_plan(ticket,audit)


def test_manual_acceptance_is_not_presented_as_automatic():
    ticket,audit=case('custom');ticket.acceptance_type='manual'
    result=diagnosis_work_plan(ticket,audit)
    assert result['suggested_role']=='内容编辑'
    assert '人工验收' in result['steps'][-1]


def test_generation_locks_diagnosis_before_checking_existing_tickets():
    from app.geo.routes import materialize_tickets
    ticket,audit=case();audit.advice=[];events=[]
    async def refresh(row,**kw):
        assert row is audit and kw.get('with_for_update') is True
        events.append('lock')
    async def scalars(query):
        assert events==['lock'];events.append('read')
        return NS(all=lambda:[NS(advice_code='robots',status='todo')])
    session=NS(refresh=AsyncMock(side_effect=refresh),scalars=AsyncMock(side_effect=scalars),commit=AsyncMock(),add=lambda _:pytest.fail('duplicate creation'))
    with patch('app.geo.routes._run_for_tenant',AsyncMock(return_value=audit)), \
         patch('app.geo.routes.materialize_ticket_specs',return_value=[{'advice_code':'robots'}]):
        result=asyncio.run(materialize_tickets(2,7,False,NS(ensure_tenant=lambda _:None),session))
    assert result['created']==0 and events==['lock','read']
