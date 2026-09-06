"""Approved legacy query fixes, exercised with real SQL and fixture identity."""
import asyncio
import os
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select, text

from test_geo_read_http_postgres import environment

pytestmark = pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires isolated PostgreSQL')


def test_legacy_progress_gets_are_read_only_and_background_recovery_persists():
    from app.geo.content.async_jobs import reconcile_stale_jobs_background
    from app.geo.content.patrol import reconcile_stale_patrol_runs_background

    async def run():
        async with environment(legacy_routes=True) as (client, engine, tables, identity):
            old = datetime(2020, 1, 1)
            async with engine.begin() as conn:
                await conn.execute(tables['tenants'].insert().values(id=1, name='fixture'))
                await conn.execute(tables['tenant_modules'].insert().values(
                    tenant_id=1, module_code='geo', status='active'))
                await conn.execute(tables['geo_content_tasks'].insert().values(
                    id=14, tenant_id=1, prompt_id=1, title='fixture', status='generating', updated_at=old))
                await conn.execute(tables['geo_async_jobs'].insert().values(
                    id=9, tenant_id=1, kind='generate_article', status='running',
                    ref_type='content_task', ref_id=14, created_at=old, started_at=old,
                    request_meta={'execution_protocol': 'advisory_v1'}))
                await conn.execute(tables['geo_visibility_patrol_runs'].insert().values(
                    id=7, tenant_id=1, status='running', trigger='manual', created_at=old, started_at=old,
                    summary={'execution_protocol': 'advisory_v1'}))

            paths = ('/async-jobs', '/async-jobs/9', '/visibility-patrol/runs', '/visibility-patrol/runs/7')
            for path in paths:
                response = await client.get('/api/v1/geo' + path, params={'tenant_id': 1})
                assert response.status_code == 200, (path, response.text)
                payload = response.json()
                item = payload['items'][0] if path in {
                    '/async-jobs', '/visibility-patrol/runs'
                } else payload
                assert item['status'] == item['stored_status'] == 'running'
                assert item['stale'] and item['reconciliation'] == 'background'

            async with engine.connect() as conn:
                assert await conn.scalar(select(tables['geo_async_jobs'].c.status)) == 'running'
                assert await conn.scalar(select(tables['geo_visibility_patrol_runs'].c.status)) == 'running'
                assert await conn.scalar(select(tables['geo_content_tasks'].c.status)) == 'generating'

            with (
                patch('app.database.engine', engine),
                patch('app.database.async_session_factory', identity['sessions']),
            ):
                assert (await reconcile_stale_jobs_background())['failed_jobs'] == 1
                assert (await reconcile_stale_patrol_runs_background())['failed_runs'] == 1

            async with engine.connect() as conn:
                assert await conn.scalar(select(tables['geo_async_jobs'].c.status)) == 'failed'
                assert await conn.scalar(select(tables['geo_visibility_patrol_runs'].c.status)) == 'failed'
                assert await conn.scalar(select(tables['geo_content_tasks'].c.status)) == 'editing'

    asyncio.run(run())


def test_pending_to_legacy_running_race_is_rechecked_under_row_lock():
    from app.geo.content.patrol import reconcile_stale_patrol_run
    from app.models import GeoVisibilityPatrolRun

    async def run():
        async with environment(legacy_routes=True) as (_client, engine, tables, identity):
            old = datetime(2020, 1, 1)
            async with engine.begin() as conn:
                await conn.execute(tables['tenants'].insert().values(id=1, name='fixture'))
                await conn.execute(tables['geo_visibility_patrol_runs'].insert().values(
                    id=7, tenant_id=1, status='pending', trigger='manual', created_at=old))

            async with identity['sessions']() as recovery_session:
                stale_view = await recovery_session.get(GeoVisibilityPatrolRun, 7)
                assert stale_view.status == 'pending'

                # A legacy worker commits running after recovery's initial read. It
                # cannot publish the new advisory protocol marker.
                async with identity['sessions']() as legacy_worker_session:
                    live = await legacy_worker_session.get(GeoVisibilityPatrolRun, 7)
                    live.status = 'running'
                    live.started_at = old
                    live.summary = {}
                    await legacy_worker_session.commit()

                with patch('app.database.engine', engine):
                    result = await reconcile_stale_patrol_run(recovery_session, stale_view)
                assert result.status == 'running'
                assert result.summary == {}

            async with engine.connect() as conn:
                stored = (await conn.execute(select(
                    tables['geo_visibility_patrol_runs'].c.status,
                    tables['geo_visibility_patrol_runs'].c.summary,
                ))).one()
            assert stored.status == 'running'
            assert stored.summary == {}

    asyncio.run(run())


