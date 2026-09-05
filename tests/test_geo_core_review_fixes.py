import asyncio
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from app.geo.audit import PageDocument, audit_url, parse_robots_ai_agents, safe_fetch, GeoAuditError
from app.geo.content.competitor_trace import build_competitor_compare
from app.geo.content.competitor_reports import freeze_report_state, restore_report_state, invalidate_report_confirmation
from app.geo.content.daily_metrics import MetricBucket


@pytest.mark.parametrize('rules,status',[
    ('User-agent: GPTBot\nDisallow: /private/', 'partial'),
    ('User-agent: GPTBot\nDisallow: /\nAllow: /', 'allowed'),
    ('User-agent: *\nDisallow: /\nUser-agent: GPTBot', 'allowed'),
    ('User-agent: GPTBot\nDisallow: /\nAllow: /public/', 'partial'),
    ('User-agent: GPTBot\nDisallow: /*', 'blocked')])
def test_robots_sitewide_rule_semantics(rules,status):
    assert parse_robots_ai_agents(rules)['agents'][0]['status']==status


@pytest.mark.parametrize('html,headers',[
    ('<meta name="robots" content="none">',{}),
    ('<meta name="robots" content="index"><meta name="robots" content="noindex">',{}),
    ('',{'x-robots-tag':'noindex, nofollow'})])
def test_indexability_respects_all_meta_and_headers(html,headers):
    document=PageDocument('https://example.com','https://example.com','<html><head>'+html+'</head></html>','text/html',headers)
    async def run():
        with patch('app.geo.audit.safe_fetch',AsyncMock(return_value=document)),patch('app.geo.audit._optional_text',AsyncMock(return_value=(False,''))):
            return await audit_url('https://example.com')
    result=asyncio.run(run())
    assert not next(c for c in result['checks'] if c['code']=='indexable')['passed']


def test_fetch_pins_validated_ip_and_preserves_host_and_tls_name():
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(200,headers={'content-type':'text/html','x-robots-tag':'noindex'},content='<html>OK</html>')
    client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    async def run():
        with patch('app.geo.audit.httpx.AsyncClient',return_value=client),patch('app.geo.audit._ensure_public_host',AsyncMock(return_value=['93.184.216.34'])):
            return await safe_fetch('https://example.com/path')
    result=asyncio.run(run())
    assert requests[0].url.host=='93.184.216.34'
    assert requests[0].headers['host']=='example.com'
    assert requests[0].extensions['sni_hostname']=='example.com'
    assert result.final_url=='https://example.com/path'
    assert result.headers['x-robots-tag']=='noindex'


def test_redirect_rechecks_destination_before_any_second_connection():
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(302,headers={'location':'http://127.0.0.1/private'})
    client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    async def run():
        with patch('app.geo.audit.httpx.AsyncClient',return_value=client),patch('app.geo.audit._ensure_public_host',AsyncMock(side_effect=[['93.184.216.34'],GeoAuditError('private')])):
            await safe_fetch('https://example.com')
    with pytest.raises(GeoAuditError): asyncio.run(run())
    assert len(requests)==1


def test_simulated_and_sparse_rows_cannot_declare_competitor_lead():
    rows=[NS(prompt_id=1,engine=str(i%2),sample_mode='mock_persona',simulated=True,competitors=['Rival'],mentions_brand=False) for i in range(8)]
    assert build_competitor_compare(rows=rows)['items']==[]
    for row in rows:
        row.simulated=False;row.sample_mode='openai_compat';row.note='method=unprimed_json_v2 analysis=completed'
    sparse=build_competitor_compare(rows=rows[:1])
    assert sparse['items'][0]['winner']=='insufficient'
    assert sparse['items'][0]['competitors'][0]['mention_rate'] is None
    assert sparse['summary']['competitor_lead']==0
    assert build_competitor_compare(rows=rows)['items'][0]['winner']=='competitor'


def test_daily_storage_keeps_all_competitors():
    b=MetricBucket();b.snapshots_visibility=20;b.competitor_counts={str(i):1 for i in range(20)}
    assert len(b.to_metrics_dict()['competitor_mentions'])==20


def test_restored_report_has_matching_evidence_and_loses_old_confirmation():
    row=NS(version_no=1,evidence={'source_count':1},title='old',source_urls=['https://old.example'],
           status='confirmed',confirmed_by=3,confirmed_at=datetime(2026,9,1))
    freeze_report_state(row)
    row.title='new';row.source_urls=['https://new.example'];row.evidence={**row.evidence,'source_count':2};row.version_no=2
    freeze_report_state(row)
    restore_report_state(row,1)
    assert row.title=='old' and row.source_urls==['https://old.example']
    assert row.evidence['source_count']==1
    assert row.status=='draft' and row.confirmed_by is None and row.confirmed_at is None
    with pytest.raises(ValueError): restore_report_state(row,99)


@pytest.mark.parametrize('archived',[False,True])
def test_report_patch_invalidates_confirmation_and_retains_version_evidence(archived):
    from app.geo.content.routes import patch_competitor_report
    from app.geo.content.schemas import CompetitorReportPatch
    from app.models.geo_competitor_report import GeoCompetitorReport
    from unittest.mock import Mock
    row=GeoCompetitorReport(id=1,tenant_id=7,title='old',competitor='rival',version_no=1,status='confirmed',
        confirmed_by=3,confirmed_at=datetime(2026,8,20),source_urls=['https://old.example'],evidence={'source_count':1})
    session=NS(get=AsyncMock(return_value=row),add=Mock(),commit=AsyncMock(),refresh=AsyncMock())
    result=asyncio.run(patch_competitor_report(1,CompetitorReportPatch(status='archived' if archived else 'draft',insight='new',source_urls=['https://new.example'],evidence={'source_count':2}),
        7,NS(ensure_tenant=lambda value:None,user_id=4),session))
    assert result['status']==('archived' if archived else 'draft') and result['confirmed_at'] is None
    assert row.evidence['_version_snapshots']['1']['source_urls']==['https://old.example']
    assert row.evidence['_version_snapshots']['2']['evidence']=={'source_count':2}
    assert '_version_snapshots' not in result['evidence']
    session.get.assert_awaited_once_with(GeoCompetitorReport,1,with_for_update=True)


def test_old_ticket_create_cannot_impersonate_contract_tasks():
    from app.geo.routes import create_action_ticket,TicketCreate
    with pytest.raises(HTTPException) as exc:
        asyncio.run(create_action_ticket(TicketCreate(title='fake',advice_code='cockpit:v1:task'),7,NS(ensure_tenant=lambda value:None),NS()))
    assert exc.value.status_code==400
