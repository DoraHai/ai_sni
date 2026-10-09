"""Service-cycle persistence tests, using only local SQL and fake page responses."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from test_seo_content_workflow import Store, ACTOR
from app import seo_service_workflows as flows
from app.api import seo_service_workflows as api
from app.models.seo import (SeoSitePage, SeoPageSnapshot, SeoCrawlRun, SeoKeywordAsset, SeoRankSnapshot,
    SeoBacklink, SeoMetricSnapshot, SeoSiteAdvisorAssignment)
from app.models.module_workspace import SeoSite
from app.models.seo_cockpit import SeoTask, SeoImageVerification
from app.models.seo_site_analytics import SeoSiteAnalyticsMonthly, SeoSiteAnalyticsSource
from app.security.auth import AuthContext

ADVISOR = AuthContext(7, "advisor", "test", None, {"seo.content": "edit", "seo.site": "edit", "seo.keywords": "edit"})


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = Store(tmp_path / "cycles.sqlite")
    with store.engine.begin() as conn:
        for model in (SeoSitePage, SeoPageSnapshot, SeoCrawlRun, SeoKeywordAsset, SeoRankSnapshot,
                      SeoBacklink, SeoMetricSnapshot, SeoImageVerification, SeoSiteAnalyticsMonthly, SeoSiteAnalyticsSource):
            conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
    monkeypatch.setattr(flows, "async_session_factory", store.session)
    monkeypatch.setattr(flows, "get_settings", lambda: SimpleNamespace(
        seo_manual_crawl_max_urls_per_tenant_per_day=20, seo_rank_snapshot_stale_hours=36,
        seo_rank_scheduler_engine_interval_days="baidu:1"))
    async def collect(url):
        return {"url": url, "status_code": 200, "issue_codes": [], "title": "现有标题",
                "meta_description": "现有说明", "indexable": True, "word_count": 100,
                "discovery_source": "single_page", "click_depth": 0}
    store.collector = AsyncMock(side_effect=collect)
    monkeypatch.setattr(flows, "collect_page_snapshot", store.collector)
    yield store
    store.engine.dispose()


def create(store, kind, key=None, actor=ADVISOR):
    async def run():
        async with store.session() as session:
            return await api.trigger_service_cycle(api.ServiceCycleTrigger(
                tenant_id=4, site_id=2, kind=kind, expected_revision=1, request_id=key or uuid4()), session, actor)
    return asyncio.run(run())


def advance(store, task_id, **fields):
    async def run():
        background = BackgroundTasks()
        async with store.session() as session:
            result = await api.advance_execution(task_id, api.ServiceCycleAdvance(tenant_id=4, site_id=2, **fields),
                                                 background, session, ADVISOR)
        await background()
        return result
    return asyncio.run(run())


def task(store, ident):
    with Session(store.engine) as db:
        return db.get(SeoTask, ident)


def add_page(store, ident=10, **values):
    with Session(store.engine) as db:
        db.add(SeoSitePage(id=ident, tenant_id=4, site_id=2, url=f"https://example.com/page/{ident}", status="pending", **values))
        db.commit()


def add_keyword(store):
    with Session(store.engine) as db:
        db.add(SeoKeywordAsset(id=20, tenant_id=4, site_id=2, keyword="测试核心词", priority="P0", status="active"))
        db.commit()


def add_rank(store, ident, rank, when=None, **values):
    fields = {"tenant_id": 4, "site_id": 2, "keyword_id": 20, "engine": "baidu", "device": "desktop",
              "region": "全国", "subject_type": "own", "source": "test", **values}
    with Session(store.engine) as db:
        db.add(SeoRankSnapshot(id=ident, rank=rank, checked_at=when or datetime.utcnow(), **fields))
        db.commit()


def test_station_notification_is_durable_deduplicated_and_read_is_user_scoped(store):
    from app.seo_notifications import visible_events
    from app.seo_content_workflow import transition
    ident = create(store, "report")["task"]["id"]
    customer = AuthContext(8, "customer", "test", 4, {"seo.content": "view", "seo.site": "view"})
    with Session(store.engine) as db:
        row = db.get(SeoTask, ident)
        transition(row, "awaiting_confirmation", datetime.now(timezone.utc), waiting_for="customer_or_advisor")
        db.commit()
        site = db.get(SeoSite, 2)
        event = visible_events(row, customer, site, False)[0]
        original = event["id"]
        transition(row, "awaiting_confirmation", datetime.now(timezone.utc), waiting_for="customer_or_advisor")
        db.commit()
        assert visible_events(row, customer, site, False)[0]["id"] == original
    async def read():
        async with store.session() as session:
            return await api.read_notification(api.NotificationRead(tenant_id=4, site_id=2, task_id=ident,
                event_id=original), session, customer)
    assert asyncio.run(read())["read"] is True
    assert asyncio.run(read())["read"] is True
    with Session(store.engine) as db:
        row = db.get(SeoTask, ident)
        site = db.get(SeoSite, 2)
        assert visible_events(row, customer, site, False)[0]["read"] is True
        assert visible_events(row, ADVISOR, site, True)[0]["read"] is False
        transition(row, "awaiting_publication", datetime.now(timezone.utc))
        db.commit()
        assert visible_events(row, customer, site, False) == []
    with pytest.raises(HTTPException) as stale:
        asyncio.run(read())
    assert stale.value.status_code == 409


def test_notifications_reject_cross_customer_and_only_show_assigned_advisor(store):
    create(store, "report")
    foreign = AuthContext(8, "foreign", "test", 99, {"seo.content": "view", "seo.site": "view"})
    async def read(ctx):
        async with store.session() as session:
            return await api.list_notifications(4, 2, session, ctx)
    with pytest.raises(HTTPException) as denied:
        asyncio.run(read(foreign))
    assert denied.value.status_code == 403
    assert asyncio.run(read(ADVISOR))["items"]
    unassigned = AuthContext(88, "unassigned", "test", None, ADVISOR.permissions)
    assert asyncio.run(read(unassigned))["items"] == []


def test_diagnosis_claim_restart_and_completion_create_real_snapshots(store):
    add_page(store)
    ident = create(store, "website")["task"]["id"]
    asyncio.run(flows.run_service_workflows())
    asyncio.run(flows.run_service_workflows())
    row = task(store, ident)
    assert row.status == "done"
    assert row.completion_evidence["metric_key"] == "seo.site.observation_count"
    assert row.completion_evidence["change_abs"] == 1
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoPageSnapshot)) == 1
        assert db.scalar(select(func.count()).select_from(SeoCrawlRun)) == 1
    asyncio.run(flows.execute_diagnosis_page(ident))
    store.collector.assert_awaited_once()


def test_diagnosed_problem_creates_child_and_waits_for_real_recheck(store):
    add_page(store)
    store.collector.side_effect = None
    store.collector.return_value = {"url": "https://example.com/page/10", "status_code": 200,
                                   "issue_codes": ["h1_missing"], "title": "待优化"}
    ident = create(store, "website")["task"]["id"]
    asyncio.run(flows.run_service_workflows())
    asyncio.run(flows.run_service_workflows())
    parent = task(store, ident)
    assert parent.params["phase"] == "awaiting_site_implementation"
    assert len(parent.params["child_task_ids"]) == 1
    child_id = parent.params["child_task_ids"][0]
    assert task(store, child_id).status == "open"
    async def recheck():
        # Reuse real snapshot writer, just as the existing single-page API does.
        async with store.session() as session:
            page = await session.get(SeoSitePage, 10)
            await flows.save_page_snapshot(session, page,
                {"url": page.url, "status_code": 200, "issue_codes": [], "title": "已修复"}, 7, datetime.utcnow())
            await session.commit()
    asyncio.run(recheck())
    asyncio.run(flows.run_service_workflows())
    assert task(store, child_id).status == "done"
    assert task(store, ident).status == "done"


def test_failed_observation_requires_explicit_retry(store):
    add_page(store)
    store.collector.side_effect = RuntimeError("network unavailable")
    ident = create(store, "website")["task"]["id"]
    asyncio.run(flows.run_service_workflows())
    asyncio.run(flows.run_service_workflows())
    store.collector.assert_awaited_once()
    assert task(store, ident).params["phase"] == "diagnosis_needs_attention"
    store.collector.side_effect = None
    store.collector.return_value = {"url": "https://example.com/page/10", "status_code": 200, "issue_codes": []}
    advance(store, ident, retry_page_id=10)
    asyncio.run(flows.run_service_workflows())
    assert task(store, ident).status == "done"
    assert store.collector.await_count == 2


def test_stale_running_claim_is_not_replayed(store):
    add_page(store)
    ident = create(store, "website")["task"]["id"]
    with Session(store.engine) as db:
        row = db.get(SeoTask, ident)
        row.params = {**row.params, "pages": {"10": {"state": "running", "token": "previous-process",
                       "started_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}}}
        db.commit()
    asyncio.run(flows.run_service_workflows())
    assert task(store, ident).params["pages"]["10"]["state"] == "failed"
    store.collector.assert_not_awaited()


def test_pause_then_cancel_prevents_new_external_work(store):
    add_page(store)
    ident = create(store, "website")["task"]["id"]
    store.edit_plan(status="paused")
    asyncio.run(flows.run_service_workflows())
    assert task(store, ident).params["phase"] == "paused"
    store.collector.assert_not_awaited()
    async def cancel():
        async with store.session() as session:
            await api.cancel_execution(ident, 4, 2, session, ADVISOR)
    asyncio.run(cancel())
    store.edit_plan(status="active")
    asyncio.run(flows.run_service_workflows())
    assert task(store, ident).status == "cancelled"
    store.collector.assert_not_awaited()


def test_monitoring_missing_data_task_waits_for_same_scope_fresh_observation(store):
    add_keyword(store)
    ident = create(store, "monitoring")["task"]["id"]
    assert task(store, ident).params["issues"][0]["reason"] == "missing"
    add_rank(store, 40, 3, engine="google")
    add_rank(store, 41, 3, site_id=99)
    advance(store, ident)
    assert task(store, ident).status == "in_progress"
    add_rank(store, 42, None)
    advance(store, ident)
    assert task(store, ident).status == "done"
    assert task(store, ident).completion_evidence["source"]["rank_snapshot_ids"] == [42]
    store.collector.assert_not_awaited()


def test_rank_drop_requires_observed_recovery_not_just_new_poll(store):
    add_keyword(store)
    add_rank(store, 40, 3, datetime.utcnow() - timedelta(hours=2))
    add_rank(store, 41, 15, datetime.utcnow() - timedelta(hours=1))
    ident = create(store, "monitoring")["task"]["id"]
    add_rank(store, 42, 14)
    advance(store, ident)
    assert task(store, ident).status == "in_progress"
    add_rank(store, 43, 0)
    advance(store, ident)
    assert task(store, ident).status == "in_progress"
    add_rank(store, 44, 3)
    advance(store, ident)
    assert task(store, ident).status == "done"


def test_clean_monitoring_replay_is_cancelled_noop_not_fake_done(store):
    add_keyword(store)
    add_rank(store, 40, 3)
    key = uuid4()
    first = create(store, "monitoring", key)
    again = create(store, "monitoring", key)
    assert first["task"]["status"] == "cancelled"
    assert first["task"]["params"]["phase"] == "no_actionable_issues"
    assert first["task"]["id"] == again["task"]["id"] and again["created"] is False
    assert first["task"]["completion_evidence"] is None


def test_monthly_report_freezes_html_and_requires_exact_hash_explanation(store):
    ident = create(store, "report")["task"]["id"]
    advance(store, ident)
    row = task(store, ident)
    report = row.params["report"]
    assert "无数据" in report["html"]
    assert report["pdf_generated"] is False
    assert row.params["phase"] == "awaiting_advisor_explanation"
    with pytest.raises(HTTPException) as error:
        advance(store, ident, explanation="缺数已说明", report_sha256="a" * 64)
    assert error.value.status_code == 409
    advance(store, ident, explanation="本月没有已接入统计数据，不能判断流量效果。", report_sha256=report["sha256"])
    row = task(store, ident)
    assert row.status == "done" and row.completion_evidence["change_abs"] == 1
    assert row.params["report"]["sha256"] == report["sha256"]
    assert row.params["explanation"]["actor_user_id"] == 7
    store.collector.assert_not_awaited()


def test_monthly_scheduler_replays_same_period_once_and_does_not_require_customer(store):
    store.edit_plan(report_cycle_enabled=True)
    asyncio.run(flows.run_service_workflows())
    asyncio.run(flows.run_service_workflows())
    with Session(store.engine) as db:
        row = db.scalar(select(SeoTask).where(SeoTask.action_type == "monthly_report"))
        ident, digest = row.id, row.params["report"]["sha256"]
    advance(store, ident, explanation="顾问业务说明", report_sha256=digest)
    asyncio.run(flows.run_service_workflows())
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoTask).where(SeoTask.action_type == "monthly_report")) == 1


def test_read_projection_and_report_are_pure_scoped_and_capabilities_derived(store):
    ident = create(store, "report")["task"]["id"]
    advance(store, ident)
    async def read(actor):
        async with store.session() as session:
            session.commit = AsyncMock(side_effect=AssertionError("GET must not mutate"))
            listing = await api.list_executions(4, 2, 1, 1, session, actor)
            detail = await api.get_execution(ident, 4, 2, session, actor)
            report = await api.read_report(ident, 4, 2, session, actor)
            return listing, detail, report
    listing, detail, report = asyncio.run(read(ADVISOR))
    assert listing["total"] == 1 and len(listing["items"]) == 1
    assert "html" not in detail["params"]["report"]
    assert detail["allowed_actions"]["explain_report"] is True
    assert "sandbox" in report.headers["content-security-policy"]
    viewer = AuthContext(9, "customer", "test", 4, {"seo.site": "view", "seo.content": "view"})
    assert asyncio.run(read(viewer))[1]["allowed_actions"]["advance"] is False
    foreign = AuthContext(9, "foreign", "test", 5, {"seo.site": "view", "seo.content": "view"})
    with pytest.raises(HTTPException):
        asyncio.run(read(foreign))
    store.collector.assert_not_awaited()


def test_keyword_edit_permission_required_for_monitoring_trigger(store):
    add_keyword(store)
    with pytest.raises(HTTPException) as error:
        create(store, "monitoring", actor=ACTOR)
    assert error.value.status_code == 403


def test_missing_keyword_cycle_does_not_rollback_website_or_report_work(store):
    add_page(store)
    store.edit_plan(website_cycle_enabled=True, monitoring_cycle_enabled=True, report_cycle_enabled=True)
    asyncio.run(flows.run_service_workflows())
    with Session(store.engine) as db:
        assert set(db.scalars(select(SeoTask.action_type))) == {"site_diagnosis", "monthly_report"}
        cursor = db.get(SeoSite, 2).site_settings["seo_service_cycle_cursors"]["monitoring"]
        assert cursor["blocker"]["code"] == "keyword_inventory_required"
    asyncio.run(flows.run_service_workflows())
    store.collector.assert_awaited_once()


def test_existing_running_page_prevents_parallel_claim_of_another_page(store):
    add_page(store)
    add_page(store, 11)
    ident = create(store, "website")["task"]["id"]
    with Session(store.engine) as db:
        row = db.get(SeoTask, ident)
        row.params = {**row.params, "pages": {"10": {"state": "running", "started_at": datetime.now(timezone.utc).isoformat()},
                                              "11": {"state": "queued"}}}
        db.commit()
    asyncio.run(flows.execute_diagnosis_page(ident))
    store.collector.assert_not_awaited()


def test_page_scope_and_host_are_rechecked_before_external_request(store):
    add_page(store)
    ident = create(store, "website")["task"]["id"]
    with Session(store.engine) as db:
        db.get(SeoSitePage, 10).url = "https://unrelated.example/page"
        db.commit()
    asyncio.run(flows.execute_diagnosis_page(ident))
    store.collector.assert_not_awaited()
    assert task(store, ident).params["pages"]["10"]["error"] == "page_url_outside_site"


def test_newer_manual_audit_is_not_overwritten_by_late_periodic_result(store):
    add_page(store)
    ident = create(store, "website")["task"]["id"]
    async def racing_fetch(url):
        with Session(store.engine) as db:
            page = db.get(SeoSitePage, 10)
            page.title, page.last_checked_at = "人工复检的新事实", datetime.utcnow()
            db.commit()
        return {"url": url, "status_code": 200, "issue_codes": [], "title": "旧响应"}
    store.collector.side_effect = racing_fetch
    asyncio.run(flows.execute_diagnosis_page(ident))
    with Session(store.engine) as db:
        assert db.get(SeoSitePage, 10).title == "人工复检的新事实"
    assert task(store, ident).params["pages"]["10"]["state"] == "failed"


def test_report_uses_frozen_stored_traffic_without_credentials_or_article_attribution(store):
    from app.models.seo_site_analytics import SeoSiteAnalyticsMonthly, SeoSiteAnalyticsSource
    month = flows.previous_month(datetime.now(timezone.utc))
    with Session(store.engine) as db:
        db.add(SeoSiteAnalyticsSource(id=30, tenant_id=4, site_id=2, source="baidu_tongji", enabled=True,
                                     secret_ciphertext="SENSITIVE_TEST_SENTINEL", config={}))
        db.add(SeoSiteAnalyticsMonthly(id=31, tenant_id=4, site_id=2, source="baidu_tongji", month=month,
                                      status="ok", uv=23, pv=45, raw_meta={}, fetched_at=datetime.now(timezone.utc)))
        db.commit()
    ident = create(store, "report")["task"]["id"]
    advance(store, ident)
    frozen = task(store, ident).params["report"]
    assert "SENSITIVE_TEST_SENTINEL" not in frozen["html"]
    assert frozen["scope"] == "site_month" and frozen["analytics_row_ids"] == [31]
    with Session(store.engine) as db:
        db.get(SeoSiteAnalyticsMonthly, 31).uv = 999
        db.commit()
    advance(store, ident)
    assert task(store, ident).params["report"]["sha256"] == frozen["sha256"]


def test_monitoring_reader_needs_keyword_permission_even_with_site_content_access(store):
    add_keyword(store)
    ident = create(store, "monitoring")["task"]["id"]
    async def read():
        async with store.session() as session:
            with pytest.raises(HTTPException) as error:
                await api.get_execution(ident, 4, 2, session, ACTOR)
            assert error.value.status_code == 403
            return await api.list_executions(4, 2, 1, 20, session, ACTOR)
    assert asyncio.run(read())["total"] == 0


def test_report_pause_resume_preserves_frozen_artifact_and_restores_human_stage(store):
    ident = create(store, "report")["task"]["id"]
    advance(store, ident)
    digest = task(store, ident).params["report"]["sha256"]
    store.edit_plan(status="paused")
    asyncio.run(flows.run_service_workflows())
    assert task(store, ident).params["phase"] == "paused"
    store.edit_plan(status="active")
    asyncio.run(flows.run_service_workflows())
    assert task(store, ident).params["phase"] == "awaiting_advisor_explanation"
    assert task(store, ident).params["report"]["sha256"] == digest


def test_default_cycles_do_not_create_or_collect_anything(store):
    add_page(store)
    add_keyword(store)
    asyncio.run(flows.run_service_workflows())
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoTask)) == 0
    store.collector.assert_not_awaited()


def test_quota_limit_does_not_start_or_double_charge_observation(store, monkeypatch):
    from app.models.module_workspace import TenantModule
    from app.seo_usage_limits import SEO_USAGE_TIMEZONE
    add_page(store)
    ident = create(store, "website")["task"]["id"]
    with Session(store.engine) as db:
        db.get(TenantModule, 1).module_settings = {"seo_daily_usage": {
            "date": datetime.now(SEO_USAGE_TIMEZONE).date().isoformat(), "crawl_urls": 20}}
        db.commit()
    asyncio.run(flows.execute_diagnosis_page(ident))
    assert task(store, ident).params["blocker"] == "crawl_quota_exhausted"
    store.collector.assert_not_awaited()
    with Session(store.engine) as db:
        assert db.get(TenantModule, 1).module_settings["seo_daily_usage"]["crawl_urls"] == 20


def test_explicit_report_preparation_counts_for_current_scheduled_period(store):
    store.edit_plan(report_cycle_enabled=True)
    ident = create(store, "report")["task"]["id"]
    advance(store, ident)
    digest = task(store, ident).params["report"]["sha256"]
    advance(store, ident, explanation="顾问说明", report_sha256=digest)
    asyncio.run(flows.run_service_workflows())
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoTask)) == 1


def test_http_routes_validate_trigger_and_expose_real_read_contract(store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/seo")
    async def session_dependency():
        async with store.session() as session:
            yield session
    app.dependency_overrides[api.get_session] = session_dependency
    app.dependency_overrides[api.require_scoped_auth] = lambda: ADVISOR
    with TestClient(app) as client:
        invalid = client.post("/api/v1/seo/workbench/service-cycles/run", json={
            "tenant_id": 4, "site_id": 2, "kind": "report", "expected_revision": 1, "request_id": "not-a-uuid"})
        assert invalid.status_code == 422
        result = client.post("/api/v1/seo/workbench/service-cycles/run", json={
            "tenant_id": 4, "site_id": 2, "kind": "report", "expected_revision": 1, "request_id": str(uuid4())})
        assert result.status_code == 200
        ident = result.json()["task"]["id"]
        listing = client.get("/api/v1/seo/workbench/executions", params={"tenant_id": 4, "site_id": 2, "page_size": 1})
        assert listing.status_code == 200 and listing.json()["total"] == 1
        assert listing.json()["read_only"] is True
        result = client.post(f"/api/v1/seo/workbench/executions/{ident}/advance", json={"tenant_id": 4, "site_id": 2})
        assert result.status_code == 200 and result.json()["read_only"] is False
        report = client.get(f"/api/v1/seo/workbench/executions/{ident}/report", params={"tenant_id": 4, "site_id": 2})
        assert report.status_code == 200 and "无数据" in report.text
