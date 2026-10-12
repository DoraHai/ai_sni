"""Read current GEO monitor state with actual PG authorization and ownership."""
import asyncio
from datetime import datetime
import json

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select, text

from app.geo import distribution_results as results
from app.geo.distribution_results import publication_monitor_status, record_publication
from app.geo.distribution_sources import load_source
from app.geo.project_scope import set_binding
from app.geo.project_workflows import save_plan
from app.geo.publication_monitor import defer_monitor_failure, initial_state, outcome, store_state
from app.models import (GeoArticleVersion, GeoChannelVariant, GeoContentTask, GeoOptimizationBusiness,
    GeoOptimizationUnit, GeoProject, GeoPrompt, GeoPublication)
from app.models.role import Role
from app.models.user import User
from test_geo_distribution_results_postgres import database, payload

FIELDS = {"module", "publication_id", "basis", "state", "evidence_source", "observed_at",
    "next_check_at", "evidence_id", "code"}
STAMP = "2026-10-11T08:00:00Z"
STAMP_MS = 1791705600000


async def adopted(sessions):
    value = await payload(sessions)
    async with sessions() as db:
        result = await record_publication(db, 7, 1, 10, 91, value)
        await db.commit()
    return result["publication_id"]


async def metadata(sessions, publication_id, value):
    async with sessions() as db:
        variant = await db.get(GeoChannelVariant, 91)
        variant.adapt_meta = value
        await db.commit()


async def read(sessions, publication_id, *, actor=7, tenant=1, scope=10):
    async with sessions() as db:
        return await publication_monitor_status(db, actor, tenant, scope, publication_id)


def assert_view(value, publication_id, state, observed_at=None, next_check_at=None):
    assert set(value) == FIELDS
    assert value == {"module": "geo", "publication_id": publication_id, "basis": "public-text",
        "state": state, "evidence_source": "none", "observed_at": observed_at,
        "next_check_at": next_check_at, "evidence_id": None, "code": "GEO_MONITOR_" + state.upper()}
    assert value["code"].isascii() and 1 <= len(value["code"]) <= 64


def test_current_native_pending_and_actual_outcome_flow_are_read_without_mutation():
    async def run():
        async with database() as sessions:
            publication_id = await adopted(sessions)
            assert_view(await read(sessions, publication_id), publication_id, "pending")
            for native, exposed in (("healthy", "observed"), ("unreachable", "unreachable"),
                                    ("mismatch", "mismatch"), ("version_changed", "version_changed")):
                async with sessions() as db:
                    variant = await db.get(GeoChannelVariant, 91)
                    pub = await db.get(GeoPublication, publication_id)
                    store_state(variant, pub, outcome(initial_state(variant), native,
                        datetime(2026, 10, 11, 8), checked_url=pub.published_url,
                        expected_sha256="a" * 64, observed_sha256="b" * 64))
                    await db.commit()
                    await db.refresh(variant)
                    before = json.loads(json.dumps(variant.adapt_meta))
                    before_updated_at = variant.updated_at
                value = await read(sessions, publication_id)
                delay = 86_400_000 if native == "healthy" else 3_600_000
                assert_view(value, publication_id, exposed, STAMP_MS, STAMP_MS + delay)
                async with sessions() as db:
                    variant = await db.get(GeoChannelVariant, 91)
                    assert variant.adapt_meta == before and variant.updated_at == before_updated_at
                    assert await db.scalar(select(func.count()).select_from(GeoPublication)) == 1
                    assert await db.scalar(text("SELECT count(*) FROM geo_distribution_publication_events")) == 1
    asyncio.run(run())


def test_actual_worker_failure_keeps_last_observation_and_only_changes_next_due_time():
    async def run():
        async with database() as sessions:
            publication_id = await adopted(sessions)
            async with sessions() as db:
                variant = await db.get(GeoChannelVariant, 91)
                pub = await db.get(GeoPublication, publication_id)
                store_state(variant, pub, outcome(initial_state(variant), "healthy", datetime(2026, 10, 11, 8),
                    checked_url=pub.published_url, expected_sha256="a" * 64, observed_sha256="b" * 64))
                await db.commit()
                await defer_monitor_failure(db, 1, 50, publication_id)
                next_due = variant.adapt_meta["publication_monitor"][str(publication_id)]["next_check_at"]
            value = await read(sessions, publication_id)
            expected = int(datetime.fromisoformat(next_due.removesuffix("Z") + "+00:00").timestamp() * 1000)
            assert_view(value, publication_id, "observed", STAMP_MS, expected)
    asyncio.run(run())


