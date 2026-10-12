"""Real login/JWT/RBAC coverage for GEO onsite AI delivery.

Only the database dependency and external HTTP transport are replaced.  Auth,
route dependencies, durable jobs and the onsite state machine are production
code.
"""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.database import get_session
from app.geo import ai_client, onsite_jobs, onsite_routes
from app.geo.content import async_jobs
from app.models import GeoActionTicket, GeoAsyncJob, GeoProject
from app.models.role import Role
from app.models.user import User
from app.security.auth import hash_password
from test_geo_onsite_postgres import _add_public_fact, _ai_result, configured, run_owned
from test_geo_project_scope_postgres import database

_AUTH_SPEC = importlib.util.spec_from_file_location(
    "geo_onsite_real_auth_api", Path(__file__).parents[1] / "app" / "api" / "auth.py"
)
assert _AUTH_SPEC and _AUTH_SPEC.loader
auth_api = importlib.util.module_from_spec(_AUTH_SPEC)
_AUTH_SPEC.loader.exec_module(auth_api)

pytestmark = pytest.mark.skipif(
    not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated PostgreSQL"
)
PASSWORD = "Geo-onsite-real-auth-2026"


async def prepare_identities(sessions):
    async with sessions() as db:
        advisor_role = await db.get(Role, 5)
        advisor_role.permissions = {"geo.assets": "edit", "geo.content": "edit"}
        advisor = await db.get(User, 7)
        advisor.password_hash = hash_password(PASSWORD)
        db.add(Role(id=7, name="onsite customer", permissions={
            "geo.assets": "view", "geo.content": "view",
        }))
        db.add(User(id=12, username="onsite customer", display_name="customer",
                    password_hash=hash_password(PASSWORD), role_id=7, tenant_id=1,
                    is_active=True))
        db.add(Role(id=8, name="other tenant customer", permissions={
            "geo.assets": "view", "geo.content": "view",
        }))
        db.add(User(id=13, username="other tenant customer", display_name="other",
                    password_hash=hash_password(PASSWORD), role_id=8, tenant_id=2,
                    is_active=True))
        db.add(Role(id=9, name="diagnosis only", permissions={"geo.diagnosis": "edit"}))
        db.add(User(id=14, username="diagnosis only", display_name="diagnosis",
                    password_hash=hash_password(PASSWORD), role_id=9, tenant_id=1,
                    is_active=True))
        await db.commit()


def application(sessions):
    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(onsite_routes.router, prefix="/api/v1/geo")

    async def session_override():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_session] = session_override
    return app


