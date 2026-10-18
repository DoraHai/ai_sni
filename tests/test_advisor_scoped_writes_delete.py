import asyncio
import json
import logging

import pytest
from app.models import GeoContentTask, GeoProject
from test_advisor_scoped_writes import write_sandbox, mutate, no_external_http_or_background_dispatch, backend


@pytest.mark.parametrize("hard", [False, True])
def test_advisor_archive_and_hard_delete_commit_with_log(tmp_path, monkeypatch, caplog, hard, backend):
    caplog.set_level(logging.INFO, logger="geo.advisor.operations")
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            response = await env.request("DELETE", "/content-tasks/10", params={"hard": str(hard).lower()})
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                row = await session.get(GeoContentTask, 10)
                assert row is None if hard else row.status == "archived"
                if hard and backend == "postgres":
                    from app.models import GeoArticleVersion, GeoChannelVariant
                    assert await session.get(GeoArticleVersion, 10) is None
                    assert await session.get(GeoChannelVariant, 10) is None
    asyncio.run(run())
    events = [json.loads(r.message) for r in caplog.records if r.name == "geo.advisor.operations"]
    assert any(e["result"] == "committed" and e["object_ids"] == {"task_id": "10"} for e in events)


def test_manual_snapshot_delete_resolves_its_prompt_project(tmp_path, monkeypatch):
    from datetime import datetime
    from app.models import GeoAnswerSnapshot, GeoDailyMetric
    from unittest.mock import AsyncMock
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            async with env.engine.begin() as conn:
                await conn.run_sync(lambda c: GeoAnswerSnapshot.__table__.create(c, checkfirst=True))
                await conn.run_sync(lambda c: GeoDailyMetric.__table__.create(c, checkfirst=True))
            async with env.factory() as session:
                session.add(GeoAnswerSnapshot(id=100, tenant_id=10, prompt_id=10,
                    raw_text="synthetic manual answer", captured_at=datetime(2026, 10, 18)))
                await session.commit()
            monkeypatch.setattr("app.geo.content.daily_metrics.safe_rebuild_for_captured_at", AsyncMock())
            response = await env.request("DELETE", "/answer-snapshots/100")
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                assert await session.get(GeoAnswerSnapshot, 100) is None
    asyncio.run(run())


@pytest.mark.parametrize("path,states", [("/facts/10", ("archived", "active")),
                                        ("/prompts/10", ("archived", "active"))])
def test_archive_and_restore_stay_on_assigned_project(tmp_path, monkeypatch, path, states):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            for status in states:
                response = await env.request("PATCH", path, body={"status": status})
                assert response.status_code == 200, response.text
                assert response.json()["status"] == status
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["unselected", "inactive", "unassigned", "disabled"])
def test_delete_denied_before_target_disappears(tmp_path, monkeypatch, failure):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, enabled=failure != "disabled") as env:
            if failure == "inactive":
                await mutate(env, GeoProject, 10, status="paused")
            elif failure == "unassigned":
                await mutate(env, GeoProject, 10, project_settings={})
            response = await env.request("DELETE", "/content-tasks/10", params={
                "tenant_id": 20 if failure == "unselected" else 10, "hard": "true"})
            assert response.status_code == 403, response.text
            async with env.factory() as session:
                assert await session.get(GeoContentTask, 10) is not None
    asyncio.run(run())


def test_hard_delete_cannot_cascade_into_another_task(tmp_path, monkeypatch, backend):
    from app.models import GeoChannelVariant
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            async with env.factory() as session:
                session.add(GeoChannelVariant(id=100, task_id=20, article_version_id=10,
                    channel="website", title="inconsistent fixture", body_markdown="synthetic foreign task"))
                await session.commit()
            response = await env.request("DELETE", "/content-tasks/10", params={"hard": "true"})
            assert response.status_code == 403, response.text
            assert response.json()["detail"]["code"] == "ADVISOR_DELETE_CASCADE_FORBIDDEN"
            async with env.factory() as session:
                assert await session.get(GeoContentTask, 10) is not None
                assert await session.get(GeoChannelVariant, 100) is not None
    asyncio.run(run())


