"""Mounted daily operations and their actual object/commit/log boundary."""
import asyncio
import json
import logging

import pytest
from app.models import GeoProject, GeoContentTask
from test_advisor_scoped_writes import write_sandbox, mutate, fixture_token


@pytest.mark.parametrize("path,body", [
    ("/facts/10/verify", {"excerpt": "synthetic evidence", "excerpt_locator": "paragraph 1",
                           "source_url": "https://evidence.example.test/page"}),
    ("/content-tasks/10/retrieve-facts/apply", {"fact_ids": [11]}),
    ("/content-tasks/10/check", None),
    ("/content-tasks/10/lint", None),
])
def test_daily_actions_commit_and_record(tmp_path, monkeypatch, caplog, path, body):
    caplog.set_level(logging.INFO, logger="geo.advisor.operations")
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            response = await env.request("POST", path, body=body)
            assert response.status_code == 200, response.text
            if path.endswith("/retrieve-facts/apply"):
                async with env.factory() as session:
                    assert (await session.get(GeoContentTask, 10)).review_status == "none"
    asyncio.run(run())
    events = [json.loads(r.message) for r in caplog.records if r.name == "geo.advisor.operations"]
    assert any(e["result"] == ("http_completed" if path.endswith("/lint") else "committed")
               and e["advisor_user_id"] == 1 and e["tenant_id"] == 10 and e["object_ids"] for e in events)
    assert any(e.get("status_code") == 200 for e in events)
    assert "synthetic evidence" not in "".join(r.message for r in caplog.records)


@pytest.mark.parametrize("failure", ["unselected", "ungranted", "unassigned", "inactive", "disabled"])
def test_new_daily_actions_stay_scoped(tmp_path, monkeypatch, failure):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, enabled=failure != "disabled") as env:
            path = "/content-tasks/10/retrieve-facts/apply"
            params = {}
            if failure == "unselected":
                path = "/content-tasks/20/retrieve-facts/apply"
                params = {"tenant_id": 20}
            elif failure == "ungranted":
                path = "/content-tasks/30/retrieve-facts/apply"
                params = {"tenant_id": 30}
            elif failure == "unassigned":
                await mutate(env, GeoProject, 10, project_settings={
                    "geo_business_scope": {"revision": 1, "business_ids": [10]},
                    "geo_service_plan": {"advisor_user_id": 3}})
            elif failure == "inactive":
                await mutate(env, GeoProject, 10, status="paused")
            response = await env.request("POST", path, body={"fact_ids": [11]}, params=params)
            assert response.status_code == 403, response.text
    asyncio.run(run())


def test_selected_second_grant_and_read_filter(tmp_path, monkeypatch):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            response = await env.request("POST", "/content-tasks/20/retrieve-facts/apply",
                auth=fixture_token(tid=20, gid=102), params={"tenant_id": 20}, body={"fact_ids": [20]})
            assert response.status_code == 200, response.text
            await mutate(env, GeoProject, 10, status="paused")
            response = await env.request("GET", "/facts")
            assert response.status_code == 200 and response.json()["items"] == []
            response = await env.request("GET", "/content-tasks/10")
            assert response.status_code == 403, response.text
    asyncio.run(run())


@pytest.mark.parametrize("status", ["generating", "adapting", "ready", "published", "archived"])
def test_readiness_check_cannot_overwrite_busy_or_protected_state(tmp_path, monkeypatch, status):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            await mutate(env, GeoContentTask, 10, status=status)
            response = await env.request("POST", "/content-tasks/10/check")
            assert response.status_code == 403, response.text
            async with env.factory() as session:
                assert (await session.get(GeoContentTask, 10)).status == status
    asyncio.run(run())


def test_project_metadata_keeps_patrol_guard(tmp_path, monkeypatch):
    from app.geo.project_routes import geo_projects_router
    from app.models import GeoVisibilityPatrolSettings
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            env.app.include_router(geo_projects_router)
            response = await env.request("PATCH", "/projects/10", body={"description": "advisor daily edit"})
            assert response.status_code == 200, response.text
            await mutate(env, GeoVisibilityPatrolSettings, 10, enabled=True)
            response = await env.request("PATCH", "/projects/10", body={"domain": "changed.example.test"})
            assert response.status_code == 403, response.text
    asyncio.run(run())


def test_audit_emits_with_default_python_warning_logging():
    import subprocess
    import sys
    script = """
import logging
from app.security.advisor_write_audit import record
logging.getLogger().setLevel(logging.WARNING)
record({'geo_advisor_actor': (1, 10), 'method': 'POST', 'path': '/api/v1/geo/content-tasks/10/check',
        'path_params': {'task_id': 10}}, 'committed')
"""
    result = subprocess.run([sys.executable, "-c", script], env={}, capture_output=True, text=True, check=True)
    event = json.loads(result.stderr)
    assert event["advisor_user_id"] == 1 and event["tenant_id"] == 10
    assert event["result"] == "committed" and event["object_ids"] == {"task_id": 10}
