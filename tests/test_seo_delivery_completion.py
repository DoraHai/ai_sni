"""Object delivery must not depend on unrelated site totals or rolling windows."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from test_seo_content_workflow import store as content_store, trigger
from test_seo_service_workflows import store as page_store, add_page, create, task
from app import seo_content_workflow as content_flow, seo_service_workflows as page_flow
from app.models.seo import SeoContentAsset, SeoSitePage, SeoContentPublication, SeoPageSnapshot, SeoCrawlRun
from app.models.seo_cockpit import SeoTask


@pytest.mark.parametrize("decline", ["other_articles_archived", "rolling_window", "flat"])
def test_target_delivery_completes_when_other_articles_leave_the_total(content_store, decline):
    store = content_store
    with Session(store.engine) as db:
        for ident in (10, 11):
            db.add(SeoContentAsset(id=ident, tenant_id=4, site_id=2, title="earlier article",
                status="published", published_at=datetime.utcnow() - timedelta(days=1)))
        db.commit()
    trigger(store)
    assert store.task().baseline["value"] == 2
    store.draft_ready()
    store.publication(status="published")
    with Session(store.engine) as db:
        for ident in ((10,) if decline == "flat" else (10, 11)):
            row = db.get(SeoContentAsset, ident)
            if decline == "rolling_window": row.published_at = datetime.utcnow() - timedelta(days=8)
            else: row.status = "archived"
        db.commit()
    asyncio.run(content_flow.run_content_workflows())
    asyncio.run(content_flow.run_content_workflows())
    assert store.task().status == "done"
    evidence = store.task().completion_evidence
    assert evidence["change_abs"] == 1
    assert evidence["effect_context"]["change_abs"] == (0 if decline == "flat" else -1)
    assert evidence["scope"]["publication_id"] == 91


def test_repaired_target_completes_when_other_pages_become_unhealthy(page_store):
    store = page_store
    add_page(store)
    with Session(store.engine) as db:
        for ident in (11, 12):
            db.add(SeoSitePage(id=ident, tenant_id=4, site_id=2, url=f"https://example.com/page/{ident}",
                status="healthy", issue_codes=[], last_checked_at=datetime.utcnow()))
        db.commit()
    store.edit_plan(website_max_pages=1)
    store.collector.side_effect = None
    store.collector.return_value = {"url": "https://example.com/page/10", "status_code": 200,
        "issue_codes": ["h1_missing"], "title": "needs repair"}
    parent_id = create(store, "website")["task"]["id"]
    asyncio.run(page_flow.run_service_workflows())
    asyncio.run(page_flow.run_service_workflows())
    child_id = task(store, parent_id).params["child_task_ids"][0]
    assert task(store, child_id).baseline["value"] == 2
    async def recheck():
        async with store.session() as session:
            page = await session.get(SeoSitePage, 10)
            await page_flow.save_page_snapshot(session, page,
                {"url": page.url, "status_code": 200, "issue_codes": [], "title": "repaired"}, 7, datetime.utcnow())
            for ident in (11, 12):
                other = await session.get(SeoSitePage, ident)
                other.status, other.issue_codes = "needs_fix", ["h1_missing"]
            await session.commit()
    asyncio.run(recheck())
    asyncio.run(page_flow.run_service_workflows())
    assert task(store, child_id).status == "done"
    assert task(store, child_id).completion_evidence["effect_context"]["change_abs"] == -1
    assert task(store, parent_id).status == "done"


def test_delivery_can_finish_after_seven_days_without_forging_current_output(content_store):
    store = content_store
    trigger(store)
    store.draft_ready()
    store.publication(status="published")
    with Session(store.engine) as db:
        job = db.get(SeoTask, store.task().id)
        job.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        when = datetime.utcnow() - timedelta(days=8)
        db.get(SeoContentAsset, job.params["content_id"]).published_at = when
        db.get(SeoContentPublication, 91).published_at = when
        db.commit()
    asyncio.run(content_flow.run_content_workflows())
    asyncio.run(content_flow.run_content_workflows())
    assert store.task().status == "done"
    assert store.task().completion_evidence["effect_context"]["after"] == 0


@pytest.mark.parametrize("mutation", ["missing", "failed", "dirty", "foreign_run", "unfinished_run", "stale", "future"])
def test_page_status_alone_or_bad_snapshot_cannot_complete(page_store, mutation):
    from app.api.seo_cockpit import completion
    from fastapi import HTTPException
    from sqlalchemy import select
    store = page_store
    add_page(store)
    created = datetime.now(timezone.utc) - timedelta(hours=1)
    async def setup_and_check():
        async with store.session() as session:
            page = await session.get(SeoSitePage, 10)
            snapshot = await page_flow.save_page_snapshot(session, page,
                {"url": page.url, "status_code": 200, "issue_codes": [], "title": "checked"}, 7, datetime.utcnow())
            await session.flush()
            run = await session.get(SeoCrawlRun, snapshot.crawl_run_id)
            if mutation == "missing": snapshot.url = "https://example.com/other"
            elif mutation == "failed": snapshot.status_code, snapshot.error_type = 503, "upstream_failure"
            elif mutation == "dirty": snapshot.issue_codes = ["h1_missing"]
            elif mutation == "foreign_run": run.tenant_id = 99
            elif mutation == "unfinished_run": run.status = "running"
            elif mutation == "stale": snapshot.fetched_at = (created + timedelta(hours=7)).replace(tzinfo=None)
            elif mutation == "future": snapshot.fetched_at += timedelta(days=1)
            await session.commit()
            job = SeoTask(id=900, tenant_id=4, site_id=2, action_type="page_remediation",
                params={"page_id": 10}, baseline={"metric_key": "seo.site.healthy_page_count", "value": 0}, created_at=created)
            with pytest.raises(HTTPException) as exc: await completion(session, job)
            assert exc.value.status_code == 409
    asyncio.run(setup_and_check())


@pytest.mark.parametrize("new_snapshot_proof", [False, True])
def test_same_clock_tick_requires_newer_snapshot_proof(page_store, new_snapshot_proof):
    from app.api.seo_cockpit import completion
    from fastapi import HTTPException
    store = page_store
    add_page(store)
    async def check():
        async with store.session() as session:
            page = await session.get(SeoSitePage, 10)
            baseline = await page_flow.save_page_snapshot(session, page,
                {"url": page.url, "status_code": 200, "issue_codes": ["h1_missing"]}, 7, datetime.utcnow())
            await session.flush()
            snapshot = await page_flow.save_page_snapshot(session, page,
                {"url": page.url, "status_code": 200, "issue_codes": []}, 7, datetime.utcnow())
            await session.flush()
            stamp = datetime.utcnow() - timedelta(minutes=1)
            baseline.fetched_at = stamp + timedelta(hours=8) - timedelta(seconds=1)
            page.last_checked_at = stamp
            snapshot.fetched_at = stamp + timedelta(hours=8)
            crawl = await session.get(SeoCrawlRun, snapshot.crawl_run_id)
            crawl.started_at = crawl.completed_at = stamp
            await session.commit()
            job = SeoTask(id=900, tenant_id=4, site_id=2, action_type="page_remediation",
                params={"page_id": 10, **({"source_snapshot_id": baseline.id} if new_snapshot_proof else {})},
                baseline={"value": 0}, created_at=stamp)
            if new_snapshot_proof:
                evidence = await completion(session, job)
                assert evidence["source"]["snapshot_id"] == snapshot.id
            else:
                with pytest.raises(HTTPException) as exc:
                    await completion(session, job)
                assert exc.value.status_code == 409
    asyncio.run(check())
