"""Committed PG/JWT metadata proofs, with no publication or outbound network."""
import asyncio
from datetime import datetime, timedelta
import json
import os
import re

from fastapi import Depends, FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_session
from app.geo import distribution_sources as sources
from app.geo.content.review import apply_decision, apply_submit, invalidate_review
from app.geo.distribution_assets import remove_asset, store_asset
from app.geo.distribution_sources import (authorize_scope, list_intake_candidates,
    list_sources, load_intake_candidate, load_source)
from app.geo.project_scope import set_binding
from app.geo.project_workflows import save_plan
from app.models import (GeoArticleVersion, GeoChannelAsset, GeoChannelVariant, GeoContentTask,
    GeoOptimizationBusiness, GeoOptimizationUnit, GeoProject, GeoPrompt, Tenant)
from app.models.role import Role
from app.models.user import User
from app.security.auth import AuthContext, require_scoped_auth
from test_geo_distribution_control_integration_postgres import auth_api, bearer, login
from test_geo_distribution_results_postgres import database
from test_geo_distribution_sources_postgres import PNG_1X1, jpeg_1x1

pytestmark = pytest.mark.skipif(not os.getenv("GEO_TEST_POSTGRES_URL"), reason="dedicated PG required")
FIELDS = {"variant_id", "draft_version", "source_revision", "readiness", "reason"}


async def page(sessions, **kwargs):
    async with sessions() as db:
        return await list_intake_candidates(db, 7, 1, 10, "wechat-article", **kwargs)


async def item(sessions, variant=91, platform="wechat-article"):
    async with sessions() as db:
        return await load_intake_candidate(db, 7, 1, 10, variant, platform)


def valid(value):
    assert set(value) == FIELDS
    assert type(value["variant_id"]) is int and value["variant_id"] > 0
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value["draft_version"])
    assert re.fullmatch(r"[A-Za-z0-9_]{1,64}", value["reason"])
    if value["readiness"] == "ready":
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value["source_revision"])
    else:
        assert value["source_revision"] is None
    for secret in ("数据分析", "fixture", "public.example", "http", "body_markdown", "adapt_meta"):
        assert secret not in json.dumps(value)


@pytest.mark.parametrize("review,reason", [("none", "not_submitted"), ("pending", "pending"),
    ("rejected", "rejected"), ("unexpected", "invalid")])
def test_completed_unapproved_drafts_are_private_metadata_and_old_gates_hold(review, reason):
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                task = await db.get(GeoContentTask, 50)
                task.review_status, task.reviewed_by, task.reviewed_at = review, None, None
                await db.commit()
            value = await item(sessions)
            valid(value)
            assert value["readiness"] == "awaiting-review"
            assert value["reason"] == "geo_distribution_review_" + reason
            assert (await page(sessions))["items"] == [value]
            async with sessions() as db:
                with pytest.raises(HTTPException) as blocked:
                    await load_source(db, 7, 1, 10, 91, "wechat-article")
                assert blocked.value.status_code == 409
                assert await list_sources(db, 7, 1, 10, "wechat-article") == []
    asyncio.run(run())


def test_approval_changes_source_revision_but_preserves_content_intent_version():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                task = await db.get(GeoContentTask, 50)
                invalidate_review(task)
                apply_submit(task, submitter_id=7)
                await db.commit()
            pending = await item(sessions)
            async with sessions() as db:
                apply_decision(await db.get(GeoContentTask, 50), decision="approved", note=None, reviewer_id=12)
                await db.commit()
            approved = await item(sessions)
            assert approved["readiness"] == "ready"
            assert approved["draft_version"] == pending["draft_version"]
            async with sessions() as db:
                assert approved["source_revision"] == (await load_source(db, 7, 1, 10, 91, "wechat-article"))["source_revision"]
            async with sessions() as db:
                task = await db.get(GeoContentTask, 50)
                task.reviewed_at += timedelta(minutes=1)
                variant = await db.get(GeoChannelVariant, 91)
                variant.status = "published"
                variant.adapt_meta = {"publication_monitor": {"state": "pending", "history": ["private"]}}
                await db.commit()
            changed_review = await item(sessions)
            assert changed_review["draft_version"] == approved["draft_version"]
            assert changed_review["source_revision"] != approved["source_revision"]
            async with sessions() as db:
                variant = await db.get(GeoChannelVariant, 91)
                variant.body_markdown += "\n实际修改正文。"
                invalidate_review(await db.get(GeoContentTask, 50))
                await db.commit()
            assert (await item(sessions))["draft_version"] != approved["draft_version"]
    asyncio.run(run())


