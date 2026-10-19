"""Real SQL object/assignment tests; no production settings or external calls.

The optional PostgreSQL cases use only an allowlisted loopback test database
and per-test owned schemas, following test_geo_project_scope_postgres.py.
"""
import asyncio
from contextlib import asynccontextmanager
import os
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
import httpx
import pytest
from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.schema import CreateTable
from starlette.requests import Request as StarletteRequest

from app.database import Base
from app.models import (GeoActionTicket, GeoArticleVersion, GeoChannelVariant,
                        GeoContentTask, GeoFact, GeoOptimizationBusiness,
                        GeoOptimizationUnit, GeoProject, GeoPrompt,
                        GeoVisibilityPatrolSettings, Role, Tenant, TenantModule, User)
from app.security.advisor_scope import AdvisorScope
from app.security.auth import AuthContext
from app.security.advisor_write_objects import check_write_objects, ensure_advisor_assignment


@compiles(JSONB, "sqlite")
def _sqlite_json(_type, _compiler, **_kw):
    return "JSON"


PREFIX = "/api/v1/geo"
TABLES = [m.__table__ for m in (
    Tenant, TenantModule, Role, User, GeoProject, GeoOptimizationBusiness,
    GeoOptimizationUnit, GeoPrompt, GeoContentTask, GeoFact, GeoArticleVersion,
    GeoChannelVariant, GeoActionTicket, GeoVisibilityPatrolSettings)]
BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(
    not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated loopback PostgreSQL"))]


def context():
    return AuthContext(1, "fixture-advisor", "顾问", 10,
                       permissions={"geo.assets": "edit", "geo.content": "edit"},
                       advisor_scope=AdvisorScope(frozenset({10, 20}), 10, 101))


def request_for(template, *, method="PATCH", path=None, query="tenant_id=10", headers=None, raw=b""):
    sent = False

    async def receive():
        nonlocal sent
        assert not sent
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    return StarletteRequest({
        "type": "http", "method": method, "path": PREFIX + template,
        "query_string": query.encode(), "headers": headers or [],
        "path_params": path or {}, "route": SimpleNamespace(path=PREFIX + template),
    }, receive)


def rule_for(template):
    # Interface contract with A; no dependency on the write whitelist module.
    return SimpleNamespace(template=PREFIX + template, assignment="project")


@asynccontextmanager
async def sandbox(tmp_path, backend="sqlite"):
    schema = None
    if backend == "postgres":
        url = make_url(os.environ["GEO_TEST_POSTGRES_URL"])
        assert url.drivername == "postgresql+asyncpg" and url.host in {"localhost", "127.0.0.1"}
        assert (url.database, url.username) in {("geo_ci", "geo_ci"), ("seo_workflow_test", "seo_workflow_tester")}
        assert not url.query
        schema = "geo_write_objects_" + uuid4().hex
        engine = create_async_engine(url, connect_args={"server_settings": {
            "search_path": schema, "statement_timeout": "15000"}},
            execution_options={"schema_translate_map": {"public": schema}})
    else:
        engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "objects.sqlite"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            if schema:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                for table in TABLES:
                    await connection.execute(CreateTable(table, include_foreign_key_constraints=[]))
            else:
                await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=TABLES))
        async with factory() as session:
            session.add_all([
                Role(id=1, name="顾问", is_system=False, permissions={"geo.assets": "edit", "geo.content": "edit"}),
                User(id=1, username="fixture-advisor", role_id=1, tenant_id=10, password_hash="unused", is_active=True),
            ])
            for tid in (10, 20, 30):
                session.add(Tenant(id=tid, name=f"tenant-{tid}"))
                session.add(TenantModule(id=tid, tenant_id=tid, module_code="geo", status="active"))
            for ident, tid, business in [(100, 10, 1), (200, 20, 2), (300, 30, 3), (400, 10, 4)]:
                session.add(GeoProject(id=ident, tenant_id=tid, tenant_module_id=tid,
                    name=f"project-{ident}", primary_domain=f"p{ident}.example", canonical_domain=f"p{ident}.example",
                    status="active", project_settings={
                        "geo_business_scope": {"revision": 1, "business_ids": [business]},
                        "geo_service_plan": {"advisor_user_id": 1, "enabled": False, "status": "paused"}}))
            for ident, tid in [(1, 10), (2, 20), (3, 30), (4, 10), (5, 10)]:
                session.add(GeoOptimizationBusiness(id=ident, tenant_id=tid, name=f"business-{ident}"))
                session.add(GeoOptimizationUnit(id=ident, tenant_id=tid, business_id=ident, name=f"unit-{ident}"))
                session.add(GeoPrompt(id=ident, tenant_id=tid, unit_id=ident, question=f"question-{ident}"))
                session.add(GeoFact(id=ident, tenant_id=tid, business_id=ident, title=f"fact-{ident}",
                                    statement="fixture statement", source_name="fixture source"))
                session.add(GeoContentTask(id=ident, tenant_id=tid, prompt_id=ident, business_id=ident,
                                           title=f"task-{ident}", status="draft"))
                session.add(GeoArticleVersion(id=ident, task_id=ident, title="article", body_markdown="body"))
                session.add(GeoChannelVariant(id=ident, task_id=ident, article_version_id=ident,
                                              channel="website", title="variant", body_markdown="body"))
            # Same numeric ID, opposite owner: content task mapping must win.
            session.add_all([
                GeoActionTicket(id=1, tenant_id=20, title="opposite owner", action="fixture", advice_code="fixture"),
                GeoActionTicket(id=2, tenant_id=10, title="opposite owner", action="fixture", advice_code="fixture"),
                GeoPrompt(id=6, tenant_id=10, unit_id=None, question="unscoped prompt"),
                GeoFact(id=6, tenant_id=10, business_id=None, title="unscoped fact", statement="fixture", source_name="fixture"),
            ])
            await session.commit()
        yield factory
    finally:
        if schema:
            assert schema.startswith("geo_write_objects_") and len(schema) == 50
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def validate(session, template, body, *, method="PATCH", path=None, query="tenant_id=10"):
    request = request_for(template, method=method, path=path, query=query)
    await check_write_objects(session, context(), request, body, rule_for(template))
    await ensure_advisor_assignment(session, context(), request, body, rule_for(template))
    assert not session.new and not session.dirty and not session.deleted


