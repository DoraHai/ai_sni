import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
import httpx
from app.seo_backlink_sources import parse_backlink_csv, candidate_url, backlink_analysis, fetch_index_candidates, import_candidates
from app.seo_backlinks import apply_backlink_evidence


def test_csv_handles_bom_chinese_quoted_newlines_and_duplicates():
    raw='\ufeff来源页面,目标页面,锚文本\r\nhttps://media.example/a,https://brand.example/a,"资料,链接\n第二行"\r\nhttps://media.example/a,https://brand.example/a,重复\r\n'.encode('utf-8')
    value=parse_backlink_csv(raw,'brand.example')
    assert value['duplicates']==1 and len(value['items'])==1 and not value['errors']
    assert '第二行' in value['items'][0]['anchor_text']


@pytest.mark.parametrize('source,target',[('http://127.0.0.1/a','https://brand.example/a'),('https://brand.example/a','https://brand.example/b'),('https://media.example/a','https://brand.example.attacker.test/a'),('https://u:p@media.example/a','https://brand.example/a'),('https://media.example:bad/a','https://brand.example/a')])
def test_csv_rejects_internal_wrong_site_credentials_and_invalid_ports(source,target):
    value=parse_backlink_csv(f'source_url,target_url\n{source},{target}\n'.encode(),'brand.example')
    assert not value['items'] and len(value['errors'])==1


def test_csv_enforces_limits_and_gb18030():
    value=parse_backlink_csv('来源页面,目标页面,锚文本\nhttps://media.example/a,https://brand.example/a,品牌'.encode('gb18030'),'brand.example')
    assert value['items'][0]['anchor_text']=='品牌'
    with pytest.raises(ValueError):parse_backlink_csv(b'x'*(2*1024*1024+1),'brand.example')
    with pytest.raises(ValueError):parse_backlink_csv(('source_url,target_url\n'+'https://media.example/a,https://brand.example/a\n'*501).encode(),'brand.example')
    with pytest.raises(ValueError):parse_backlink_csv(b'bad_header\nx','brand.example')


def test_import_keeps_existing_links_and_records_candidates_as_pending():
    session=SimpleNamespace(scalar=AsyncMock(side_effect=[9,None]))
    items=[{'source_url':'https://media.example/a','target_url':'https://brand.example/a','anchor_text':'品牌'}]*2
    result=asyncio.run(import_candidates(session,7,8,items,'csv'))
    assert result=={'created':1,'existing':1}
    statement=session.scalar.call_args.args[0]
    assert statement.compile().params['verification']['state']=='pending'
    assert 'DO NOTHING' in str(statement)


def test_analysis_records_loss_transition_once_and_preserves_provenance():
    now=datetime(2026,9,5)
    row=SimpleNamespace(source_url='https://media.example/a',target_url='https://brand.example/a',source_domain='media.example',anchor_text='品牌',status='active',verification={'state':'pending','provenance':{'source':'csv'}},missing_checks=0,first_seen_at=None)
    response=SimpleNamespace(body='<a href="https://brand.example/a" rel="nofollow">资料</a>',final_url=row.source_url,status_code=200,error_type=None)
    apply_backlink_evidence(row,response,now)
    response.body='<p>没有链接</p>'
    apply_backlink_evidence(row,response,now+timedelta(hours=1))
    apply_backlink_evidence(row,response,now+timedelta(hours=22))
    apply_backlink_evidence(row,response,now+timedelta(days=1))
    assert row.verification['provenance']=={'source':'csv'}
    stats=backlink_analysis([row],now+timedelta(days=2))
    assert sum(day['lost'] for day in stats['trend'])==1
    assert sum(day['new'] for day in stats['trend'])==1
    assert stats['top_domain_share']==100 and stats['lost']==1