@pytest.mark.parametrize("change,reason", [("master", "master_stale"), ("empty", "content_empty"),
    ("quality", "adaptation_pending"), ("meta", "adaptation_invalid"), ("facts", "publish_gate_blocked")])
def test_real_adaptation_failures_and_asset_missing_remain_completed_candidates(change, reason):
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                variant = await db.get(GeoChannelVariant, 91)
                if change == "master":
                    db.add(GeoArticleVersion(id=93, task_id=50, version_no=4, kind="master",
                        title="new", body_markdown="new", created_at=datetime(2026, 10, 11, 9)))
                elif change == "empty": variant.body_markdown = ""
                elif change == "quality": variant.adapt_meta = {"publishable": False}
                elif change == "meta": variant.adapt_meta = ["private"]
                else:
                    await db.execute(text("DELETE FROM geo_task_facts WHERE task_id=50"))
                await db.commit()
            value = await item(sessions)
            valid(value)
            assert value["readiness"] == "awaiting-adaptation"
            assert value["reason"] == "geo_distribution_" + reason
            if change != "meta":
                red = await item(sessions, 92, "xiaohongshu-image")
                assert red["readiness"] == "awaiting-adaptation"
    asyncio.run(run())


def test_real_asset_edits_change_version_and_reapproval_does_not():
    async def run():
        async with database() as sessions:
            missing = await item(sessions, 92, "xiaohongshu-image")
            assert missing["reason"] == "geo_distribution_assets_unavailable"
            async with sessions() as db:
                asset = await store_asset(db, 7, 1, 10, 92, 0, PNG_1X1)
                asset_id = asset.id
                await db.commit()
            pending = await item(sessions, 92, "xiaohongshu-image")
            assert pending["readiness"] == "awaiting-review"
            assert pending["draft_version"] != missing["draft_version"]
            async with sessions() as db:
                task = await db.get(GeoContentTask, 50)
                apply_submit(task, submitter_id=7)
                apply_decision(task, decision="approved", note=None, reviewer_id=12)
                task.reviewed_at = (await db.get(GeoChannelAsset, asset_id)).created_at + timedelta(minutes=1)
                await db.commit()
            ready = await item(sessions, 92, "xiaohongshu-image")
            assert ready["readiness"] == "ready" and ready["draft_version"] == pending["draft_version"]
            async with sessions() as db:
                await remove_asset(db, 7, 1, 10, 92, asset_id)
                await store_asset(db, 7, 1, 10, 92, 0, jpeg_1x1())
                await db.commit()
            replacement = await item(sessions, 92, "xiaohongshu-image")
            assert replacement["draft_version"] != ready["draft_version"]
            assert replacement["readiness"] == "awaiting-review"
    asyncio.run(run())


@pytest.mark.parametrize("state", ["generating", "adapting", "archived", "cancelled"])
def test_in_progress_and_terminal_task_not_candidates(state):
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                (await db.get(GeoContentTask, 50)).status = state
                await db.commit()
            assert await page(sessions) == {"items": [], "next_cursor": None}
            assert await item(sessions) is None
    asyncio.run(run())


def test_latest_selection_never_resurrects_older_draft_and_point_recheck_distinguishes_none():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                task = await db.get(GeoContentTask, 50)
                invalidate_review(task)
                db.add(GeoChannelVariant(id=99, task_id=50, article_version_id=90, channel="wechat",
                    title="latest", body_markdown="latest body", status="generating",
                    updated_at=datetime(2026, 10, 12, 1)))
                await db.commit()
            assert await item(sessions, 91) is None and await item(sessions, 99) is None
            async with sessions() as db:
                (await db.get(GeoChannelVariant, 99)).status = "draft"
                await db.commit()
            assert (await item(sessions, 99))["readiness"] == "awaiting-review"
            assert await item(sessions, 91) is None
            assert await item(sessions, 92) is None and await item(sessions, 999) is None
    asyncio.run(run())


