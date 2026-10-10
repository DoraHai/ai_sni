"""Actual HTTP and PostgreSQL aggregation; all customers are isolated fixtures."""
import asyncio
from copy import deepcopy
import os
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select, text

from app import seo_onsite_ai as ai, seo_onsite_ai_health as health
from app.api import seo_onsite_ai as api
from app.models.module_workspace import SeoSite
from app.models.seo_cockpit import SeoTask
from test_seo_onsite_ai_postgres import fixture, request
from test_seo_workflow_postgres import ADVISOR
from test_seo_onsite_ai_health import ADMIN

pytestmark = pytest.mark.skipif(not os.getenv("SEO_WORKFLOW_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")


@pytest.mark.parametrize("protocol", [None, "wrong"])
def test_protocol_rejection_preserves_task_site_quota_and_never_calls(monkeypatch, protocol):
    provider = AsyncMock(side_effect=AssertionError("No supplier permitted"))
    monkeypatch.setattr(ai, "generate", provider)
    async def run():
        async with fixture() as (sessions, task):
            async with sessions() as db:
                before_task = deepcopy((await db.get(SeoTask, task["id"])).params)
                before_site = deepcopy((await db.get(SeoSite, 2)).site_settings)
            statements = []
            engine = sessions.kw["bind"].sync_engine
            def observed(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)
            event.listen(engine, "before_cursor_execute", observed)
            app = FastAPI()
            app.include_router(api.router, prefix="/api/v1/seo")
            async def db_dep():
                async with sessions() as db:
                    yield db
            app.dependency_overrides[api.get_seo_session] = db_dep
            app.dependency_overrides[api.require_seo_scoped_auth] = lambda: ADVISOR
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(f"/api/v1/seo/workbench/onsite-tasks/{task['id']}/ai-proposal",
                    json=request(task).model_dump(mode="json"),
                    headers={} if protocol is None else {"X-Snipers-Onsite-Protocol": protocol})
            assert response.status_code == 409 and not statements
            event.remove(engine, "before_cursor_execute", observed)
            async with sessions() as db:
                assert (await db.get(SeoTask, task["id"])).params == before_task
                assert (await db.get(SeoSite, 2)).site_settings == before_site
            provider.assert_not_called()
    asyncio.run(run())


def test_global_queue_counts_all_requests_and_reads_without_mutation(monkeypatch):
    provider = AsyncMock(side_effect=AssertionError("No supplier permitted"))
    monkeypatch.setattr(ai, "generate", provider)
    async def run():
        async with fixture() as (sessions, task):
            async with sessions() as db:
                row = await db.get(SeoTask, task["id"])
                row.params = {**row.params, "onsite_ai_requests": {
                    "old": {"state": "unknown", "prompt": "PRIVATE-CUSTOMER-PROMPT"},
                    "new": {"state": "queued", "queued_at": "2026-10-11T08:00:00+08:00"},
                    "done": {"state": "ready"}}}
                for ident, action, schema, runs in [
                    (101, "onsite_optimization", 1, {"a": {"state": "queued", "queued_at": "2026-10-10T23:00:00Z"},
                        "b": {"state": "running", "started_at": "2026-10-11T00:30:00Z"},
                        "c": {"state": "running"}}),
                    (102, "content_workflow", 1, {"ignored": {"state": "queued"}}),
                    (103, "onsite_optimization", 2, {"ignored": {"state": "unknown"}}),
                    (104, "onsite_optimization", 1, {}),
                ]:
                    db.add(SeoTask(id=ident, tenant_id=99, site_id=99, module="seo", action_type=action,
                        title="PRIVATE-CUSTOMER-TITLE", params={"onsite": {"schema": schema}, "onsite_ai_requests": runs},
                        status="open", created_by="fixture", assignee_role="advisor", baseline={}))
                await db.commit()
                before = {r.id: deepcopy(r.params) for r in await db.scalars(select(SeoTask))}
            app = FastAPI()
            app.include_router(api.router, prefix="/api/v1/seo")
            app.dependency_overrides[api.require_auth] = lambda: ADMIN
            async def db_dep():
                async with sessions() as db:
                    await db.execute(text("SET TRANSACTION READ ONLY"))
                    yield db
            app.dependency_overrides[api.get_primary_session] = db_dep
            old_tick = health.worker_status()["last_tick_at"]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/v1/seo/workbench/onsite-ai/health")
                again = await client.get("/api/v1/seo/workbench/onsite-ai/health")
            assert response.status_code == again.status_code == 200
            value = response.json()
            assert set(value) == {"schema", "module", "observed_at", "worker", "queue"}
            assert value["schema"] == 1 and value["module"] == "seo"
            assert value["queue"] == {"state": "available", "queued": 2, "running": 2, "unknown": 1,
                "oldest_queued_at": "2026-10-10T23:00:00+00:00", "oldest_running_at": "2026-10-11T00:30:00+00:00"}
            assert value["worker"]["scope"] == "this_process"
            assert value["worker"]["last_tick_at"] == old_tick == again.json()["worker"]["last_tick_at"]
            assert response.headers["cache-control"] == "no-store"
            assert "PRIVATE" not in response.text and 'tenant_id' not in response.text
            async with sessions() as db:
                assert {r.id: r.params for r in await db.scalars(select(SeoTask))} == before
            provider.assert_not_called()
    asyncio.run(run())


@pytest.mark.parametrize("broken", [False, True])
def test_empty_queue_is_zero_but_missing_structure_is_unavailable(broken):
    async def run():
        async with fixture() as (sessions, task):
            async with sessions() as db:
                if broken:
                    await db.execute(text("DROP TABLE seo_tasks"))
                    await db.commit()
                response = await api.onsite_ai_health(ADMIN, db)
                if broken:
                    import json
                    assert response.status_code == 200
                    assert json.loads(response.body)["queue"] == health.unavailable_queue()
                else:
                    import json
                    assert json.loads(response.body)["queue"] == {"state": "available", "queued": 0, "running": 0, "unknown": 0,
                        "oldest_queued_at": None, "oldest_running_at": None}
    asyncio.run(run())


def test_health_real_jwt_checks_current_role_and_user_on_full_seo_router():
    import jwt
    from app.api.seo import router as seo_router
    from app.models.user import User
    from app.models.role import Role
    from app.security import auth
    async def run():
        async with fixture() as (sessions, task):
            async with sessions() as db:
                db.add(Role(id=92, name="health-global", permissions=ADMIN.permissions))
                db.add(User(id=91, username="health-global", password_hash="unused", role_id=92, is_active=True))
                await db.commit()
            app = FastAPI()
            app.include_router(seo_router)
            async def db_dep():
                async with sessions() as db:
                    await db.execute(text("SET TRANSACTION READ ONLY"))
                    yield db
            app.dependency_overrides[api.get_primary_session] = db_dep
            token = jwt.encode({"sub": "91"}, auth._jwt_secret(), algorithm=auth.JWT_ALG)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                    headers={"Authorization": "Bearer " + token}) as client:
                path = "/api/v1/seo/workbench/onsite-ai/health"
                assert (await client.get(path)).status_code == 200
                async with sessions() as db:
                    (await db.get(Role, 92)).permissions = {"settings.accounts": "edit"}
                    await db.commit()
                assert (await client.get(path)).status_code == 403
                async with sessions() as db:
                    (await db.get(User, 91)).is_active = False
                    await db.commit()
                assert (await client.get(path)).status_code == 401
    asyncio.run(run())


def test_invalid_historical_queue_timestamp_is_not_guessed_or_reported_empty():
    async def run():
        async with fixture() as (sessions, task):
            async with sessions() as db:
                row = await db.get(SeoTask, task["id"])
                row.params = {**row.params, "onsite_ai_requests": {
                    "bad": {"state": "queued", "queued_at": "PRIVATE-INVALID-TIME"}}}
                await db.commit()
                result = await api.onsite_ai_health(ADMIN, db)
                assert result.status_code == 503 and b"PRIVATE" not in result.body
    asyncio.run(run())
