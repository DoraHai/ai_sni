"""Actual candidate broker JWT/router/PG -> native GEO result integration.

Device publication reports and human public-page confirmations are synthetic;
no real platform or outbound network is used. Native facts, review, authorization,
result adapter, publication/placement writes and monitor state are not mocked.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

import httpx
from sqlalchemy import text

from app.geo.distribution_sources import load_source
from app.geo.publication_monitor import list_monitor, state_for
from app.geo.publication_monitor import initial_state, outcome, store_state
from app.models import GeoChannelVariant, GeoContentTask, GeoMediaPlacement, GeoPublication
from app.models.role import Role
from app.models.user import User
from app.security.auth import hash_password
from test_geo_distribution_control_integration_postgres import (
    CENTRAL, PASSWORD, _load, application, bearer, login,
)
from test_geo_distribution_results_postgres import database, counts

SCOPE = {"module": "geo", "tenant_id": 1, "scope_id": 10}
URL = "https://mp.weixin.qq.com/s/Synthetic-geo-verified"


def central_modules():
    loaded = {}
    for name in ("distribution_contract", "distribution_control", "distribution_scheduling",
                 "distribution_publication_verify", "distribution_publication_results", "distribution_queue"):
        loaded[name] = _load("app." + name, CENTRAL / "app" / (name + ".py"))
    router = _load("geo_publication_broker_router_fixture", CENTRAL / "app/api/distribution.py")
    return loaded, router


@asynccontextmanager
async def fixture():
    modules, router = central_modules()
    async with database() as sessions:
        async with sessions() as db:
            connection = await db.connection()
            raw = (await connection.get_raw_connection()).driver_connection
            for name in ("distribution_control_schema.sql", "distribution_scheduling_schema.sql",
                         "distribution_publication_schema.sql", "distribution_queue_schema.sql"):
                await raw.execute((CENTRAL / "scripts" / name).read_text(encoding="utf-8"))
            db.add(User(id=8, username="other fixture advisor", display_name="other advisor",
                role_id=5, tenant_id=None, password_hash=hash_password(PASSWORD), is_active=True))
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(sessions, router)),
                                    base_url="http://test") as client:
            advisor = await login(client, "scope fixture advisor")
            admin = await login(client, "fixture platform admin")
            other = await login(client, "other fixture advisor")
            yield sessions, client, modules, advisor, admin, other


async def call(client, token, method, path, **kwargs):
    return await client.request(method, "/api/distribution/v1" + path, headers=bearer(token), **kwargs)


async def published(client, modules, advisor, admin):
    created = await call(client, admin, "POST", "/devices", json={"label": "isolated GEO fixture"})
    assert created.status_code == 200, created.text
    device = created.json()["device"]
    binding = await call(client, admin, "POST", "/bindings", json={**SCOPE,
        "device_id": device["id"], "account_id": "geo-fixture-account",
        "external_account_id": "gh_geo_fixture", "platform": "wechat-article",
        "confirm_account_ownership": True})
    assert binding.status_code == 200, binding.text
    binding_id = binding.json()["binding"]["id"]
    policy = await call(client, admin, "POST", "/account-policy", json={
        "binding_id": binding_id, "expected_revision": 0, "enabled": True, "timezone": "UTC",
        "min_interval_seconds": 0, "daily_limit": 10, "windows": [{"start": 0, "end": 1440}],
        "request_id": str(uuid4())})
    assert policy.status_code == 200, policy.text
    started = await call(client, advisor, "POST", "/control", json={**SCOPE, "action": "start",
        "expected_revision": 0, "request_id": str(uuid4())})
    assert started.status_code == 200, started.text
    source = await call(client, advisor, "GET", "/source", params={**SCOPE,
        "variant_id": 91, "platform": "wechat-article"})
    assert source.status_code == 200, source.text
    source = source.json()
    queued = await call(client, advisor, "POST", "/tasks", json={**SCOPE, "variant_id": 91,
        "binding_id": binding_id, "source_revision": source["source_revision"],
        "expected_digest": source["content_digest"], "action": "publish",
        "confirm_reviewed_content": True, "confirm_manual_publication": True,
        "expires_in_seconds": 3600, "request_id": str(uuid4())})
    assert queued.status_code == 200, queued.text
    task = queued.json()["task"]
    exchange = await call(client, device["credential"], "POST", "/device/exchange", json={
        "contractVersion": 1, "deviceId": device["id"], "receipts": []})
    assert exchange.status_code == 200, exchange.text
    envelope = exchange.json()["tasks"][0]
    assert envelope["id"] == task["id"]
    receipt = {"receiptId": str(uuid4()), "sequence": 1, "contractVersion": 1,
        "taskId": envelope["id"], "customerId": "1", "projectId": "geo-10",
        "deviceId": device["id"], "accountId": "geo-fixture-account", "platform": "wechat-article",
        "contentVersion": envelope["content"]["version"], "contentDigest": envelope["contentDigest"],
        "leaseId": envelope["leaseId"], "status": "succeeded", "code": "HUMAN_PUBLISHED",
        "at": modules["distribution_control"].now_ms(), "evidence": "human-reported", "publicUrl": URL}
    accepted = await call(client, device["credential"], "POST", "/device/exchange", json={
        "contractVersion": 1, "deviceId": device["id"], "receipts": [receipt]})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["receiptAcks"][0]["status"] == "succeeded"
    return task, device, source


def check(task, **changes):
    return {**SCOPE, "task_id": task["id"], "mode": "human", "expected_public_url": URL,
        "confirm_public_access": True, "confirm_target_account": True,
        "confirm_approved_content": True, "request_id": str(uuid4()), **changes}


async def native_and_central_counts(sessions):
    native = await counts(sessions)
    async with sessions() as db:
        central = tuple([await db.scalar(text("SELECT count(*) FROM " + table)) for table in (
            "distribution_tasks", "distribution_publication_checks", "distribution_publication_writebacks")])
    return native, central


def test_real_broker_check_adopts_native_publication_placement_and_pending_monitor():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, _other):
            task, _device, source = await published(client, modules, advisor, admin)
            assert await native_and_central_counts(sessions) == ((0, 0, 0, 0), (1, 0, 0))
            response = await call(client, advisor, "POST", "/publication-check", json=check(task))
            assert response.status_code == 200, response.text
            publication = response.json()["publication"]
            assert publication["check"]["verification"] == "human-verified"
            assert publication["writeback"]["state"] == "written"
            assert publication["writeback"]["result"] == {"module": "geo", "publication_id": 1,
                "placement_id": 1, "monitor_state": "pending", "verification": "human-verified", "idempotent": False}
            assert await native_and_central_counts(sessions) == ((1, 1, 1, 1), (1, 1, 1))
            async with sessions() as db:
                native = await db.get(GeoPublication, 1)
                placement = await db.get(GeoMediaPlacement, 1)
                variant = await db.get(GeoChannelVariant, 91)
                assert native.published_url == placement.published_url == URL
                assert placement.citation_national is None
                assert state_for(variant, native)["state"] == "pending"
                monitor = await list_monitor(db, 1, 50)
                assert monitor["items"][0]["state"] == "pending"
                current = await load_source(db, 7, 1, 10, 91, "wechat-article")
                assert current["source_revision"] != source["source_revision"]
    asyncio.run(run())


def test_check_request_replay_and_bookkeeping_revision_do_not_duplicate_native_writes():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, _other):
            task, _device, _source = await published(client, modules, advisor, admin)
            payload = check(task)
            first = await call(client, advisor, "POST", "/publication-check", json=payload)
            assert first.status_code == 200, first.text
            assert (await call(client, advisor, "POST", "/publication-check", json=payload)).json() == first.json()
            conflict = await call(client, advisor, "POST", "/publication-check", json={**payload,
                "confirm_target_account": False, "mode": "machine"})
            assert conflict.status_code == 409
            again = await call(client, advisor, "POST", "/publication-check", json=check(task))
            assert again.status_code == 200, again.text
            assert again.json()["publication"]["writeback"]["state"] == "written"
            retry = {**SCOPE, "task_id": task["id"], "event_id": first.json()["publication"]["writeback"]["event_id"],
                "request_id": str(uuid4())}
            retried = await call(client, advisor, "POST", "/publication-writeback", json=retry)
            assert retried.status_code == 200, retried.text
            assert retried.json()["publication"]["writeback"]["attempts"] == 1
            assert await native_and_central_counts(sessions) == ((1, 1, 1, 1), (1, 2, 1))
    asyncio.run(run())


def test_concurrent_actual_router_checks_write_one_native_result_while_project_paused():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, _other):
            task, _device, _source = await published(client, modules, advisor, admin)
            paused = await call(client, advisor, "POST", "/control", json={**SCOPE,
                "action": "pause", "expected_revision": 1, "request_id": str(uuid4())})
            assert paused.status_code == 200, paused.text
            responses = await asyncio.gather(*[call(client, advisor, "POST", "/publication-check",
                json=check(task)) for _ in range(6)])
            assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
            assert all(r.json()["publication"]["writeback"]["state"] == "written" for r in responses)
            assert await native_and_central_counts(sessions) == ((1, 1, 1, 1), (1, 6, 1))
    asyncio.run(run())


def test_review_revoked_after_report_retains_verified_check_and_blocks_native_adoption():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, _other):
            task, _device, _source = await published(client, modules, advisor, admin)
            async with sessions() as db:
                native_task = await db.get(GeoContentTask, 50)
                native_task.review_status = "none"
                native_task.reviewed_by = native_task.reviewed_at = None
                await db.commit()
            response = await call(client, advisor, "POST", "/publication-check", json=check(task))
            assert response.status_code == 200, response.text
            publication = response.json()["publication"]
            assert publication["check"]["status"] == "verified"
            assert publication["writeback"]["state"] == "blocked"
            assert publication["writeback"]["code"] == "geo_distribution_publish_gate_blocked"
            assert await native_and_central_counts(sessions) == ((0, 0, 0, 0), (1, 1, 1))
            retry = {**SCOPE, "task_id": task["id"], "event_id": publication["writeback"]["event_id"],
                "request_id": str(uuid4())}
            again = await call(client, advisor, "POST", "/publication-writeback", json=retry)
            assert again.status_code == 200, again.text
            assert again.json()["publication"]["writeback"]["state"] == "blocked"
            assert await native_and_central_counts(sessions) == ((0, 0, 0, 0), (1, 1, 1))
    asyncio.run(run())


def test_native_database_failure_after_writes_rolls_back_and_explicit_retry_only_registers():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, _other):
            task, device, _source = await published(client, modules, advisor, admin)
            # Inject a DB failure at the final append-only native event, after
            # real _write_publication, placement and monitor flush have run.
            async with sessions() as db:
                await db.execute(text("CREATE FUNCTION fixture_fail_native_result() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic storage interruption'; END $$"))
                await db.execute(text("CREATE TRIGGER fixture_fail_native_result BEFORE INSERT ON geo_distribution_publication_events FOR EACH ROW EXECUTE FUNCTION fixture_fail_native_result()"))
                await db.commit()
            first = await call(client, advisor, "POST", "/publication-check", json=check(task))
            assert first.status_code == 200, first.text
            publication = first.json()["publication"]
            assert publication["check"]["status"] == "verified"
            assert publication["writeback"]["state"] == "pending"
            assert publication["writeback"]["code"] == "WRITEBACK_UNAVAILABLE"
            assert await native_and_central_counts(sessions) == ((0, 0, 0, 0), (1, 1, 1))
            async with sessions() as db:
                assert (await db.get(GeoChannelVariant, 91)).status == "exported"
                assert (await db.get(GeoContentTask, 50)).status == "ready"
                await db.execute(text("DROP TRIGGER fixture_fail_native_result ON geo_distribution_publication_events"))
                await db.commit()
            req = {**SCOPE, "task_id": task["id"], "event_id": publication["writeback"]["event_id"],
                "request_id": str(uuid4())}
            wrong = await call(client, advisor, "POST", "/publication-writeback", json={**req,
                "event_id": str(uuid4())})
            assert wrong.status_code == 409
            retried = await call(client, advisor, "POST", "/publication-writeback", json=req)
            assert retried.status_code == 200, retried.text
            assert retried.json()["publication"]["writeback"]["state"] == "written"
            assert retried.json()["publication"]["writeback"]["attempts"] == 2
            assert (await call(client, advisor, "POST", "/publication-writeback", json=req)).json() == retried.json()
            assert await native_and_central_counts(sessions) == ((1, 1, 1, 1), (1, 1, 1))
            exchange = await call(client, device["credential"], "POST", "/device/exchange", json={
                "contractVersion": 1, "deviceId": device["id"], "receipts": []})
            assert exchange.status_code == 200, exchange.text
            assert exchange.json()["tasks"] == []
    asyncio.run(run())


def test_actual_jwt_scope_three_confirmations_and_list_sanitization():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, other):
            task, device, source = await published(client, modules, advisor, admin)
            for name in ("confirm_public_access", "confirm_target_account", "confirm_approved_content"):
                assert (await call(client, advisor, "POST", "/publication-check", json=check(task, **{name: False}))).status_code == 422
            assert (await call(client, advisor, "POST", "/publication-check", json=check(task, body="forged"))).status_code == 422
            for token in (other, admin, device["credential"]):
                denied = await call(client, token, "POST", "/publication-check", json=check(task))
                assert denied.status_code in (401, 403), denied.text
            assert (await call(client, advisor, "POST", "/publication-check", json=check(task, tenant_id=2))).status_code == 403
            good = await call(client, advisor, "POST", "/publication-check", json=check(task))
            assert good.status_code == 200, good.text
            listing = await call(client, advisor, "GET", "/tasks", params=SCOPE)
            assert listing.status_code == 200, listing.text
            assert listing.headers["cache-control"] == "no-store"
            item = listing.json()["items"][0]
            assert item["publication"]["writeback"]["result"]["publication_id"] == 1
            assert set(item["publication"]["check"]) == {"id", "task_id", "actor_id", "mode", "public_url",
                "reported_at", "checked_at", "status", "code", "verification"}
            assert set(item["publication"]["writeback"]) == {"event_id", "state", "attempts", "updated_at", "code", "result"}
            assert device["credential"] not in listing.text and source["content"]["body"] not in listing.text
            for key in ("content", "credential_hash", "payload", "request_fingerprint", "grant_id", "lease_id"):
                assert key not in item
            assert (await call(client, other, "GET", "/tasks", params=SCOPE)).status_code == 403
            assert (await call(client, advisor, "GET", "/tasks", params={**SCOPE, "scope_id": 11})).status_code == 404
            async with sessions() as db:
                role = await db.get(Role, 5)
                role.permissions = {"geo.assets": "view", "geo.content": "view"}
                await db.commit()
            assert (await call(client, advisor, "GET", "/tasks", params=SCOPE)).status_code == 403
    asyncio.run(run())


def test_reported_unknown_outcome_never_creates_check_or_native_result():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, _other):
            task, _device, _source = await published(client, modules, advisor, admin)
            async with sessions() as db:
                await db.execute(text("UPDATE distribution_tasks SET status='unknown' WHERE id=:id"), {"id": task["id"]})
                await db.commit()
            response = await call(client, advisor, "POST", "/publication-check", json=check(task))
            assert response.status_code == 409, response.text
            assert await native_and_central_counts(sessions) == ((0, 0, 0, 0), (1, 0, 0))
    asyncio.run(run())


def test_actual_monitor_get_reads_pending_then_latest_observed_without_native_snapshot_rewrite():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, _other):
            task, device, source = await published(client, modules, advisor, admin)
            params = {**SCOPE, "task_id": task["id"], "publication_id": 999}
            before = await call(client, advisor, "GET", "/publication-monitor", params=params)
            assert before.status_code == 409, before.text
            checked = await call(client, advisor, "POST", "/publication-check", json=check(task))
            assert checked.status_code == 200, checked.text
            assert checked.json()["publication"]["writeback"]["state"] == "written"
            pending = await call(client, advisor, "GET", "/publication-monitor", params=params)
            assert pending.status_code == 200, pending.text
            assert pending.headers["cache-control"] == "no-store"
            assert pending.json()["monitor"] == {"module": "geo", "publication_id": 1,
                "basis": "public-text", "state": "pending", "evidence_source": "none",
                "observed_at": None, "next_check_at": None, "evidence_id": None, "code": "GEO_MONITOR_PENDING"}
            async with sessions() as db:
                variant = await db.get(GeoChannelVariant, 91)
                pub = await db.get(GeoPublication, 1)
                store_state(variant, pub, outcome(initial_state(variant), "healthy", datetime(2026, 10, 11, 8),
                    checked_url=pub.published_url, expected_sha256="a" * 64, observed_sha256="b" * 64))
                await db.commit()
            observed = await call(client, advisor, "GET", "/publication-monitor", params=params)
            assert observed.status_code == 200, observed.text
            assert observed.json()["monitor"] == {"module": "geo", "publication_id": 1,
                "basis": "public-text", "state": "observed", "evidence_source": "none",
                "observed_at": 1791705600000, "next_check_at": 1791792000000,
                "evidence_id": None, "code": "GEO_MONITOR_OBSERVED"}
            assert URL not in observed.text and source["content"]["body"] not in observed.text
            assert device["credential"] not in observed.text
            snapshot = await call(client, advisor, "GET", "/tasks", params=SCOPE)
            assert snapshot.json()["items"][0]["publication"]["writeback"]["result"]["monitor_state"] == "pending"
            assert await native_and_central_counts(sessions) == ((1, 1, 1, 1), (1, 1, 1))
    asyncio.run(run())


def test_actual_monitor_get_historical_edits_remain_readable_but_scope_and_role_revocation_deny():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, other):
            task, device, _source = await published(client, modules, advisor, admin)
            checked = await call(client, advisor, "POST", "/publication-check", json=check(task))
            assert checked.status_code == 200, checked.text
            async with sessions() as db:
                variant = await db.get(GeoChannelVariant, 91)
                variant.body_markdown = "later private unreviewed draft"
                native_task = await db.get(GeoContentTask, 50)
                native_task.review_status = "none"
                native_task.reviewed_by = native_task.reviewed_at = None
                await db.commit()
            params = {**SCOPE, "task_id": task["id"]}
            history = await call(client, advisor, "GET", "/publication-monitor", params=params)
            assert history.status_code == 200, history.text
            assert history.json()["monitor"]["state"] == "pending"
            assert "private" not in history.text
            for token in (other, admin, device["credential"]):
                denied = await call(client, token, "GET", "/publication-monitor", params=params)
                assert denied.status_code in {401, 403}, denied.text
            wrong = await call(client, advisor, "GET", "/publication-monitor", params={**params, "tenant_id": 2})
            assert wrong.status_code == 403, wrong.text
            async with sessions() as db:
                role = await db.get(Role, 5)
                role.permissions = {"geo.assets": "view", "geo.content": "view"}
                await db.commit()
            denied = await call(client, advisor, "GET", "/publication-monitor", params=params)
            assert denied.status_code == 403, denied.text
            assert await native_and_central_counts(sessions) == ((1, 1, 1, 1), (1, 1, 1))
    asyncio.run(run())


def test_actual_monitor_get_invalid_metadata_is_sanitized_and_never_creates_new_work():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, _other):
            task, _device, _source = await published(client, modules, advisor, admin)
            checked = await call(client, advisor, "POST", "/publication-check", json=check(task))
            assert checked.status_code == 200, checked.text
            async with sessions() as db:
                variant = await db.get(GeoChannelVariant, 91)
                variant.adapt_meta = {"publication_monitor": {"1": {"state": "healthy", "checked_at": "private bad date",
                    "history": ["private history"], "observed_url": "https://private.example/token"}}}
                await db.commit()
            response = await call(client, advisor, "GET", "/publication-monitor", params={**SCOPE, "task_id": task["id"]})
            assert response.status_code == 200, response.text
            assert response.json()["monitor"]["state"] == "unavailable"
            assert response.json()["monitor"]["observed_at"] is None
            assert "private" not in response.text and "healthy" not in response.text
            assert await native_and_central_counts(sessions) == ((1, 1, 1, 1), (1, 1, 1))
    asyncio.run(run())