def test_more_than_fifty_pages_are_ascending_and_final_cursor_null_then_old_id_rechecked():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                invalidate_review(await db.get(GeoContentTask, 50))
                for i in range(121):
                    db.add(GeoContentTask(id=1000+i, tenant_id=1, prompt_id=40, business_id=20,
                        title="private", status="editing", review_status="pending"))
                    db.add(GeoArticleVersion(id=2000+i, task_id=1000+i, version_no=1,
                        title="private", body_markdown="private", kind="master"))
                    db.add(GeoChannelVariant(id=3000+i, task_id=1000+i, article_version_id=2000+i,
                        channel="wechat", title="private", body_markdown="private", status="draft"))
                await db.commit()
            pages, cursor = [], None
            for _ in range(3):
                result = await page(sessions, after_variant_id=cursor)
                pages.append(result)
                cursor = result["next_cursor"]
            assert [len(p["items"]) for p in pages] == [50, 50, 22]
            assert cursor is None
            ids = [v["variant_id"] for p in pages for v in p["items"]]
            assert ids == sorted(set(ids)) and len(ids) == 122
            assert pages[0]["next_cursor"] == ids[49] and pages[1]["next_cursor"] == ids[99]
            assert await page(sessions, after_variant_id=ids[-1]) == {"items": [], "next_cursor": None}
            async with sessions() as db:
                task = await db.get(GeoContentTask, 50)
                apply_submit(task, submitter_id=7)
                apply_decision(task, decision="approved", note=None, reviewer_id=12)
                await db.commit()
            assert (await page(sessions))["items"][0]["readiness"] == "ready"
    asyncio.run(run())


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 51}, {"limit": True},
    {"after_variant_id": 0}, {"after_variant_id": -1}, {"after_variant_id": "91"}])
def test_strict_pagination_inputs(kwargs):
    async def run():
        async with database() as sessions:
            with pytest.raises(HTTPException) as exc: await page(sessions, **kwargs)
            assert exc.value.status_code == 422
    asyncio.run(run())


def test_single_connection_pool_existing_locks_dirty_objects_and_outer_sql_are_preserved():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                schema = await db.scalar(text("SELECT current_schema()"))
                await db.execute(text("CREATE TABLE caller_marker (id int PRIMARY KEY)"))
                await db.commit()
            engine = create_async_engine(sessions.kw["bind"].url, pool_size=1, max_overflow=0,
                pool_timeout=1, connect_args={"server_settings": {"search_path": schema}},
                execution_options={"schema_translate_map": {"public": schema}})
            one = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with one() as db:
                    await authorize_scope(db, 7, 1, 10)
                    variant = await db.get(GeoChannelVariant, 91, with_for_update=True)
                    role = await db.get(Role, 5)
                    variant.body_markdown = "uncommitted private draft"
                    role.permissions = {"geo.assets": "view", "geo.content": "view"}
                    db.add(Role(id=999, name="uncommitted role", permissions={}))
                    await db.execute(text("SET LOCAL lock_timeout='8000ms'"))
                    await db.execute(text("SET LOCAL statement_timeout='25000ms'"))
                    await db.execute(text("INSERT INTO caller_marker VALUES (1)"))
                    result = await asyncio.wait_for(list_intake_candidates(db, 7, 1, 10, "wechat-article"), 3)
                    assert result["items"][0]["readiness"] == "ready"
                    assert variant.body_markdown == "uncommitted private draft"
                    assert role.permissions["geo.assets"] == "view" and len(db.new) == 1
                    assert await db.scalar(text("SHOW lock_timeout")) == "8s"
                    assert await db.scalar(text("SHOW statement_timeout")) == "25s"
                    assert await db.scalar(text("SELECT count(*) FROM caller_marker")) == 1
                    assert await db.scalar(text("SELECT count(*) FROM roles WHERE id=999")) == 0
                    await db.rollback()
                async with one() as db:
                    assert await db.scalar(text("SELECT count(*) FROM caller_marker")) == 0
                    assert (await db.get(Role, 5)).permissions["geo.assets"] == "edit"
                    assert (await db.get(GeoChannelVariant, 91)).body_markdown != "uncommitted private draft"
            finally: await engine.dispose()
    asyncio.run(run())