def test_readiness_reports_orphans_without_assigning_and_write_helper_still_assigns():
    from app.models import GeoFact, GeoOptimizationBusiness, GeoVisibilityPatrolSettings
    from app.geo.content.onboarding import attach_orphan_onboarding_facts

    async def run():
        async with environment(extra_models=(GeoFact, GeoOptimizationBusiness, GeoVisibilityPatrolSettings),
                               legacy_routes=True) as (client, engine, tables, identity):
            facts = [dict(id=i, tenant_id=1, business_id=None, status='active',
                          trust_level='verified', meta={'from_onboarding': True}) for i in range(1, 7)]
            facts[2]['meta'] = {'from_onboarding': False}
            facts[3]['status'] = 'inactive'
            facts[4]['tenant_id'] = 2
            facts[5]['business_id'] = 99
            async with engine.begin() as conn:
                await conn.execute(tables['tenants'].insert(), [{'id': 1, 'name': 'fixture'}, {'id': 2, 'name': 'other'}])
                await conn.execute(tables['tenant_modules'].insert().values(tenant_id=1, module_code='geo', status='active'))
                await conn.execute(tables['geo_optimization_businesses'].insert().values(id=42, tenant_id=1, status='active'))
                await conn.execute(tables['geo_facts'].insert(), facts)
                before = (await conn.execute(select(tables['geo_facts']).order_by(tables['geo_facts'].c.id))).mappings().all()
            url = '/api/v1/geo/onboarding/readiness'
            result = await client.get(url, params={'tenant_id': 1})
            assert result.status_code == 200, result.text
            payload = result.json()
            assert {'items', 'ready_count', 'total', 'ready', 'blocking', 'tenant_name'} <= payload.keys()
            assert payload['unassigned_onboarding_facts']['count'] == 2
            assert payload['unassigned_onboarding_facts']['automatic_assignment'] is False
            async with engine.connect() as conn:
                after = (await conn.execute(select(tables['geo_facts']).order_by(tables['geo_facts'].c.id))).mappings().all()
            assert after == before
            # Normal submission still owns this write helper; no new background backfill.
            async with identity['sessions']() as session:
                assert await attach_orphan_onboarding_facts(session, tenant_id=1, business_id=42) == 2
                await session.commit()
            again = await client.get(url, params={'tenant_id': 1})
            assert again.json()['unassigned_onboarding_facts']['count'] == 0
            async with engine.connect() as conn:
                values = dict((await conn.execute(select(tables['geo_facts'].c.id, tables['geo_facts'].c.business_id))).all())
            assert values == {1: 42, 2: 42, 3: None, 4: None, 5: None, 6: 99}
            assert (await client.get(url, params={'tenant_id': 2})).status_code == 403
    asyncio.run(run())


async def seed_export(engine, tables):
    async with engine.begin() as conn:
        await conn.execute(tables['tenants'].insert().values(id=1, name='fixture'))
        await conn.execute(tables['tenant_modules'].insert().values(tenant_id=1, module_code='geo', status='active'))
        await conn.execute(tables['geo_prompts'].insert().values(id=1, tenant_id=1, question='Fixture question'))
        await conn.execute(tables['geo_content_tasks'].insert().values(
            id=14, tenant_id=1, prompt_id=1, title='Fixture', status='editing', review_status='approved', reviewed_by=9001))
        await conn.execute(tables['geo_article_versions'].insert().values(id=18, task_id=14, version_no=1))
        await conn.execute(tables['geo_channel_variants'].insert().values(
            id=20, task_id=14, article_version_id=18, channel='website', title='Fixture title',
            body_markdown='# Heading\n\n| A | B |\n| --- | --- |\n| one | two |\n\n## FAQ\n\nQ: Test?\n\nA: Fixture.',
            status='draft', export_format='markdown', adapt_meta={
                'delivery': 'adapted_draft_not_publishable', 'publication_monitor': {'state': 'pending'},
                'push_deliveries': {'fixture': {'state': 'unknown'}}}))