async def login(client, username):
    response = await client.post("/api/v1/auth/login", json={
        "username": username, "password": PASSWORD,
    })
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    me = await client.get("/api/v1/auth/me", headers=auth(token))
    assert me.status_code == 200 and me.json()["user"]["username"] == username
    return token


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def proposal_transport(counter, *, entered=None, release=None):
    original = httpx.AsyncClient

    async def handler(_request):
        counter.append("provider")
        if entered is not None:
            entered.set()
        if release is not None:
            await release.wait()
        proposal = _ai_result([
            {"id": "structured_content", "kind": "structured_content"},
            {"id": "knowledge", "kind": "knowledge"},
            {"id": "faq", "kind": "faq"},
        ])
        return httpx.Response(200, json={
            "id": "mock-provider-request",
            "choices": [{"message": {"content": json.dumps(proposal)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                      "prompt_tokens_details": {"cached_tokens": 0}},
        })

    def factory(*_args, **kwargs):
        # Keep the test's ASGI client intact.  The production provider client
        # is the only AsyncClient constructed without a base_url.
        if kwargs.get("base_url") is not None:
            return original(*_args, **kwargs)
        return original(timeout=kwargs.get("timeout"), transport=httpx.MockTransport(handler))
    return factory


async def install_provider(monkeypatch, counter, **transport_kwargs):
    async def credentials(_session, _tenant_id):
        return {"api_key": "fixture-key",
                "base_url": "https://provider.invalid/compatible-mode/v1",
                "model": "deepseek-v4-flash", "provider": "dashscope"}
    monkeypatch.setattr(onsite_routes, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(ai_client.httpx, "AsyncClient",
                        proposal_transport(counter, **transport_kwargs))


def create_payload():
    return {"tenant_id": 1, "project_id": 10, "request_id": str(uuid4()),
            "work_type": "startup", "owner_name": "fixture operator"}


def action_payload(row, action, **extra):
    return {"tenant_id": 1, "project_id": 10, "action": action,
            "expected_revision": row["workflow"]["revision"], **extra}


def test_real_jwt_advisor_closes_delivery_and_customer_is_read_only(monkeypatch):
    async def scenario():
        async with database() as sessions:
            await configured(sessions)
            await prepare_identities(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            provider_calls = []
            await install_provider(monkeypatch, provider_calls)
            captured = []

            async def capture(job_id, tenant_id):
                captured.append((job_id, tenant_id))
            monkeypatch.setattr(async_jobs, "run_job_in_background", capture)
            app = application(sessions)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://test") as client:
                advisor = await login(client, "scope fixture advisor")
                customer = await login(client, "onsite customer")
                other = await login(client, "other tenant customer")
                diagnosis_only = await login(client, "diagnosis only")
                created = await client.post("/api/v1/geo/workbench/onsite-tasks",
                                            json=create_payload(), headers=auth(advisor))
                assert created.status_code == 200, created.text
                row = created.json()
                request_id = str(uuid4())
                queued = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/ai-proposal",
                    json={"tenant_id": 1, "project_id": 10,
                          "expected_revision": 1, "request_id": request_id,
                          "mode": "initial"},
                    headers={**auth(advisor),
                             "X-Snipers-Onsite-Protocol": "durable-v1"},
                )
                assert queued.status_code == 202, queued.text
                assert captured == [(queued.json()["request_run"]["job_id"], 1)]
                await run_owned(sessions, captured[0][0])
                polled = await client.get(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/ai-requests/{request_id}",
                    params={"tenant_id": 1, "project_id": 10}, headers=auth(advisor))
                assert polled.status_code == 200, polled.text
                row = polled.json()
                assert row["request_run"]["state"] == "ready"
                assert row["workflow"]["phase"] == "review"
                assert provider_calls == ["provider"]

                # Acceptance is impossible before approval, implementation and evidence.
                premature = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                    json=action_payload(row, "accept", note="premature"), headers=auth(advisor))
                assert premature.status_code == 409
                approved = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                    json=action_payload(row, "approve", note="facts checked"), headers=auth(advisor))
                assert approved.status_code == 200, approved.text
                stale = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                    json=action_payload(row, "approve", note="duplicate"), headers=auth(advisor))
                assert stale.status_code == 409
                row = approved.json()
                implemented = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                    json=action_payload(row, "implement", note="website changed"),
                    headers=auth(advisor))
                assert implemented.status_code == 200, implemented.text
                row = implemented.json()

                items = row["workflow"]["items"]
                root_parts = []
                llms = ""
                for item in items:
                    if item["kind"] == "schema":
                        root_parts.append(
                            '<script type="application/ld+json">' + item["expected"] + "</script>"
                        )
                    elif item["kind"] == "llms":
                        llms = item["expected"]
                    else:
                        root_parts.append(item["expected"])

                async def safe_fetch(url, **_kwargs):
                    body = llms if url.endswith("/llms.txt") else "<main>" + " ".join(root_parts) + "</main>"
                    return SimpleNamespace(final_url=url, html=body)
                monkeypatch.setattr(onsite_routes, "safe_fetch", safe_fetch)
                checked = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                    json=action_payload(row, "recheck"), headers=auth(advisor))
                assert checked.status_code == 200, checked.text
                row = checked.json()
                assert row["workflow"]["phase"] == "acceptance"
                accepted = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                    json=action_payload(row, "accept", note="human accepted evidence"),
                    headers=auth(advisor))
                assert accepted.status_code == 200, accepted.text
                assert accepted.json()["workflow"]["phase"] == "done"
                assert accepted.json()["completion_evidence"]["recheck"]["passed"] is True

                listing = await client.get("/api/v1/geo/workbench/onsite-tasks",
                                           params={"tenant_id": 1, "project_id": 10},
                                           headers=auth(customer))
                assert listing.status_code == 200, listing.text
                assert listing.json()["items"][0]["allowed_actions"] == []
                assert listing.json()["items"][0]["completion_evidence"]["recheck"]["passed"]
                for path, payload in (
                    ("/api/v1/geo/workbench/onsite-tasks", create_payload()),
                    (f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                     action_payload(row, "accept", note="customer bypass")),
                ):
                    denied = await client.post(path, json=payload, headers=auth(customer))
                    assert denied.status_code == 403
                denied_ai = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/ai-proposal",
                    json={"tenant_id": 1, "project_id": 10,
                          "expected_revision": row["workflow"]["revision"],
                          "request_id": str(uuid4()), "mode": "revise"},
                    headers={**auth(customer),
                             "X-Snipers-Onsite-Protocol": "durable-v1"})
                assert denied_ai.status_code == 403
                cross = await client.get("/api/v1/geo/workbench/onsite-tasks",
                                         params={"tenant_id": 1, "project_id": 10},
                                         headers=auth(other))
                assert cross.status_code == 403
                wrong_permission = await client.get(
                    "/api/v1/geo/workbench/onsite-tasks",
                    params={"tenant_id": 1, "project_id": 10},
                    headers=auth(diagnosis_only))
                assert wrong_permission.status_code == 403
    asyncio.run(scenario())


