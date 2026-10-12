"""Native GEO adapter integration with the candidate shared distribution broker."""
import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.schema import CreateTable

import app as app_package
from app.database import get_session
from app.geo.distribution_assets import router as geo_assets_router
from app.geo.project_scope import set_binding
from app.geo.project_workflows import save_plan
from app.models import (
    GeoActionTicket,
    GeoAnswerSnapshot,
    GeoArticleVersion,
    GeoChannelAsset,
    GeoChannelVariant,
    GeoContentTask,
    GeoFact,
    GeoOptimizationBusiness,
    GeoOptimizationUnit,
    GeoProject,
    GeoPrompt,
    GeoPublication,
    GeoTaskFact,
    GeoTrackingEngine,
    Tenant,
    TenantModule,
)
from app.models.role import Role
from app.models.user import User
from app.security.auth import hash_password

pytestmark = pytest.mark.skipif(
    not os.getenv("DISTRIBUTION_TEST_POSTGRES_URL"),
    reason="requires dedicated distribution PostgreSQL",
)

ROOT = Path(__file__).parents[1]
CENTRAL = Path(os.getenv(
    "DISTRIBUTION_CONTROL_SOURCE",
    r"D:\SNIPERS国内版\ai_sni-worktrees\distribution-control-20261011",
))
PASSWORD = "Geo-distribution-integration-2026"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    setattr(app_package, name.rsplit(".", 1)[-1], module)
    spec.loader.exec_module(module)
    return module


def central_modules():
    contract = _load(
        "app.distribution_contract", CENTRAL / "app" / "distribution_contract.py"
    )
    control = _load(
        "app.distribution_control", CENTRAL / "app" / "distribution_control.py"
    )
    _load(
        "app.distribution_scheduling", CENTRAL / "app" / "distribution_scheduling.py"
    )
    router = _load(
        "geo_distribution_router_fixture", CENTRAL / "app" / "api" / "distribution.py"
    )
    return contract, control, router


_AUTH_SPEC = importlib.util.spec_from_file_location(
    "geo_distribution_real_auth_api", ROOT / "app" / "api" / "auth.py"
)
assert _AUTH_SPEC and _AUTH_SPEC.loader
auth_api = importlib.util.module_from_spec(_AUTH_SPEC)
_AUTH_SPEC.loader.exec_module(auth_api)