async def stored_export_state(engine, tables):
    async with engine.connect() as conn:
        return {name: [dict(r) for r in (await conn.execute(select(tables[name]))).mappings()]
                for name in ('geo_content_tasks', 'geo_channel_variants', 'geo_prompts', 'geo_publications')}


def test_export_get_is_read_only_and_post_requires_edit_without_approving_or_publishing():
    from app.models import GeoFact, GeoTaskFact

    async def run():
        async with environment(extra_models=(GeoFact, GeoTaskFact), legacy_routes=True) as (client, engine, tables, identity):
            await seed_export(engine, tables)
            path = '/api/v1/geo/content-tasks/14/export'
            params = {'tenant_id': 1, 'channel': 'website'}
            before = await stored_export_state(engine, tables)
            # A pure GET must finish even while another transaction owns the task write lock.
            async with engine.begin() as locker:
                await locker.execute(select(tables['geo_content_tasks']).with_for_update())
                preview = await asyncio.wait_for(client.get(path, params=params), timeout=3)
            assert preview.status_code == 200, preview.text
            view = preview.json()
            assert view['read_only'] and '<table' in view['body_html'] and 'FAQ' in view['body_html']
            assert view['quality'] == 'unknown' and view['status'] == 'draft'
            assert await stored_export_state(engine, tables) == before
            body = {'expected_revision': view['export_revision']}
            assert (await client.post(path, params=params, json=body)).status_code == 403
            identity['ctx'].permissions = {'geo.content': 'edit'}
            assert (await client.post(path, params=params, json={})).status_code == 422
            result = await client.post(path, params=params, json=body)
            assert result.status_code == 200, result.text
            assert not result.json()['read_only'] and result.json()['status'] == 'exported'
            after = await stored_export_state(engine, tables)
            task = after['geo_content_tasks'][0]
            variant = after['geo_channel_variants'][0]
            assert task['review_status'] == 'approved' and task['reviewed_by'] == 9001
            assert variant['adapt_meta']['delivery'] == 'adapted_draft_not_publishable'
            assert variant['adapt_meta']['publication_monitor'] == {'state': 'pending'}
            assert variant['adapt_meta']['push_deliveries'] == {'fixture': {'state': 'unknown'}}
            assert after['geo_publications'] == []
            assert (await client.post(path, params=params, json=body)).status_code == 409
            # Export an already published representation without demoting it or its review.
            async with engine.begin() as conn:
                await conn.execute(tables['geo_content_tasks'].update().values(status='published'))
                await conn.execute(tables['geo_channel_variants'].update().values(status='published'))
            preview = (await client.get(path, params=params)).json()
            result = await client.post(path, params=params, json={'expected_revision': preview['export_revision']})
            assert result.status_code == 200 and result.json()['status'] == 'published'
            assert (await stored_export_state(engine, tables))['geo_content_tasks'][0]['status'] == 'published'
            assert (await client.get(path, params={'tenant_id': 2})).status_code == 403
            async with engine.begin() as conn:
                await conn.execute(tables['tenant_modules'].update().values(status='disabled'))
            assert (await client.get(path, params=params)).status_code == 403
            assert (await client.post(path, params=params, json={'expected_revision': preview['export_revision']})).status_code == 403
    asyncio.run(run())