def test_missing_evidence_and_revoked_role_stop_before_provider(monkeypatch):
    async def scenario():
        async with database() as sessions:
            await configured(sessions)
            await prepare_identities(sessions)
            provider_calls = []
            await install_provider(monkeypatch, provider_calls)
            captured = []

            async def capture(job_id, tenant_id):
                captured.append((job_id, tenant_id))
            monkeypatch.setattr(async_jobs, "run_job_in_background", capture)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(sessions)),
                                         base_url="http://test") as client:
                token = await login(client, "scope fixture advisor")
                task = (await client.post("/api/v1/geo/workbench/onsite-tasks",
                                          json=create_payload(), headers=auth(token))).json()
                missing = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{task['id']}/ai-proposal",
                    json={"tenant_id": 1, "project_id": 10, "expected_revision": 1,
                          "request_id": str(uuid4()), "mode": "initial"},
                    headers={**auth(token), "X-Snipers-Onsite-Protocol": "durable-v1"})
                assert missing.status_code == 409 and not captured and not provider_calls
                async with sessions() as db:
                    await _add_public_fact(db)
                request_id = str(uuid4())
                queued = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{task['id']}/ai-proposal",
                    json={"tenant_id": 1, "project_id": 10, "expected_revision": 1,
                          "request_id": request_id, "mode": "initial"},
                    headers={**auth(token), "X-Snipers-Onsite-Protocol": "durable-v1"})
                assert queued.status_code == 202
                async with sessions() as db:
                    role = await db.get(Role, 5)
                    role.permissions = {"geo.assets": "view", "geo.content": "view"}
                    await db.commit()
                await run_owned(sessions, captured[-1][0])
                assert provider_calls == []
                async with sessions() as db:
                    job = await db.get(GeoAsyncJob, captured[-1][0])
                    assert job.result_meta["public_state"] == "stale"
    asyncio.run(scenario())


def test_cancel_during_mock_provider_discards_late_result(monkeypatch):
    async def scenario():
        async with database() as sessions:
            await configured(sessions)
            await prepare_identities(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            entered, release, provider_calls = asyncio.Event(), asyncio.Event(), []
            await install_provider(monkeypatch, provider_calls, entered=entered, release=release)
            captured = []

            async def capture(job_id, tenant_id):
                captured.append((job_id, tenant_id))
            monkeypatch.setattr(async_jobs, "run_job_in_background", capture)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(sessions)),
                                         base_url="http://test") as client:
                token = await login(client, "scope fixture advisor")
                task = (await client.post("/api/v1/geo/workbench/onsite-tasks",
                                          json=create_payload(), headers=auth(token))).json()
                request_id = str(uuid4())
                queued = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{task['id']}/ai-proposal",
                    json={"tenant_id": 1, "project_id": 10, "expected_revision": 1,
                          "request_id": request_id, "mode": "initial"},
                    headers={**auth(token), "X-Snipers-Onsite-Protocol": "durable-v1"})
                assert queued.status_code == 202
                runner = asyncio.create_task(run_owned(sessions, captured[0][0]))
                await asyncio.wait_for(entered.wait(), timeout=5)
                cancelled = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{task['id']}/ai-requests/{request_id}/cancel",
                    params={"tenant_id": 1, "project_id": 10}, headers=auth(token))
                assert cancelled.status_code == 200, cancelled.text
                release.set()
                await runner
                polled = await client.get(
                    f"/api/v1/geo/workbench/onsite-tasks/{task['id']}/ai-requests/{request_id}",
                    params={"tenant_id": 1, "project_id": 10}, headers=auth(token))
                assert polled.status_code == 200
                assert polled.json()["request_run"]["state"] == "cancelled"
                assert polled.json()["workflow"]["revision"] == 1
                assert "ai_proposal" not in polled.json()["workflow"]
                assert provider_calls == ["provider"]
                async with sessions() as db:
                    job = await db.get(GeoAsyncJob, captured[0][0])
                    assert job.status == "cancelled"
    asyncio.run(scenario())