@asynccontextmanager
async def distribution_database():
    url = make_url(os.environ["DISTRIBUTION_TEST_POSTGRES_URL"])
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in {"127.0.0.1", "localhost"}
    assert url.port == 55443
    assert (url.database, url.username) == (
        "distribution_control_test", "distribution_test"
    )
    assert not url.query
    schema = "geo_distribution_test_" + uuid4().hex
    engine = create_async_engine(
        url,
        pool_size=5,
        connect_args={"server_settings": {
            "search_path": schema,
            "lock_timeout": "5000",
            "statement_timeout": "15000",
        }},
        execution_options={"schema_translate_map": {"public": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            for model in (
                Tenant, GeoProject, GeoOptimizationBusiness, GeoOptimizationUnit,
                GeoPrompt, GeoContentTask, GeoAnswerSnapshot, GeoTrackingEngine,
                GeoActionTicket, GeoArticleVersion, GeoTaskFact, GeoFact,
                GeoPublication, GeoChannelVariant, GeoChannelAsset, TenantModule, Role, User,
            ):
                await connection.execute(CreateTable(
                    model.__table__, include_foreign_key_constraints=[]
                ))
            # GEO tenant policy intentionally addresses this registry in the
            # database public schema.  This dedicated test database keeps an
            # empty registry; tenant/module rows in the random schema remain
            # the only entitlement source used by the scenario.
            await connection.execute(text(
                "CREATE TABLE IF NOT EXISTS public.demo_tenant_bindings (tenant_id bigint, "
                "demo_tenant_id bigint, dataset_key varchar(64), "
                "dataset_version varchar(40), status varchar(16), version integer)"
            ))
            raw = (await connection.get_raw_connection()).driver_connection
            await raw.execute(
                (CENTRAL / "scripts" / "distribution_control_schema.sql").read_text(
                    encoding="utf-8"
                )
            )
            await raw.execute(
                (CENTRAL / "scripts" / "distribution_scheduling_schema.sql").read_text(
                    encoding="utf-8"
                )
            )
        yield sessions
    finally:
        try:
            if created:
                assert schema.startswith("geo_distribution_test_")
                async with engine.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            await engine.dispose()


READY_BODY = """scope fixture 数据分析平台覆盖 80% 场景。

## 定义

scope fixture 数据分析平台是一种用于汇聚与分析业务数据的系统。

## 对比选型

与传统报表工具相比，自助分析更适合跨部门协作。

## 操作步骤

步骤 1：明确场景。
步骤 2：核对事实。
步骤 3：试点上线。

## FAQ

- **Q：** 需要关注什么？
  **A：** 建议核验来源与时效。
- **Q：** 如何验证？
  **A：** 建议核对应事实卡。

## 结论

scope fixture 数据分析平台覆盖 80% 场景。

## 来源

- 来源：fixture whitepaper

scope fixture 数据分析平台实施约 14 天。
scope fixture 数据分析平台服务 120 家客户。

*更新时间：2026-10-11*
"""

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


async def seed(sessions):
    async with sessions() as db:
        db.add_all([
            Tenant(id=1, name="scope fixture"),
            TenantModule(id=1, tenant_id=1, module_code="geo", status="active"),
            Role(id=5, name="fixture advisor", permissions={
                "geo.assets": "edit", "geo.content": "edit",
            }),
            User(id=7, username="scope fixture advisor", display_name="advisor",
                 role_id=5, tenant_id=None, password_hash=hash_password(PASSWORD),
                 is_active=True),
            Role(id=6, name="fixture platform admin", permissions={
                "settings.accounts": "edit", "settings.customers": "edit",
            }),
            User(id=9, username="fixture platform admin", display_name="admin",
                 role_id=6, tenant_id=None, password_hash=hash_password(PASSWORD),
                 is_active=True),
            GeoProject(id=10, tenant_id=1, tenant_module_id=1, name="project 10",
                       primary_domain="p10.example", canonical_domain="p10.example",
                       status="active"),
            GeoOptimizationBusiness(id=20, tenant_id=1, name="business 20"),
            GeoOptimizationUnit(id=30, tenant_id=1, business_id=20, name="unit"),
            GeoPrompt(id=40, tenant_id=1, unit_id=30,
                      question="数据分析平台哪个好用"),
            GeoContentTask(id=50, tenant_id=1, prompt_id=40, business_id=20,
                           title="approved distribution source", status="ready",
                           target_channels=["wechat", "xiaohongshu"], pipeline_step="ready",
                           review_status="approved", reviewed_by=12,
                           reviewed_at=datetime(2026, 10, 11, 8, 10, 0),
                           rule_result={"geo_score": 90}),
            GeoArticleVersion(id=90, task_id=50, version_no=3, kind="master",
                              title="数据分析平台怎么选", body_markdown=READY_BODY,
                              outline={"direct_answer": "scope fixture 数据分析平台覆盖 80% 场景。",
                                       "updated_at": "2026-10-11"},
                              author_name="fixture author", created_by=7,
                              created_at=datetime(2026, 10, 11, 8, 0, 0)),
            GeoChannelVariant(id=91, task_id=50, article_version_id=90,
                              channel="wechat", title="公众号：数据分析平台怎么选",
                              body_markdown=READY_BODY, status="exported", adapt_meta={},
                              created_at=datetime(2026, 10, 11, 8, 5, 0),
                              updated_at=datetime(2026, 10, 11, 8, 5, 0)),
            GeoChannelVariant(id=92, task_id=50, article_version_id=90,
                              channel="xiaohongshu", title="小红书：数据分析平台怎么选",
                              body_markdown=READY_BODY, status="exported", adapt_meta={},
                              created_at=datetime(2026, 10, 11, 8, 5, 0),
                              updated_at=datetime(2026, 10, 11, 8, 5, 0)),
        ])
        statements = [
            "scope fixture 数据分析平台覆盖 80% 场景。",
            "scope fixture 数据分析平台实施约 14 天。",
            "scope fixture 数据分析平台服务 120 家客户。",
            "scope fixture 数据分析平台是一种用于汇聚与分析业务数据的系统。",
            "与传统报表工具相比，自助分析更适合跨部门协作。",
            "来源：fixture whitepaper",
        ]
        for offset, statement in enumerate(statements):
            fact_id = 80 + offset
            db.add(GeoFact(
                id=fact_id, tenant_id=1, business_id=20,
                title=f"fact {offset + 1}", statement=statement,
                fact_type="product", source_name="fixture whitepaper",
                source_url=f"https://public.example/fact-{offset + 1}",
                trust_level="verified", status="active",
            ))
            db.add(GeoTaskFact(task_id=50, fact_id=fact_id, sort_order=offset))
        await db.commit()
        await set_binding(db, 1, 10, [20], 0, 7)
        await save_plan(db, 1, 10, {
            "enabled": False, "status": "active", "prompt_ids": [40],
            "interval_days": 7, "advisor_user_id": 7,
        }, 0, 7)
        await db.commit()


def application(sessions, router_module):
    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(router_module.router)
    app.include_router(geo_assets_router, prefix="/api/v1/geo")

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
    return response.json()["token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_real_jwt_geo_source_broker_exchange_and_stale_authorization_fence():
    async def scenario():
        contract, control, router_module = central_modules()
        async with distribution_database() as sessions:
            await seed(sessions)
            app = application(sessions, router_module)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                advisor = await login(client, "scope fixture advisor")
                admin = await login(client, "fixture platform admin")

                uploaded = await client.post(
                    "/api/v1/geo/distribution-assets",
                    data={"tenant_id": "1", "scope_id": "10", "variant_id": "92",
                          "sort_order": "0"},
                    files={"file": ("cover.png", PNG_1X1, "image/png")},
                    headers=bearer(advisor),
                )
                assert uploaded.status_code == 200, uploaded.text
                uploaded_asset = uploaded.json()["asset"]
                assert uploaded_asset["sha256"] == hashlib.sha256(PNG_1X1).hexdigest()
                assert uploaded_asset["mediaType"] == "image/png"
                editable = await client.get(
                    "/api/v1/geo/distribution-assets",
                    params={"tenant_id": 1, "scope_id": 10, "variant_id": 92},
                    headers=bearer(advisor),
                )
                assert editable.status_code == 200, editable.text
                assert editable.json()["review_status"] == "none"
                assert editable.json()["assets"][0]["id"] == uploaded_asset["id"]
                asset_content = await client.get(
                    f"/api/v1/geo/distribution-assets/{uploaded_asset['id'].removeprefix('geo-asset-')}/content",
                    params={"tenant_id": 1, "scope_id": 10, "variant_id": 92},
                    headers=bearer(advisor),
                )
                assert asset_content.status_code == 200, asset_content.text
                assert asset_content.content == PNG_1X1
                denied_assets = await client.get(
                    "/api/v1/geo/distribution-assets",
                    params={"tenant_id": 1, "scope_id": 10, "variant_id": 92},
                    headers=bearer(admin),
                )
                assert denied_assets.status_code == 403
                async with sessions() as db:
                    task = await db.get(GeoContentTask, 50)
                    assert task.review_status == "none" and task.reviewed_at is None
                    asset = await db.get(
                        GeoChannelAsset,
                        int(uploaded_asset["id"].removeprefix("geo-asset-")),
                    )
                    task.review_status = "approved"
                    task.reviewed_by = 12
                    task.reviewed_at = asset.created_at + timedelta(minutes=1)
                    await db.commit()

                # Replacement uses the same authenticated HTTP surface. Both
                # removal and upload revoke native customer review, so an old
                # approval cannot silently carry over to changed image bytes.
                deleted = await client.delete(
                    f"/api/v1/geo/distribution-assets/{uploaded_asset['id'].removeprefix('geo-asset-')}",
                    params={"tenant_id": 1, "scope_id": 10, "variant_id": 92},
                    headers=bearer(advisor),
                )
                assert deleted.status_code == 200, deleted.text
                async with sessions() as db:
                    task = await db.get(GeoContentTask, 50)
                    assert task.review_status == "none" and task.reviewed_at is None
                replacement = await client.post(
                    "/api/v1/geo/distribution-assets",
                    data={"tenant_id": "1", "scope_id": "10", "variant_id": "92",
                          "sort_order": "0"},
                    files={"file": ("replacement.png", PNG_1X1, "image/png")},
                    headers=bearer(advisor),
                )
                assert replacement.status_code == 200, replacement.text
                uploaded_asset = replacement.json()["asset"]
                async with sessions() as db:
                    task = await db.get(GeoContentTask, 50)
                    replacement_asset = await db.get(
                        GeoChannelAsset,
                        int(uploaded_asset["id"].removeprefix("geo-asset-")),
                    )
                    assert task.review_status == "none" and task.reviewed_at is None
                    task.review_status = "approved"
                    task.reviewed_by = 12
                    task.reviewed_at = replacement_asset.created_at + timedelta(minutes=1)
                    await db.commit()

                listing = await client.get(
                    "/api/distribution/v1/sources",
                    params={"module": "geo", "tenant_id": 1, "scope_id": 10,
                            "platform": "wechat-article"},
                    headers=bearer(advisor),
                )
                assert listing.status_code == 200, listing.text
                assert listing.headers["cache-control"] == "no-store"
                assert len(listing.json()["items"]) == 1
                summary = listing.json()["items"][0]
                assert set(summary) == {
                    "variant_id", "source_revision", "title", "platform"
                }

                preview = await client.get(
                    "/api/distribution/v1/source",
                    params={"module": "geo", "tenant_id": 1, "scope_id": 10,
                            "variant_id": 91, "platform": "wechat-article"},
                    headers=bearer(advisor),
                )
                assert preview.status_code == 200, preview.text
                source = preview.json()
                assert source["source_revision"] == summary["source_revision"]
                assert source["content_digest"] == contract.content_digest(source["content"])

                red_preview = await client.get(
                    "/api/distribution/v1/source",
                    params={"module": "geo", "tenant_id": 1, "scope_id": 10,
                            "variant_id": 92, "platform": "xiaohongshu-image"},
                    headers=bearer(advisor),
                )
                assert red_preview.status_code == 200, red_preview.text
                red_source = red_preview.json()
                assert red_source["content"]["assets"] == [{
                    "id": uploaded_asset["id"],
                    "sha256": hashlib.sha256(PNG_1X1).hexdigest(),
                    "mediaType": "image/png",
                    "bytes": len(PNG_1X1),
                }]
                assert red_source["content_digest"] == contract.content_digest(red_source["content"])

                device_response = await client.post(
                    "/api/distribution/v1/devices",
                    json={"label": "isolated fixture device"}, headers=bearer(admin),
                )
                assert device_response.status_code == 200, device_response.text
                device = device_response.json()["device"]
                binding_response = await client.post(
                    "/api/distribution/v1/bindings",
                    json={
                        "module": "geo", "tenant_id": 1, "scope_id": 10,
                        "device_id": device["id"], "account_id": "fixture-account",
                        "external_account_id": "fixture-external-account",
                        "platform": "wechat-article",
                        "confirm_account_ownership": True,
                    }, headers=bearer(admin),
                )
                assert binding_response.status_code == 200, binding_response.text
                binding_id = binding_response.json()["binding"]["id"]
                red_binding_response = await client.post(
                    "/api/distribution/v1/bindings",
                    json={
                        "module": "geo", "tenant_id": 1, "scope_id": 10,
                        "device_id": device["id"], "account_id": "fixture-red-account",
                        "external_account_id": "fixture-red-external-account",
                        "platform": "xiaohongshu-image",
                        "confirm_account_ownership": True,
                    }, headers=bearer(admin),
                )
                assert red_binding_response.status_code == 200, red_binding_response.text
                red_binding_id = red_binding_response.json()["binding"]["id"]

                started = await client.post(
                    "/api/distribution/v1/control",
                    json={"module": "geo", "tenant_id": 1, "scope_id": 10,
                          "action": "start", "expected_revision": 0,
                          "request_id": str(uuid4())},
                    headers=bearer(advisor),
                )
                assert started.status_code == 200, started.text
                assert started.json()["project"]["state"] == "running"

                async def enqueue(action, *, selected_source=source, selected_variant=91,
                                  selected_binding=binding_id):
                    response = await client.post(
                        "/api/distribution/v1/tasks",
                        json={
                            "module": "geo", "tenant_id": 1, "scope_id": 10,
                            "variant_id": selected_variant, "binding_id": selected_binding,
                            "source_revision": selected_source["source_revision"],
                            "expected_digest": selected_source["content_digest"],
                            "action": action, "confirm_reviewed_content": True,
                            "confirm_manual_publication": False,
                            "expires_in_seconds": 3600,
                            "request_id": str(uuid4()),
                        }, headers=bearer(advisor),
                    )
                    assert response.status_code == 200, response.text
                    return response.json()["task"]

                preflight = await enqueue("preflight")
                handoff = await enqueue("handoff")
                red_preflight = await enqueue(
                    "preflight", selected_source=red_source, selected_variant=92,
                    selected_binding=red_binding_id,
                )
                exchange = await client.post(
                    "/api/distribution/v1/device/exchange",
                    json={"contractVersion": 1, "deviceId": device["id"],
                          "receipts": []},
                    headers={"Authorization": f"Bearer {device['credential']}"},
                )
                assert exchange.status_code == 200, exchange.text
                envelope = exchange.json()
                by_id = {row["id"]: row for row in envelope["tasks"]}
                assert preflight["id"] in by_id and handoff["id"] in by_id
                assert red_preflight["id"] in by_id
                assert by_id[preflight["id"]]["projectId"] == "geo-10"
                red_task = by_id[red_preflight["id"]]
                assert red_task["content"]["assets"][0]["id"] == uploaded_asset["id"]
                downloaded = await client.get(
                    f"/api/distribution/v1/device/tasks/{red_task['id']}/assets/{uploaded_asset['id']}",
                    headers={"Authorization": f"Bearer {device['credential']}"},
                )
                assert downloaded.status_code == 200, downloaded.text
                assert downloaded.content == PNG_1X1
                assert downloaded.headers["content-type"] == "image/png"
                assert downloaded.headers["cache-control"] == "no-store"
                assert downloaded.headers["etag"] == f'"{hashlib.sha256(PNG_1X1).hexdigest()}"'

                preflight_task = by_id[preflight["id"]]
                receipt = {
                    "receiptId": str(uuid4()), "sequence": 1, "contractVersion": 1,
                    "taskId": preflight_task["id"], "customerId": "1",
                    "projectId": "geo-10", "deviceId": device["id"],
                    "accountId": "fixture-account", "platform": "wechat-article",
                    "contentVersion": preflight_task["content"]["version"],
                    "contentDigest": preflight_task["contentDigest"],
                    "leaseId": preflight_task["leaseId"], "status": "succeeded",
                    "code": "PREFLIGHT_OK", "at": control.now_ms(),
                    "evidence": "none", "publicUrl": None,
                }
                acknowledged = await client.post(
                    "/api/distribution/v1/device/exchange",
                    json={"contractVersion": 1, "deviceId": device["id"],
                          "receipts": [receipt]},
                    headers={"Authorization": f"Bearer {device['credential']}"},
                )
                assert acknowledged.status_code == 200, acknowledged.text
                assert acknowledged.json()["receiptAcks"][0]["status"] == "succeeded"

                # A new master plus review revocation invalidates the queued
                # handoff.  Exchange must re-read native GEO and fence it.
                async with sessions() as db:
                    task = await db.get(GeoContentTask, 50)
                    task.review_status = "none"
                    task.reviewed_at = None
                    task.reviewed_by = None
                    db.add(GeoArticleVersion(
                        id=92, task_id=50, version_no=4, kind="master",
                        title="changed master", body_markdown=READY_BODY,
                        outline={}, author_name="fixture", created_by=7,
                        created_at=datetime(2026, 10, 11, 9, 0, 0),
                    ))
                    await db.commit()
                fenced = await client.post(
                    "/api/distribution/v1/device/exchange",
                    json={"contractVersion": 1, "deviceId": device["id"],
                          "receipts": []},
                    headers={"Authorization": f"Bearer {device['credential']}"},
                )
                assert fenced.status_code == 200, fenced.text
                assert all(row["id"] != handoff["id"] for row in fenced.json()["tasks"])
                async with sessions() as db:
                    row = (await db.execute(text(
                        "SELECT revoked,status FROM distribution_tasks WHERE id::text=:id"
                    ), {"id": handoff["id"]})).one()
                    assert row.revoked is True and row.status == "unknown"
                    events = list((await db.execute(text(
                        "SELECT result FROM distribution_events WHERE task_id::text=:id"
                    ), {"id": handoff["id"]})).scalars())
                    assert "AUTHORIZATION_OR_LEASE_INVALID" in events
    asyncio.run(scenario())