def test_default_configuration_gets_render_defaults_without_persisting_rows():
    from app.models import GeoChannelAccount, GeoFact, GeoMediaPlacement, GeoTaskFact

    async def run():
        async with environment(
            extra_models=(GeoChannelAccount, GeoFact, GeoMediaPlacement, GeoTaskFact),
            legacy_routes=True,
        ) as (
            client,
            engine,
            tables,
            identity,
        ):
            identity["ctx"].permissions = {
                "geo.content": "view",
                "geo.diagnosis": "view",
            }
            async with engine.begin() as conn:
                await conn.execute(
                    tables["tenants"].insert().values(id=1, name="fixture")
                )
                await conn.execute(
                    tables["tenant_modules"].insert().values(
                        tenant_id=1, module_code="geo", status="active"
                    )
                )
                await conn.execute(
                    tables["geo_prompts"].insert().values(
                        id=1, tenant_id=1, question="Fixture question"
                    )
                )
                await conn.execute(
                    tables["geo_content_tasks"].insert().values(
                        id=14, tenant_id=1, prompt_id=1, title="Fixture"
                    )
                )

            paths = (
                "/publishing-channel-options",
                "/publishing-channels",
                "/publishing-channels/auto-push-status",
                "/tracking-engines",
                "/monitoring-stance",
                "/media-placements",
                "/channel-blueprint",
                "/content-tasks/14",
            )
            payloads = {}
            for path in paths:
                response = await client.get(
                    "/api/v1/geo" + path, params={"tenant_id": 1}
                )
                assert response.status_code == 200, (path, response.text)
                payloads[path] = response.json()

            assert payloads["/publishing-channels"]["configuration_initialized"] is False
            assert all(
                item["virtual_default"]
                for item in payloads["/publishing-channels"]["items"]
            )
            assert all(
                item["virtual_default"]
                for item in payloads["/tracking-engines"]["items"]
            )
            assert payloads["/monitoring-stance"]["configuration_initialized"] is False
            assert payloads["/media-placements"]["configuration_initialized"] is False
            assert all(
                item["virtual_default"]
                for item in payloads["/publishing-channel-options"]["items"]
            )

            async with engine.connect() as conn:
                counts = {
                    name: await conn.scalar(
                        select(text("count(*)")).select_from(tables[name])
                    )
                    for name in (
                        "geo_publishing_channels",
                        "geo_tracking_engines",
                        "geo_ai_settings",
                        "geo_media_placements",
                    )
                }
            assert counts == {name: 0 for name in counts}

            assert (
                await client.get(
                    "/api/v1/geo/tracking-engines", params={"tenant_id": 2}
                )
            ).status_code == 403

    asyncio.run(run())


@pytest.mark.parametrize('change', ['body', 'article', 'monitor'])
def test_export_waits_for_task_lock_and_rechecks_revision_or_preserves_new_monitor(change):
    from app.models import GeoFact, GeoTaskFact

    async def run():
        async with environment(extra_models=(GeoFact, GeoTaskFact), legacy_routes=True) as (client, engine, tables, identity):
            await seed_export(engine, tables)
            identity['ctx'].permissions = {'geo.content': 'edit'}
            path = '/api/v1/geo/content-tasks/14/export'
            params = {'tenant_id': 1, 'channel': 'website'}
            preview = (await client.get(path, params=params)).json()
            pending = None
            try:
                async with engine.begin() as locker:
                    await locker.execute(select(tables['geo_content_tasks']).with_for_update())
                    pending = asyncio.create_task(client.post(path, params=params, json={'expected_revision': preview['export_revision']}))
                    blocked = False
                    for _ in range(100):
                        async with engine.connect() as inspect:
                            blocked = await inspect.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND application_name='geo_fixture_post' AND cardinality(pg_blocking_pids(pid))>0)"))
                        if blocked:
                            break
                        await asyncio.sleep(.02)
                    assert blocked, 'POST did not wait on the actual PostgreSQL task lock'
                    if change == 'article':
                        await locker.execute(tables['geo_article_versions'].insert().values(id=19, task_id=14, version_no=2))
                    else:
                        updates = {'body_markdown': 'Updated body'} if change == 'body' else {
                            'adapt_meta': {'delivery': 'adapted_draft_not_publishable', 'publication_monitor': {'state': 'healthy'},
                                           'push_deliveries': {'fixture': {'state': 'unknown'}}}}
                        await locker.execute(tables['geo_channel_variants'].update().values(**updates))
                result = await asyncio.wait_for(pending, timeout=5)
                assert result.status_code == (200 if change == 'monitor' else 409), result.text
                state = await stored_export_state(engine, tables)
                assert state['geo_content_tasks'][0]['review_status'] == 'approved'
                if change in {'body', 'article'}:
                    assert state['geo_channel_variants'][0]['status'] == 'draft'
                    if change == 'body':
                        assert state['geo_channel_variants'][0]['body_markdown'] == 'Updated body'
                else:
                    assert state['geo_channel_variants'][0]['adapt_meta']['publication_monitor']['state'] == 'healthy'
                assert state['geo_publications'] == []
            finally:
                if pending and not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
    asyncio.run(run())
