import asyncio
import json
import logging
from unittest.mock import AsyncMock

import pytest
from app.models import GeoArticleVersion, GeoChannelVariant, GeoContentTask, GeoProject
from app.geo.content.export_view import export_revision
from test_advisor_scoped_writes import write_sandbox, mutate


def test_advisor_exports_current_variant_and_records(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="geo.advisor.operations")
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            async with env.factory() as session:
                variant = await session.get(GeoChannelVariant, 10)
                revision = export_revision(variant, 10)
            response = await env.request("POST", "/content-tasks/10/export",
                body={"expected_revision": revision}, params={"channel": "website"})
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                assert (await session.get(GeoChannelVariant, 10)).status == "exported"
    asyncio.run(run())
    assert any(json.loads(r.message)["result"] == "committed" for r in caplog.records
               if r.name == "geo.advisor.operations")


@pytest.mark.parametrize("action", ["export", "publications", "push", "push-batch", "variants"])
@pytest.mark.parametrize("failure", ["unselected", "inactive", "disabled"])
def test_publication_operations_stay_scoped(tmp_path, monkeypatch, action, failure):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, enabled=failure != "disabled") as env:
            params = {}
            if failure == "inactive":
                await mutate(env, GeoProject, 10, status="paused")
            if failure == "unselected":
                params["tenant_id"] = 20
            response = await env.request("POST", "/content-tasks/10/" + action, body={}, params=params)
            assert response.status_code == 403, response.text
    asyncio.run(run())


def test_actor_rechecked_before_each_external_attempt():
    from types import SimpleNamespace
    from app.security.advisor_write_publish import recheck_external
    from fastapi import HTTPException
    from unittest.mock import patch
    session = SimpleNamespace(info={"advisor_scoped_write": (object(), SimpleNamespace(scope={}))})
    check = AsyncMock(side_effect=HTTPException(403, "revoked"))
    with patch("app.security.advisor_write_commit.recheck_advisor_before_commit", check):
        with pytest.raises(HTTPException):
            asyncio.run(recheck_external(session, "external_attempt"))
    assert check.await_count == 1


def test_advisor_records_existing_publication_without_seeding_channels(tmp_path, monkeypatch):
    from sqlalchemy import select
    from app.models import GeoPublication, GeoPublishingChannel
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            monkeypatch.setattr("app.geo.content.routes.ensure_geo_entitlement", AsyncMock())
            monkeypatch.setattr("app.geo.content.routes.assert_can_publish", lambda *_a, **_kw: None)
            monkeypatch.setattr("app.geo.content.routes._build_rule_input", AsyncMock(return_value=None))
            response = await env.request("POST", "/content-tasks/10/publications", body={
                "tenant_id": 10, "channel": "website", "published_url": "https://published.example.test/article"})
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                assert len(list(await session.scalars(select(GeoPublication)))) == 1
                assert not list(await session.scalars(select(GeoPublishingChannel)))
    asyncio.run(run())


def test_advisor_variant_channel_array_reaches_real_job_reservation(tmp_path, monkeypatch):
    from starlette.background import BackgroundTasks
    from app.models import GeoAsyncJob
    queued = []
    monkeypatch.setattr(BackgroundTasks, 'add_task', lambda _self, fn, *args, **kw: queued.append(args))
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            response = await env.request('POST', '/content-tasks/10/variants',
                body={'channels': ['website'], 'use_llm': False})
            assert response.status_code == 200, response.text
            job = response.json()['job']
            assert queued == [(job['id'], 10)]
            async with env.factory() as session:
                saved = await session.get(GeoAsyncJob, job['id'])
                assert saved.request_meta['advisor_authority']['body']['channels'] == ['website']
    asyncio.run(run())


@pytest.mark.parametrize('foreign', [False, True])
def test_advisor_batch_targets_array_is_scoped_and_enqueues_selected_tenant(tmp_path, monkeypatch, foreign):
    from starlette.background import BackgroundTasks
    from app.models import GeoChannelAccount, GeoPublishingChannel
    queued = []
    monkeypatch.setattr(BackgroundTasks, 'add_task', lambda _self, fn, *args, **kw: queued.append(args))
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            async with env.engine.begin() as connection:
                await connection.run_sync(lambda conn: GeoChannelAccount.__table__.create(conn))
            async with env.factory() as session:
                for ident, tid in [(70, 10), (71, 20)]:
                    session.add(GeoPublishingChannel(id=ident, tenant_id=tid, name='fixture', channel_type='website'))
                    await session.flush()
                    session.add(GeoChannelAccount(id=ident, tenant_id=tid, channel_id=ident, display_name='fixture'))
                await session.commit()
            monkeypatch.setattr('app.geo.content.routes.ensure_geo_entitlement', AsyncMock())
            monkeypatch.setattr('app.geo.content.routes.assert_can_publish', lambda *_a, **_kw: None)
            monkeypatch.setattr('app.geo.content.routes._build_rule_input', AsyncMock(return_value=None))
            monkeypatch.setattr('app.geo.content.multi_push.list_push_targets', AsyncMock(return_value=[
                {'ready': True, 'account_id': 70, 'channel_id': 70, 'adapt_key': 'website', 'channel_type': 'website'}]))
            response = await env.request('POST', '/content-tasks/10/push-batch', body={
                'tenant_id': 10, 'mode': 'draft', 'create_publication': False,
                'targets': [{'account_id': 71 if foreign else 70, 'channel': 'website'}]})
            if foreign:
                assert response.status_code == 403, response.text
                assert not queued
            else:
                assert response.status_code == 200, response.text
                assert response.json()['queued_targets'] == 1
                assert queued == [(response.json()['job']['id'], 10)]
    asyncio.run(run())


@pytest.mark.parametrize('suffix,body', [
    ('variants', {'channels': [{'engine_key': 'unexpected'}]}),
    ('push-batch', {'tenant_id': 10, 'targets': [{'account_id': 70, 'channel': 'website', 'tenant_id': 20}]}),
])
def test_action_arrays_still_reject_unreviewed_nested_fields(tmp_path, monkeypatch, suffix, body):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            response = await env.request('POST', '/content-tasks/10/' + suffix, body=body)
            assert response.status_code == 403, response.text
    asyncio.run(run())
