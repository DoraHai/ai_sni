"""Current central scan_channel with actual native GEO, JWT and owned PG."""
import asyncio
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.geo.content.review import apply_decision, apply_submit, invalidate_review
from app.models import GeoChannelVariant, GeoContentTask
from test_geo_distribution_publication_broker_postgres import fixture, call, SCOPE


async def configured(client, advisor, admin):
    response = await call(client, admin, "POST", "/devices", json={"label": "GEO intake fixture"})
    assert response.status_code == 200, response.text
    device = response.json()["device"]
    response = await call(client, admin, "POST", "/bindings", json={**SCOPE,
        "device_id": device["id"], "account_id": "geo-intake-account",
        "external_account_id": "gh_geo_intake", "platform": "wechat-article",
        "confirm_account_ownership": True})
    assert response.status_code == 200, response.text
    binding = response.json()["binding"]["id"]
    response = await call(client, advisor, "POST", "/project-channel", json={**SCOPE,
        "binding_id": binding, "content_type": "article", "enabled": True,
        "expected_revision": 0, "request_id": str(uuid4())})
    assert response.status_code == 200, response.text
    response = await call(client, admin, "POST", "/channel-permission", json={
        "platform": "wechat-article", "content_type": "article", "enabled": True,
        "expected_revision": 0, "request_id": str(uuid4())})
    assert response.status_code == 200, response.text
    response = await call(client, advisor, "POST", "/control", json={**SCOPE,
        "action": "start", "expected_revision": 0, "request_id": str(uuid4())})
    assert response.status_code == 200, response.text
    return binding


def test_actual_scan_single_pool_pending_approval_edit_and_point_recheck_create_no_device_tasks():
    async def run():
        async with fixture() as (sessions, client, modules, advisor, admin, other):
            await configured(client, advisor, admin)
            async with sessions() as db:
                invalidate_review(await db.get(GeoContentTask, 50))
                schema = await db.scalar(text("SELECT current_schema()"))
                await db.commit()
            engine = create_async_engine(sessions.kw["bind"].url, pool_size=1, max_overflow=0,
                pool_timeout=1, connect_args={"server_settings": {"search_path": schema,
                    "lock_timeout": "8000", "statement_timeout": "25000"}},
                execution_options={"schema_translate_map": {"public": schema}})
            one = async_sessionmaker(engine, expire_on_commit=False)
            queue = modules["distribution_queue"]
            try:
                await asyncio.wait_for(queue.run_once(one), 5)
                response = await call(client, advisor, "GET", "/queue", params=SCOPE)
                assert response.status_code == 200, response.text
                pending = response.json()["items"][0]
                assert pending["state"] == "awaiting-review" and pending["source_revision"] is None
                async with one() as db:
                    task = await db.get(GeoContentTask, 50)
                    apply_submit(task, submitter_id=7)
                    apply_decision(task, decision="approved", note=None, reviewer_id=12)
                    await db.commit()
                await asyncio.wait_for(queue.run_once(one), 5)
                response = await call(client, advisor, "GET", "/queue", params=SCOPE)
                approved = response.json()["items"][0]
                assert approved["id"] == pending["id"] and approved["source_revision"]
                async with one() as db:
                    invalidate_review(await db.get(GeoContentTask, 50))
                    variant = await db.get(GeoChannelVariant, 91)
                    variant.body_markdown += "\n新的顾问修订。"
                    await db.commit()
                await asyncio.wait_for(queue.run_once(one), 5)
                response = await call(client, advisor, "GET", "/queue", params=SCOPE)
                records = response.json()["items"]
                assert len(records) == 2
                assert next(q for q in records if q["id"] == pending["id"])["state"] == "superseded"
                async with one() as db:
                    latest_at = (await db.get(GeoChannelVariant, 91)).updated_at
                    db.add(GeoChannelVariant(id=99, task_id=50, article_version_id=90, channel="wechat",
                        title="new pending", body_markdown="new pending body", status="draft",
                        updated_at=latest_at + timedelta(minutes=1)))
                    await db.commit()
                await asyncio.wait_for(queue.run_once(one), 5)
                response = await call(client, advisor, "GET", "/queue", params=SCOPE)
                records = response.json()["items"]
                assert len(records) == 3
                assert all(q["state"] == "superseded" for q in records if q["variant_id"] == 91)
                assert next(q for q in records if q["variant_id"] == 99)["state"] == "awaiting-review"
                async with one() as db:
                    assert await db.scalar(text("SELECT count(*) FROM distribution_tasks")) == 0
                    assert await db.scalar(text("SELECT count(*) FROM geo_publications")) == 0
                    assert await db.scalar(text("SELECT count(*) FROM distribution_publish_reservations")) == 0
                    assert await db.scalar(text("SHOW lock_timeout")) == "8s"
                    assert await db.scalar(text("SHOW statement_timeout")) == "25s"
                assert (await call(client, other, "GET", "/queue", params=SCOPE)).status_code == 403
            finally:
                await engine.dispose()
    asyncio.run(run())