def test_current_role_revocation_ignores_caller_cached_edit_permissions():
    async def run():
        async with database() as sessions:
            async with sessions() as cached:
                role = await cached.get(Role, 5)
                async with sessions() as changed:
                    (await changed.get(Role, 5)).permissions = {"geo.assets": "view", "geo.content": "view"}
                    await changed.commit()
                role.permissions = {"geo.assets": "edit", "geo.content": "edit"}
                with pytest.raises(HTTPException) as exc:
                    await load_intake_candidate(cached, 7, 1, 10, 91, "wechat-article")
                assert exc.value.status_code == 403
                assert role.permissions["geo.assets"] == "edit"
    asyncio.run(run())


def test_structure_failure_returns_503_not_none_and_restores_outer_transaction():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                await db.execute(text("SET LOCAL lock_timeout='8000ms'"))
                await db.execute(text("ALTER TABLE geo_channel_variants RENAME TO intake_missing"))
                with pytest.raises(HTTPException) as exc:
                    await load_intake_candidate(db, 7, 1, 10, 91, "wechat-article")
                assert exc.value.status_code == 503
                assert "intake_missing" not in str(exc.value.detail)
                assert await db.scalar(text("SHOW lock_timeout")) == "8s"
                assert await db.scalar(text("SELECT count(*) FROM intake_missing")) == 2
                await db.rollback()
            assert (await item(sessions))["readiness"] == "ready"
    asyncio.run(run())


def test_wrapped_native_service_503_is_never_awaiting_adaptation(monkeypatch):
    async def broken(*args, **kwargs): raise HTTPException(503, "private service URL")
    monkeypatch.setattr(sources, "_build_rule_input", broken)
    async def run():
        async with database() as sessions:
            with pytest.raises(HTTPException) as exc: await item(sessions)
            assert exc.value.status_code == 503 and "private" not in str(exc.value.detail)
    asyncio.run(run())


def test_cancellation_rolls_back_only_read_savepoint_and_restores_settings(monkeypatch):
    original = sources._latest_article
    async def run():
        entered = asyncio.Event()
        async def delay(*args, **kwargs):
            value = await original(*args, **kwargs)
            entered.set()
            await asyncio.Event().wait()
            return value
        async with database() as sessions:
            async with sessions() as db:
                await db.execute(text("SET LOCAL lock_timeout='8000ms'"))
                await db.execute(text("SET LOCAL statement_timeout='25000ms'"))
                monkeypatch.setattr(sources, "_latest_article", delay)
                task = asyncio.create_task(list_intake_candidates(db, 7, 1, 10, "wechat-article"))
                await asyncio.wait_for(entered.wait(), 3)
                task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
                assert await db.scalar(text("SHOW lock_timeout")) == "8s"
                assert await db.scalar(text("SHOW statement_timeout")) == "25s"
                assert await db.scalar(select(func.count()).select_from(GeoChannelVariant)) == 2
    asyncio.run(run())