@pytest.mark.parametrize("value", [None, {}, {"publication_monitor": {}},
    {"publication_monitor": {"999": {"state": "healthy", "checked_at": STAMP}}}])
def test_absent_entry_is_not_queued_with_no_invented_dates(value):
    async def run():
        async with database() as sessions:
            publication_id = await adopted(sessions)
            await metadata(sessions, publication_id, value)
            assert_view(await read(sessions, publication_id), publication_id, "not_queued")
    asyncio.run(run())


@pytest.mark.parametrize("value", [[], "invalid", {"publication_monitor": None}, {"publication_monitor": []},
    {"publication_monitor": {"1": None}}, {"publication_monitor": {"1": []}},
    {"publication_monitor": {"1": {}}}, {"publication_monitor": {"1": {"state": "unknown"}}},
    {"publication_monitor": {"1": {"state": "captured", "checked_at": STAMP}}},
    {"publication_monitor": {"1": {"state": "healthy"}}},
    {"publication_monitor": {"1": {"state": "observed", "checked_at": False}}},
    {"publication_monitor": {"1": {"state": "healthy", "checked_at": "2026-10-11T08:00:00"}}},
    {"publication_monitor": {"1": {"state": "healthy", "checked_at": "2101-01-01T00:00:00Z"}}},
    {"publication_monitor": {"1": {"state": "pending", "next_check_at": "secret error https://private.example/token"}}},
    {"publication_monitor": {"1": {"state": True}}}])
def test_bad_metadata_fails_safe_without_echoing_source_errors_or_urls(value):
    async def run():
        async with database() as sessions:
            publication_id = await adopted(sessions)
            assert publication_id == 1
            await metadata(sessions, publication_id, value)
            result = await read(sessions, publication_id)
            assert_view(result, publication_id, "unavailable")
            assert "secret" not in json.dumps(result) and "private.example" not in json.dumps(result)
    asyncio.run(run())


@pytest.mark.parametrize("publish_mode", ["manual_export", "wechat_api"])
def test_publishing_mode_and_untrusted_extra_metadata_never_claim_observation_provenance(publish_mode):
    async def run():
        async with database() as sessions:
            publication_id = await adopted(sessions)
            async with sessions() as db:
                pub = await db.get(GeoPublication, publication_id)
                pub.publish_mode = publish_mode
                variant = await db.get(GeoChannelVariant, 91)
                variant.adapt_meta = {"publication_monitor": {str(publication_id): {"state": "healthy",
                    "checked_at": "2026-10-11T16:00:00+08:00", "next_check_at": "2026-10-12T08:00:00Z",
                    "evidence_source": "manual", "evidence_id": 99, "history": ["hidden history"],
                    "body": "private reviewed article", "observed_url": "https://private.example/token",
                    "last_error": "private error", "code": "INJECTED_ERROR"}}}
                await db.commit()
            result = await read(sessions, publication_id)
            assert_view(result, publication_id, "observed", STAMP_MS, STAMP_MS + 86_400_000)
            assert "private" not in json.dumps(result) and "INJECTED" not in json.dumps(result)
    asyncio.run(run())


def test_body_review_and_new_master_changes_do_not_rewrite_historical_monitor_state():
    async def run():
        async with database() as sessions:
            publication_id = await adopted(sessions)
            await metadata(sessions, publication_id, {"publication_monitor": {str(publication_id): {
                "state": "healthy", "checked_at": STAMP, "next_check_at": "2026-10-12T08:00:00Z"}}})
            async with sessions() as db:
                variant = await db.get(GeoChannelVariant, 91)
                variant.body_markdown = "new private body requiring fresh review"
                task = await db.get(GeoContentTask, 50)
                task.review_status = "none"
                task.reviewed_by = task.reviewed_at = None
                db.add(GeoArticleVersion(id=999, task_id=50, version_no=4, kind="master", title="new master",
                    body_markdown="new private body", outline={}, author_name="fixture", created_by=7))
                await db.commit()
                with pytest.raises(HTTPException):
                    await load_source(db, 7, 1, 10, 91, "wechat-article")
            result = await read(sessions, publication_id)
            assert_view(result, publication_id, "observed", STAMP_MS, STAMP_MS + 86_400_000)
            async with sessions() as db:
                assert (await db.get(GeoContentTask, 50)).review_status == "none"
                assert (await db.get(GeoChannelVariant, 91)).body_markdown == "new private body requiring fresh review"
    asyncio.run(run())


