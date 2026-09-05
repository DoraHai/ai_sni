import asyncio
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from bs4 import BeautifulSoup
from app.geo.audit import canonical_evidence, audit_url, PageDocument, _schema_types
from app.geo.content.competitor_scope import competitor_names


@pytest.mark.parametrize('href,valid', [('/preferred',True),('https://other.example/page',True),('javascript:alert(1)',False),('https://user:password@example.com/',False),('https://example.com/#part',False),('https://example.com:bad/',False),('',False),('https://example.com/a b',False)])
def test_canonical_checks_format_without_fetching_target(href,valid):
    soup=BeautifulSoup(f'<html><head><link rel="canonical" href="{href}"></head></html>','html.parser')
    url,passed,_=canonical_evidence(soup,'https://example.com/original')
    assert passed is valid
    if href=='/preferred': assert url=='https://example.com/preferred'


def test_canonical_must_be_unique_and_in_head_and_respects_base():
    for html in ['<html><head></head><body><link rel="canonical" href="/a"></body></html>', '<head><link rel="canonical" href="/a"><link rel="canonical" href="/b"></head>']:
        assert not canonical_evidence(BeautifulSoup(html,'html.parser'),'https://example.com')[1]
    soup=BeautifulSoup('<head><base href="https://cdn.example/root/"><link rel="canonical" href="page"></head>','html.parser')
    assert canonical_evidence(soup,'https://example.com')[0]=='https://cdn.example/root/page'


def test_nested_schema_types_are_detected_without_context_false_positive():
    assert _schema_types([{'@type':'Article','publisher':{'@type':'Organization'},'author':[{'@type':'Person'}],'@context':{'@type':'Fake'}}])=={'Article','Organization','Person'}


def test_hidden_html_cannot_pass_content_or_heading_rules():
    html='<html><head><title>Title</title></head><body><h1>Visible</h1><div hidden><h1>Hidden</h1><span hidden>'+('text '*600)+'</span></div><div style="display: none !important"><h2>Hidden</h2></div><script type="application/ld+json">{"@type":"Article","publisher":{"@type":"Organization"}}</script></body></html>'
    doc=PageDocument(requested_url='https://example.com',final_url='https://example.com',html=html,content_type='text/html')
    with patch('app.geo.audit.safe_fetch',AsyncMock(return_value=doc)),patch('app.geo.audit._optional_text',AsyncMock(return_value=(False,''))):
        result=asyncio.run(audit_url('https://example.com'))
    checks={c['code']:c for c in result['checks']}
    assert result['rule_version']=='1.2.0'
    assert checks['h1']['passed'] and not checks['substantial']['passed'] and not checks['heading_depth']['passed']
    assert checks['entity_schema']['passed']
    assert result['score']==max(0,100-sum(c['deduction'] for c in result['checks']))


def test_names_deduplicate_without_truncation_or_invented_aliases():
    assert competitor_names([' Rival ','RIVAL','rival','Other'])==['other','rival']
    assert len(competitor_names([f'Rival{i}' for i in range(35)]))==35
    assert competitor_names(['IBM','International Business Machines'])==['ibm','international business machines']


def test_comparison_count_cannot_exceed_answer_count_due_to_case_variants():
    from app.geo.content.competitor_trace import build_competitor_compare
    rows=[NS(id=i,prompt_id=1,engine='deepseek',captured_at=datetime(2026,9,5),mentions_brand=False,brand_position='unknown',competitors=[' Rival ','RIVAL','rival'],sample_mode='openai_compat',simulated=False,note='method=unprimed_json_v2 analysis=completed',citation_accuracy='unknown') for i in range(8)]
    result=build_competitor_compare(rows=rows,questions={1:'Question'})
    rivals=result['items'][0]['competitors']
    assert len(rivals)==1 and rivals[0]['name']=='rival' and rivals[0]['mention_count']==8


def test_overview_exposes_dedup_evidence_and_rolling_source_scope():
    from app.geo.content.routes import competitor_insights
    from datetime import timedelta
    now=datetime.utcnow()
    def sample(i,when,comps):
        return NS(id=i,prompt_id=7,engine='kimi',captured_at=when,mentions_brand=False,competitors=comps,cited_urls=['https://source.example'],sample_mode='openai_compat',simulated=False,note='method=unprimed_json_v2 analysis=completed',citation_accuracy='unknown')
    rows=[sample(1,now,[' Rival ','RIVAL']),sample(2,now-timedelta(days=8),['rival'])]
    session=NS(scalars=AsyncMock(return_value=rows))
    with patch('app.geo.content.routes._active_competitor_prompt_context',AsyncMock(return_value=(rows,{7:'question'},{}))):
        result=asyncio.run(competitor_insights(1,NS(ensure_tenant=lambda _:None),session))
    assert len(result['items'])==1
    item=result['items'][0]
    assert item['mention_count']==2 and item['snapshot_ids']==[1,2] and item['prompt_ids']==[7]
    assert item['source_urls']==['https://source.example']
    assert result['summary']['sources_last_7d']==1
    assert '168' in result['statistical_scope']['window']


def test_duplicate_title_and_cjk_threshold_are_not_inflated():
    doc=PageDocument(requested_url='https://example.com',final_url='https://example.com',content_type='text/html',html='<html><head><title>A sufficiently long title</title><title>Another long title</title></head><body>'+('文'*499)+'</body></html>')
    with patch('app.geo.audit.safe_fetch',AsyncMock(return_value=doc)),patch('app.geo.audit._optional_text',AsyncMock(return_value=(False,''))):
        result=asyncio.run(audit_url('https://example.com'))
    checks={c['code']:c for c in result['checks']}
    assert not checks['title']['passed'] and not checks['substantial']['passed']


def test_heatmap_uses_deduplicated_mentions_and_unknown_for_small_samples():
    from app.geo.content.competitor_scope import engine_heatmap
    rows=[NS(engine='kimi',mentions_brand=True,competitors=['Rival','RIVAL']) for _ in range(8)]
    rows.append(NS(engine='deepseek',mentions_brand=False,competitors=[]))
    result=engine_heatmap(rows)
    assert result['engines']==['deepseek','kimi']
    assert result['rows'][0]['cells']==[None,1]
    assert result['rows'][1]['cells']==[None,1]
