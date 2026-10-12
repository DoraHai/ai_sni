import asyncio
from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import PositiveInt
from sqlalchemy.exc import SQLAlchemyError

from app import automation_projects as shared
from app.geo import automation_routes, onsite_jobs


def test_geo_routes_publish_full_read_control_contract_and_narrow_coverage():
    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in automation_routes.router.routes}
    assert ("/workbench/automation-projects", ("GET",)) in routes
    assert ("/workbench/automation-projects/{scope_id}/control", ("GET",)) in routes
    assert ("/workbench/automation-projects/{scope_id}/control", ("PUT",)) in routes
    assert ("/workbench/automation-projects/{scope_id}/control", ("POST",)) in routes
    assert ("/workbench/automation-projects/{scope_id}/runs", ("GET",)) in routes
    assert ("/workbench/automation-projects/{scope_id}/runs/{run_id}", ("GET",)) in routes
    assert ("/workbench/automation-projects/{scope_id}/runs/{run_id}/events", ("GET",)) in routes
    assert ("/workbench/automation-projects/{scope_id}/events", ("GET",)) in routes
    assert ("/workbench/automation-projects/{scope_id}/configuration-basis", ("GET",)) in routes
    assert ("/workbench/automation-projects/{scope_id}/events/export", ("GET",)) in routes
    health_routes = {(route.path, tuple(sorted(route.methods or ()))) for route in automation_routes.health_router.routes}
    assert ("/workbench/automation-health", ("GET",)) in health_routes
    assert automation_routes.COVERAGE["controlled"] == ["configured_onsite_ai", "periodic_workflow", "visibility_patrol"]
    assert {"manual_onsite_ai", "distribution", "website_mutation", "approval", "acceptance"} <= set(
        automation_routes.COVERAGE["not_controlled"]
    )


def test_project_view_never_claims_uncontrolled_geo_operations():
    key = shared.scope("geo", 4, 9)
    view = shared.project_view(key, None, coverage=automation_routes.COVERAGE)
    assert view["capabilities"]["available_operations"] == ["onsite_ai"]
    assert view["coverage"] == automation_routes.COVERAGE


def test_automation_worker_settlement_uses_only_safe_refs_and_continues(monkeypatch):
    calls = []
    resumed = asyncio.Event()

    async def settle(_session, token, **kwargs):
        calls.append((token, kwargs))
        return True

    async def resume(key, run_id):
        calls.append((key, run_id))
        resumed.set()

    monkeypatch.setattr(shared, "settle_step", settle)
    monkeypatch.setattr(automation_routes, "run_automation", resume)

    class Session:
        commits = 0

        async def commit(self):
            self.commits += 1

    token = {
        "module": "geo", "tenant_id": 4, "scope_id": 9,
        "run_id": "12345678-1234-4234-8234-123456789abc",
        "generation": 2, "step_key": "onsite_ai:17", "task_id": 17,
        "request_id": "12345678-1234-4234-8234-123456789abd", "owner_user_id": 7,
    }
    job = SimpleNamespace(request_meta={"automation_token": token})

    async def resolve(_session, _job):
        return token

    monkeypatch.setattr(onsite_jobs, "_automation_token", resolve)

    async def scenario():
        session = Session()
        assert await onsite_jobs._settle_automation(
            session, job, status="succeeded", fee_state="recorded", success=True
        )
        await asyncio.wait_for(resumed.wait(), 1)
        assert session.commits == 1

    asyncio.run(scenario())
    _, kwargs = calls[0]
    assert kwargs["evidence_refs"] == ("geo_ticket:17",)
    assert kwargs["result_links"] == (
        "/api/v1/geo/workbench/onsite-tasks/17?tenant_id=4&project_id=9",
    )
    assert "prompt" not in str(calls).lower()


def test_non_automation_job_has_no_shared_side_effect(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("shared ledger must not be touched")

    monkeypatch.setattr(shared, "settle_step", forbidden)
    async def none(_session, _job):
        return None
    monkeypatch.setattr(onsite_jobs, "_automation_token", none)
    session = SimpleNamespace(commit=forbidden)
    job = SimpleNamespace(request_meta={"request_id": "manual"})
    assert asyncio.run(onsite_jobs._settle_automation(
        session, job, status="failed", error_code="onsite_ai_failed"
    )) is False


def test_adapter_errors_are_redacted_and_no_store():
    app = FastAPI()
    router = APIRouter(route_class=automation_routes.AutomationRoute)

    @router.get("/database-error")
    async def database_error():
        raise SQLAlchemyError("PRIVATE DATABASE DETAIL")

    @router.get("/positive/{value}")
    async def positive(value: PositiveInt):
        return {"value": value}

    app.include_router(router)
    response = TestClient(app).get("/database-error")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "automation_unavailable"
    assert "PRIVATE" not in response.text
    invalid = TestClient(app).get("/positive/0")
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "no-store"
    assert invalid.json()["detail"]["code"] == "automation_invalid_request"


def test_project_automation_only_accepts_unused_first_draft():
    assert automation_routes._automatic_initial_blocker({
        "phase": "draft", "revision": 1,
    }) is None
    assert automation_routes._automatic_initial_blocker({
        "phase": "review", "revision": 2,
    })[0] == "automation_task_not_draft"
    assert automation_routes._automatic_initial_blocker({
        "phase": "draft", "revision": 1, "ai_proposal": {"schema": 2},
    })[0] == "automation_existing_proposal"
    assert automation_routes._automatic_initial_blocker({
        "phase": "draft", "revision": 1, "ai_run": {"state": "unknown"},
    })[0] == "automation_prior_ai_request"