SUCCESS_CASES = [
    ("POST", "/facts", {}, {"tenant_id": 10, "business_id": 1, "statement": "manual fact"}),
    ("PATCH", "/facts/{fact_id}", {"fact_id": 1}, {"title": "manual fact"}),
    ("POST", "/prompts", {}, {"tenant_id": 10, "unit_id": 1, "question": "manual question"}),
    ("PATCH", "/prompts/{prompt_id}", {"prompt_id": 1}, {"question": "edited question"}),
    ("PATCH", "/optimization-businesses/{business_id}", {"business_id": 1}, {"description": "manual business"}),
    ("POST", "/optimization-units", {}, {"tenant_id": 10, "business_id": 1, "name": "manual unit"}),
    ("PATCH", "/optimization-units/{unit_id}", {"unit_id": 1}, {"description": "manual unit"}),
    ("POST", "/content-tasks", {}, {"tenant_id": 10, "prompt_id": 1, "fact_ids": [1]}),
    ("PATCH", "/content-tasks/{task_id}", {"task_id": 1}, {"brief": {"references": [{"fact_ids": [1]}]}}),
    ("PUT", "/content-tasks/{task_id}/facts", {"task_id": 1}, {"fact_ids": [1]}),
    ("PUT", "/content-tasks/{task_id}/article", {"task_id": 1}, {"expected_article_id": 1, "body_markdown": "manual"}),
    ("PUT", "/content-tasks/{task_id}/article", {"task_id": 1}, {"expected_article_id": None, "body_markdown": "first"}),
    ("PATCH", "/content-tasks/{task_id}/variants/{channel}", {"task_id": 1, "channel": "website"}, {"title": "manual variant"}),
]


@pytest.mark.parametrize("method,template,path,body", SUCCESS_CASES)
@pytest.mark.parametrize("backend", BACKENDS)
def test_each_manual_route_object_contract(tmp_path, method, template, path, body, backend):
    async def run():
        async with sandbox(tmp_path, backend) as factory, factory() as session:
            await validate(session, template, body, method=method, path=path)
    asyncio.run(run())


