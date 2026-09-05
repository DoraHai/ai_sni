import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from app.seo_backlink_opportunities import competitor_domains, compare_samples


def sample(source, target):
    return {'state': 'completed', 'items': [{'source_url': 'https://' + source + '/article',
            'target_url': 'https://' + target + '/', 'anchor_text': '资料'}]}


@pytest.mark.parametrize('value', ['127.0.0.1', 'brand.example', 'sub.brand.example', 'https://peer.example/path', 'https://u:p@peer.example', 'peer.example:8080', 'localhost'])
def test_competitors_reject_unsafe_or_wrong_scope(value):
    with pytest.raises(ValueError):
        competitor_domains([value], 'brand.example')


def test_competitors_normalize_and_deduplicate():
    assert competitor_domains(['www.peer.example', 'https://peer.example/'], 'brand.example') == ['peer.example']


def test_gap_groups_competitors_and_excludes_own_known_links():
    values = {'brand.example': sample('existing.example', 'brand.example'),
              'peer.example': sample('media.example', 'peer.example'),
              'peer2.example': sample('media.example', 'peer2.example'),
              'peer3.example': sample('known.example', 'peer3.example')}
    result = compare_samples('brand.example', values, ['https://known.example/other'])
    assert result['comparison_available']
    assert len(result['items']) == 1
    assert result['items'][0]['competitor_count'] == 2
    assert len(result['items'][0]['evidence']) == 2
    assert result['items'][0]['state'] == 'candidate'


def test_failed_own_query_is_unknown_not_zero():
    values = {'brand.example': {'state': 'failed'}, 'peer.example': sample('media.example', 'peer.example')}
    assert compare_samples('brand.example', values)['comparison_available'] is False
    assert compare_samples('brand.example', values)['items'] == []


def test_query_reserves_budget_and_preserves_partial_results_without_creating_backlinks():
    from app.api.seo import query_backlink_opportunities, BacklinkOpportunityQuery
    site = SimpleNamespace(tenant_id=7, canonical_domain='brand.example', site_settings={})
    session = SimpleNamespace(get=AsyncMock(return_value=site), commit=AsyncMock(), scalars=AsyncMock(return_value=[]), rollback=AsyncMock())
    ctx = SimpleNamespace(ensure_tenant=lambda value: None)
    req = BacklinkOpportunityQuery(tenant_id=7, site_id=9, competitors=['peer.example', 'peer2.example'])
    calls = []
    async def fetch(domain):
        assert site.site_settings['backlink_opportunities']['state'] == 'running'
        assert session.commit.await_count >= 1
        calls.append(domain)
        if domain == 'peer2.example':
            raise ValueError('secret provider response must not leak')
        return {**sample('media.example' if domain != 'brand.example' else 'own.example', domain), 'rejected': 0}
    with patch('app.api.seo._seo_site', new=AsyncMock()), patch('app.api.seo.index_status', return_value={'configured': True}), patch('app.api.seo.fetch_index_candidates', new=AsyncMock(side_effect=fetch)):
        result = asyncio.run(query_backlink_opportunities(req, session, ctx))
        assert result['state'] == 'partial' and len(result['items']) == 1
        assert 'secret' not in str(result)
        assert len(calls) == 3
        # Changing competitor list must not bypass the daily paid-call budget.
        req.competitors = ['new.example']
        with pytest.raises(HTTPException) as exc:
            asyncio.run(query_backlink_opportunities(req, session, ctx))
        assert exc.value.status_code == 429 and len(calls) == 3


def test_disabled_and_wrong_tenant_never_call_provider():
    from app.api.seo import query_backlink_opportunities, BacklinkOpportunityQuery
    req = BacklinkOpportunityQuery(tenant_id=7, site_id=9, competitors=['peer.example'])
    session = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(tenant_id=8)))
    ctx = SimpleNamespace(ensure_tenant=lambda value: None)
    with patch('app.api.seo._seo_site', new=AsyncMock()), patch('app.api.seo.fetch_index_candidates', new=AsyncMock()) as fetch:
        for configured, code in [(False, 503), (True, 404)]:
            with patch('app.api.seo.index_status', return_value={'configured': configured}):
                with pytest.raises(HTTPException) as exc:
                    asyncio.run(query_backlink_opportunities(req, session, ctx))
                assert exc.value.status_code == code
        fetch.assert_not_called()


def test_postgres_concurrent_batches_share_one_reservation():
    import os
    from uuid import uuid4
    from sqlalchemy import text, MetaData
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.models.module_workspace import SeoSite
    from app.models.seo import SeoBacklink
    from app.api.seo import query_backlink_opportunities, BacklinkOpportunityQuery
    url = os.environ.get('SEO_USAGE_TEST_DATABASE_URL')
    if not url:
        pytest.skip('requires local PostgreSQL validation database')
    async def scenario():
        schema='gap_'+uuid4().hex
        engine=create_async_engine(url,connect_args={'server_settings':{'search_path':schema}})
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                for model in [SeoSite,SeoBacklink]:
                    table=model.__table__.to_metadata(MetaData())
                    for constraint in list(table.foreign_key_constraints):table.constraints.remove(constraint)
                    await connection.run_sync(lambda sync:table.create(sync))
            sessions=async_sessionmaker(engine,expire_on_commit=False)
            async with sessions() as session:
                session.add(SeoSite(id=9,tenant_id=7,tenant_module_id=1,name='Site',domain='brand.example',canonical_domain='brand.example',status='active'))
                await session.commit()
            entered,release=asyncio.Event(),asyncio.Event()
            async def provider(domain):
                entered.set();await release.wait()
                return {'items':[],'rejected':0}
            req=BacklinkOpportunityQuery(tenant_id=7,site_id=9,competitors=['peer.example'])
            ctx=SimpleNamespace(ensure_tenant=lambda _:None)
            with patch('app.api.seo._seo_site',new=AsyncMock()),patch('app.api.seo.index_status',return_value={'configured':True}),patch('app.api.seo.fetch_index_candidates',new=AsyncMock(side_effect=provider)) as fetch:
                async with sessions() as first,sessions() as second:
                    task=asyncio.create_task(query_backlink_opportunities(req,first,ctx))
                    await asyncio.wait_for(entered.wait(),5)
                    with pytest.raises(HTTPException) as exc:
                        await asyncio.wait_for(query_backlink_opportunities(req,second,ctx),5)
                    assert exc.value.status_code==429
                    await second.rollback()
                    release.set()
                    result=await asyncio.wait_for(task,5)
                    assert result['state']=='completed' and fetch.await_count==2
        finally:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(scenario())