async def seed_snapshot_project_slices(env):
    from datetime import datetime, date
    from app.models import (GeoAnswerSnapshot, GeoDailyMetric, GeoOptimizationBusiness,
        GeoOptimizationUnit, GeoPrompt)
    async with env.engine.begin() as conn:
        await conn.run_sync(lambda c: GeoAnswerSnapshot.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: GeoDailyMetric.__table__.create(c, checkfirst=True))
    async with env.factory() as session:
        session.add(GeoOptimizationBusiness(id=50, tenant_id=10, name='foreign assigned business'))
        await session.flush()
        session.add(GeoOptimizationUnit(id=50, tenant_id=10, business_id=50, name='foreign unit'))
        await session.flush()
        session.add(GeoPrompt(id=50, tenant_id=10, unit_id=50, question='foreign project question'))
        session.add(GeoProject(id=50, tenant_id=10, tenant_module_id=10, name='foreign project',
            primary_domain='foreign.example.test', canonical_domain='foreign.example.test', status='active',
            project_settings={'geo_business_scope': {'business_ids': [50]},
                'geo_service_plan': {'advisor_user_id': 2}}))
        await session.flush()
        for ident, pid in [(100, 10), (101, 50)]:
            session.add(GeoAnswerSnapshot(id=ident, tenant_id=10, prompt_id=pid, raw_text='synthetic project answer',
                captured_at=datetime(2026, 10, 18), engine='deepseek', sample_mode='manual', simulated=False))
        for ident, scope, bid, count in [(1000, 'b50', 50, 7), (1001, 'b10', 10, 1), (1002, 't', None, 99)]:
            session.add(GeoDailyMetric(id=ident, tenant_id=10, metric_date=date(2026, 10, 18),
                scope_key=scope, business_id=bid, snapshots_visibility=count))
        await session.commit()


def test_snapshot_list_and_delete_only_affect_assigned_project_slices(tmp_path, monkeypatch, backend):
    from app.models import GeoAnswerSnapshot, GeoDailyMetric
    from unittest.mock import AsyncMock
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            await seed_snapshot_project_slices(env)
            rebuild = AsyncMock(side_effect=AssertionError('advisor delete must not rebuild tenant-wide metrics'))
            monkeypatch.setattr('app.geo.content.daily_metrics.safe_rebuild_for_captured_at', rebuild)
            response = await env.request('GET', '/answer-snapshots')
            assert response.status_code == 200, response.text
            assert [r['id'] for r in response.json()['items']] == [100]
            response = await env.request('GET', '/answer-snapshots', params={'prompt_id': 50})
            assert response.status_code == 200 and response.json()['items'] == []
            async with env.factory() as session:
                foreign = await session.get(GeoDailyMetric, 1000)
                before = {c.name: getattr(foreign, c.name) for c in GeoDailyMetric.__table__.columns}
            response = await env.request('DELETE', '/answer-snapshots/100')
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                assert await session.get(GeoAnswerSnapshot, 100) is None
                assert await session.get(GeoAnswerSnapshot, 101) is not None
                assert (await session.get(GeoDailyMetric, 1001)).snapshots_visibility == 0
                assert (await session.get(GeoDailyMetric, 1002)).snapshots_visibility == 99
                foreign = await session.get(GeoDailyMetric, 1000)
                assert before == {c.name: getattr(foreign, c.name) for c in GeoDailyMetric.__table__.columns}
            rebuild.assert_not_awaited()
    asyncio.run(run())


def test_snapshot_delete_and_derived_metrics_roll_back_when_grant_changes(tmp_path, monkeypatch):
    from app.models import GeoAnswerSnapshot, GeoDailyMetric
    from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
    from app.security import advisor_write_snapshot_metrics
    from datetime import datetime
    from sqlalchemy import update
    original = advisor_write_snapshot_metrics.rebuild_before_delete
    async def revoke(session, *args):
        await original(session, *args)
        await session.execute(update(Grant).where(Grant.id == 101).values(revoked_at=datetime.utcnow(), revoked_by=2, revoke_reason="admin_uncheck"))
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            await seed_snapshot_project_slices(env)
            monkeypatch.setattr(advisor_write_snapshot_metrics, 'rebuild_before_delete', revoke)
            response = await env.request('DELETE', '/answer-snapshots/100')
            assert response.status_code in {401, 403}, response.text
            async with env.factory() as session:
                assert await session.get(GeoAnswerSnapshot, 100) is not None
                assert (await session.get(GeoDailyMetric, 1001)).snapshots_visibility == 1
                assert (await session.get(GeoDailyMetric, 1000)).snapshots_visibility == 7
    asyncio.run(run())