@pytest.mark.parametrize("key", ["business_id", "unit_id", "prompt_id", "fact_id", "content_task_id",
                                 "article_id", "article_version_id", "variant_id", "project_id"])
@pytest.mark.parametrize("foreign", [2, 3])
def test_every_object_type_checks_selected_tenant(tmp_path, key, foreign):
    async def run():
        ident = foreign * 100 if key == "project_id" else foreign
        async with sandbox(tmp_path) as factory, factory() as session:
            with pytest.raises(HTTPException) as denied:
                await validate(session, "/content-tasks/{task_id}",
                               {"brief": {"nested": [{key: ident}]}}, path={"task_id": 1})
            assert denied.value.status_code == 403
            assert denied.value.detail["code"] == "ADVISOR_TENANT_NOT_GRANTED"
    asyncio.run(run())


@pytest.mark.parametrize("body", [
    {"brief": {"fact_ids": [1, 2]}}, {"brief": [{"prompt_ids": [1, 3]}]},
    {"brief": {"mystery_id": None}}, {"brief": {"mystery_ids": []}},
    {"brief": {"owner_user_id": 1}}, {"brief": {"id": 1}},
    {"brief": {"businessId": 2}}, {"brief": {"fact_ids": "1,2"}},
])
def test_nested_arrays_and_unknown_fields_fail_closed(tmp_path, body):
    async def run():
        async with sandbox(tmp_path) as factory, factory() as session:
            with pytest.raises(HTTPException) as denied:
                await validate(session, "/content-tasks/{task_id}", body, path={"task_id": 1})
            assert denied.value.status_code == 403
    asyncio.run(run())


@pytest.mark.parametrize("query,status", [
    ("tenant_id=10&tenant_id=20", 403), ("tenant_id=10&business_id=3", 403),
    ("tenant_id=10&fact_ids=1&fact_ids=2", 403), ("tenant_id=10&project_id=400", 403),
    ("tenant_id=10&unknown_ids=1", 403), ("tenant_id=10&fact_id=999", 404),
    ("tenant_id=10&fact_id=true", 422),
])
def test_all_query_values_checked(tmp_path, query, status):
    async def run():
        async with sandbox(tmp_path) as factory, factory() as session:
            with pytest.raises(HTTPException) as denied:
                await validate(session, "/content-tasks/{task_id}", {}, path={"task_id": 1}, query=query)
            assert denied.value.status_code == status
    asyncio.run(run())


@pytest.mark.parametrize("body", [{"fact_ids": [4]}, {"fact_ids": [6]}, {"prompt_id": 6}, {"business_id": 5}])
def test_same_tenant_other_project_and_unscoped_objects_rejected(tmp_path, body):
    async def run():
        async with sandbox(tmp_path) as factory, factory() as session:
            with pytest.raises(HTTPException) as denied:
                await validate(session, "/content-tasks/{task_id}/facts", body, path={"task_id": 1}, method="PUT")
            assert denied.value.detail["code"] == "ADVISOR_ASSIGNMENT_REQUIRED"
    asyncio.run(run())


@pytest.mark.parametrize("model,ident,values", [
    (GeoProject, 100, {"status": "archived"}),
    (GeoProject, 100, {"project_settings": {"geo_business_scope": {"business_ids": [1]},
                                          "geo_service_plan": {"advisor_user_id": 99}}}),
    (User, 1, {"is_active": False}), (User, 1, {"tenant_id": 30}),
    (Role, 1, {"permissions": {"geo.assets": "edit", "geo.content": "view"}}),
])
def test_assignment_reloads_after_changes(tmp_path, model, ident, values):
    async def run():
        async with sandbox(tmp_path) as factory, factory() as session:
            await validate(session, "/facts/{fact_id}", {}, path={"fact_id": 1})
            # End the read snapshot; the next request must query current rows.
            await session.rollback()
            async with factory() as admin:
                await admin.execute(update(model).where(model.id == ident).values(**values))
                await admin.commit()
            with pytest.raises(HTTPException) as denied:
                await validate(session, "/facts/{fact_id}", {}, path={"fact_id": 1})
            assert denied.value.detail["code"] == "ADVISOR_ASSIGNMENT_REQUIRED"
    asyncio.run(run())