def test_index_query_uses_fixed_origin_no_retry_and_filters_unrelated_results():
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={'status_code':20000,'tasks':[{'status_code':20000,'result':[{'items':[{'url_from':'https://media.example/a','url_to':'https://brand.example/a','anchor':'品牌'},{'url_from':'https://media.example/b','url_to':'https://other.example/a'}]}]}]})
    original=httpx.AsyncClient
    settings=SimpleNamespace(seo_backlink_index_enabled=True,seo_dataforseo_login='test',seo_dataforseo_password='dummy')
    with patch('app.seo_backlink_sources.get_settings',return_value=settings),patch('app.seo_backlink_sources.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
        result=asyncio.run(fetch_index_candidates('brand.example'))
    assert len(requests)==1 and str(requests[0].url)=='https://api.dataforseo.com/v3/backlinks/backlinks/live'
    assert result['rejected']==1 and len(result['items'])==1


def test_index_disabled_does_not_contact_provider():
    settings=SimpleNamespace(seo_backlink_index_enabled=False,seo_dataforseo_login='',seo_dataforseo_password='')
    with patch('app.seo_backlink_sources.get_settings',return_value=settings),patch('app.seo_backlink_sources.httpx.AsyncClient') as client:
        with pytest.raises(ValueError):asyncio.run(fetch_index_candidates('brand.example'))
    client.assert_not_called()


def test_import_preview_errors_never_partially_write():
    from app.api.seo import import_backlink_file
    from fastapi import HTTPException
    session=SimpleNamespace(commit=AsyncMock())
    upload=SimpleNamespace(read=AsyncMock(return_value=b'source_url,target_url\nhttps://media.example/a,https://other.example/a'))
    ctx=SimpleNamespace(ensure_tenant=lambda _:None)
    with patch('app.api.seo._seo_site',new=AsyncMock(return_value=SimpleNamespace(canonical_domain='brand.example'))),patch('app.api.seo.import_candidates',new=AsyncMock()) as write:
        with pytest.raises(HTTPException) as exc:asyncio.run(import_backlink_file(1,2,False,upload,session,ctx))
        assert exc.value.status_code==422
    write.assert_not_called();session.commit.assert_not_called()


def test_index_database_reservation_prevents_concurrent_and_failed_retries():
    import os
    from uuid import uuid4
    from sqlalchemy import text, MetaData
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.models.module_workspace import SeoSite
    from app.models.seo import SeoBacklink
    from app.api.seo import query_backlink_index, BacklinkScope
    url = os.environ.get('SEO_USAGE_TEST_DATABASE_URL')
    if not url:
        pytest.skip('requires local PostgreSQL validation database')
    async def scenario():
        schema = 'index_' + uuid4().hex
        engine = create_async_engine(url, connect_args={'server_settings':{'search_path':schema}})
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                for model in [SeoSite, SeoBacklink]:
                    table = model.__table__.to_metadata(MetaData())
                    for key in list(table.foreign_key_constraints):
                        table.constraints.remove(key)
                    await connection.run_sync(lambda sync: table.create(sync))
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                session.add(SeoSite(id=9,tenant_id=7,tenant_module_id=1,name='Site',domain='brand.example',canonical_domain='brand.example',status='active'))
                await session.commit()
            entered, release = asyncio.Event(), asyncio.Event()
            async def provider(_):
                entered.set()
                await release.wait()
                raise ValueError('模拟网络失败')
            ctx=SimpleNamespace(ensure_tenant=lambda _:None)
            req=BacklinkScope(tenant_id=7,site_id=9)
            with patch('app.api.seo._seo_site',new=AsyncMock()), patch('app.api.seo.index_status',return_value={'configured':True}), patch('app.api.seo.fetch_index_candidates',new=AsyncMock(side_effect=provider)) as fetch:
                async with sessions() as first, sessions() as second:
                    task=asyncio.create_task(query_backlink_index(req,first,ctx))
                    await asyncio.wait_for(entered.wait(),5)
                    cached=await asyncio.wait_for(query_backlink_index(req,second,ctx),5)
                    assert cached['cached'] and cached['state']=='running'
                    await second.rollback()  # Release read transaction's row lock.
                    release.set()
                    outcome=await asyncio.wait_for(task,5)
                    assert outcome['state']=='failed'
                async with sessions() as session:
                    cached=await query_backlink_index(req,session,ctx)
                    assert cached['cached'] and cached['state']=='failed'
                assert fetch.await_count==1
        finally:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(scenario())


def test_csv_accepts_utf16_export():
    value=parse_backlink_csv('来源页面,目标页面,锚文本\nhttps://media.example/a,https://brand.example/a,品牌'.encode('utf-16'),'brand.example')
    assert value['items'][0]['anchor_text']=='品牌'
