"""Native PostgreSQL + HTTP proofs for the GEO v2 adapter."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateTable

from app import automation_projects as core
from app import onsite_workflow as onsite_work
from app.automation_project_contract import Configure, Control, ConfigurationV2
from app.geo import automation_routes
from app.geo.automation_v2_adapter import (live_basis, legacy_prompt_ids,
                                            aggregate_step_fee,
                                            owned_target_ids, owned_visibility_prompt_ids,
                                            provider_fee_receipt,
                                            SUPPORTED_OPERATIONS,
                                            validate_configuration)
from app.geo.project_scope import set_binding
from app.geo.project_workflows import save_plan
from app.models import GeoTrackingEngine, GeoVisibilityPatrolSettings
from app.models import GeoVisibilityPatrolRun, GeoAnswerSnapshot
from app.models import (GeoActionTicket, GeoArticleVersion, GeoAsyncJob, GeoContentTask,
                        GeoChannelVariant, GeoFact, GeoPublication, GeoTaskFact)
from app.models import GeoCompetitorAlias
from app.models.role import Role
from app.models.user import User
from app.models import GeoPrompt
from app.security.auth import AuthContext, require_scoped_auth
from app.database import get_session
from test_geo_project_scope_postgres import database

pytestmark = pytest.mark.skipif(not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated PostgreSQL")


async def install(sessions):
    root = Path(__file__).parents[1]
    async with sessions.kw["bind"].begin() as connection:
        await connection.execute(CreateTable(GeoVisibilityPatrolSettings.__table__, include_foreign_key_constraints=[]))
        await connection.execute(CreateTable(GeoVisibilityPatrolRun.__table__, include_foreign_key_constraints=[]))
        await connection.execute(CreateTable(GeoCompetitorAlias.__table__, include_foreign_key_constraints=[]))
        raw = (await connection.get_raw_connection()).driver_connection
        await raw.execute((root / "scripts/automation_projects_schema.sql").read_text(encoding="utf-8"))
        await raw.execute((root / "scripts/automation_projects_v2_schema.sql").read_text(encoding="utf-8"))
    # DDL invalidates cached plans; callers never retry an uncertain write.
    await sessions.kw["bind"].dispose()


async def foundation(sessions):
    await install(sessions)
    async with sessions() as db:
        await set_binding(db, 1, 10, [20], 0, 7)
        await save_plan(db, 1, 10, dict(enabled=True, status="active", prompt_ids=[40],
            interval_days=7, advisor_user_id=7), 0, 7)
        db.add(GeoVisibilityPatrolSettings(tenant_id=1, enabled=True, auto_persist=True,
            prefer_real=True, prompt_limit=20, engine_keys=["deepseek"]))
        db.add(GeoTrackingEngine(id=90, tenant_id=1, engine_key="deepseek",
            display_name="DeepSeek", enabled=True, sample_mode="openai_compat", sort_order=10))
        db.add(GeoTrackingEngine(id=91, tenant_id=1, engine_key="chatgpt",
            display_name="ChatGPT", enabled=True, sample_mode="openai_compat", sort_order=20))
        db.add(GeoCompetitorAlias(id=70, tenant_id=1, alias_name="竞品A", canonical_name="竞品A"))
        snapshot = await db.get(GeoAnswerSnapshot, 60)
        snapshot.competitors = ["竞品A"]
        snapshot.cited_urls = ["https://competitor.example/source"]
        await db.commit()


def configuration(basis):
    return {"contract_version": 2, "operations": ["visibility_patrol"],
        "targets": basis["targets"], "service_plan": basis["service_plan"],
        "source_bindings": basis["source_bindings"],
        "cycle": {"mode": "daily", "enabled": True},
        "limits": {"max_dispatches_per_run": 20, "max_external_calls_per_run": 20},
        "stop_condition": "drafts_ready_or_blocked", "owner_user_id": 7}


async def configure_and_start(sessions):
    key = core.scope("geo", 1, 10)
    async with sessions() as db:
        basis = await live_basis(db, 1, 10)
        value = configuration(basis)
        value["targets"] = [next(target for target in basis["targets"]
                                 if target["variant"] == "deepseek")]
        configured, _, _ = await core.configure_project(
            db, key, Configure(tenant_id=1, request_id=uuid4(), expected_version=0,
                               configuration=value), 7)
        started, _, _ = await core.control_project(
            db, key, Control(tenant_id=1, request_id=uuid4(),
                             expected_version=configured["version"], action="start"), 7)
        await db.commit()
    return key, started


def test_project_claim_excludes_legacy_and_end_project_keeps_ownership():
    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            key = core.scope("geo", 1, 10)
            async with sessions() as db:
                basis = await live_basis(db, 1, 10, ["visibility_patrol"])
                assert {target["variant"] for target in basis["targets"]} == {"deepseek", "chatgpt"}
                request = Configure(tenant_id=1, request_id=uuid4(), expected_version=0,
                                    configuration=configuration(basis))
                project, _, _ = await core.configure_project(db, key, request, 7)
                await db.commit()
            async with sessions() as db:
                assert await owned_visibility_prompt_ids(db, 1) == {40}
                assert 40 not in await legacy_prompt_ids(db, 1, 20)
                request = Control(tenant_id=1, request_id=uuid4(),
                                  expected_version=project["version"], action="end_project")
                await core.control_project(db, key, request, 7)
                await db.commit()
            async with sessions() as db:
                assert await owned_visibility_prompt_ids(db, 1) == {40}
                assert 40 not in await legacy_prompt_ids(db, 1, 20)
                duplicate = configuration(await live_basis(db, 1, 10))
                await db.execute(text("""INSERT INTO automation_projects
                    (module,tenant_id,scope_id,owner_user_id,configuration)
                    VALUES ('geo',1,11,7,CAST(:configuration AS jsonb))"""),
                    {"configuration": json.dumps(duplicate)})
                await db.commit()
            async with sessions() as db:
                with pytest.raises(Exception) as error:
                    await owned_visibility_prompt_ids(db, 1)
                assert getattr(error.value, "status_code", None) == 409
    asyncio.run(scenario())


def test_mixed_source_bindings_are_an_exact_unordered_set_and_can_drop_visibility():
    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            async with sessions() as db:
                mixed = await live_basis(db, 1, 10, ["periodic_workflow", "visibility_patrol"])
                value = configuration(mixed)
                value["operations"] = ["periodic_workflow", "visibility_patrol"]
                value["targets"] = [
                    *mixed["targets_by_operation"]["periodic_workflow"],
                    *mixed["targets_by_operation"]["visibility_patrol"],
                ]
                value["source_bindings"] = list(reversed(value["source_bindings"]))
                await validate_configuration(
                    db, 1, 10, ConfigurationV2.model_validate(value), 7
                )

                periodic = await live_basis(db, 1, 10, ["periodic_workflow"])
                value["operations"] = ["periodic_workflow"]
                value["targets"] = periodic["targets_by_operation"]["periodic_workflow"]
                value["source_bindings"] = list(reversed(periodic["source_bindings"]))
                await validate_configuration(
                    db, 1, 10, ConfigurationV2.model_validate(value), 7
                )
                assert {row["kind"] for row in value["source_bindings"]} == {
                    "project_prompt_set", "project_scope_registry"
                }
    asyncio.run(scenario())


def test_non_visibility_basis_does_not_require_patrol_settings():
    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            async with sessions() as db:
                settings = await db.get(GeoVisibilityPatrolSettings, 1)
                await db.delete(settings)
                await db.commit()
            async with sessions() as db:
                periodic = await live_basis(db, 1, 10, ["periodic_workflow"])
                assert periodic["targets_by_operation"]["periodic_workflow"]
                with pytest.raises(Exception) as error:
                    await live_basis(db, 1, 10, ["visibility_patrol"])
                assert getattr(error.value, "status_code", None) == 409
    asyncio.run(scenario())


def test_operation_basis_ignores_unrelated_large_or_invalid_sources():
    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            async with sessions() as db:
                task = await db.get(GeoContentTask, 50)
                task.target_channels = ["INVALID CHANNEL"]
                db.add_all([
                    GeoAnswerSnapshot(
                        id=1000 + index, tenant_id=1, prompt_id=40,
                        engine="deepseek", raw_text=f"sample {index}",
                        captured_at=datetime(2026, 10, 1),
                        sample_mode="manual", simulated=False,
                    ) for index in range(500)
                ])
                await db.commit()
            async with sessions() as db:
                assert (await live_basis(db, 1, 10, ["visibility_patrol"]))[
                    "targets_by_operation"]["visibility_patrol"]
                assert (await live_basis(db, 1, 10, ["periodic_workflow"]))[
                    "targets_by_operation"]["periodic_workflow"]
                with pytest.raises(Exception) as competitor_error:
                    await live_basis(db, 1, 10, ["competitor_report_draft"])
                assert competitor_error.value.detail["code"] == "automation_competitor_source_too_large"
                with pytest.raises(Exception) as channel_error:
                    await live_basis(db, 1, 10, ["channel_variant_draft"])
                assert channel_error.value.detail["code"] == "automation_channel_registry_invalid"
    asyncio.run(scenario())


def test_provider_fee_receipt_only_records_reviewable_usage_ledger():
    async def scenario():
        async with database() as sessions:
            async with sessions.kw["bind"].begin() as connection:
                await connection.execute(text("""CREATE TABLE api_usage_events(
                    id bigserial primary key, tenant_id bigint not null,
                    module varchar(20) not null, job_ref varchar(200) not null,
                    state varchar(20) not null, estimated_amount numeric)"""))
            async with sessions() as db:
                assert await provider_fee_receipt(
                    db, tenant_id=1, job_ref="missing"
                ) == ("unknown_charge", [])
                await db.execute(text("""INSERT INTO api_usage_events
                    (tenant_id,module,job_ref,state,estimated_amount)
                    VALUES (1,'geo','known','succeeded',1.25)"""))
                await db.commit()
            async with sessions() as db:
                fee, refs = await provider_fee_receipt(
                    db, tenant_id=1, job_ref="known"
                )
                assert fee == "recorded" and refs == ["api_event:1"]
    asyncio.run(scenario())


def test_step_fee_aggregation_uses_provider_receipts_only():
    assert aggregate_step_fee({"calls": []}) == "not_called"
    assert aggregate_step_fee({"calls": [
        {"kind": "http", "fee_state": "not_called"}
    ]}) == "not_called"
    assert aggregate_step_fee({"calls": [
        {"kind": "provider", "fee_state": "recorded"},
        {"kind": "provider", "fee_state": "recorded"},
    ]}) == "recorded"
    assert aggregate_step_fee({"calls": [
        {"kind": "provider", "fee_state": "recorded"},
        {"kind": "provider", "fee_state": "unknown_charge"},
    ]}) == "unknown_charge"


def test_typed_onsite_basis_uses_real_ticket_revision_and_snapshot_hash():
    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            async with sessions() as db:
                workflow = onsite_work.new_workflow(
                    "geo", "startup", None, "p10.example",
                    [{"id": "faq", "kind": "faq",
                      "target_url": "https://p10.example/",
                      "expected": "", "instruction": "补齐公开问答"}],
                    7, "维护人员",
                )
                workflow["project_id"] = 10
                db.add(GeoActionTicket(
                    id=88, tenant_id=1, advice_code="onsite:v1:fixture",
                    title="站内任务", priority="medium", status="todo",
                    action="制定方案", acceptance_type="manual",
                    created_by=7, progress={"onsite": workflow}, evidence=[],
                ))
                await db.commit()
            async with sessions() as db:
                basis = await live_basis(db, 1, 10, ["onsite_ai"])
                assert basis["targets_by_operation"]["onsite_ai"] == [{
                    "operation": "onsite_ai", "object_type": "onsite_task",
                    "object_id": 88, "source_revision": 1,
                    "source_hash": basis["targets_by_operation"]["onsite_ai"][0]["source_hash"],
                    "variant": None,
                }]
                value = configuration(basis)
                value["operations"] = ["onsite_ai"]
                value["targets"] = basis["targets_by_operation"]["onsite_ai"]
                await validate_configuration(
                    db, 1, 10, ConfigurationV2.model_validate(value), 7
                )
    asyncio.run(scenario())


def test_channel_variant_control_creates_one_rules_only_child(monkeypatch):
    captured = []

    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            async with sessions() as db:
                task = await db.get(GeoContentTask, 50)
                task.target_channels = ["zhihu"]
                db.add(GeoArticleVersion(
                    id=95, task_id=50, version_no=1, kind="master",
                    title="母稿", body_markdown="正文", outline={}, created_by=7,
                ))
                await db.commit()
                task.review_status = "approved"
                task.reviewed_by = 7
                task.reviewed_at = datetime.utcnow()
                await db.commit()
            key = core.scope("geo", 1, 10)
            async with sessions() as db:
                basis = await live_basis(db, 1, 10, ["channel_variant_draft"])
                debug_task = await db.get(GeoContentTask, 50)
                debug_article = await db.get(GeoArticleVersion, 95)
                assert basis["targets_by_operation"]["channel_variant_draft"], (
                    debug_task.review_status, debug_task.reviewed_by,
                    debug_task.reviewed_at, debug_task.target_channels,
                    debug_article.created_at,
                )
                value = configuration(basis)
                value["operations"] = ["channel_variant_draft"]
                value["targets"] = basis["targets_by_operation"]["channel_variant_draft"]
                configured, _, _ = await core.configure_project(db, key, Configure(
                    tenant_id=1, request_id=uuid4(), expected_version=0,
                    configuration=value), 7)
                started, _, _ = await core.control_project(db, key, Control(
                    tenant_id=1, request_id=uuid4(), expected_version=configured["version"],
                    action="start"), 7)
                await db.commit()
            @asynccontextmanager
            async def factory(*_args, **_kwargs):
                async with sessions() as db:
                    yield db

            async def capture(job_id, tenant_id):
                captured.append((job_id, tenant_id))

            monkeypatch.setattr(automation_routes, "async_session_factory", factory)
            monkeypatch.setattr(automation_routes.async_jobs, "run_job_in_background", capture)
            await automation_routes.run_automation(key, str(started["current_run_id"]))
            async with sessions() as db:
                child = await db.scalar(select(GeoAsyncJob).where(
                    GeoAsyncJob.kind == "create_variants", GeoAsyncJob.ref_id == 50))
                assert child is not None and child.request_meta["channels"] == ["zhihu"]
                assert child.request_meta["use_llm"] is False
                assert child.request_meta["automation_token"]["target"]["variant"] == "zhihu"
                assert captured == [(child.id, 1)]
                task = await db.get(GeoContentTask, 50)
                task.review_status = "none"
                task.reviewed_by = None
                task.reviewed_at = None
                await db.commit()
            async with sessions() as db:
                refreshed = await live_basis(db, 1, 10, ["channel_variant_draft"])
                assert refreshed["targets_by_operation"]["channel_variant_draft"] == []
    asyncio.run(scenario())


@pytest.mark.parametrize(("external_limit", "pause_after_first", "expected_status", "expected_requests"), [
    (20, False, "succeeded", 2), (1, False, "blocked", 1),
    (20, True, "blocked", 1),
])
def test_controlled_publication_monitor_records_each_redirect_hop(
        monkeypatch, external_limit, pause_after_first, expected_status, expected_requests):
    network_requests = []
    original_client = httpx.AsyncClient
    sessions_ref = None
    key_ref = None

    async def transport(request):
        network_requests.append(str(request.url))
        if len(network_requests) == 1:
            if pause_after_first:
                async with sessions_ref() as pause_db:
                    current = await core.read_project(pause_db, key_ref)
                    await core.control_project(pause_db, key_ref, Control(
                        tenant_id=1, request_id=uuid4(),
                        expected_version=current["version"], action="pause"), 7)
                    await pause_db.commit()
            return httpx.Response(302, headers={"location": "https://p10.example/final"})
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<html><body>published body</body></html>")

    def client_factory(*_args, **kwargs):
        return original_client(
            timeout=kwargs.get("timeout"), follow_redirects=False,
            transport=httpx.MockTransport(transport), headers=kwargs.get("headers"),
        )

    async def scenario():
        async with database() as sessions:
            nonlocal sessions_ref, key_ref
            await foundation(sessions)
            async with sessions() as db:
                db.add(GeoArticleVersion(id=96, task_id=50, version_no=1, kind="master",
                    title="发布标题", body_markdown="发布正文", outline={}, created_by=7))
                db.add(GeoChannelVariant(id=97, task_id=50, article_version_id=96,
                    channel="website", title="发布标题", body_markdown="发布正文",
                    status="published", adapt_meta={}))
                db.add(GeoPublication(id=98, variant_id=97, channel="website",
                    published_url="https://p10.example/article", status="published"))
                await db.commit()
            key = core.scope("geo", 1, 10)
            sessions_ref, key_ref = sessions, key
            async with sessions() as db:
                basis = await live_basis(db, 1, 10, ["publication_monitor"])
                value = configuration(basis)
                value["operations"] = ["publication_monitor"]
                value["targets"] = basis["targets_by_operation"]["publication_monitor"]
                value["limits"]["max_external_calls_per_run"] = external_limit
                configured, _, _ = await core.configure_project(db, key, Configure(
                    tenant_id=1, request_id=uuid4(), expected_version=0,
                    configuration=value), 7)
                started, _, _ = await core.control_project(db, key, Control(
                    tenant_id=1, request_id=uuid4(), expected_version=configured["version"],
                    action="start"), 7)
                await db.commit()
            async with sessions() as db:
                assert await owned_target_ids(
                    db, 1, "publication_monitor", "publication"
                ) == {98}

            @asynccontextmanager
            async def factory(*_args, **_kwargs):
                async with sessions() as db:
                    yield db

            monkeypatch.setattr(automation_routes, "async_session_factory", factory)
            monkeypatch.setattr("app.geo.audit._ensure_public_host",
                                AsyncMock(return_value=["93.184.216.34"]))
            monkeypatch.setattr("app.geo.audit.httpx.AsyncClient", client_factory)
            monkeypatch.setattr("app.geo.publication_monitor.match_publication", lambda *_args: {
                "observed_sha256": "a" * 64, "expected_sha256": "b" * 64,
                "matched_passages": 1, "total_passages": 1,
            })
            await automation_routes.run_automation(key, str(started["current_run_id"]))
            async with sessions() as db:
                run = await core.read_run(db, key, started["current_run_id"])
                step = run["steps"][0]
                assert step["status"] == expected_status, step
                assert [call["call_key"] for call in step["calls"]] == [
                    f"publication_98:hop_{index}" for index in range(1, expected_requests + 1)]
                assert all(call["kind"] == "http" and call["fee_state"] == "not_called"
                           for call in step["calls"])
                assert len(network_requests) == expected_requests
                variant = await db.get(GeoChannelVariant, 97)
                if expected_status == "succeeded":
                    assert variant.adapt_meta["publication_monitor"]["98"]["state"] == "healthy"
                else:
                    assert not (variant.adapt_meta or {}).get("publication_monitor")
    asyncio.run(scenario())


def test_basis_export_health_http_and_fresh_identity_revocation(tmp_path):
    async def scenario():
        repository = Path(__file__).resolve().parents[1]
        head_before = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip()
        async with database() as sessions:
            await foundation(sessions)
            async with sessions() as db:
                basis = await live_basis(db, 1, 10, ["visibility_patrol"])
                configured, _, _ = await core.configure_project(db, core.scope("geo", 1, 10), Configure(
                    tenant_id=1, request_id=uuid4(), expected_version=0,
                    configuration=configuration(basis)), 7)
                started, _, _ = await core.control_project(
                    db, core.scope("geo", 1, 10), Control(
                        tenant_id=1, request_id=uuid4(),
                        expected_version=configured["version"], action="start"), 7)
                role = await db.get(Role, 5)
                role.permissions = {**role.permissions, "settings.accounts": "edit", "settings.customers": "edit"}
                await db.commit()
            ctx = AuthContext(7, "scope fixture advisor", "fixture advisor", None,
                              {"geo.assets": "edit", "geo.content": "edit",
                               "settings.accounts": "edit", "settings.customers": "edit"})
            app = FastAPI()
            app.include_router(automation_routes.router, prefix="/api/v1/geo")
            app.include_router(automation_routes.health_router, prefix="/api/v1/geo")

            async def session_override():
                async with sessions() as db:
                    yield db
            app.dependency_overrides[get_session] = session_override
            app.dependency_overrides[require_scoped_auth] = lambda: ctx
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                basis_response = await client.get(
                    "/api/v1/geo/workbench/automation-projects/10/configuration-basis",
                    params={"tenant_id": 1, "operation": "visibility_patrol"},
                )
                assert basis_response.status_code == 200
                payload = basis_response.json()
                assert payload["targets"][0]["variant"] == "deepseek"
                assert {row["kind"] for row in payload["source_bindings"]} == {
                    "tenant_patrol_settings", "project_prompt_set", "project_scope_registry"}
                control_response = await client.get(
                    "/api/v1/geo/workbench/automation-projects/10/control", params={"tenant_id": 1}
                )
                assert control_response.status_code == 200
                control_payload = control_response.json()
                assert {"visibility_patrol", "periodic_workflow"} <= set(
                    control_payload["capabilities"]["available_operations"])
                assert control_payload["coverage"]["controlled"] == ["visibility_patrol"]
                basis_by_operation = {}
                for operation in sorted(SUPPORTED_OPERATIONS):
                    operation_response = await client.get(
                        "/api/v1/geo/workbench/automation-projects/10/configuration-basis",
                        params={"tenant_id": 1, "operation": operation},
                    )
                    assert operation_response.status_code == 200, (
                        operation, operation_response.text)
                    basis_by_operation[operation] = operation_response.json()
                run_response = await client.get(
                    f"/api/v1/geo/workbench/automation-projects/10/runs/{started['current_run_id']}",
                    params={"tenant_id": 1},
                )
                assert run_response.status_code == 200
                health = await client.get("/api/v1/geo/workbench/automation-health")
                assert health.status_code == 200 and health.headers["cache-control"] == "no-store"
                assert health.json()["scope"] == {"kind": "global", "tenant_id": None}
                scenarios = [{"case": "health_available", "method": "GET",
                    "path": "/api/v1/geo/workbench/automation-health",
                    "status": health.status_code,
                    "headers": {"cache-control": health.headers["cache-control"]},
                    "body": health.json()}]
                export = await client.get(
                    "/api/v1/geo/workbench/automation-projects/10/events/export",
                    params={"tenant_id": 1, "format": "json", "after_id": 0, "limit": 500},
                )
                assert export.status_code == 200 and export.json()["snapshot_upper_id"] >= 1
                responses = {}
                for operation, body in basis_by_operation.items():
                    responses[
                        "/api/v1/geo/workbench/automation-projects/10/configuration-basis"
                        f"?tenant_id=1&operation={operation}"
                    ] = {"status": 200, "headers": {"cache-control": "no-store"},
                         "body": body}
                responses[
                    "/api/v1/geo/workbench/automation-projects/10/control?tenant_id=1"
                ] = {"status": 200, "headers": {"cache-control": "no-store"},
                     "body": control_payload}
                responses[
                    f"/api/v1/geo/workbench/automation-projects/10/runs/{started['current_run_id']}?tenant_id=1"
                ] = {"status": 200, "headers": {"cache-control": "no-store"},
                     "body": run_response.json()}
                responses[
                    "/api/v1/geo/workbench/automation-projects/10/events/export?tenant_id=1&format=json&after_id=0&limit=500"
                ] = {"status": 200, "headers": {"cache-control": "no-store"},
                     "body": export.json()}
                responses["/api/v1/geo/workbench/automation-health"] = {
                    "status": 200, "headers": {"cache-control": "no-store"},
                    "body": health.json()}
                sample = {"source": "synthetic AuthContext over native ASGI/PostgreSQL",
                          "responses": responses, "scenarios": scenarios}

            async def capture_health(case, context=None, session_provider=None):
                app.dependency_overrides[require_scoped_auth] = (
                    (lambda: context) if context is not None else
                    (lambda: (_ for _ in ()).throw(HTTPException(401, "未登录"))))
                app.dependency_overrides[get_session] = session_provider or session_override
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                              base_url="http://test") as scenario_client:
                    result = await scenario_client.get("/api/v1/geo/workbench/automation-health")
                scenarios.append({"case": case, "method": "GET",
                    "path": "/api/v1/geo/workbench/automation-health",
                    "status": result.status_code,
                    "headers": {"cache-control": result.headers.get("cache-control", "")},
                    "body": result.json()})
                return result

            async with database() as pending_sessions:
                async with pending_sessions() as pending_db:
                    pending_role = await pending_db.get(Role, 5)
                    pending_role.permissions = {
                        **pending_role.permissions,
                        "settings.accounts": "edit", "settings.customers": "edit"}
                    await pending_db.commit()
                async def pending_session_override():
                    async with pending_sessions() as pending_db:
                        yield pending_db
                pending = await capture_health(
                    "health_schema_pending", ctx, pending_session_override)
                assert pending.status_code == 200
                assert pending.json()["state"] == "schema_pending" and pending.json()["as_of"]

            async def failing_session_override():
                async with sessions() as live_db:
                    class FailingSession:
                        async def get(self, *args, **kwargs):
                            return await live_db.get(*args, **kwargs)
                        async def execute(self, *_args, **_kwargs):
                            raise SQLAlchemyError("simulated health SQL failure")
                        async def scalar(self, *_args, **_kwargs):
                            raise SQLAlchemyError("simulated health SQL failure")
                    yield FailingSession()
            unavailable = await capture_health(
                "health_db_unavailable", ctx, failing_session_override)
            assert unavailable.status_code == 503
            assert unavailable.json()["state"] == "unavailable"
            assert unavailable.json()["as_of"]
            assert unavailable.json()["counts"] == {
                "projects": None, "runs": None,
                "pending_human": None, "unknown_cost": None}
            assert (await capture_health("health_auth_missing")).status_code == 401
            assert (await capture_health("health_api_key_rejected",
                AuthContext(None, "api", "api", None,
                            {"settings.accounts": "edit", "settings.customers": "edit"}))).status_code == 403
            assert (await capture_health("health_tenant_bound_rejected",
                AuthContext(7, "advisor", "advisor", 1,
                            {"settings.accounts": "edit", "settings.customers": "edit"}))).status_code == 403
            assert (await capture_health("health_ordinary_advisor_rejected",
                AuthContext(7, "advisor", "advisor", None,
                            {"geo.content": "edit"}))).status_code == 403
            assert (await capture_health("health_single_permission_rejected",
                AuthContext(7, "advisor", "advisor", None,
                            {"settings.accounts": "edit"}))).status_code == 403
            async with sessions() as db:
                role = await db.get(Role, 5)
                role.permissions = {"geo.assets": "edit", "geo.content": "edit"}
                await db.commit()
            app.dependency_overrides[require_scoped_auth] = lambda: ctx
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                revoked = await client.get("/api/v1/geo/workbench/automation-health")
                assert revoked.status_code == 403 and revoked.headers["cache-control"] == "no-store"
                scenarios.append({"case": "health_fresh_role_revoked", "method": "GET",
                    "path": "/api/v1/geo/workbench/automation-health",
                    "status": revoked.status_code,
                    "headers": {"cache-control": revoked.headers["cache-control"]},
                    "body": revoked.json()})
            head_after = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repository, text=True
            ).strip()
            source_tree_clean = not subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=repository, text=True
            ).strip()
            freeze_mode = os.getenv("GEO_AUTOMATION_FREEZE") == "1"
            source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            sample.update(
                backend_commit=head_after,
                source_tree_clean=source_tree_clean,
                capture={
                    "head_before": head_before,
                    "head_after": head_after,
                    "freeze_mode": freeze_mode,
                    "source": "tests/test_geo_automation_v2_postgres.py",
                    "source_sha256": source_sha256,
                },
            )
            assert head_before == head_after
            if freeze_mode:
                assert source_tree_clean
            assert all(
                response["headers"].get("cache-control") == "no-store"
                for response in sample["responses"].values()
            )
            assert all(
                scenario["headers"].get("cache-control") == "no-store"
                for scenario in sample["scenarios"]
            )
            (tmp_path / "geo-automation-v2-http.json").write_text(
                json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
            stable = Path(os.environ.get("TEMP") or os.environ.get("TMP") or str(tmp_path)) / "geo-automation-v2-http-sample.json"
            stable.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    asyncio.run(scenario())


def test_controlled_patrol_records_each_mock_http_call_and_persists_one_snapshot(monkeypatch):
    provider_calls = 0
    original_client = httpx.AsyncClient

    async def provider(request):
        nonlocal provider_calls
        provider_calls += 1
        body = ({"raw_text": "MAXXDRIVE 是经过公开资料核验的工业齿轮箱系列。"}
                if provider_calls == 1 else {
                    "suggested_mentions_brand": True, "suggested_competitors": [],
                    "suggested_brand_position": "top", "suggested_sentiment": "positive",
                })
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

    def client_factory(*_args, **kwargs):
        return original_client(timeout=kwargs.get("timeout"), transport=httpx.MockTransport(provider))

    async def credentials(_session, _tenant_id):
        return {"api_key": "fixture", "base_url": "https://provider.invalid/v1",
                "model": "fixture-model", "provider": "fixture", "source": "fixture"}

    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            key, started = await configure_and_start(sessions)

            @asynccontextmanager
            async def factory(*_args, **_kwargs):
                async with sessions() as db:
                    yield db

            @asynccontextmanager
            async def execution_lock(_run_id):
                yield True

            async def ai_setting(_session, _tenant_id):
                return SimpleNamespace(monitoring_stance="hybrid")

            monkeypatch.setattr(automation_routes, "async_session_factory", factory)
            monkeypatch.setattr("app.geo.content.patrol.patrol_execution_lock", execution_lock)
            monkeypatch.setattr("app.geo.content.ai_settings.resolve_llm_credentials", credentials)
            monkeypatch.setattr("app.geo.content.ai_settings.ensure_ai_setting", ai_setting)
            monkeypatch.setattr("app.ai.deepseek.httpx.AsyncClient", client_factory)
            await automation_routes.run_automation(key, str(started["current_run_id"]))

            async with sessions() as db:
                run = await core.read_run(db, key, started["current_run_id"])
                step = run["steps"][0]
                assert step["status"] == "succeeded"
                assert [call["state"] for call in step["calls"]] == ["succeeded", "succeeded"]
                assert len({call["call_key"] for call in step["calls"]}) == 2
                assert await db.scalar(select(GeoAnswerSnapshot).where(
                    GeoAnswerSnapshot.tenant_id == 1,
                    GeoAnswerSnapshot.prompt_id == 40,
                    GeoAnswerSnapshot.engine == "deepseek")) is not None
                assert await db.scalar(text("SELECT count(*) FROM geo_visibility_patrol_runs")) == 1
    asyncio.run(scenario())
    assert provider_calls == 2


def test_pause_after_mock_response_records_late_receipt_without_business_write(monkeypatch):
    provider_calls = 0
    original_client = httpx.AsyncClient

    async def credentials(_session, _tenant_id):
        return {"api_key": "fixture", "base_url": "https://provider.invalid/v1",
                "model": "fixture-model", "provider": "fixture", "source": "fixture"}

    async def scenario():
        nonlocal provider_calls
        async with database() as sessions:
            await foundation(sessions)
            key, started = await configure_and_start(sessions)

            async def provider(request):
                nonlocal provider_calls
                provider_calls += 1
                async with sessions() as db:
                    current = await core.read_project(db, key)
                    await core.control_project(db, key, Control(
                        tenant_id=1, request_id=uuid4(), expected_version=current["version"], action="pause"
                    ), 7)
                    await db.commit()
                body = {"raw_text": "迟到响应不得写入正式样本。"}
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

            def client_factory(*_args, **kwargs):
                return original_client(timeout=kwargs.get("timeout"), transport=httpx.MockTransport(provider))

            @asynccontextmanager
            async def factory(*_args, **_kwargs):
                async with sessions() as db:
                    yield db

            @asynccontextmanager
            async def execution_lock(_run_id):
                yield True

            async def ai_setting(_session, _tenant_id):
                return SimpleNamespace(monitoring_stance="hybrid")

            monkeypatch.setattr(automation_routes, "async_session_factory", factory)
            monkeypatch.setattr("app.geo.content.patrol.patrol_execution_lock", execution_lock)
            monkeypatch.setattr("app.geo.content.ai_settings.resolve_llm_credentials", credentials)
            monkeypatch.setattr("app.geo.content.ai_settings.ensure_ai_setting", ai_setting)
            monkeypatch.setattr("app.ai.deepseek.httpx.AsyncClient", client_factory)
            await automation_routes.run_automation(key, str(started["current_run_id"]))

            async with sessions() as db:
                run = await core.read_run(db, key, started["current_run_id"])
                step = run["steps"][0]
                assert step["status"] == "blocked"
                assert step["calls"][0]["state"] == "succeeded"
                assert (await core.read_project(db, key))["state"] == "paused"
                assert await db.scalar(select(GeoAnswerSnapshot).where(
                    GeoAnswerSnapshot.tenant_id == 1,
                    GeoAnswerSnapshot.prompt_id == 40,
                    GeoAnswerSnapshot.engine == "deepseek",
                    GeoAnswerSnapshot.patrol_run_id.is_not(None))) is None
    asyncio.run(scenario())
    assert provider_calls == 1


def test_controlled_periodic_workflow_creates_human_ticket_and_legacy_tick_cannot_duplicate(monkeypatch):
    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            key = core.scope("geo", 1, 10)
            async with sessions() as db:
                basis = await live_basis(db, 1, 10, ["periodic_workflow"])
                value = configuration(basis)
                value["operations"] = ["periodic_workflow"]
                value["targets"] = basis["targets_by_operation"]["periodic_workflow"]
                configured, _, _ = await core.configure_project(db, key, Configure(
                    tenant_id=1, request_id=uuid4(), expected_version=0,
                    configuration=value), 7)
                started, _, _ = await core.control_project(db, key, Control(
                    tenant_id=1, request_id=uuid4(), expected_version=configured["version"], action="start"), 7)
                await db.commit()

            @asynccontextmanager
            async def factory(*_args, **_kwargs):
                async with sessions() as db:
                    yield db

            monkeypatch.setattr(automation_routes, "async_session_factory", factory)
            monkeypatch.setattr("app.geo.project_workflows.async_session_factory", factory)
            await automation_routes.run_automation(key, str(started["current_run_id"]))
            async with sessions() as db:
                run = await core.read_run(db, key, started["current_run_id"])
                assert run["steps"][0]["status"] == "succeeded", run["steps"][0]
                assert run["steps"][0]["fee_state"] == "not_called"
                assert await db.scalar(select(GeoActionTicket).where(
                    GeoActionTicket.tenant_id == 1,
                    GeoActionTicket.advice_code == "workqueue:v1:prompt-40")) is not None
            from app.geo.project_workflows import refresh_project
            await refresh_project(10, session_factory=factory)
            async with sessions() as db:
                assert await db.scalar(text("SELECT count(*) FROM geo_action_tickets")) == 1
    asyncio.run(scenario())


def test_controlled_brief_writes_reviewable_job_only_and_does_not_edit_task(monkeypatch):
    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            key = core.scope("geo", 1, 10)
            async with sessions() as db:
                basis = await live_basis(db, 1, 10, ["content_brief_suggestion"])
                value = configuration(basis)
                value["operations"] = ["content_brief_suggestion"]
                value["targets"] = basis["targets_by_operation"]["content_brief_suggestion"]
                assert [target["object_id"] for target in value["targets"]] == [50]
                configured, _, _ = await core.configure_project(db, key, Configure(
                    tenant_id=1, request_id=uuid4(), expected_version=0,
                    configuration=value), 7)
                started, _, _ = await core.control_project(db, key, Control(
                    tenant_id=1, request_id=uuid4(), expected_version=configured["version"], action="start"), 7)
                await db.commit()

            @asynccontextmanager
            async def factory(*_args, **_kwargs):
                async with sessions() as db:
                    yield db
            monkeypatch.setattr(automation_routes, "async_session_factory", factory)
            await automation_routes.run_automation(key, str(started["current_run_id"]))
            async with sessions() as db:
                run = await core.read_run(db, key, started["current_run_id"])
                assert run["steps"][0]["status"] == "succeeded"
                assert run["steps"][0]["calls"] == []
                task = await db.get(GeoContentTask, 50)
                assert task.brief is None
                job = await db.scalar(select(GeoAsyncJob).where(
                    GeoAsyncJob.kind == "automation_brief_suggestion",
                    GeoAsyncJob.ref_id == 50))
                assert job.status == "succeeded"
                assert job.result_meta["persisted"] is False
                assert job.result_meta["suggested_brief"]["ai_question"] == "scope question 20"
    asyncio.run(scenario())


def test_controlled_competitor_report_is_nonpersistent_review_draft(monkeypatch):
    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            key = core.scope("geo", 1, 10)
            async with sessions() as db:
                basis = await live_basis(db, 1, 10, ["competitor_report_draft"])
                value = configuration(basis)
                value["operations"] = ["competitor_report_draft"]
                value["targets"] = basis["targets_by_operation"]["competitor_report_draft"]
                assert [target["object_id"] for target in value["targets"]] == [70]
                configured, _, _ = await core.configure_project(db, key, Configure(
                    tenant_id=1, request_id=uuid4(), expected_version=0,
                    configuration=value), 7)
                started, _, _ = await core.control_project(db, key, Control(
                    tenant_id=1, request_id=uuid4(), expected_version=configured["version"], action="start"), 7)
                await db.commit()
            @asynccontextmanager
            async def factory(*_args, **_kwargs):
                async with sessions() as db:
                    yield db
            monkeypatch.setattr(automation_routes, "async_session_factory", factory)
            await automation_routes.run_automation(key, str(started["current_run_id"]))
            async with sessions() as db:
                run = await core.read_run(db, key, started["current_run_id"])
                assert run["steps"][0]["status"] == "succeeded"
                assert run["steps"][0]["calls"] == []
                job = await db.scalar(select(GeoAsyncJob).where(
                    GeoAsyncJob.kind == "automation_competitor_report",
                    GeoAsyncJob.ref_id == 70))
                assert job.result_meta["persisted"] is False
                assert "竞品A" in job.result_meta["report"]["markdown"]
                assert "competitor.example" in job.result_meta["report"]["markdown"]
    asyncio.run(scenario())


def test_controlled_master_draft_uses_mock_transport_and_stops_at_human_review(monkeypatch):
    provider_calls = 0
    original_client = httpx.AsyncClient

    async def credentials(_session, _tenant_id):
        return {"api_key": "fixture", "base_url": "https://provider.invalid/v1",
                "model": "fixture-model", "provider": "fixture", "source": "fixture"}

    async def provider(request):
        nonlocal provider_calls
        provider_calls += 1
        body = {"title": "scope fixture 产品说明", "direct_answer": "scope fixture 提供产品能力甲。",
                "sections": [
                    {"type": "definition", "heading": "定义与背景",
                     "body": "产品能力甲。产品能力乙。产品能力丙。"},
                    {"type": "faq", "heading": "常见问题", "items": [
                        {"q": "能力是什么？", "a": "产品能力甲。"},
                        {"q": "资料来源？", "a": "公开资料甲、公开资料乙和公开资料丙。"}]},
                    {"type": "conclusion", "heading": "结论与建议",
                     "body": "scope fixture 可基于三项公开资料进一步人工核对。"}],
                "used_fact_ids": [80, 81, 82], "disclaimer": "需人工审核后使用",
                "updated_at": "2026-10-11"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]})

    def client_factory(*_args, **kwargs):
        return original_client(timeout=kwargs.get("timeout"), transport=httpx.MockTransport(provider))

    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            async with sessions() as db:
                task = await db.get(GeoContentTask, 50)
                task.brief = {"industry": "工业", "audience": "采购", "intent": "recommend",
                              "content_type": "answer_guide", "cta": "人工咨询"}
                for ident, value in ((80, "产品能力甲"), (81, "产品能力乙"), (82, "产品能力丙")):
                    db.add(GeoFact(id=ident, tenant_id=1, business_id=20,
                        title=f"公开资料{ident}", statement=value, fact_type="product",
                        source_name=f"公开资料{ident}", source_url=f"https://facts.example/{ident}",
                        trust_level="verified", status="active", meta={}))
                    db.add(GeoTaskFact(task_id=50, fact_id=ident, sort_order=ident - 80))
                await db.commit()
            key = core.scope("geo", 1, 10)
            async with sessions() as db:
                basis = await live_basis(db, 1, 10, ["content_master_draft", "periodic_workflow"])
                value = configuration(basis)
                value["operations"] = ["content_master_draft", "periodic_workflow"]
                value["targets"] = [
                    *basis["targets_by_operation"]["content_master_draft"],
                    *basis["targets_by_operation"]["periodic_workflow"],
                ]
                configured, _, _ = await core.configure_project(db, key, Configure(
                    tenant_id=1, request_id=uuid4(), expected_version=0,
                    configuration=value), 7)
                started, _, _ = await core.control_project(db, key, Control(
                    tenant_id=1, request_id=uuid4(), expected_version=configured["version"], action="start"), 7)
                await db.commit()

            @asynccontextmanager
            async def factory(*_args, **_kwargs):
                async with sessions() as db:
                    yield db

            async def run_child(job_id, tenant_id):
                with patch("app.database.async_session_factory", factory):
                    await async_jobs._run_owned_job(job_id, tenant_id=tenant_id)

            from app.geo.content import async_jobs
            monkeypatch.setattr(automation_routes, "async_session_factory", factory)
            monkeypatch.setattr(automation_routes.async_jobs, "run_job_in_background", run_child)
            monkeypatch.setattr("app.geo.project_workflows.async_session_factory", factory)
            monkeypatch.setattr("app.geo.content.ai_settings.resolve_llm_credentials", credentials)
            monkeypatch.setattr("app.ai.deepseek.httpx.AsyncClient", client_factory)
            await automation_routes.run_automation(key, str(started["current_run_id"]))
            # The first step creates an article, so it is no longer present in
            # the live candidate basis. The pending periodic target must still
            # validate and run without revalidating the completed target.
            await automation_routes.run_automation(key, str(started["current_run_id"]))
            for _ in range(50):
                async with sessions() as db:
                    observed = await core.read_run(db, key, started["current_run_id"])
                    if observed["steps"][1]["status"] != "running":
                        break
                await asyncio.sleep(0.02)
            async with sessions() as db:
                run = await core.read_run(db, key, started["current_run_id"])
                step = run["steps"][0]
                job = await db.scalar(select(GeoAsyncJob).where(
                    GeoAsyncJob.kind == async_jobs.KIND_GENERATE,
                    GeoAsyncJob.ref_id == 50))
                assert step["status"] == "succeeded", {"step": step, "job_error": job.error if job else None}
                assert len(step["calls"]) == provider_calls >= 1
                assert all(call["fee_state"] == "unknown_charge" for call in step["calls"])
                article = await db.scalar(select(GeoArticleVersion).where(
                    GeoArticleVersion.task_id == 50))
                assert article is not None and article.version_no == 1
                task = await db.get(GeoContentTask, 50)
                assert task.review_status == "none" and task.status == "editing"
                assert run["steps"][1]["status"] == "succeeded", run["steps"]
    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["prompt", "advisor"])
def test_live_source_or_advisor_change_after_response_blocks_second_call_and_snapshot(monkeypatch, mutation):
    provider_calls = 0
    original_client = httpx.AsyncClient

    async def credentials(_session, _tenant_id):
        return {"api_key": "fixture", "base_url": "https://provider.invalid/v1",
                "model": "fixture-model", "provider": "fixture", "source": "fixture"}

    async def scenario():
        nonlocal provider_calls
        async with database() as sessions:
            await foundation(sessions)
            key, started = await configure_and_start(sessions)

            async def provider(request):
                nonlocal provider_calls
                provider_calls += 1
                async with sessions() as db:
                    if mutation == "prompt":
                        (await db.get(GeoPrompt, 40)).question = "changed after provider response"
                    else:
                        (await db.get(User, 7)).is_active = False
                    await db.commit()
                body = {"raw_text": "返回成功也必须重新核对实时来源。"}
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]})

            def client_factory(*_args, **kwargs):
                return original_client(timeout=kwargs.get("timeout"), transport=httpx.MockTransport(provider))

            @asynccontextmanager
            async def factory(*_args, **_kwargs):
                async with sessions() as db:
                    yield db

            @asynccontextmanager
            async def execution_lock(_run_id):
                yield True

            async def ai_setting(_session, _tenant_id):
                return SimpleNamespace(monitoring_stance="hybrid")

            monkeypatch.setattr(automation_routes, "async_session_factory", factory)
            monkeypatch.setattr("app.geo.content.patrol.patrol_execution_lock", execution_lock)
            monkeypatch.setattr("app.geo.content.ai_settings.resolve_llm_credentials", credentials)
            monkeypatch.setattr("app.geo.content.ai_settings.ensure_ai_setting", ai_setting)
            monkeypatch.setattr("app.ai.deepseek.httpx.AsyncClient", client_factory)
            await automation_routes.run_automation(key, str(started["current_run_id"]))
            async with sessions() as db:
                run = await core.read_run(db, key, started["current_run_id"])
                assert run["steps"][0]["status"] == "blocked"
                assert len(run["steps"][0]["calls"]) == 1
                assert run["steps"][0]["calls"][0]["fee_state"] == "unknown_charge"
                assert await db.scalar(select(GeoAnswerSnapshot).where(
                    GeoAnswerSnapshot.tenant_id == 1,
                    GeoAnswerSnapshot.prompt_id == 40,
                    GeoAnswerSnapshot.patrol_run_id.is_not(None))) is None
    asyncio.run(scenario())
    assert provider_calls == 1
