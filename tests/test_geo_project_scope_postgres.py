"""Project ownership and report isolation on owned PostgreSQL schemas only."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime
import os
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import text, select, func
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.schema import CreateTable

from app.models import (Tenant, GeoProject, GeoOptimizationBusiness, GeoOptimizationUnit, GeoPrompt,
                        GeoContentTask, GeoAnswerSnapshot, GeoTrackingEngine, GeoActionTicket, GeoArticleVersion,
                        GeoTaskFact, GeoFact, GeoPublication, GeoChannelVariant, TenantModule)
from app.models.user import User
from app.models.role import Role
from app.geo.project_scope import set_binding, project_scope, binding
from app.geo.content.report_routes import _evidence

pytestmark = pytest.mark.skipif(not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated PostgreSQL")


@asynccontextmanager
async def database():
    url = make_url(os.environ["GEO_TEST_POSTGRES_URL"])
    assert url.drivername == "postgresql+asyncpg" and url.host in {"127.0.0.1", "localhost"}
    assert (url.database, url.username) in {("geo_ci", "geo_ci"), ("seo_workflow_test", "seo_workflow_tester")} and not url.query
    schema = "geo_scope_test_" + uuid4().hex
    engine = create_async_engine(url, pool_size=10, connect_args={"server_settings": {
        "search_path": schema, "lock_timeout": "5000", "statement_timeout": "15000"}},
        execution_options={"schema_translate_map": {"public": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            for model in (Tenant, GeoProject, GeoOptimizationBusiness, GeoOptimizationUnit,
                          GeoPrompt, GeoContentTask, GeoAnswerSnapshot, GeoTrackingEngine, GeoActionTicket,
                          GeoArticleVersion, GeoTaskFact, GeoFact, GeoPublication, GeoChannelVariant, TenantModule, Role, User):
                await connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
            await connection.execute(text("""CREATE TABLE demo_tenant_bindings (tenant_id bigint, demo_tenant_id bigint,
                dataset_key varchar(64), dataset_version varchar(40), status varchar(16), version integer)"""))
        async with sessions() as db:
            db.add_all([Tenant(id=1, name="scope fixture"), Tenant(id=2, name="other fixture")])
            db.add_all([TenantModule(id=1, tenant_id=1, module_code="geo", status="active"),
                Role(id=5, name="fixture advisor", permissions={"geo.assets": "edit", "geo.content": "edit"}),
                User(id=7, username="scope fixture advisor", role_id=5, password_hash="unused", is_active=True)])
            for ident, tenant in ((10, 1), (11, 1), (12, 2)):
                db.add(GeoProject(id=ident, tenant_id=tenant, tenant_module_id=1, name=f"project {ident}",
                    primary_domain=f"p{ident}.example", canonical_domain=f"p{ident}.example", status="active"))
            for ident, tenant in ((20, 1), (21, 1), (22, 2)):
                db.add(GeoOptimizationBusiness(id=ident, tenant_id=tenant, name=f"business {ident}"))
                db.add(GeoOptimizationUnit(id=ident+10, tenant_id=tenant, business_id=ident, name="unit"))
                db.add(GeoPrompt(id=ident+20, tenant_id=tenant, unit_id=ident+10, question=f"scope question {ident}"))
                db.add(GeoContentTask(id=ident+30, tenant_id=tenant, prompt_id=ident+20, business_id=ident,
                    title=f"task {ident}", status="draft"))
                db.add(GeoAnswerSnapshot(id=ident+40, tenant_id=tenant, prompt_id=ident+20, engine="deepseek",
                    captured_at=datetime(2026, 10, 1), raw_text=f"answer {ident}", sample_mode="manual", simulated=False))
            await db.commit()
        yield sessions
    finally:
        try:
            if created:
                assert schema.startswith("geo_scope_test_") and len(schema) == len("geo_scope_test_")+32
                async with engine.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            await engine.dispose()


def test_binding_keeps_existing_settings_and_rejects_foreign_and_stale_updates():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                p = await db.get(GeoProject, 10)
                p.project_settings = {"geo_report_template": [{"key": "custom"}]}
                await db.commit()
            async with sessions() as db:
                result = await set_binding(db, 1, 10, [20], 0, 7)
                await db.commit()
                assert result["revision"] == 1
                assert (await db.get(GeoProject, 10)).project_settings["geo_report_template"]
            for project, ids, revision, status in ((10, [22], 1, 404), (10, [21], 0, 409), (11, [20], 0, 409), (12, [21], 0, 404)):
                async with sessions() as db:
                    with pytest.raises(HTTPException) as error:
                        await set_binding(db, 1, project, ids, revision, 7)
                    assert error.value.status_code == status
    asyncio.run(run())


def test_project_cycles_are_idempotent_resume_on_evidence_and_stop_on_revocation():
    from app.geo.project_workflows import save_plan, refresh_project
    from app.geo.work_execution import freeze_samples
    from datetime import timezone
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                await set_binding(db, 1, 10, [20], 0, 7)
                await save_plan(db, 1, 10, dict(enabled=True, status="active", prompt_ids=[40],
                    interval_days=7, advisor_user_id=7), 0, 7)
                await db.commit()
            now = datetime(2026, 10, 9, tzinfo=timezone.utc)
            await asyncio.gather(*(refresh_project(10, session_factory=sessions, now=now) for _ in range(6)))
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(GeoActionTicket)) == 1
                row = await db.scalar(select(GeoActionTicket))
                state = row.progress["project_workflow"]
                assert state["phase"] == "baseline" and state["sequence"] == 1
                notice = state["notice_id"]
                snapshot = await db.get(GeoAnswerSnapshot, 60)
                snapshot.sample_mode = "openai_compat"
                snapshot.note = "method=unprimed_json_v2 analysis=completed"
                row.content_task_id = 50
                row.baseline_snapshot = {"prompt_id": 40, "samples": freeze_samples([snapshot])}
                await db.commit()
            await refresh_project(10, session_factory=sessions, now=now)
            async with sessions() as db:
                row = await db.scalar(select(GeoActionTicket))
                assert row.progress["project_workflow"]["phase"] == "materials"
                assert row.progress["project_workflow"]["notice_id"] != notice
                second = row.progress["project_workflow"]["notice_id"]
            await refresh_project(10, session_factory=sessions, now=now)
            async with sessions() as db:
                row = await db.scalar(select(GeoActionTicket))
                assert row.progress["project_workflow"]["notice_id"] == second
                (await db.get(User, 7)).is_active = False
                await db.commit()
            await refresh_project(10, session_factory=sessions, now=now)
            async with sessions() as db:
                assert (await db.get(GeoProject, 10)).project_settings["geo_workflow_blocker"] == "advisor_assignment_unavailable"
                assert await db.scalar(select(func.count()).select_from(GeoActionTicket)) == 1
    asyncio.run(run())


def test_concurrent_two_projects_cannot_claim_same_business():
    async def run():
        async with database() as sessions:
            async def update(project):
                async with sessions() as db:
                    result = await set_binding(db, 1, project, [20], 0, 7)
                    await db.commit()
                    return result
            results = await asyncio.gather(update(10), update(11), return_exceptions=True)
            assert sum(isinstance(r, dict) for r in results) == 1
            assert sum(isinstance(r, HTTPException) and r.status_code == 409 for r in results) == 1
    asyncio.run(run())


def test_legacy_ticket_reads_keep_project_scope_and_paused_plan_blocks_legacy_write():
    from app.geo.project_workflows import save_plan, refresh_project, ensure_ticket_project
    from app.geo.routes import build_ticket_execution_plan
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                await set_binding(db, 1, 10, [20], 0, 7)
                await save_plan(db, 1, 10, dict(enabled=True, status="active", prompt_ids=[40],
                    interval_days=7, advisor_user_id=7), 0, 7)
                await db.commit()
            await refresh_project(10, session_factory=sessions)
            async with sessions() as db:
                row = await db.scalar(select(GeoActionTicket))
                plan = await build_ticket_execution_plan(db, row, 1)
                assert {p['id'] for p in plan['prompts']} == {40}
                assert {t['id'] for t in plan['tasks']} == {50}
                with pytest.raises(HTTPException) as error:
                    await set_binding(db, 1, 10, [], 1, 7)
                assert error.value.status_code == 409
                await db.rollback()
            async with sessions() as db:
                await save_plan(db, 1, 10, dict(enabled=True, status="paused", prompt_ids=[40],
                    interval_days=7, advisor_user_id=7), 1, 7)
                await db.commit()
            async with sessions() as db:
                row = await db.scalar(select(GeoActionTicket))
                with pytest.raises(HTTPException) as error:
                    await ensure_ticket_project(db, row, 1, 40)
                assert error.value.status_code == 409
    asyncio.run(run())


def test_empty_project_never_falls_back_and_scoped_report_excludes_other_projects(monkeypatch):
    from app.geo.content import report_routes
    from types import SimpleNamespace
    async def publications(*args):
        return [SimpleNamespace(id=70, task_id=50), SimpleNamespace(id=71, task_id=51), SimpleNamespace(id=72, task_id=52)]
    monkeypatch.setattr(report_routes, "load_tenant_publications", publications)
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                empty = await _evidence(db, 1, None, date(2026, 10, 1), date(2026, 10, 9), 10)
                assert not empty["prompts"] and not empty["snapshots"] and not empty["publications"]
                await set_binding(db, 1, 10, [20], 0, 7)
                await db.commit()
            async with sessions() as db:
                data = await _evidence(db, 1, None, date(2026, 10, 1), date(2026, 10, 9), 10)
                assert set(data["prompts"]) == {40}
                assert [s.id for s in data["snapshots"]] == [60]
                assert [p.id for p in data["publications"]] == [70]
                assert data["data_scope"] == {"kind": "project", "project_id": 10, "business_ids": [20]}
                with pytest.raises(HTTPException) as error:
                    await project_scope(db, 1, 10, 21)
                assert error.value.status_code == 404
    asyncio.run(run())