@pytest.mark.parametrize("template,body", [
    ("/facts", {"title": "unscoped"}), ("/prompts", {"question": "unscoped"}),
    ("/optimization-units", {"name": "unscoped"}), ("/content-tasks", {"title": "unscoped"}),
    ("/optimization-businesses", {"name": "new unbound business"}),
    ("/facts/import", {"business_id": 1}), ("/prompts/import", {"unit_id": 1}),
    ("/prompts/import-csv", {"unit_id": 1}),
])
def test_query_scope_cannot_authorize_unbound_creation_or_import(tmp_path, template, body):
    async def run():
        async with sandbox(tmp_path) as factory, factory() as session:
            with pytest.raises(HTTPException) as denied:
                await validate(session, template, body, method="POST", query="tenant_id=10&business_id=1&project_id=100")
            assert denied.value.detail["code"] == "ADVISOR_ASSIGNMENT_REQUIRED"
    asyncio.run(run())


@pytest.mark.parametrize("trigger", ["patrol", "cycle"])
@pytest.mark.parametrize("template,path,body", [
    ("/facts", {}, {"business_id": 1}), ("/prompts", {}, {"unit_id": 1}),
    ("/facts/{fact_id}", {"fact_id": 1}, {}), ("/prompts/{prompt_id}", {"prompt_id": 1}, {}),
])
def test_enabled_execution_chains_allow_assigned_preparation(tmp_path, trigger, template, path, body):
    async def run():
        async with sandbox(tmp_path) as factory, factory() as session:
            if trigger == "patrol":
                session.add(GeoVisibilityPatrolSettings(tenant_id=10, enabled=True))
            else:
                project = await session.get(GeoProject, 100)
                project.project_settings = {**project.project_settings,
                    "geo_service_plan": {"advisor_user_id": 1, "enabled": True, "status": "active"}}
            await session.commit()
            await validate(session, template, body, method="PATCH" if path else "POST", path=path)
    asyncio.run(run())


def test_child_article_must_belong_to_current_task_and_variant_must_exist(tmp_path):
    async def run():
        async with sandbox(tmp_path) as factory, factory() as session:
            # Another task in the same business/project still cannot supply the
            # optimistic version token for this task.
            session.add(GeoContentTask(id=7, tenant_id=10, business_id=1, prompt_id=1, title="sibling"))
            session.add(GeoArticleVersion(id=7, task_id=7, title="sibling", body_markdown="body"))
            await session.commit()
            for template, path, body, status in [
                ("/content-tasks/{task_id}/article", {"task_id": 1}, {"expected_article_id": 7}, 403),
                ("/content-tasks/{task_id}/variants/{channel}", {"task_id": 1, "channel": "absent"}, {}, 404),
            ]:
                with pytest.raises(HTTPException) as denied:
                    await validate(session, template, body, path=path)
                assert denied.value.status_code == status
    asyncio.run(run())


@pytest.mark.parametrize("template", ["/integration/tasks/{task_id}", "/workbench/onsite-tasks/{task_id}/actions"])
def test_content_task_mapping_cannot_be_reused_for_other_routes(tmp_path, template):
    async def run():
        async with sandbox(tmp_path) as factory, factory() as session:
            with pytest.raises(HTTPException) as denied:
                await validate(session, template, {}, path={"task_id": 1})
            assert denied.value.detail["code"] == "ADVISOR_TENANT_NOT_GRANTED"
    asyncio.run(run())


@pytest.mark.parametrize("model,ident,values", [
    (GeoOptimizationUnit, 1, {"business_id": 2}),
    (GeoContentTask, 1, {"prompt_id": 2}),
    (GeoChannelVariant, 1, {"article_version_id": 2}),
])
def test_implicit_parent_relationships_are_checked(tmp_path, model, ident, values):
    async def run():
        async with sandbox(tmp_path) as factory, factory() as session:
            await session.execute(update(model).where(model.id == ident).values(**values))
            await session.commit()
            template = "/content-tasks/{task_id}/variants/{channel}"
            with pytest.raises(HTTPException) as denied:
                await validate(session, template, {}, path={"task_id": 1, "channel": "website"})
            assert denied.value.status_code == 403
    asyncio.run(run())


