import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from app.seo_backlinks import apply_backlink_evidence, extract_site_links, page_evidence, discover_backlinks


def result(body='<a rel="nofollow ugc" href="https://brand.example/service">品牌</a>', status=200, error=None):
    return SimpleNamespace(body=body, final_url="https://media.example/article", status_code=status, error_type=error)


def asset():
    return SimpleNamespace(source_url="https://media.example/article", target_url="https://brand.example/service", status="active", first_seen_at=None, last_seen_at=None, missing_checks=0, verification=None)


def test_discovery_extracts_actual_anchors_and_rejects_lookalikes_mentions_and_scripts():
    body = '''<base href="https://brand.example/"><a href="/service">资料</a>
    <a href="https://brand.example.evil.test/">假的</a><a href="javascript:alert(1)">脚本</a>
    <a href="https://user:pass@brand.example/private">凭据</a><script>brand.example</script>
    <p>brand.example 提及</p><a href="https://sub.brand.example/help" rel="sponsored nofollow">赞助</a>'''
    links = extract_site_links(body, 'https://media.example/story', 'brand.example')
    assert len(links) == 2
    assert links[1]['rel'] == ['nofollow', 'sponsored']
    assert extract_site_links(body, 'https://brand.example/story', 'brand.example') == []


def test_found_and_loss_require_separated_observations_and_recovery_resets_count():
    row = asset(); now = datetime(2026, 9, 5)
    assert apply_backlink_evidence(row, result(), now)['state'] == 'found'
    assert row.first_seen_at == now and row.anchor_text == '品牌'
    assert row.verification['rel'] == ['nofollow','ugc']
    missing = result('<p>文章已更新</p>')
    apply_backlink_evidence(row, missing, now + timedelta(hours=1))
    apply_backlink_evidence(row, missing, now + timedelta(hours=2))
    assert row.missing_checks == 1 and row.status == 'active'
    apply_backlink_evidence(row, missing, now + timedelta(hours=22))
    assert row.status == 'lost' and row.missing_checks == 2
    apply_backlink_evidence(row, result(), now + timedelta(hours=23))
    assert row.status == 'active' and row.missing_checks == 0 and row.first_seen_at == now


@pytest.mark.parametrize('response', [result('',503,'http_error'),result('<title>安全验证</title>'),result('<title>Sign in</title>'),result('blocked',403)])
def test_inaccessible_pages_never_mark_link_lost(response):
    row = asset()
    for _ in range(25):
        evidence = apply_backlink_evidence(row, response)
    assert row.status == 'active' and row.missing_checks == 0
    assert evidence['state'] in {'unreachable','blocked'}
    assert row.last_checked_at is not None and len(evidence['history']) == 20


def test_discovery_is_idempotent_without_overwriting_paused_assets():
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    with patch('app.seo_backlinks.fetch_backlink_page',new=AsyncMock(return_value=result())):
        evidence = asyncio.run(discover_backlinks(session, 7, 9, 'https://media.example/article', 'brand.example'))
    assert evidence['found'] == 1 and evidence['created'] == 0
    statement = session.scalar.call_args.args[0]
    assert 'ON CONFLICT ON CONSTRAINT uq_seo_backlink_site_source_target DO NOTHING' in str(statement)
    assert statement.compile().params['tenant_id'] == 7


def test_verify_rejects_cross_site_before_network():
    from app.api.seo import verify_site_backlink, BacklinkScope
    row = asset(); row.tenant_id=7;row.site_id=10
    session = SimpleNamespace(get=AsyncMock(return_value=row))
    ctx = SimpleNamespace(ensure_tenant=lambda _: None)
    with patch('app.api.seo._seo_site', new=AsyncMock()), patch('app.api.seo.fetch_backlink_page', new=AsyncMock()) as fetch:
        with pytest.raises(HTTPException) as error:
            asyncio.run(verify_site_backlink(1,BacklinkScope(tenant_id=7,site_id=9),session,ctx))
    assert error.value.status_code == 404
    fetch.assert_not_called()


