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


def test_project_metadata_allowed_during_patrol(tmp_path, monkeypatch):
    from app.geo.project_routes import geo_projects_router
    from app.models import GeoVisibilityPatrolSettings
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            env.app.include_router(geo_projects_router)
            response = await env.request("PATCH", "/projects/10", body={"description": "advisor daily edit"})
            assert response.status_code == 200, response.text
            await mutate(env, GeoVisibilityPatrolSettings, 10, enabled=True)
            response = await env.request("PATCH", "/projects/10", body={"domain": "changed.example.test"})
            assert response.status_code == 200, response.text
    asyncio.run(run())


def test_audit_emits_with_default_python_warning_logging():
    import os
    import subprocess
    import sys
    script = """
import logging
from app.security.advisor_write_audit import record
logging.getLogger().setLevel(logging.WARNING)
record({'geo_advisor_actor': (1, 10), 'method': 'POST', 'path': '/api/v1/geo/content-tasks/10/check',
        'path_params': {'task_id': 10}}, 'committed')
"""
    # Windows' asyncio socket provider needs SystemRoot even for this isolated
    # import. Keep the child otherwise empty, with no application configuration.
    child_env = {'SystemRoot': os.environ['SystemRoot']} if os.name == 'nt' else {}
    result = subprocess.run([sys.executable, "-c", script], env=child_env, capture_output=True, text=True, check=True)
    event = json.loads(result.stderr)
    assert event["advisor_user_id"] == 1 and event["tenant_id"] == 10
    assert event["result"] == "committed" and event["object_ids"] == {"task_id": 10}


def test_new_fact_operation_records_the_database_assigned_id(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="geo.advisor.operations")
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            response = await env.request("POST", "/facts", body={"tenant_id": 10, "business_id": 10,
                "title": "new audited fact", "statement": "synthetic statement", "source_name": "fixture source"})
            assert response.status_code == 200, response.text
            return response.json()["id"]
    ident = asyncio.run(run())
    events = [json.loads(r.message) for r in caplog.records if r.name == "geo.advisor.operations"]
    assert any(e["result"] == "committed" and ident in e["object_ids"].get("geo_facts", []) for e in events)


def test_project_visibility_reads_do_not_expose_another_project(tmp_path, monkeypatch):
    from app.geo.content.search_visibility_routes import router
    from app.geo.content.search_visibility import KIND
    from app.models import GeoAsyncJob, GeoOptimizationBusiness, GeoOptimizationUnit
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            env.app.include_router(router, prefix="/api/v1/geo")
            async with env.factory() as session:
                (await session.get(GeoOptimizationUnit, 10)).keyword = "own term"
                session.add(GeoOptimizationBusiness(id=50, tenant_id=10, name="foreign business"))
                await session.flush()
                session.add(GeoOptimizationUnit(id=50, tenant_id=10, business_id=50, name="foreign unit", keyword="foreign term"))
                session.add(GeoProject(id=50, tenant_id=10, tenant_module_id=10, name="foreign project",
                    primary_domain="foreign.example.test", canonical_domain="foreign.example.test", status="active",
                    project_settings={"geo_business_scope": {"business_ids": [50]}, "geo_service_plan": {"advisor_user_id": 3}}))
                session.add(GeoAsyncJob(id=100, tenant_id=10, kind=KIND, status="succeeded", ref_type="geo_project", ref_id=50))
                await session.commit()
            response = await env.request("GET", "/projects/10/search-visibility/config")
            assert response.status_code == 200, response.text
            assert response.json()["suggested_core_terms"] == ["own term"]
            for suffix in ("", "/config", "/runs/100", "/runs/100/csv"):
                response = await env.request("GET", "/projects/50/search-visibility" + suffix)
                assert response.status_code == 403, response.text
            await mutate(env, GeoProject, 10, status="paused")
            response = await env.request("GET", "/projects/10/search-visibility")
            assert response.status_code == 403, response.text
    asyncio.run(run())


@pytest.mark.parametrize("chain", ["patrol", "period", "plan"])
def test_operation_during_execution_keeps_configuration_and_project_guards(tmp_path, monkeypatch, chain):
    from app.models import GeoOptimizationPeriod, GeoVisibilityPatrolSettings
    from datetime import datetime, timedelta
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            async with env.factory() as session:
                if chain == "patrol":
                    (await session.get(GeoVisibilityPatrolSettings, 10)).enabled = True
                elif chain == "period":
                    session.add(GeoOptimizationPeriod(tenant_id=10, status="active", name="fixture period",
                        starts_at=datetime.now(), ends_at=datetime.now() + timedelta(days=7)))
                else:
                    import copy
                    project = await session.get(GeoProject, 10)
                    settings = copy.deepcopy(project.project_settings)
                    settings["geo_service_plan"]["enabled"] = True
                    project.project_settings = settings
                await session.commit()
            for path, body in [("/facts/10", {"statement": "Updated while running"}),
                               ("/prompts/10", {"question": "Updated assigned question?"})]:
                response = await env.request("PATCH", path, body=body)
                assert response.status_code == 200, response.text
            response = await env.request("PUT", "/visibility-patrol/settings", body={"enabled": False})
            assert response.status_code == 403, response.text
            response = await env.request("PATCH", "/facts/20", body={"statement": "foreign"})
            assert response.status_code == 403, response.text
            await mutate(env, GeoProject, 10, status="paused")
            response = await env.request("PATCH", "/facts/10", body={"statement": "inactive"})
            assert response.status_code == 403, response.text
    asyncio.run(run())