def test_real_jwt_cross_scope_and_current_revocation():
    async def run():
        async with database() as sessions:
            app = FastAPI()
            app.include_router(auth_api.router)
            async def db_session():
                async with sessions() as db: yield db
            app.dependency_overrides[get_session] = db_session
            @app.get("/api/v1/geo/content-tasks/test-intake")
            async def endpoint(tenant_id: int, scope_id: int,
                    ctx: AuthContext = Depends(require_scoped_auth), db=Depends(get_session)):
                ctx.ensure_tenant(tenant_id)
                return await list_intake_candidates(db, ctx.user_id, tenant_id, scope_id, "wechat-article")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                token = await login(client, "scope fixture advisor")
                admin = await login(client, "fixture platform admin")
                async def call(credential=token, tenant=1, scope=10):
                    return await client.get("/api/v1/geo/content-tasks/test-intake", params={"tenant_id": tenant, "scope_id": scope}, headers=bearer(credential))
                assert (await call()).status_code == 200
                assert (await call(admin)).status_code == 403
                assert (await call(tenant=2)).status_code == 403
                assert (await call(scope=999)).status_code == 404
                async with sessions() as db:
                    (await db.get(Role, 5)).permissions = {"geo.assets": "view", "geo.content": "view"}
                    await db.commit()
                assert (await call()).status_code == 403
                async with sessions() as db:
                    (await db.get(User, 7)).is_active = False
                    await db.commit()
                assert (await call()).status_code == 401
    asyncio.run(run())


def test_authorized_second_project_never_reads_another_projects_pending_source():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                db.add(GeoProject(id=11, tenant_id=1, tenant_module_id=1, name="other project",
                    primary_domain="other.example", canonical_domain="other.example", status="active"))
                db.add(GeoOptimizationBusiness(id=21, tenant_id=1, name="other business"))
                db.add(GeoOptimizationUnit(id=31, tenant_id=1, business_id=21, name="other unit"))
                db.add(GeoPrompt(id=41, tenant_id=1, unit_id=31, question="other prompt"))
                db.add(GeoContentTask(id=51, tenant_id=1, business_id=21, prompt_id=41,
                    title="private other project", status="editing", review_status="pending"))
                db.add(GeoArticleVersion(id=95, task_id=51, version_no=1, kind="master",
                    title="private", body_markdown="private"))
                db.add(GeoChannelVariant(id=96, task_id=51, article_version_id=95,
                    channel="wechat", title="private", body_markdown="private", status="draft"))
                await db.commit()
                await set_binding(db, 1, 11, [21], 0, 7)
                await save_plan(db, 1, 11, {"enabled": False, "status": "active", "prompt_ids": [41],
                    "interval_days": 7, "advisor_user_id": 7}, 0, 7)
                await db.commit()
            assert [v["variant_id"] for v in (await page(sessions))["items"]] == [91]
            async with sessions() as db:
                other = await list_intake_candidates(db, 7, 1, 11, "wechat-article")
                assert [v["variant_id"] for v in other["items"]] == [96]
                assert await load_intake_candidate(db, 7, 1, 11, 91, "wechat-article") is None
                with pytest.raises(HTTPException) as exc:
                    await list_intake_candidates(db, 7, 1, 11, "unsupported")
                assert exc.value.status_code == 422
    asyncio.run(run())


def test_frozen_historical_rows_still_load_without_database_system_function_dependencies():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                schema = await db.scalar(text("SELECT current_schema()"))
            assert schema.startswith("geo_results_test_")
            async with sessions.kw["bind"].connect() as connection:
                connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
                await connection.execute(text(f'VACUUM FREEZE "{schema}".geo_channel_variants'))
            assert (await item(sessions))["readiness"] == "ready"
    asyncio.run(run())


def test_optional_image_table_missing_preserves_text_channel_and_image_channel_fails_closed():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                await db.execute(text("ALTER TABLE geo_channel_assets RENAME TO intake_optional_missing"))
                assert (await list_intake_candidates(db, 7, 1, 10, "wechat-article"))["items"][0]["readiness"] == "ready"
                assert (await load_intake_candidate(db, 7, 1, 10, 91, "wechat-article"))["readiness"] == "ready"
                with pytest.raises(HTTPException) as exc:
                    await load_intake_candidate(db, 7, 1, 10, 92, "xiaohongshu-image")
                assert exc.value.status_code == 503
                assert "intake_optional_missing" not in str(exc.value.detail)
                assert await db.scalar(select(func.count()).select_from(GeoChannelVariant)) == 2
                await db.rollback()
    asyncio.run(run())