async def second_project(sessions):
    async with sessions() as db:
        db.add_all([GeoProject(id=11, tenant_id=1, tenant_module_id=1, name="other project",
            primary_domain="p11.example", canonical_domain="p11.example", status="active"),
            GeoOptimizationBusiness(id=21, tenant_id=1, name="business 21"),
            GeoOptimizationUnit(id=31, tenant_id=1, business_id=21, name="other unit"),
            GeoPrompt(id=41, tenant_id=1, unit_id=31, question="other scope prompt")])
        await db.commit()
        await set_binding(db, 1, 11, [21], 0, 7)
        await save_plan(db, 1, 11, {"enabled": False, "status": "active", "prompt_ids": [41],
            "interval_days": 7, "advisor_user_id": 7}, 0, 7)
        await db.commit()


@pytest.mark.parametrize("change", ["tenant", "project", "role", "actor", "assignment", "task_prompt", "pub_variant"])
def test_live_authorization_and_exact_project_ownership_cannot_be_swallowed_as_unavailable(change):
    async def run():
        async with database() as sessions:
            publication_id = await adopted(sessions)
            tenant, scope = 1, 10
            if change == "tenant":
                tenant = 2
            elif change in {"project", "task_prompt"}:
                await second_project(sessions)
                if change == "project":
                    scope = 11
                else:
                    async with sessions() as db:
                        task = await db.get(GeoContentTask, 50)
                        task.prompt_id = 41
                        await db.commit()
            else:
                async with sessions() as db:
                    if change == "role":
                        role = await db.get(Role, 5)
                        role.permissions = {"geo.assets": "view", "geo.content": "view"}
                    elif change == "actor":
                        (await db.get(User, 7)).is_active = False
                    elif change == "assignment":
                        await save_plan(db, 1, 10, {"enabled": False, "status": "paused", "prompt_ids": [40],
                            "interval_days": 7, "advisor_user_id": 7}, 1, 7)
                    else:
                        (await db.get(GeoPublication, publication_id)).variant_id = 999
                    await db.commit()
            with pytest.raises(HTTPException) as exc:
                await read(sessions, publication_id, tenant=tenant, scope=scope)
            assert exc.value.status_code == 403
            assert exc.value.detail["code"] == "GEO_MONITOR_SCOPE_FORBIDDEN"
    asyncio.run(run())


def test_missing_database_structure_is_unavailable_and_preserves_caller_transaction():
    async def run():
        async with database() as sessions:
            publication_id = await adopted(sessions)
            async with sessions() as db:
                await db.execute(text("ALTER TABLE geo_publications RENAME TO fixture_missing_publications"))
                await db.commit()
                result = await publication_monitor_status(db, 7, 1, 10, publication_id)
                assert_view(result, publication_id, "unavailable")
                assert await db.scalar(select(Role.id).where(Role.id == 5)) == 5
                await db.commit()
    asyncio.run(run())


def test_status_read_does_not_flush_caller_pending_orm_changes():
    async def run():
        async with database() as sessions:
            publication_id = await adopted(sessions)
            async with sessions() as db:
                variant = await db.get(GeoChannelVariant, 91)
                pending_role = Role(id=99, name="caller pending role", permissions={})
                db.add(pending_role)
                variant.body_markdown = "caller pending draft edit"
                result = await publication_monitor_status(db, 7, 1, 10, publication_id)
                assert_view(result, publication_id, "pending")
                assert pending_role in db.new
                assert variant.body_markdown == "caller pending draft edit" and variant in db.dirty
                assert await db.scalar(text("SELECT count(*) FROM roles WHERE id=99")) == 0
                await db.rollback()
    asyncio.run(run())


def test_missing_record_denies_without_creating_or_queueing_monitoring():
    async def run():
        async with database() as sessions:
            with pytest.raises(HTTPException) as exc:
                await read(sessions, 999)
            assert exc.value.status_code == 403
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(GeoPublication)) == 0
                assert (await db.get(GeoChannelVariant, 91)).adapt_meta == {}
    asyncio.run(run())


def test_http_service_failure_after_actual_authorization_is_unavailable_without_raw_error(monkeypatch):
    async def run():
        async with database() as sessions:
            publication_id = await adopted(sessions)
            def unavailable_projection(*args):
                raise HTTPException(503, "private upstream failure https://private.example/token")
            # Only fault-inject the pure projection after all actual DB identity,
            # role, project, tenant and publication ownership checks completed.
            monkeypatch.setattr(results, "_stored_monitor_view", unavailable_projection)
            result = await read(sessions, publication_id)
            assert_view(result, publication_id, "unavailable")
            assert "private" not in json.dumps(result)
    asyncio.run(run())
