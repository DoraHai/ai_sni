"""Persistence and ownership tests for the independent onsite task API."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable
from test_seo_content_workflow import Store
from app.api import seo_onsite as api, seo_cockpit
from app.models.seo import SeoSitePage, SeoKeywordAsset, SeoSiteAdvisorAssignment
from app.security.auth import AuthContext

ADVISOR = AuthContext(7, "advisor", "advisor", None, {"seo.content":"edit", "seo.site":"edit", "seo.keywords":"edit"})
CUSTOMER = AuthContext(12, "customer", "customer", 4, {"seo.content":"view", "seo.site":"view"})

@pytest.fixture
def store(tmp_path, monkeypatch):
    value = Store(tmp_path/"onsite.sqlite")
    with value.engine.begin() as conn:
        for model in (SeoSitePage, SeoKeywordAsset):
            conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
    with Session(value.engine) as db:
        db.add(SeoSitePage(id=10, tenant_id=4, site_id=2, url="https://example.com/p", status="pending",
                          title_suggestion="重点词的事实标题", description_suggestion="事实描述"))
        db.add(SeoKeywordAsset(id=11, tenant_id=4, site_id=2, keyword="重点词", status="active", priority="P0", landing_page="https://example.com/p"))
        db.commit()
    async def fetch(url, **kwargs):
        assert kwargs["allowed_hosts"] == frozenset({"example.com", "www.example.com"})
        return SimpleNamespace(error_type=None, status_code=200, final_url=url,
            body='<title>重点词的事实标题</title><meta name="description" content="事实描述"><meta name="keywords" content="重点词"><body>重点词<a href="/faq">问题</a></body>')
    monkeypatch.setattr(api, "fetch_url", fetch)
    yield value
    value.engine.dispose()

def create(store, actor=ADVISOR, **values):
    async def run():
        async with store.session() as db:
            return await api.create(api.Create(tenant_id=4, site_id=2, request_id=uuid4(),
                work_type="monthly", month="2026-10", owner_name="实施员", **values), db, actor)
    return asyncio.run(run())

def act(store, task, action, actor=ADVISOR, **values):
    async def run():
        async with store.session() as db:
            return await api.act(task["id"], api.Update(tenant_id=4, site_id=2, action=action,
                expected_revision=task["workflow"]["revision"], **values), db, actor)
    return asyncio.run(run())

def test_monthly_plan_binds_keywords_and_finishes_with_real_page_receipt(store):
    row = create(store)
    value = row["workflow"]
    assert value["source"]["keywords"][0]["id"] == 11 and len(value["items"]) == 5
    items = [dict(i, expected="https://example.com/faq") if i["kind"]=="internal_link" else i for i in value["items"]]
    row = act(store, row, "save_proposal", items=items)
    row = act(store, row, "approve", note="核对重点词和事实")
    row = act(store, row, "implement", note="维护人员已修改页面")
    row = act(store, row, "recheck")
    assert row["workflow"]["phase"] == "acceptance" and row["completion_evidence"] is None
    row = act(store, row, "accept", note="核对网站实施质量")
    assert row["workflow"]["phase"] == "done" and row["completion_evidence"]["recheck"]["passed"]
    assert row["workflow"]["month"] == "2026-10"

def test_customer_cannot_create_or_inject_mutations_and_assignment_revocation_stops_writes(store):
    with pytest.raises(HTTPException) as err:
        create(store, CUSTOMER)
    assert err.value.status_code == 403
    row = create(store)
    with pytest.raises(HTTPException):
        act(store, row, "save_proposal", CUSTOMER, items=row["workflow"]["items"])
    with Session(store.engine) as db:
        db.get(SeoSiteAdvisorAssignment, 3).active = False
        db.commit()
    with pytest.raises(HTTPException) as err:
        act(store, row, "save_proposal", items=row["workflow"]["items"])
    assert err.value.status_code == 403

def test_source_change_and_old_generic_completion_cannot_bypass_current_review(store):
    row = create(store)
    async def old_path():
        async with store.session() as db:
            await seo_cockpit.update_task(row["id"], seo_cockpit.TaskUpdate(tenant_id=4, site_id=2, status="done"), ADVISOR, db)
    with pytest.raises(HTTPException) as err:
        asyncio.run(old_path())
    assert err.value.status_code == 409
    with Session(store.engine) as db:
        db.get(SeoKeywordAsset, 11).landing_page = "https://example.com/another"
        db.commit()
    with pytest.raises(HTTPException) as err:
        act(store, row, "save_proposal", items=row["workflow"]["items"])
    assert err.value.status_code == 409

def test_foreign_site_customer_and_keyword_ids_never_create_work(store):
    with pytest.raises(HTTPException):
        create(store, keyword_ids=[999])
    async def run():
        async with store.session() as db:
            with pytest.raises(HTTPException) as err:
                await api.list_tasks(5, 2, None, db, CUSTOMER)
            assert err.value.status_code == 403
        async with store.session() as db:
            with pytest.raises(HTTPException) as err:
                await api.list_tasks(4, 999, None, db, ADVISOR)
            assert err.value.status_code == 404
        async with store.session() as db:
            value = await api.list_tasks(4, 2, None, db, CUSTOMER)
            assert value["items"] == [] and value["can_create"] is False
    asyncio.run(run())