@pytest.mark.parametrize("settings", [
    {"geo_business_scope": {"business_ids": "1"}},
    {"geo_business_scope": {"business_ids": [1, 1]}},
    {"geo_business_scope": {"business_ids": [1]}, "geo_service_plan": [1]},
])
def test_malformed_scope_and_assignment_fail_closed(tmp_path, settings):
    async def run():
        async with sandbox(tmp_path) as factory, factory() as session:
            await session.execute(update(GeoProject).where(GeoProject.id == 100).values(project_settings=settings))
            await session.commit()
            with pytest.raises(HTTPException) as denied:
                await validate(session, "/facts/{fact_id}", {}, path={"fact_id": 1})
            assert denied.value.detail["code"] == "ADVISOR_ASSIGNMENT_REQUIRED"
    asyncio.run(run())


@pytest.mark.parametrize("filename,raw,status", [
    ("rows.csv", b"fact_ids\n[1]\n[2]\n", 403),
    ("rows.json", b'[{"business_id":1},{"nested":{"fact_id":3}}]', 403),
    ("rows.csv", b"tenant_id,fact_id\n10,1\n20,1\n", 403),
    ("rows.csv", b"fact_id,fact_id\n1,2\n", 403),
    ("rows.json", b'{"fact_id":2,"fact_id":1}', 403),
    ("rows.json", b'[{"fact_id":999}]', 404),
    ("rows.txt", b'[{"fact_id":1}]', 403),
    ("rows.csv", b'fact_id,meta\n1\n', 403),
    ("rows.csv", b"meta\n{\"unknown_id\":1}\n", 403),
    ("rows.csv", b"fact_ids\n[1]\n", 200),
    ("rows.json", b'[{"fact_ids":[1],"business_id":1}]', 200),
])
def test_every_uploaded_row_checked_and_upload_preserved(tmp_path, filename, raw, status):
    async def run():
        encoded = httpx.Request("POST", "http://test", files={"file": (filename, raw)})
        multipart = encoded.read()
        request = request_for("/facts/import", method="POST",
                              headers=[(k.lower(), v) for k, v in encoded.headers.raw], raw=multipart)
        async with sandbox(tmp_path) as factory, factory() as session:
            if status == 200:
                await check_write_objects(session, context(), request, None, rule_for("/facts/import"))
            else:
                with pytest.raises(HTTPException) as denied:
                    await check_write_objects(session, context(), request, None, rule_for("/facts/import"))
                assert denied.value.status_code == status
            upload = (await request.form())["file"]
            assert await upload.read() == raw
    asyncio.run(run())


@pytest.mark.parametrize("backend", BACKENDS)
def test_http_contract_rejects_before_mutation_and_preserves_body(tmp_path, backend):
    async def run():
        async with sandbox(tmp_path, backend) as factory:
            app = FastAPI()

            @app.patch(PREFIX + "/content-tasks/{task_id}")
            async def write(task_id: int, request: Request):
                body = await request.json()
                async with factory() as session:
                    await check_write_objects(session, context(), request, body, rule_for("/content-tasks/{task_id}"))
                    await ensure_advisor_assignment(session, context(), request, body, rule_for("/content-tasks/{task_id}"))
                    assert await request.json() == body
                    row = await session.get(GeoContentTask, task_id)
                    row.title = body.get("title", row.title)
                    await session.commit()
                    return {"title": row.title}

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                for payload, suffix in [
                    ({"title": "forbidden", "brief": {"fact_ids": [1, 2]}}, ""),
                    ({"title": "forbidden", "brief": {"fact_ids": [1, 4]}}, ""),
                    ({"title": "forbidden"}, "&tenant_id=20"),
                ]:
                    response = await client.patch(PREFIX + "/content-tasks/1?tenant_id=10" + suffix, json=payload)
                    assert response.status_code == 403, response.text
                    async with factory() as session:
                        assert (await session.get(GeoContentTask, 1)).title == "task-1"
                # Content task 2 is foreign even though action ticket 2 is local.
                assert (await client.patch(PREFIX + "/content-tasks/2?tenant_id=10", json={})).status_code == 403
                response = await client.patch(PREFIX + "/content-tasks/1?tenant_id=10", json={"title": "saved"})
                assert response.status_code == 200 and response.json()["title"] == "saved"
                async with factory() as session:
                    assert (await session.get(GeoContentTask, 1)).title == "saved"
    asyncio.run(run())