def test_discover_rejects_wrong_publication_site_and_invalid_url():
    from app.api.seo import discover_site_backlinks, BacklinkDiscovery
    ctx = SimpleNamespace(ensure_tenant=lambda _: None)
    publication=SimpleNamespace(tenant_id=7,content_asset_id=11,page_url='https://media.example/article',status='published')
    content=SimpleNamespace(tenant_id=7,site_id=99)
    session=SimpleNamespace(get=AsyncMock(side_effect=[publication,content]))
    with patch('app.api.seo._seo_site',new=AsyncMock(return_value=SimpleNamespace(canonical_domain='brand.example'))),patch('app.api.seo.discover_backlinks',new=AsyncMock()) as discover:
        with pytest.raises(HTTPException) as error:
            asyncio.run(discover_site_backlinks(BacklinkDiscovery(tenant_id=7,site_id=9,source_url=publication.page_url,publication_id=2),session,ctx))
        assert error.value.status_code == 404
        with pytest.raises(HTTPException) as error:
            asyncio.run(discover_site_backlinks(BacklinkDiscovery(tenant_id=7,site_id=9,source_url='javascript:bad'),session,ctx))
        assert error.value.status_code == 422
        discover.assert_not_called()


def test_database_discovery_inserts_once_and_keeps_evidence():
    import os
    from uuid import uuid4
    from sqlalchemy import text, select, MetaData
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.models.seo import SeoBacklink, SeoContentPublication, SeoContentAsset
    from app.models.module_workspace import SeoSite
    from app.seo_backlinks import discover_published_backlinks
    url = os.environ.get('SEO_USAGE_TEST_DATABASE_URL')
    if not url:
        pytest.skip('requires local PostgreSQL validation database')
    async def scenario():
        schema = 'backlinks_' + uuid4().hex
        engine = create_async_engine(url, connect_args={'server_settings':{'search_path':schema}})
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                for model in [SeoBacklink, SeoContentPublication, SeoContentAsset, SeoSite]:
                    table = model.__table__.to_metadata(MetaData())
                    for foreign_key in list(table.foreign_key_constraints):
                        table.constraints.remove(foreign_key)
                    await connection.run_sync(lambda sync: table.create(sync))
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            with patch('app.seo_backlinks.fetch_backlink_page',new=AsyncMock(return_value=result())):
                async with sessions() as session:
                    first = await discover_backlinks(session,7,9,'https://media.example/article','brand.example')
                    await session.commit()
                async with sessions() as session:
                    second = await discover_backlinks(session,7,9,'https://media.example/article','brand.example')
                    await session.commit()
                    row = await session.scalar(select(SeoBacklink))
                    assert row.verification['state'] == 'found'
                    assert row.verification['rel'] == ['nofollow','ugc']
                    assert row.tenant_id == 7 and row.site_id == 9
            assert first['created'] == 1 and second['created'] == 0
            async with sessions() as session:
                session.add(SeoSite(id=9, tenant_id=7,tenant_module_id=1,name='Site',domain='brand.example',canonical_domain='brand.example',status='active'))
                session.add(SeoContentAsset(id=11,tenant_id=7,site_id=9,title='Article',status='published'))
                session.add(SeoContentPublication(id=21,tenant_id=7,content_asset_id=11,platform_code='manual',platform_name='Media',status='published',page_url='https://media.example/article'))
                await session.commit()
            with patch('app.database.async_session_factory',sessions),patch('app.module_scope.list_active_module_tenants',new=AsyncMock(return_value=[SimpleNamespace(id=7)])),patch('app.seo_backlinks.fetch_backlink_page',new=AsyncMock(return_value=result())):
                assert await discover_published_backlinks() == {'checked':1}
                assert await discover_published_backlinks() == {'checked':0}
            async with sessions() as session:
                publication = await session.get(SeoContentPublication,21)
                assert publication.link_discovery['found']==1
                assert publication.link_discovery['created']==0
        finally:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(scenario())
