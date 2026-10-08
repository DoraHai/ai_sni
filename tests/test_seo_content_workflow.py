"""Transactional workflow tests; SQLite persistence and an isolated renderer.

SQLite does not prove PostgreSQL row-lock behaviour. No suppliers or network.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app import seo_content_workflow as flow
from app.api import seo as api, seo_cockpit as cockpit, seo_page_captures as captures
from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import SeoContentAsset, SeoContentConfirmation, SeoContentPublication, SeoPublishAttempt, SeoSiteAdvisorAssignment
from app.models.seo_cockpit import SeoTask
from app.models.seo_page_capture import SeoPageCapture
from app.security.auth import AuthContext
from app.seo_page_capture import CaptureResult


@compiles(JSONB, "sqlite")
def jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class Adapter:
    def __init__(self, store):
        self.store = store
        self.db = Session(store.engine, expire_on_commit=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.db.close()

    def add(self, row):
        if row.id is None:
            self.store.next_id += 1
            row.id = self.store.next_id
        self.db.add(row)

    async def get(self, model, ident, **kwargs):
        return self.db.get(model, ident, **kwargs)

    async def scalar(self, query):
        return self.db.scalar(query)

    async def scalars(self, query):
        return self.db.scalars(query)

    async def execute(self, query):
        return self.db.execute(query)

    async def flush(self):
        self.db.flush()

    async def commit(self):
        self.db.commit()

    async def rollback(self):
        self.db.rollback()

    async def refresh(self, row):
        self.db.refresh(row)


class Store:
    def __init__(self, path):
        self.engine = create_engine(f"sqlite:///{path}")
        self.next_id = 100
        with self.engine.begin() as conn:
            for model in (SeoSite, TenantModule, SeoContentAsset, SeoContentConfirmation,
                          SeoContentPublication, SeoPublishAttempt, SeoSiteAdvisorAssignment, SeoTask, SeoPageCapture):
                conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
            conn.execute(text("CREATE TABLE alembic_version (version_num TEXT)"))
            conn.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": flow.SCHEMA})
        with Session(self.engine) as db:
            db.add(TenantModule(id=1, tenant_id=4, module_code="seo", status="active"))
            db.add(SeoSite(id=2, tenant_id=4, tenant_module_id=1, name="isolated", domain="example.com",
                           canonical_domain="example.com", status="active", site_settings={"seo_service_plan": {
                               "revision": 1, "status": "active", "content_topics": ["选型", "安装"],
                               "optimization_directions": ["依据公开资料"], "content_cycle_enabled": False}}))
            db.add(SeoSiteAdvisorAssignment(id=3, tenant_id=4, site_id=2, advisor_user_id=7, active=True))
            db.commit()

    def session(self):
        return Adapter(self)

    def edit_plan(self, **values):
        with Session(self.engine) as db:
            site = db.get(SeoSite, 2)
            site.site_settings = {**site.site_settings, "seo_service_plan": {**site.site_settings["seo_service_plan"], **values}}
            db.commit()

    def task(self):
        with Session(self.engine) as db:
            return db.scalar(select(SeoTask).order_by(SeoTask.id.desc()))

    def draft_ready(self, *, confirm=True):
        with Session(self.engine) as db:
            task = db.scalar(select(SeoTask))
            content = db.get(SeoContentAsset, task.params["content_id"])
            content.draft, content.status = "<p>有出处的隔离测试稿件</p>", "ready"
            if confirm:
                db.add(SeoContentConfirmation(id=90, tenant_id=4, site_id=2, content_asset_id=content.id,
                    content_version=content.version_count, content_hash=api._content_confirmation_hash(content),
                    decision="approve", actor_mode="advisor_proxy", actor_user_id=7, actor_role_name="顾问"))
            db.commit()

    def publication(self, *, status="manual_required", ident=91):
        with Session(self.engine) as db:
            task = db.scalar(select(SeoTask))
            content = db.get(SeoContentAsset, task.params["content_id"])
            row = SeoContentPublication(id=ident, tenant_id=4, content_asset_id=content.id,
                platform_code="zhihu", platform_name="知乎", publish_mode="manual", source_version=1,
                adapted_content=content.draft, status=status)
            if status == "published":
                row.page_url, row.published_at = f"https://example.com/article/{ident}", datetime.utcnow()
                content.status, content.published_at = "published", row.published_at
            db.add(row)
            db.commit()


ACTOR = AuthContext(7, "advisor", "test", None, {"seo.content": "edit", "seo.site": "edit"})


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = Store(tmp_path / "workflow.sqlite")
    monkeypatch.setattr(flow, "async_session_factory", store.session)
    monkeypatch.setattr(captures, "async_session_factory", store.session)
    settings = SimpleNamespace(seo_page_capture_enabled=True, seo_page_capture_timeout_seconds=30,
                               seo_page_capture_viewport_width=1365, seo_page_capture_viewport_height=768)
    monkeypatch.setattr(captures, "get_settings", lambda: settings)
    async def render(**kwargs):
        return CaptureResult(**{k: v for k, v in kwargs.items() if k != "url"}, source_url=kwargs["url"],
            captured_at=datetime.now(timezone.utc), status="succeeded", viewport_width=1365, viewport_height=768,
            final_url=kwargs["url"], http_status=200, sha256="a" * 64, storage_key="b" * 32 + ".png")
    renderer = AsyncMock(side_effect=render)
    monkeypatch.setattr(captures, "_capture_service", lambda: SimpleNamespace(capture_page=renderer))
    store.renderer = renderer
    yield store
    store.engine.dispose()


def trigger(store, request_id=None, actor=ACTOR, revision=1):
    async def run():
        async with store.session() as session:
            return await api.trigger_content_workflow(api.ContentWorkflowTrigger(
                tenant_id=4, site_id=2, expected_revision=revision, request_id=request_id or uuid4()), session, actor)
    return asyncio.run(run())


def advance(store, publication_id=None):
    async def run():
        background = BackgroundTasks()
        async with store.session() as session:
            result = await api.advance_content_workflow_task(store.task().id,
                api.ContentWorkflowAdvance(tenant_id=4, site_id=2, publication_id=publication_id),
                background, session, ACTOR)
        await background()
        return result
    return asyncio.run(run())


def test_trigger_replays_across_sessions_and_revision_changes(store):
    key = uuid4()
    first = trigger(store, key)
    store.edit_plan(revision=2, status="paused")
    again = trigger(store, key)
    assert first["created"] is True and again["created"] is False
    assert first["task"]["id"] == again["task"]["id"]
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoContentAsset)) == 1
    assert store.task().params["phase"] == "awaiting_draft"
    store.renderer.assert_not_awaited()


def test_one_active_chain_prevents_different_keys_flooding_drafts(store):
    trigger(store)
    with pytest.raises(HTTPException) as error:
        trigger(store)
    assert error.value.detail["code"] == "content_workflow_already_active"


@pytest.mark.parametrize("actor", [
    AuthContext(8, "not-assigned", "admin", None, {"seo.content": "edit", "seo.site": "edit"}),
    AuthContext(7, "viewer", "test", None, {"seo.content": "view", "seo.site": "view"}),
    AuthContext(7, "cross-tenant", "test", 5, {"seo.content": "edit", "seo.site": "edit"}),
    AuthContext(None, "service", "admin", None, {"seo.content": "edit", "seo.site": "edit"}),
])
def test_trigger_enforces_server_identity_assignment_and_tenant(store, actor):
    with pytest.raises(HTTPException) as error:
        trigger(store, actor=actor)
    assert error.value.status_code == 403
    assert store.task() is None


@pytest.mark.parametrize("revisions", [["0104"], [flow.SCHEMA, "unknown"], ["unknown"], []])
def test_unknown_old_or_multiple_schema_versions_do_no_work(store, revisions):
    with store.engine.begin() as conn:
        conn.execute(text("DELETE FROM alembic_version"))
        for revision in revisions:
            conn.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": revision})
    asyncio.run(flow.run_content_workflows())
    with pytest.raises(HTTPException) as error:
        trigger(store)
    assert error.value.status_code == 503
    assert store.task() is None


def test_cycle_opt_in_pause_due_and_restart_resume(store):
    asyncio.run(flow.run_content_workflows())
    assert store.task() is None
    store.edit_plan(content_cycle_enabled=True, status="paused")
    asyncio.run(flow.run_content_workflows())
    assert store.task() is None
    store.edit_plan(status="active")
    asyncio.run(flow.run_content_workflows())
    first = store.task()
    asyncio.run(flow.run_content_workflows())
    assert store.task().id == first.id
    with Session(store.engine) as db:
        db.get(SeoTask, first.id).status = "cancelled"
        db.commit()
    asyncio.run(flow.run_content_workflows())
    assert store.task().id == first.id  # next cycle not yet due
    with Session(store.engine) as db:
        site = db.get(SeoSite, 2)
        cursor = {**site.site_settings["seo_content_workflow_cursor"], "next_due_at": "2020-01-01T00:00:00+00:00"}
        site.site_settings = {**site.site_settings, "seo_content_workflow_cursor": cursor}
        db.commit()
    asyncio.run(flow.run_content_workflows())
    assert store.task().id != first.id
    assert store.task().params["plan_topic"] == "安装"


def test_exact_confirmation_then_manual_return_resumes_to_real_page_evidence(store):
    trigger(store)
    store.draft_ready(confirm=False)
    assert advance(store)["params"]["phase"] == "awaiting_confirmation"
    store.draft_ready()
    assert advance(store)["params"]["phase"] == "awaiting_publication"
    store.publication()
    assert advance(store)["params"]["phase"] == "awaiting_manual_publication"
    store.renderer.assert_not_awaited()

    async def complete():
        async with store.session() as session:
            # Real existing manual completion endpoint, no mocked publication fact.
            return await api.complete_manual_publication(91, api.DistributionManualComplete(
                tenant_id=4, site_id=2, page_url="https://example.com/article/91", source_version=1), session, ACTOR)
    result = asyncio.run(complete())
    assert result["status"] == "published"
    # Simulate lost HTTP background dispatch/restart: scheduler recovers pending.
    asyncio.run(flow.run_content_workflows())
    assert store.task().params["phase"] == "awaiting_page_evidence"
    asyncio.run(flow.run_content_workflows())
    task = store.task()
    assert task.status == "done"
    assert task.completion_evidence["change_abs"] == 1
    assert task.completion_evidence["source"]["publication_id"] == 91
    assert task.completion_evidence["seo_effect"] == "not_evaluated"
    asyncio.run(flow.run_content_workflows())
    store.renderer.assert_awaited_once()


@pytest.mark.parametrize("status", ["failed", "publishing", "pending", "unknown"])
def test_uncertain_or_failed_publications_never_retry_or_capture(store, status):
    trigger(store)
    store.draft_ready()
    store.publication(status=status)
    advance(store)
    asyncio.run(flow.run_content_workflows())
    assert store.task().params["phase"] == "publication_needs_check"
    store.renderer.assert_not_awaited()
    with Session(store.engine) as db:
        assert db.get(SeoContentPublication, 91).status == status
        assert db.scalar(select(func.count()).select_from(SeoPublishAttempt)) == 0


def test_edit_invalidates_confirmation_and_multiple_publications_require_selection(store):
    trigger(store)
    store.draft_ready()
    store.publication(status="published")
    store.publication(status="published", ident=92)
    assert advance(store)["params"]["phase"] == "awaiting_publication_selection"
    with pytest.raises(HTTPException):
        advance(store, 999)
    with Session(store.engine) as db:
        content = db.get(SeoContentAsset, store.task().params["content_id"])
        content.draft = "实质修改"
        db.commit()
    assert advance(store, 91)["params"]["blocker"] == "confirmation_stale"
    store.renderer.assert_not_awaited()


def test_pause_blocks_existing_capture_dispatch_and_reuses_it_after_resume(store):
    trigger(store)
    store.draft_ready()
    store.publication(status="published")
    async def reserve():
        async with store.session() as session:
            row, _ = await captures.reserve_publication_page_capture(session, tenant_id=4, site_id=2,
                publication_id=91, page_url="https://example.com/article/91")
            await session.commit()
            return row.id
    capture_id = asyncio.run(reserve())
    store.edit_plan(status="paused")
    asyncio.run(captures.execute_page_capture(capture_id))
    assert advance(store)["params"]["phase"] == "paused"
    store.renderer.assert_not_awaited()
    store.edit_plan(status="active")
    asyncio.run(flow.run_content_workflows())
    asyncio.run(flow.run_content_workflows())
    assert store.task().status == "done"
    assert store.task().completion_evidence["source"]["capture_id"] == capture_id
    store.renderer.assert_awaited_once()


def test_cancel_and_generic_done_cannot_bypass_evidence(store):
    trigger(store)
    async def run():
        async with store.session() as session:
            with pytest.raises(HTTPException) as error:
                await cockpit.update_task(store.task().id, cockpit.TaskUpdate(tenant_id=4, site_id=2, status="done"), ACTOR, session)
            assert error.value.status_code == 409
        async with store.session() as session:
            await cockpit.cancel_task(store.task().id, 4, 2, ACTOR, session)
    asyncio.run(run())
    asyncio.run(flow.run_content_workflows())
    assert store.task().status == "cancelled"
    store.renderer.assert_not_awaited()


def test_rollback_leaves_no_draft_task_or_cycle_cursor(store):
    async def run():
        async with store.session() as session:
            site = await session.get(SeoSite, 2)
            await flow.reserve_content_workflow(session, site, request_key="rollback", actor_id=7)
            await session.rollback()
    asyncio.run(run())
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoContentAsset)) == 0
        assert db.scalar(select(func.count()).select_from(SeoTask)) == 0
        assert "seo_content_workflow_cursor" not in db.get(SeoSite, 2).site_settings


def test_plan_update_preserves_schedule_and_cursor_for_older_clients(store):
    store.edit_plan(content_cycle_enabled=True, content_interval_days=14)
    trigger(store)
    async def update():
        async with store.session() as session:
            return await api.update_seo_service_plan(api.SeoServicePlanUpdate(
                tenant_id=4, site_id=2, expected_revision=1, optimization_directions=["技术优化"],
                content_topics=["新选题"], status="paused"), session, ACTOR)
    result = asyncio.run(update())
    assert result["content_cycle_enabled"] is True and result["content_interval_days"] == 14
    with Session(store.engine) as db:
        assert db.get(SeoSite, 2).site_settings["seo_content_workflow_cursor"]["sequence"] == 1


@pytest.mark.parametrize("status", ["pending", "running"])
def test_long_restart_recovers_only_unstarted_capture(store, status):
    trigger(store)
    store.draft_ready()
    store.publication(status="published")
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    with Session(store.engine) as db:
        publication = db.get(SeoContentPublication, 91)
        publication.published_at = (old - timedelta(minutes=1)).replace(tzinfo=None)
        db.add(SeoPageCapture(id=95, tenant_id=4, site_id=2, relation_type="publication", relation_id=91,
            source_url=publication.page_url, status=status, source="auto", captured_at=old,
            redirect_chain=[], warnings={}, viewport_width=1365, viewport_height=768))
        db.commit()
    asyncio.run(flow.run_content_workflows())
    if status == "pending":
        store.renderer.assert_awaited_once()
    else:
        store.renderer.assert_not_awaited()
        assert store.task().params["blocker"] == "timeout"


def test_failed_capture_needs_explicit_recheck_and_can_resume(store):
    trigger(store)
    store.draft_ready()
    store.publication(status="published")
    store.renderer.side_effect = RuntimeError("isolated supplier failure")
    asyncio.run(flow.run_content_workflows())
    asyncio.run(flow.run_content_workflows())
    assert store.task().params["phase"] == "page_evidence_needs_attention"
    asyncio.run(flow.run_content_workflows())
    store.renderer.assert_awaited_once()
    assert store.task().status == "in_progress"


@pytest.mark.parametrize("mutation", ["manual", "foreign_scope", "stale_confirmation"])
def test_unrelated_or_incomplete_evidence_never_completes_task(store, mutation):
    trigger(store)
    store.draft_ready()
    store.publication(status="published")
    asyncio.run(flow.run_content_workflows())
    with Session(store.engine) as db:
        task = db.get(SeoTask, store.task().id)
        capture = db.get(SeoPageCapture, task.params["capture_id"])
        if mutation == "manual":
            capture.source, capture.uploaded_by, capture.uploaded_at = "manual", 7, datetime.now(timezone.utc)
        elif mutation == "foreign_scope":
            capture.tenant_id = 5
        else:
            content = db.get(SeoContentAsset, task.params["content_id"])
            content.version_count += 1
        db.commit()
    asyncio.run(flow.run_content_workflows())
    assert store.task().status == "in_progress"
    assert store.task().completion_evidence is None


def test_multiple_platform_selection_is_scoped_and_records_actor(store):
    trigger(store)
    store.draft_ready()
    store.publication(status="published")
    store.publication(status="published", ident=92)
    advance(store, 92)
    task = advance(store)
    assert task["status"] == "done"
    assert task["params"]["publication_selected_by"] == 7
    assert task["completion_evidence"]["source"]["publication_id"] == 92
    store.renderer.assert_awaited_once()


def test_revoked_advisor_stops_scheduled_chain(store):
    trigger(store)
    store.draft_ready()
    store.publication(status="published")
    with Session(store.engine) as db:
        db.get(SeoSiteAdvisorAssignment, 3).active = False
        db.commit()
    asyncio.run(flow.run_content_workflows())
    store.renderer.assert_not_awaited()
    with pytest.raises(HTTPException) as error:
        advance(store)
    assert error.value.status_code == 403


def test_internal_due_reminder_does_not_claim_notification(store):
    trigger(store)
    with Session(store.engine) as db:
        task = db.get(SeoTask, store.task().id)
        task.params = {**task.params, "phase_since": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}
        db.commit()
    advance(store)
    assert store.task().params["attention_overdue"] is True
    assert store.task().params["notification_sent"] is False


def test_scheduler_contains_site_failure_and_reaches_later_site(store, monkeypatch):
    with Session(store.engine) as db:
        db.add(SeoSite(id=8, tenant_id=5, tenant_module_id=1, name="later", domain="later.example",
                       canonical_domain="later.example", status="active"))
        db.commit()
    worker = AsyncMock(side_effect=[RuntimeError("broken connection and rollback"), None])
    monkeypatch.setattr(flow, "process_site", worker)
    asyncio.run(flow.run_content_workflows())
    assert [call.args[0] for call in worker.await_args_list] == [2, 8]


def test_cycle_records_system_trigger_without_impersonating_advisor(store):
    store.edit_plan(content_cycle_enabled=True)
    asyncio.run(flow.run_content_workflows())
    task = store.task()
    assert task.created_by == "cockpit" and task.params["triggered_by_user_id"] is None
    with Session(store.engine) as db:
        assert db.get(SeoContentAsset, task.params["content_id"]).created_by is None


def test_capture_queue_and_rollback_failure_do_not_hide_published_fact(monkeypatch):
    publication = SimpleNamespace(id=91, tenant_id=4, status="published", page_url="https://example.com/article")
    session = SimpleNamespace(rollback=AsyncMock(side_effect=RuntimeError("connection lost")))
    monkeypatch.setattr(api, "reserve_publication_page_capture", AsyncMock(side_effect=RuntimeError("queue unavailable")))
    result = asyncio.run(api._queue_published_page_verification(session, publication, SimpleNamespace(site_id=2), None))
    assert result == {"state": "not_queued", "capture_id": None, "reason": "capture_queue_failed"}
    assert publication.status == "published"


def test_reading_task_does_not_advance_or_write(store):
    trigger(store)
    store.draft_ready()
    async def read():
        async with store.session() as session:
            session.commit = AsyncMock(side_effect=AssertionError("GET must not write"))
            result = await cockpit.get_task(store.task().id, 4, 2, ACTOR, session)
            session.commit.assert_not_awaited()
            return result
    assert asyncio.run(read())["params"]["phase"] == "awaiting_draft"
    store.renderer.assert_not_awaited()


def test_rejection_and_revision_need_new_confirmation_before_handoff(store):
    trigger(store)
    with Session(store.engine) as db:
        content = db.get(SeoContentAsset, store.task().params["content_id"])
        content.draft, content.status = "正文待内审", "draft"
        db.commit()
    assert advance(store)["params"]["phase"] == "awaiting_internal_review"
    store.draft_ready()
    with Session(store.engine) as db:
        db.get(SeoContentConfirmation, 90).decision = "reject"
        db.commit()
    assert advance(store)["params"]["blocker"] == "confirmation_rejected"
    with Session(store.engine) as db:
        content = db.get(SeoContentAsset, store.task().params["content_id"])
        content.version_count += 1
        content.draft = "根据意见修订后的正文"
        db.add(SeoContentConfirmation(id=99, tenant_id=4, site_id=2, content_asset_id=content.id,
            content_version=content.version_count, content_hash=api._content_confirmation_hash(content),
            decision="approve", actor_mode="advisor_proxy", actor_user_id=7, actor_role_name="顾问"))
        db.commit()
    assert advance(store)["params"]["phase"] == "awaiting_publication"


@pytest.mark.parametrize("plan", [{"status": "paused"}, {"content_topics": []}, {"optimization_directions": []}])
def test_paused_or_incomplete_plan_cannot_create_work(store, plan):
    store.edit_plan(**plan)
    with pytest.raises(HTTPException) as error:
        trigger(store)
    assert error.value.status_code == 409
    assert store.task() is None


def test_revision_conflict_creates_nothing(store):
    with pytest.raises(HTTPException) as error:
        trigger(store, revision=2)
    assert error.value.detail["code"] == "service_plan_version_conflict"
    assert store.task() is None
