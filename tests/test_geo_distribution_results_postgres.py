"""Real native gates, PostgreSQL transactions, monitoring and replay proofs."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.schema import CreateTable

from app.geo.distribution_results import record_publication, content_digest, _validate
from app.geo.distribution_sources import load_source
from app.geo.publication_monitor import list_monitor, report_check, state_for, store_state
from app.models import (Tenant, TenantModule, GeoProject, GeoOptimizationBusiness,
    GeoOptimizationUnit, GeoOptimizationPeriod, GeoPrompt, GeoContentTask,
    GeoArticleVersion, GeoChannelVariant, GeoChannelAsset, GeoFact, GeoTaskFact,
    GeoPublication, GeoMediaPlacement, GeoActionTicket, GeoAnswerSnapshot, GeoTrackingEngine)
from app.models.role import Role
from app.models.user import User
from test_geo_distribution_control_integration_postgres import seed

ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.skipif(not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated PostgreSQL")


@asynccontextmanager
async def database():
    url = make_url(os.environ["GEO_TEST_POSTGRES_URL"])
    assert url.drivername == "postgresql+asyncpg" and url.host == "127.0.0.1"
    assert url.port == 55507 and (url.database, url.username) == ("geo_ci", "geo_ci") and not url.query
    schema = "geo_results_test_" + uuid4().hex
    engine = create_async_engine(url, pool_size=10, connect_args={"server_settings": {
        "search_path": schema, "lock_timeout": "10000", "statement_timeout": "15000"}},
        execution_options={"schema_translate_map": {"public": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            for model in (Tenant, TenantModule, GeoProject, GeoOptimizationBusiness,
                GeoOptimizationUnit, GeoOptimizationPeriod, GeoPrompt, GeoContentTask,
                GeoArticleVersion, GeoChannelVariant, GeoChannelAsset, GeoFact, GeoTaskFact,
                GeoPublication, GeoMediaPlacement, GeoActionTicket, GeoAnswerSnapshot, GeoTrackingEngine, Role, User):
                await connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
            # Native tenant policy uses a fixed public registry; this empty
            # registry exists only in the guarded, owned 55507 test database.
            await connection.execute(text("CREATE TABLE IF NOT EXISTS public.demo_tenant_bindings (tenant_id bigint, demo_tenant_id bigint, dataset_key varchar(64), dataset_version varchar(40), status varchar(16), version integer)"))
            raw = (await connection.get_raw_connection()).driver_connection
            ddl = (ROOT / "scripts/geo_distribution_results_schema.sql").read_text(encoding="utf-8")
            await raw.execute(ddl)
            await raw.execute(ddl)  # Candidate is re-applicable; no production migration.
        await seed(sessions)
        yield sessions
    finally:
        try:
            async with engine.begin() as connection:
                assert schema.startswith("geo_results_test_") and len(schema) == 49
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            await engine.dispose()


async def payload(sessions, *, platform="wechat-article", variant_id=91):
    async with sessions() as db:
        source = await load_source(db, 7, 1, 10, variant_id, platform)
    return {"event_id": str(uuid4()), "task_id": str(uuid4()),
        "source_revision": source["source_revision"], "content_digest": content_digest(source["content"]),
        "platform": platform,
        "public_url": "https://mp.weixin.qq.com/s/Verified-page" if platform == "wechat-article" else "https://www.xiaohongshu.com/explore/abcdef1234567890abcdef12",
        "reported_at": 1791705600000, "verification": "human-verified", "verified_at": 1791705660000, "verified_by": 7}


async def counts(sessions):
    async with sessions() as db:
        return (await db.scalar(select(func.count()).select_from(GeoPublication)),
            await db.scalar(select(func.count()).select_from(GeoMediaPlacement)),
            await db.scalar(text("SELECT count(*) FROM geo_distribution_publications")),
            await db.scalar(text("SELECT count(*) FROM geo_distribution_publication_events")))


def test_verified_registration_is_native_pending_monitor_and_not_ai_citation():
    async def run():
        async with database() as sessions:
            value = await payload(sessions)
            async with sessions() as db:
                result = await record_publication(db, 7, 1, 10, 91, value)
                assert result == {"module": "geo", "publication_id": 1, "placement_id": 1,
                    "monitor_state": "pending", "verification": "human-verified", "idempotent": False}
                # Adapter must not secretly commit anything for its caller.
                assert await counts(sessions) == (0, 0, 0, 0)
                await db.commit()
            assert await counts(sessions) == (1, 1, 1, 1)
            async with sessions() as db:
                variant = await db.get(GeoChannelVariant, 91)
                pub = await db.get(GeoPublication, 1)
                placement = await db.get(GeoMediaPlacement, 1)
                task = await db.get(GeoContentTask, 50)
                assert task.status == "published" and variant.status == "published"
                assert task.review_status == "approved" and task.reviewed_by == 12
                assert placement.related_prompt_id == 40 and placement.citation_national is None
                monitor = await list_monitor(db, 1, 50)
                assert len(monitor["items"]) == 1 and monitor["items"][0]["state"] == "pending"
                assert monitor["items"][0]["can_check"] is True
                check = report_check(variant, pub, 90)
                assert check["verified"] is False and check["citation_accuracy"] == "not_evaluated"
                from app.geo.content.report_routes import _evidence
                from app.geo.content.report_data import citation_rows
                report = await _evidence(db, 1, None, date(2026, 10, 1), date(2026, 10, 31), project_id=10)
                assert len(report["publications"]) == 1
                assert report["publication_checks"][1]["verified"] is False
                assert report["data_scope"]["project_id"] == 10
                rows = citation_rows(report["publications"], report["snapshots"],
                    report["start"], report["end"], "real", report["publication_checks"])
                assert len(rows) == 1 and rows[0]["exact_count"] == rows[0]["loose_count"] == 0
    asyncio.run(run())


def test_exact_repeat_new_verification_event_and_monitor_updates_do_not_duplicate():
    async def run():
        async with database() as sessions:
            value = await payload(sessions)
            async with sessions() as db:
                await record_publication(db, 7, 1, 10, 91, value)
                await db.commit()
            async with sessions() as db:
                repeated = await record_publication(db, 7, 1, 10, 91, value)
                assert repeated["idempotent"] is True
                await db.commit()
            async with sessions() as db:
                variant = await db.get(GeoChannelVariant, 91)
                pub = await db.get(GeoPublication, 1)
                # Only a real monitor can make this observation; registration
                # must preserve it and must not invent such evidence itself.
                store_state(variant, pub, {**state_for(variant, pub), "state": "unreachable", "failures": 1})
                await db.commit()
            async with sessions() as db:
                repeated = await record_publication(db, 7, 1, 10, 91, {**value,
                    "event_id": str(uuid4()), "verification": "machine-verified", "verified_at": value["verified_at"] + 1000})
                assert repeated["idempotent"] and repeated["monitor_state"] == "unreachable"
                assert repeated["verification"] == "machine-verified"
                await db.commit()
            assert await counts(sessions) == (1, 1, 1, 2)
    asyncio.run(run())


def test_concurrent_exact_and_distinct_event_repeats_create_one_native_result():
    async def run():
        async with database() as sessions:
            value = await payload(sessions)
            async def adopt(v):
                async with sessions() as db:
                    result = await record_publication(db, 7, 1, 10, 91, v)
                    await db.commit()
                    return result
            outcomes = await asyncio.gather(*(adopt({**value, "event_id": value["event_id"] if i < 3 else str(uuid4())}) for i in range(6)))
            assert sum(not r["idempotent"] for r in outcomes) == 1
            assert {r["publication_id"] for r in outcomes} == {1}
            assert await counts(sessions) == (1, 1, 1, 4)
    asyncio.run(run())


@pytest.mark.parametrize("changed", [{"source_revision": "stale-revision"}, {"content_digest": "0" * 64}])
def test_source_revision_and_digest_are_checked_before_any_native_write(changed):
    async def run():
        async with database() as sessions:
            value = await payload(sessions)
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await record_publication(db, 7, 1, 10, 91, {**value, **changed})
                assert exc.value.detail["code"] == "geo_distribution_result_source_changed"
            assert await counts(sessions) == (0, 0, 0, 0)
    asyncio.run(run())


@pytest.mark.parametrize("new_event", [False, True])
def test_same_task_or_event_cannot_register_a_different_url(new_event):
    async def run():
        async with database() as sessions:
            value = await payload(sessions)
            async with sessions() as db:
                await record_publication(db, 7, 1, 10, 91, value)
                await db.commit()
            changed = {**value, "public_url": "https://mp.weixin.qq.com/s/Different-page"}
            if new_event:
                changed["event_id"] = str(uuid4())
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await record_publication(db, 7, 1, 10, 91, changed)
                assert exc.value.detail["code"] == "geo_distribution_result_conflict"
            assert await counts(sessions) == (1, 1, 1, 1)
    asyncio.run(run())


@pytest.mark.parametrize("revoke", ["review", "role", "advisor", "entitlement", "latest-master", "content"])
def test_replay_cannot_bypass_current_authorization_or_native_review(revoke):
    async def run():
        async with database() as sessions:
            value = await payload(sessions)
            async with sessions() as db:
                await record_publication(db, 7, 1, 10, 91, value)
                await db.commit()
            async with sessions() as db:
                if revoke == "review":
                    (await db.get(GeoContentTask, 50)).review_status = "none"
                elif revoke == "role":
                    (await db.get(Role, 5)).permissions = {"geo.assets": "view", "geo.content": "view"}
                elif revoke == "advisor":
                    project = await db.get(GeoProject, 10)
                    project.project_settings = {**project.project_settings, "geo_service_plan": {
                        **project.project_settings["geo_service_plan"], "advisor_user_id": 999}}
                elif revoke == "entitlement":
                    (await db.get(TenantModule, 1)).status = "disabled"
                elif revoke == "latest-master":
                    db.add(GeoArticleVersion(id=93, task_id=50, version_no=4, kind="master",
                        title="new master", body_markdown="new body", outline={}, created_by=7))
                else:
                    variant = await db.get(GeoChannelVariant, 91)
                    variant.title += " 已修改"
                await db.commit()
            async with sessions() as db:
                with pytest.raises(HTTPException):
                    await record_publication(db, 7, 1, 10, 91, value)
            assert await counts(sessions) == (1, 1, 1, 1)
    asyncio.run(run())


def test_cross_tenant_wrong_variant_and_untrusted_verifier_are_denied():
    async def run():
        async with database() as sessions:
            value = await payload(sessions)
            for tenant, scope, variant, v in ((2, 10, 91, value), (1, 10, 92, value),
                (1, 10, 91, {**value, "verified_by": 9})):
                async with sessions() as db:
                    with pytest.raises(HTTPException):
                        await record_publication(db, 7, tenant, scope, variant, v)
            assert await counts(sessions) == (0, 0, 0, 0)
    asyncio.run(run())


def test_rollback_and_append_only_history():
    async def run():
        async with database() as sessions:
            value = await payload(sessions)
            async with sessions() as db:
                await record_publication(db, 7, 1, 10, 91, value)
                await db.rollback()
            assert await counts(sessions) == (0, 0, 0, 0)
            async with sessions() as db:
                await record_publication(db, 7, 1, 10, 91, value)
                await db.commit()
            for table in ("geo_distribution_publications", "geo_distribution_publication_events"):
                async with sessions() as db:
                    with pytest.raises(Exception, match="append only"):
                        await db.execute(text(f"DELETE FROM {table}"))
                    await db.rollback()
            assert await counts(sessions) == (1, 1, 1, 1)
    asyncio.run(run())


def test_adapter_failure_rolls_back_partial_native_write_even_if_caller_commits(monkeypatch):
    from app.geo import distribution_results
    original = distribution_results._write_publication
    async def fail_after_write(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("injected failure after native publication flush")
    async def run():
        async with database() as sessions:
            value = await payload(sessions)
            monkeypatch.setattr(distribution_results, "_write_publication", fail_after_write)
            async with sessions() as db:
                with pytest.raises(RuntimeError, match="injected failure"):
                    await record_publication(db, 7, 1, 10, 91, value)
                await db.commit()  # Broker retry/error state would commit here.
            assert await counts(sessions) == (0, 0, 0, 0)
            async with sessions() as db:
                assert (await db.get(GeoContentTask, 50)).status == "ready"
                assert (await db.get(GeoChannelVariant, 91)).status == "exported"
    asyncio.run(run())


def test_existing_native_manual_publication_and_placement_are_reused():
    from app.geo.content.routes import _write_publication
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                await load_source(db, 7, 1, 10, 91, "wechat-article")
                task, variant = await db.get(GeoContentTask, 50), await db.get(GeoChannelVariant, 91)
                await _write_publication(db, task=task, variant=variant, channel="wechat",
                    published_url="https://mp.weixin.qq.com/s/Verified-page", note="existing manual registration", publish_mode="manual_export")
                db.add(GeoMediaPlacement(tenant_id=1, name="existing placement", channel_key="wechat",
                    published_url="https://mp.weixin.qq.com/s/Verified-page", status="published", related_prompt_id=40, created_by=7))
                await db.commit()
            value = await payload(sessions)
            async with sessions() as db:
                result = await record_publication(db, 7, 1, 10, 91, value)
                assert result["publication_id"] == result["placement_id"] == 1
                await db.commit()
            assert await counts(sessions) == (1, 1, 1, 1)
            async with sessions() as db:
                assert (await db.get(GeoMediaPlacement, 1)).name == "existing placement"
                assert (await db.get(GeoPublication, 1)).note == "existing manual registration"
    asyncio.run(run())


def test_xiaohongshu_manifest_digest_and_real_review_gate_are_retained():
    from app.geo.distribution_assets import store_asset
    from test_geo_distribution_control_integration_postgres import PNG_1X1
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                asset = await store_asset(db, 7, 1, 10, 92, 0, PNG_1X1)
                task = await db.get(GeoContentTask, 50)
                task.review_status, task.reviewed_by = "approved", 12
                task.reviewed_at = asset.created_at + timedelta(minutes=1)
                await db.commit()
            value = await payload(sessions, platform="xiaohongshu-image", variant_id=92)
            async with sessions() as db:
                result = await record_publication(db, 7, 1, 10, 92, value)
                assert result["monitor_state"] == "pending"
                await db.commit()
            async with sessions() as db:
                asset = await db.scalar(select(GeoChannelAsset))
                asset.content_bytes = b"modified"
                await db.commit()
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await record_publication(db, 7, 1, 10, 92, value)
                assert exc.value.detail["code"] == "geo_distribution_asset_manifest_invalid"
    asyncio.run(run())


@pytest.mark.parametrize("url", ["http://mp.weixin.qq.com/s/abc", "https://mp.weixin.qq.com.evil/s/abc",
    "https://user@mp.weixin.qq.com/s/abc", "https://mp.weixin.qq.com:443/s/abc",
    "https://mp.weixin.qq.com/s/abc?token=secret", "https://mp.weixin.qq.com/s/abc#fragment",
    "https://mp.weixin.qq.com/s/abc\n", "https://127.0.0.1/s/abc", "https://mp.weixin.qq.com/", 
    "https://www.xiaohongshu.com/explore/abcdef"])
def test_url_validation_rejects_noncanonical_or_wrong_platform(url):
    value = {"event_id": str(uuid4()), "task_id": str(uuid4()), "source_revision": "revision",
        "content_digest": "a" * 64, "platform": "wechat-article", "public_url": url,
        "reported_at": 1791705600000, "verification": "human-verified", "verified_at": 1791705600000, "verified_by": 7}
    with pytest.raises(HTTPException) as exc:
        _validate(value, 7)
    assert exc.value.status_code == 422


def test_digest_is_identical_to_shared_contract_for_unicode_and_ordered_images():
    central = Path(os.getenv("DISTRIBUTION_CONTROL_SOURCE", r"D:\SNIPERS国内版\ai_sni-worktrees\distribution-control-20261011"))
    spec = importlib.util.spec_from_file_location("geo_result_contract_proof", central / "app/distribution_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    content = {"version": "geo-r1", "title": "中文 😀", "body": "第一行\n正文", "assets": [
        {"id": "geo-asset-1", "sha256": "a" * 64, "mediaType": "image/png", "bytes": 12}]}
    assert content_digest(content) == module.content_digest(content)


@pytest.mark.parametrize("change", [{"verification": "unknown"}, {"verification": "human-reported"},
    {"verified_by": True}, {"verified_at": 1}, {"body": "untrusted new article"}])
def test_unverified_results_or_open_body_payload_cannot_enter_native_registration(change):
    value = {"event_id": str(uuid4()), "task_id": str(uuid4()), "source_revision": "revision",
        "content_digest": "a" * 64, "platform": "wechat-article", "public_url": "https://mp.weixin.qq.com/s/abc",
        "reported_at": 1791705600000, "verification": "human-verified", "verified_at": 1791705600000, "verified_by": 7}
    with pytest.raises(HTTPException) as exc:
        _validate({**value, **change}, 7)
    assert exc.value.status_code == 422