def test_recheck_refuses_revoked_actor_and_changed_project_after_network(monkeypatch):
    async def scenario():
        async with database() as sessions:
            await configured(sessions)
            await prepare_identities(sessions)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(sessions)),
                                         base_url="http://test") as client:
                token = await login(client, "scope fixture advisor")
                row = (await client.post("/api/v1/geo/workbench/onsite-tasks",
                                         json=create_payload(), headers=auth(token))).json()
                expected = {
                    "structured_content": "verified structured content",
                    "knowledge": "verified knowledge content",
                    "faq": "verified faq content",
                    "schema": '{"@type":"Organization","name":"verified brand"}',
                    "llms": "# verified llms content",
                }
                items = [{**item, "expected": expected[item["kind"]]}
                         for item in row["workflow"]["items"]]
                saved = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                    json=action_payload(row, "save_proposal", items=items), headers=auth(token))
                assert saved.status_code == 200, saved.text
                row = saved.json()
                approved = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                    json=action_payload(row, "approve", note="human reviewed"), headers=auth(token))
                assert approved.status_code == 200
                row = approved.json()
                implemented = await client.post(
                    f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                    json=action_payload(row, "implement", note="human implemented"),
                    headers=auth(token))
                assert implemented.status_code == 200
                row = implemented.json()

                async def attempt(mutate):
                    entered, release = asyncio.Event(), asyncio.Event()

                    async def delayed_fetch(url, **_kwargs):
                        entered.set()
                        await release.wait()
                        if url.endswith("llms.txt"):
                            body = "# verified llms content"
                        else:
                            body = ('<main>verified structured content verified knowledge content '
                                    'verified faq content</main><script type="application/ld+json">'
                                    '{"@type":"Organization","name":"verified brand"}</script>')
                        return SimpleNamespace(final_url=url, html=body)

                    monkeypatch.setattr(onsite_routes, "safe_fetch", delayed_fetch)
                    request = asyncio.create_task(client.post(
                        f"/api/v1/geo/workbench/onsite-tasks/{row['id']}/actions",
                        json=action_payload(row, "recheck"), headers=auth(token)))
                    await asyncio.wait_for(entered.wait(), timeout=5)
                    async with sessions() as db:
                        await mutate(db)
                        await db.commit()
                    release.set()
                    return await asyncio.wait_for(request, timeout=5)

                async def revoke(db):
                    role = await db.get(Role, 5)
                    role.permissions = {"geo.assets": "view", "geo.content": "view"}

                revoked = await attempt(revoke)
                assert revoked.status_code == 403, revoked.text
                async with sessions() as db:
                    stored = await db.get(GeoActionTicket, row["id"])
                    assert stored.progress["onsite"]["phase"] == "recheck"
                    assert stored.progress["onsite"]["revision"] == row["workflow"]["revision"]
                    role = await db.get(Role, 5)
                    role.permissions = {"geo.assets": "edit", "geo.content": "edit"}
                    await db.commit()

                async def change_domain(db):
                    project = await db.get(GeoProject, 10)
                    project.canonical_domain = "changed.example"

                changed = await attempt(change_domain)
                assert changed.status_code == 409, changed.text
                async with sessions() as db:
                    stored = await db.get(GeoActionTicket, row["id"])
                    assert stored.progress["onsite"]["phase"] == "recheck"
                    assert stored.progress["onsite"]["revision"] == row["workflow"]["revision"]
    asyncio.run(scenario())
