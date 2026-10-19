"""Real HTTP/SQL regressions run on the isolated CI fixture backends."""
import asyncio
import json
import logging
from datetime import datetime

import pytest
from sqlalchemy import select

from app import models as m
from test_advisor_scoped_writes import (
    backend, fixture_token, mutate, no_external_http_or_background_dispatch, write_sandbox,
)
from test_geo_advisor_completion_http import foreign_project


@pytest.mark.parametrize('actor', ('partial', 'all', 'ungranted', 'not-selected', 'admin'))
def test_alias_replace_requires_selected_customer_and_all_projects(tmp_path, monkeypatch, backend, caplog, actor):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend,
                extra_tables=('geo_competitor_aliases',)) as env:
            await foreign_project(env)
            if actor == 'all':
                await mutate(env, m.GeoProject, 50, project_settings={
                    'geo_business_scope': {'business_ids': [50]},
                    'geo_service_plan': {'advisor_user_id': 1}})
            async with env.factory() as session:
                session.add(m.GeoCompetitorAlias(tenant_id=10, alias_name='old', canonical_name='old brand'))
                await session.commit()

            async def aliases():
                async with env.factory() as session:
                    return list((await session.execute(select(m.GeoCompetitorAlias.tenant_id,
                        m.GeoCompetitorAlias.alias_name, m.GeoCompetitorAlias.canonical_name)
                        .order_by(m.GeoCompetitorAlias.id))).all())

            before = await aliases()
            tenant = 30 if actor == 'ungranted' else 20 if actor == 'not-selected' else 10
            response = await env.request('PUT', '/competitor-aliases',
                params={'tenant_id': tenant, 'project_id': 10}, body={'alias_map': {'new': 'new brand'}},
                auth=fixture_token(uid=2, native=True) if actor == 'admin' else None)
            if actor in {'all', 'admin'}:
                assert response.status_code == 200, response.text
                assert await aliases() == [(10, 'new', 'new brand')]
                if actor == 'all':
                    events = [json.loads(r.message) for r in caplog.records
                              if r.name == 'geo.advisor.operations' and r.message.startswith('{')]
                    assert any(e['advisor_user_id'] == 1 and e['tenant_id'] == 10
                        and e['path'] == '/api/v1/geo/competitor-aliases'
                        and e['result'] == 'committed'
                        and e['object_ids'].get('geo_competitor_aliases') for e in events)
            else:
                assert response.status_code == 403, response.text
                assert await aliases() == before
    with caplog.at_level(logging.INFO, logger='geo.advisor.operations'):
        asyncio.run(run())


@pytest.mark.parametrize('all_projects', (False, True))
def test_onboarding_brand_terms_are_shared_customer_data(tmp_path, monkeypatch, backend, all_projects):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            await foreign_project(env)
            if all_projects:
                await mutate(env, m.GeoProject, 50, project_settings={
                    'geo_business_scope': {'business_ids': [50]},
                    'geo_service_plan': {'advisor_user_id': 1}})
            async with env.factory() as session:
                before = list((await session.get(m.Tenant, 10)).brand_terms or [])
            response = await env.request('POST', '/onboarding/apply', params={'project_id': 10}, body={
                'tenant_id': 10, 'brand_terms': ['shared fixture brand'], 'create_website_channel': False})
            assert response.status_code == (200 if all_projects else 403), response.text
            async with env.factory() as session:
                after = list((await session.get(m.Tenant, 10)).brand_terms or [])
                assert after == (before + ['shared fixture brand'] if all_projects else before)
    asyncio.run(run())


@pytest.mark.parametrize('all_projects', (False, True))
def test_backfill_only_matches_publications_in_selected_project(tmp_path, monkeypatch, backend, all_projects):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            await foreign_project(env)
            if all_projects:
                await mutate(env, m.GeoProject, 50, project_settings={
                    'geo_business_scope': {'business_ids': [50]},
                    'geo_service_plan': {'advisor_user_id': 1}})
            async with env.factory() as session:
                session.add(m.GeoArticleVersion(id=50, task_id=50, version_no=1,
                    title='foreign article', body_markdown='foreign article'))
                await session.flush()
                session.add(m.GeoChannelVariant(id=50, task_id=50, article_version_id=50,
                    channel='website', title='foreign variant', body_markdown='foreign variant'))
                await session.flush()
                for ident in (10, 50):
                    session.add(m.GeoPublication(id=ident, variant_id=ident, channel='website',
                        published_url=f'https://public.test/article/{ident}', status='published'))
                session.add(m.GeoAnswerSnapshot(id=10, tenant_id=10, prompt_id=10, engine='other',
                    raw_text='owned answer citing both projects', captured_at=datetime(2026, 10, 19),
                    cited_urls=['https://public.test/article/50', 'https://public.test/article/10']))
                snapshot = await session.get(m.GeoAnswerSnapshot, 50)
                snapshot.cited_urls = ['https://public.test/article/50']
                await session.commit()
            response = await env.request('POST', '/attribution/backfill', params={'project_id': 10})
            assert response.status_code == 200, response.text
            assert response.json()['publication_count'] == 1
            assert response.json()['scanned'] == 1
            async with env.factory() as session:
                assert (await session.get(m.GeoAnswerSnapshot, 10)).matched_publication_ids == [10]
                assert (await session.get(m.GeoAnswerSnapshot, 50)).matched_publication_ids is None
    asyncio.run(run())


@pytest.mark.parametrize('creator', ('advisor', 'admin'))
def test_advisor_archives_do_not_mint_or_expose_public_share_tokens(tmp_path, monkeypatch, backend, creator):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend,
                extra_tables=('geo_deliverable_archives',)) as env:
            from app.geo.content.oauth_public import router
            env.app.include_router(router)
            response = await env.request('POST', '/deliverables/archives', params={'project_id': 10},
                body={'pack': {'data_scope': {'project_id': 10}}, 'title': 'fixture archive'},
                auth=fixture_token(uid=2, native=True) if creator == 'admin' else None)
            assert response.status_code == 200, response.text
            ident = response.json()['id']
            async with env.factory() as session:
                row = await session.get(m.GeoDeliverableArchive, ident)
                token = row.share_token
                assert bool(token) is (creator == 'admin')
                assert row.pack_json['data_scope']['project_id'] == 10
            if creator == 'advisor':
                assert response.json()['share_token'] is None
            for path in ('/deliverables/archives', f'/deliverables/archives/{ident}'):
                read = await env.request('GET', path)
                assert read.status_code == 200, read.text
                items = read.json().get('items', [read.json()])
                assert all(item['share_token'] is None for item in items)
            # Preserve the existing administrator public-sharing contract.
            if creator == 'admin':
                import httpx
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app),
                        base_url='http://fixture') as client:
                    public = await client.get('/api/v1/geo/deliverables/share/' + token)
                    assert public.status_code == 200, public.text
    asyncio.run(run())
