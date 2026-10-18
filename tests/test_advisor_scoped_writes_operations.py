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
