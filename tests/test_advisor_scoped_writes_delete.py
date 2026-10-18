import asyncio
import json
import logging

import pytest
from app.models import GeoContentTask, GeoProject
from test_advisor_scoped_writes import write_sandbox, mutate, no_external_http_or_background_dispatch


@pytest.mark.parametrize("hard", [False, True])
def test_advisor_archive_and_hard_delete_commit_with_log(tmp_path, monkeypatch, caplog, hard):
    caplog.set_level(logging.INFO, logger="geo.advisor.operations")
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            response = await env.request("DELETE", "/content-tasks/10", params={"hard": str(hard).lower()})
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                row = await session.get(GeoContentTask, 10)
                assert row is None if hard else row.status == "archived"
    asyncio.run(run())
    events = [json.loads(r.message) for r in caplog.records if r.name == "geo.advisor.operations"]
    assert any(e["result"] == "committed" and e["object_ids"] == {"task_id": "10"} for e in events)


def test_manual_snapshot_delete_resolves_its_prompt_project(tmp_path, monkeypatch):
    from datetime import datetime
    from app.models import GeoAnswerSnapshot
    from unittest.mock import AsyncMock
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            async with env.engine.begin() as conn:
                await conn.run_sync(lambda c: GeoAnswerSnapshot.__table__.create(c, checkfirst=True))
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
                                        ("/prompts/10", ("paused", "active"))])
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
