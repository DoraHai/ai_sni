"""Real PostgreSQL permissions, durable quota, nonce and in-flight race tests.

Only the existing explicitly opted-in loopback test DB and random owned schemas.
All provider calls are replaced; no production customers, network or new DDL.
"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
import json
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.schema import CreateTable

from test_seo_workflow_postgres import database, ADVISOR
from app import seo_onsite_ai as ai, seo_onsite_ai_jobs as jobs
from app.api import seo_onsite_ai as api, seo_onsite as onsite
from app.api_metering import scope as meter_scope
from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import SeoSitePage, SeoSiteAdvisorAssignment, SeoKeywordAsset
from app.models.seo_cockpit import SeoTask
from app.models.seo_qa import SeoQaFact
from app.models.tenant import Tenant
from app.models.user import User
from app.models.role import Role
from app.security.auth import AuthContext

REAL_CHAT_JSON = ai.deepseek.chat_json

pytestmark = pytest.mark.skipif(not os.getenv("SEO_WORKFLOW_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")


@asynccontextmanager
async def fixture():
    async with database() as sessions:
        async with sessions() as db:
            await db.execute(CreateTable(SeoSitePage.__table__, include_foreign_key_constraints=[]))
            db.add(SeoSitePage(id=10, tenant_id=4, site_id=2, url="https://example.com/p",
                status="checked", http_status=200, last_checked_at=datetime(2026, 10, 10),
                title="事实标题", meta_description="公开说明"))
            kw = await db.get(SeoKeywordAsset, 20)
            kw.priority, kw.landing_page = "P0", "https://example.com/p"
            await db.commit()
        async with sessions() as db:
            task = await onsite.create(onsite.Create(tenant_id=4, site_id=2, request_id=uuid4(),
                work_type="monthly", month="2026-10", owner_name="人工实施员"), db, ADVISOR)
        yield sessions, task


def request(task, **updates):
    return api.Request(**(dict(tenant_id=4, site_id=2, expected_revision=task["workflow"]["revision"],
                              request_id=uuid4(), mode="initial") | updates))


async def complete(sessions, task_id, req, db, ctx):
    """Exercise production enqueue + independent worker + polling transactions."""
    queued = await api.ai_proposal(task_id, req, db, ctx)
    if queued["replayed"]:
        return queued
    state = await jobs.execute_request(task_id, req.tenant_id, req.site_id, str(req.request_id), sessions=sessions)
    if state == "stale":
        raise HTTPException(409, {"code":"onsite_ai_result_stale"})
    await db.rollback()
    db.expire_all()
    return await api.proposal_status(task_id, req.request_id, req.tenant_id, req.site_id, db, ctx)


def answer(facts):
    items = []
    for item in facts["items"]:
        expected = "https://example.com/p" if item["kind"] == "internal_link" else "公开资料建议"
        if item["kind"] in {"keyword", "meta_keywords"}:
            expected = facts["keywords"][0]["keyword"]
        items.append({**item, "expected": expected, "reason": "依据资料，需人工核实", "source_refs": ["fact:30:v1"],
                      "missing_information": []})
    return {"items": items}


@pytest.fixture(autouse=True)
def supplier(monkeypatch):
    calls = []
    monkeypatch.setattr(ai.deepseek, "_resolve_creds", lambda: ("dummy-not-real", "https://api.deepseek.com", "deepseek-chat"))
    async def chat(system, user, **kwargs):
        calls.append(meter_scope.get())
        return answer(json.loads(user))
    monkeypatch.setattr(ai.deepseek, "chat_json", chat)
    return calls


def test_success_replay_scope_and_manual_review_boundary(supplier):
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            async with sessions() as db:
                result = await complete(sessions, task["id"], req, db, ADVISOR)
            assert result["workflow"]["phase"] == "review" and result["workflow"]["revision"] == 2
            assert result["workflow"]["ai_run"]["request_id"] == str(req.request_id)
            assert result["workflow"]["ai_run"]["state"] == "ready"
            assert "reason" not in result["workflow"]["items"][0]
            assert result["workflow"]["ai_proposal"]["items"][0]["source_refs"] == ["fact:30:v1"]
            assert result["completion_evidence"] is None and "approval" not in result["workflow"]
            assert result["capabilities"]["website_execution"]["enabled"] is False
            assert len(supplier) == 1
            meter = supplier[0]
            assert (meter.tenant_id, meter.user_id, meter.module, meter.operation) == (4, 7, "seo", "seo.onsite_ai_proposal")
            assert meter.job_ref == f"site:2:onsite_ai_proposal:{task['id']}:{req.request_id}"
            async with sessions() as db:
                replay = await complete(sessions, task["id"], req, db, ADVISOR)
                assert replay["replayed"] and len(supplier) == 1
                assert (await db.get(SeoSite, 2)).site_settings["onsite_ai_quota"]["count"] == 1
                with pytest.raises(HTTPException) as exc:
                    await complete(sessions, task["id"], req.model_copy(update={"mode": "revise"}), db, ADVISOR)
                assert exc.value.status_code == 409
            async with sessions() as db:
                edited = await onsite.act(task["id"], onsite.Update(tenant_id=4,site_id=2,action="save_proposal",
                    expected_revision=2, items=result["workflow"]["items"]),db,ADVISOR)
                assert "ai_proposal" not in edited["workflow"]
    asyncio.run(run())


def test_nonce_concurrency_has_one_provider_and_releases_site_lock(monkeypatch, supplier):
    async def run():
        async with fixture() as (sessions, task):
            entered, finish = asyncio.Event(), asyncio.Event()
            original = ai.deepseek.chat_json
            async def blocked(*args, **kwargs):
                entered.set()
                await finish.wait()
                return await original(*args, **kwargs)
            monkeypatch.setattr(ai.deepseek, "chat_json", blocked)
            req = request(task)
            async def call():
                async with sessions() as db: return await complete(sessions, task["id"],req,db,ADVISOR)
            first = asyncio.create_task(call())
            await asyncio.wait_for(entered.wait(), 3)
            replays = await asyncio.wait_for(asyncio.gather(*(call() for _ in range(4))), 3)
            assert all(r["replayed"] and r["workflow"]["ai_run"]["state"] == "running" for r in replays)
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await complete(sessions, task["id"], request(task), db, ADVISOR)
                assert exc.value.detail["code"] == "onsite_ai_busy"
            finish.set()
            assert (await first)["workflow"]["ai_run"]["state"] == "ready" and len(supplier) == 1
    asyncio.run(run())


@pytest.mark.parametrize("change", ["manual", "assignment", "role", "user", "binding", "module", "site", "fact", "page", "keyword", "cancel"])
def test_inflight_changes_discard_output_without_overwriting_or_leaking(monkeypatch, supplier, change):
    async def run():
        async with fixture() as (sessions, task):
            original = ai.deepseek.chat_json
            async def changed(*args, **kwargs):
                async with sessions() as db:
                    if change == "manual":
                        row=await db.get(SeoTask,task["id"])
                        row.params={**row.params,"onsite":{**row.params["onsite"],"revision":2}}
                    elif change == "cancel":
                        await onsite.act(task["id"], onsite.Update(tenant_id=4,site_id=2,
                            action="cancel" if change == "cancel" else "save_proposal", expected_revision=1,
                            note="人工取消" if change == "cancel" else "", items=None if change == "cancel" else task["workflow"]["items"]), db, ADVISOR)
                    elif change == "assignment": (await db.get(SeoSiteAdvisorAssignment,3)).active=False
                    elif change == "role": (await db.get(Role,5)).permissions={"seo.site":"view","seo.content":"view"}
                    elif change == "user": (await db.get(User,7)).is_active=False
                    elif change == "binding": (await db.get(User,7)).tenant_id=99
                    elif change == "module": (await db.get(TenantModule,1)).expires_at=date(2020,1,1)
                    elif change == "site": (await db.get(SeoSite,2)).status="paused"
                    elif change == "fact": (await db.get(SeoQaFact,30)).statement="Changed facts"
                    elif change == "page": (await db.get(SeoSitePage,10)).title="Changed page"
                    elif change == "keyword": (await db.get(SeoKeywordAsset,20)).landing_page="https://example.com/moved"
                    await db.commit()
                return await original(*args, **kwargs)
            monkeypatch.setattr(ai.deepseek,"chat_json",changed)
            async with sessions() as db:
                if change=="cancel":
                    assert (await complete(sessions,task["id"],request(task),db,ADVISOR))["request_run"]["state"]=="unknown"
                else:
                    with pytest.raises(HTTPException) as exc: await complete(sessions, task["id"],request(task),db,ADVISOR)
                    assert exc.value.status_code==409 and "items" not in exc.value.detail
            async with sessions() as db:
                row=await db.get(SeoTask,task["id"])
                w=row.params["onsite"]
                assert w["ai_run"]["state"]==("unknown" if change=="cancel" else "stale") and "ai_proposal" not in w
                assert w["items"]==task["workflow"]["items"]
                assert w["revision"]==(2 if change in {"manual","cancel"} else 1)
                assert (await db.get(SeoSite,2)).site_settings["onsite_ai_quota"]["count"]==1
    asyncio.run(run())


@pytest.mark.parametrize("kind,state", [("timeout","unknown"),("http","failed"),("malformed","unknown")])
def test_supplier_failures_are_durable_sanitized_and_never_auto_retry(monkeypatch,kind,state):
    async def run():
        async with fixture() as (sessions, task):
            calls=[]
            async def failure(*args, **kwargs):
                calls.append(1)
                if kind=="timeout": raise TimeoutError("secret supplier body")
                if kind=="malformed": return {"items":[],"secret":"sk-secret"}
                r=httpx.Response(503,request=httpx.Request("POST","https://api.deepseek.com"))
                raise httpx.HTTPStatusError("secret",request=r.request,response=r)
            monkeypatch.setattr(ai.deepseek,"chat_json",failure)
            req=request(task)
            async with sessions() as db:
                result=await complete(sessions, task["id"],req,db,ADVISOR)
                assert result["workflow"]["ai_run"]["state"]==state
                assert "secret" not in json.dumps(result)
                assert result["workflow"]["revision"]==1
            async with sessions() as db:
                assert (await complete(sessions, task["id"],req,db,ADVISOR))["replayed"]
            assert len(calls)==1
    asyncio.run(run())


def test_daily_cap_and_nonce_conflict_hold_with_platform_controls_disabled(supplier):
    async def run():
        async with fixture() as (sessions, task):
            for index in range(5):
                req=request(task,mode="initial" if index==0 else "revise")
                async with sessions() as db: task=await complete(sessions, task["id"],req,db,ADVISOR)
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await complete(sessions, task["id"],request(task,mode="revise"),db,ADVISOR)
                assert exc.value.status_code==429
            assert len(supplier)==5
            assert not task["capabilities"]["ai_planning"]["can_generate"]
    asyncio.run(run())


def test_advisor_list_filters_before_cursor_and_never_writes(supplier):
    async def run():
        async with fixture() as (sessions, task):
            async with sessions() as db:
                db.add_all([Tenant(id=99,name="unassigned customer"),
                    TenantModule(id=99,tenant_id=99,module_code="seo",status="active"),
                    SeoSite(id=99,tenant_id=99,tenant_module_id=99,name="foreign",domain="foreign.example",canonical_domain="foreign.example",status="active")])
                for index in range(2,8):
                    db.add(SeoTask(id=100+index,tenant_id=4 if index%2==0 else 99,site_id=2 if index%2==0 else 99,
                        module="seo",action_type=onsite.ACTION_TYPE,title="task",params={"onsite":deepcopy(task["workflow"])},
                        status="open",created_by="7",assignee_role="seo_advisor",baseline={}))
                await db.commit()
            async with sessions() as db:
                page=await api.advisor_tasks(None,2,None,db,ADVISOR)
                assert [i["id"] for i in page["items"]]==[106,104] and page["next_before_id"]==104
                second=await api.advisor_tasks(104,2,None,db,ADVISOR)
                assert [i["id"] for i in second["items"]]==[102,task["id"]] and second["next_before_id"] is None
                assert all(i["tenant_name"]=="isolated" and i["scope_name"]=="isolated" for i in page["items"])
                assert not db.dirty and not db.new and not supplier
            async with sessions() as db:
                (await db.get(SeoSiteAdvisorAssignment,3)).active=False
                await db.commit()
            async with sessions() as db:
                assert (await api.advisor_tasks(None,50,None,db,ADVISOR))["items"]==[]
    asyncio.run(run())


def test_cross_customer_stale_revision_and_closed_tasks_do_not_call(supplier):
    async def run():
        async with fixture() as (sessions, task):
            cases=[request(task,tenant_id=99),request(task,site_id=99),request(task,expected_revision=2)]
            for req in cases:
                async with sessions() as db:
                    with pytest.raises(HTTPException): await complete(sessions, task["id"],req,db,ADVISOR)
            async with sessions() as db:
                await onsite.act(task["id"],onsite.Update(tenant_id=4,site_id=2,expected_revision=1,
                    action="cancel",note="取消"),db,ADVISOR)
            async with sessions() as db:
                with pytest.raises(HTTPException): await complete(sessions, task["id"],request(task,expected_revision=2),db,ADVISOR)
                assert "onsite_ai_quota" not in (await db.get(SeoSite,2)).site_settings
            assert not supplier
    asyncio.run(run())


def test_revision_after_failed_recheck_clears_all_prior_evidence(supplier):
    async def run():
        async with fixture() as (sessions, task):
            async with sessions() as db:
                row=await db.get(SeoTask,task["id"])
                w={**row.params["onsite"],"phase":"recheck","approval":{"hash":"old"},
                   "implementation":{"note":"old"},"recheck":{"passed":False},"acceptance":{"note":"old"}}
                row.params={**row.params,"onsite":w}
                row.completion_evidence={"old":"evidence"}
                await db.commit()
            async with sessions() as db:
                result=await complete(sessions, task["id"],request(task,mode="revise"),db,ADVISOR)
                assert result["workflow"]["phase"]=="review"
                assert not set(result["workflow"]) & {"approval","implementation","recheck","acceptance"}
                assert result["completion_evidence"] is None
    asyncio.run(run())


def test_stale_running_nonce_becomes_unknown_without_any_second_call(monkeypatch,supplier):
    async def run():
        async with fixture() as (sessions, task):
            started,finish=asyncio.Event(),asyncio.Event()
            original=ai.deepseek.chat_json
            async def slow(*args,**kwargs):
                started.set(); await finish.wait()
                return await original(*args,**kwargs)
            monkeypatch.setattr(ai.deepseek,"chat_json",slow)
            req=request(task)
            async def call():
                async with sessions() as db: return await complete(sessions, task["id"],req,db,ADVISOR)
            operation=asyncio.create_task(call())
            await asyncio.wait_for(started.wait(),3)
            async with sessions() as db:
                row=await db.get(SeoTask,task["id"])
                run=dict(row.params["onsite_ai_requests"][str(req.request_id)])
                run["started_at"]=(ai.now()-timedelta(minutes=3)).isoformat()
                api.save_run(row,run)
                await db.commit()
            await jobs.execute_request(task["id"],4,2,str(req.request_id),sessions=sessions)
            replay=await call()
            assert replay["workflow"]["ai_run"]["state"]=="unknown" and replay["replayed"]
            finish.set()
            assert (await operation)["request_run"]["state"]=="unknown"
            async with sessions() as db:
                w=(await db.get(SeoTask,task["id"])).params["onsite"]
                assert w["revision"]==1 and w["ai_run"]["state"]=="unknown"
            assert len(supplier)==1
    asyncio.run(run())


def test_site_quota_serializes_different_tasks_before_provider(supplier):
    async def run():
        async with fixture() as (sessions, task):
            async with sessions() as db:
                site=await db.get(SeoSite,2)
                site.site_settings={**site.site_settings,"onsite_ai_quota":{"day":ai.day(),"count":4}}
                row=await db.get(SeoTask,task["id"])
                db.add(SeoTask(id=100,tenant_id=4,site_id=2,module="seo",action_type=onsite.ACTION_TYPE,
                    title="second task",params={"onsite":deepcopy(row.params["onsite"])},status="open",created_by="7",
                    assignee_role="seo_advisor",baseline={}))
                await db.commit()
            async def call(ident):
                async with sessions() as db:
                    try: return await api.ai_proposal(ident,request(task),db,ADVISOR)
                    except HTTPException as exc: return exc.status_code
            results=await asyncio.gather(call(task["id"]),call(100))
            assert sum(isinstance(r,dict) for r in results)==1 and 429 in results
            assert not supplier
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            assert len(supplier)==1
    asyncio.run(run())


@pytest.mark.parametrize("change",["bound_elsewhere","inactive_site","expired_module","readonly_role","other_advisor"])
def test_advisor_queue_does_not_leak_unavailable_scope(change):
    async def run():
        async with fixture() as (sessions,task):
            async with sessions() as db:
                if change=="bound_elsewhere": (await db.get(User,7)).tenant_id=99
                elif change=="inactive_site": (await db.get(SeoSite,2)).status="paused"
                elif change=="expired_module": (await db.get(TenantModule,1)).expires_at=date(2020,1,1)
                elif change=="readonly_role": (await db.get(Role,5)).permissions={"seo.site":"view","seo.content":"view"}
                elif change=="other_advisor": (await db.get(SeoSiteAdvisorAssignment,3)).advisor_user_id=8
                await db.commit()
            async with sessions() as db:
                page=await api.advisor_tasks(None,50,None,db,ADVISOR)
                assert page["items"]==[] and page["next_before_id"] is None
    asyncio.run(run())


def test_http_contract_limits_extra_fields_and_get_no_side_effects(supplier):
    from fastapi import FastAPI
    async def run():
        async with fixture() as (sessions,task):
            app=FastAPI()
            app.include_router(api.router,prefix="/api/v1/seo")
            async def db_dep():
                async with sessions() as db: yield db
            app.dependency_overrides[api.get_seo_session]=db_dep
            app.dependency_overrides[api.require_seo_scoped_auth]=lambda: ADVISOR
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
                assert (await client.get("/api/v1/seo/workbench/advisor-tasks?limit=51")).status_code==422
                r=await client.get("/api/v1/seo/workbench/advisor-tasks?limit=1&tenant_id=4")
                assert r.status_code==200 and r.json()["items"][0]["id"]==task["id"]
                req=request(task).model_dump(mode="json")
                path=f"/api/v1/seo/workbench/onsite-tasks/{task['id']}/ai-proposal"
                assert (await client.post(path,json={**req,"url":"https://unbound.example"})).status_code==422
                result=await client.post(path,json=req)
                assert result.status_code==202 and result.json()["request_run"]["state"]=="queued"
                assert not supplier
                status_path=result.json()["links"]["status"]
                assert (await client.get(status_path)).json()["request_run"]["state"]=="queued"
                await jobs.run_onsite_ai_jobs(sessions=sessions)
                assert (await client.get(status_path)).json()["request_run"]["state"]=="ready"
            assert len(supplier)==1
    asyncio.run(run())


def test_startup_missing_files_remain_unapproved_and_expired_foreign_facts_are_excluded(monkeypatch):
    async def run():
        async with fixture() as (sessions,unused):
            async with sessions() as db:
                db.add_all([
                    SeoQaFact(id=31,tenant_id=4,site_id=2,title="expired",statement="EXPIRED_SECRET_FACT",
                        source_name="fixture",status="active",version=1,expires_at=datetime(2020,1,1,tzinfo=timezone.utc)),
                    SeoQaFact(id=32,tenant_id=99,site_id=99,title="foreign",statement="FOREIGN_SECRET_FACT",
                        source_name="fixture",status="active",version=1),
                ])
                await db.commit()
            async with sessions() as db:
                task=await onsite.create(onsite.Create(tenant_id=4,site_id=2,request_id=uuid4(),
                    work_type="startup",owner_name="维护人员"),db,ADVISOR)
            async def missing(system,user,**kwargs):
                assert "EXPIRED_SECRET_FACT" not in user and "FOREIGN_SECRET_FACT" not in user
                facts=json.loads(user)
                return {"items":[{**i,"expected":"","reason":"需取得真实文件与网站结构依据",
                    "source_refs":[],"missing_information":["请补充网站当前文件和架构"]} for i in facts["items"]]}
            monkeypatch.setattr(ai.deepseek,"chat_json",missing)
            async with sessions() as db:
                result=await complete(sessions, task["id"],request(task),db,ADVISOR)
                assert result["workflow"]["ai_run"]["state"]=="ready"
                assert result["workflow"]["ai_proposal"]["missing_information"]
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await onsite.act(task["id"],onsite.Update(tenant_id=4,site_id=2,expected_revision=2,
                        action="approve",note="不能审核缺项"),db,ADVISOR)
                assert exc.value.status_code==422
    asyncio.run(run())


def test_one_nonce_across_tasks_is_one_charge_even_under_concurrency(supplier):
    async def run():
        async with fixture() as (sessions, task):
            async with sessions() as db:
                db.add(SeoTask(id=100,tenant_id=4,site_id=2,module="seo",action_type=onsite.ACTION_TYPE,
                    title="second",params={"onsite":deepcopy(task["workflow"])},status="open",created_by="7",
                    assignee_role="seo_advisor",baseline={}))
                await db.commit()
            req=request(task)
            async def call(ident):
                async with sessions() as db:
                    try: return await api.ai_proposal(ident,req,db,ADVISOR)
                    except HTTPException as exc: return exc.detail["code"]
            results=await asyncio.gather(call(task["id"]),call(100))
            assert sum(isinstance(r,dict) for r in results)==1
            assert not supplier
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            assert "onsite_ai_request_conflict" in results and len(supplier)==1
            async with sessions() as db:
                assert (await db.get(SeoSite,2)).site_settings["onsite_ai_quota"]["count"]==1
    asyncio.run(run())


def test_same_tenant_nonce_cannot_be_reused_on_another_assigned_site(supplier):
    async def run():
        async with fixture() as (sessions, task):
            async with sessions() as db:
                db.add_all([
                    SeoSite(id=3,tenant_id=4,tenant_module_id=1,name="other assigned",domain="second.example",
                            canonical_domain="second.example",status="active"),
                    SeoSiteAdvisorAssignment(id=4,tenant_id=4,site_id=3,advisor_user_id=7,active=True)])
                await db.commit()
            async with sessions() as db:
                other=await onsite.create(onsite.Create(tenant_id=4,site_id=3,request_id=uuid4(),
                    work_type="startup",owner_name="维护人员"),db,ADVISOR)
            req=request(task)
            async with sessions() as db: await complete(sessions, task["id"],req,db,ADVISOR)
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await complete(sessions, other["id"],req.model_copy(update={"site_id":3}),db,ADVISOR)
                assert exc.value.detail["code"]=="onsite_ai_request_conflict"
                assert "onsite_ai_quota" not in ((await db.get(SeoSite,3)).site_settings or {})
            assert len(supplier)==1
    asyncio.run(run())


def test_nonsecret_provider_metadata_and_quota_are_committed_before_call(monkeypatch):
    async def run():
        async with fixture() as (sessions,task):
            req=request(task)
            original=ai.deepseek.chat_json
            async def inspect(*args,**kwargs):
                async with sessions() as db:
                    row=await db.get(SeoTask,task["id"])
                    run=row.params["onsite_ai_requests"][str(req.request_id)]
                    assert run["state"]=="running"
                    assert run["provider_metadata"]=={"base_url":"https://api.deepseek.com","model":"deepseek-chat"}
                    assert "dummy-not-real" not in json.dumps(row.params)
                    assert (await db.get(SeoSite,2)).site_settings["onsite_ai_quota"]["count"]==1
                return await original(*args,**kwargs)
            monkeypatch.setattr(ai.deepseek,"chat_json",inspect)
            async with sessions() as db:
                result=await complete(sessions, task["id"],req,db,ADVISOR)
                assert result["workflow"]["ai_run"]["state"]=="ready"
                assert "provider_metadata" not in json.dumps(result)
                assert "dummy-not-real" not in json.dumps(result)
    asyncio.run(run())


def test_conflicting_real_output_is_saved_as_blocked_draft_and_cannot_be_approved(monkeypatch):
    async def run():
        async with fixture() as (sessions,task):
            async with sessions() as db:
                fact=await db.get(SeoQaFact,30)
                fact.statement="AQ-20 测量范围为 0 至 20 ppm。"
                fact.source_url="https://example.com/p"
                db.add(SeoQaFact(id=31,tenant_id=4,site_id=2,title="另一份同日检测仪说明",
                    statement="同型号 AQ-20 另一份资料写 0 至 50 ppm，与 0 至 20 ppm 资料冲突，未核实有效版本。",
                    source_name="合成公开资料",source_url="https://example.com/p",status="active",version=1))
                await db.commit()
            calls=[]
            async def output(system,user,**kwargs):
                calls.append(1)
                facts=json.loads(user)
                assert facts["schema_version"]==2 and facts["bound_pages"][0]["id"]==10
                raw=answer(facts)
                for item in raw["items"]:
                    if item["kind"]=="title":
                        item.update(expected="AQ-20 测量范围 0 至 20 ppm",missing_information=["测量范围冲突待确认"])
                    elif item["kind"]=="description":
                        item.update(expected="",reason="量程存在冲突",missing_information=[])
                    elif item["kind"]=="internal_link":
                        item["expected"]='<a href="https://example.com/p">选型</a>'
                    item.pop("kind"); item.pop("target_url")
                return {**raw,"schema_version":2}
            monkeypatch.setattr(ai.deepseek,"chat_json",output)
            req=request(task)
            async with sessions() as db:
                result=await complete(sessions, task["id"],req,db,ADVISOR)
                assert result["workflow"]["phase"]=="review"
                assert result["workflow"]["ai_run"]["state"]=="ready"
                descriptions=result["workflow"]["ai_proposal"]["items"]
                for item,reason in zip(result["workflow"]["items"],descriptions):
                    if item["kind"] in {"title","description","internal_link"}:
                        assert not item["expected"] and reason["missing_information"]
                    if item["kind"]=="description":
                        assert any("0 至 50 ppm" in m and "0 至 20 ppm" in m for m in reason["missing_information"])
                assert result["capabilities"]["website_execution"]["enabled"] is False
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await onsite.act(task["id"],onsite.Update(tenant_id=4,site_id=2,expected_revision=2,
                        action="approve",note="缺项不得审批"),db,ADVISOR)
                assert exc.value.status_code==422
            async with sessions() as db:
                assert (await complete(sessions, task["id"],req,db,ADVISOR))["replayed"]
            assert len(calls)==1
    asyncio.run(run())


def test_url_with_missing_information_cannot_launder_foreign_destination(monkeypatch):
    async def run():
        async with fixture() as (sessions,task):
            async def output(system,user,**kwargs):
                raw=answer(json.loads(user))
                item=next(i for i in raw["items"] if i["kind"]=="internal_link")
                item.update(expected='<a href="https://foreign.example/collect">帮助</a>',missing_information=["尚待确认"])
                return raw
            monkeypatch.setattr(ai.deepseek,"chat_json",output)
            async with sessions() as db:
                result=await complete(sessions, task["id"],request(task),db,ADVISOR)
                assert result["workflow"]["ai_run"]["state"]=="unknown"
                assert result["workflow"]["items"]==task["workflow"]["items"]
                assert result["workflow"]["revision"]==1
                assert "foreign.example" not in json.dumps(result)
    asyncio.run(run())


def test_queued_submission_survives_request_session_and_concurrent_delivery(supplier):
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            async def submit():
                async with sessions() as db:
                    return await api.ai_proposal(task["id"], req, db, ADVISOR)
            results = await asyncio.gather(*(submit() for _ in range(5)))
            assert sum(not r["replayed"] for r in results) == 1
            assert all(r["request_run"]["state"] == "queued" for r in results)
            assert not supplier
            assert results[0]["poll_after_seconds"] == 3
            assert results[0]["request_run"]["started_at"] is None
            assert results[0]["allowed_actions"] == ["cancel"]
            # The original HTTP session is gone; a fresh scheduler discovers DB work.
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            async with sessions() as db:
                result = await api.proposal_status(task["id"], req.request_id, 4, 2, db, ADVISOR)
                assert result["request_run"]["state"] == "ready" and result["poll_after_seconds"] is None
                assert not db.dirty and not db.new
                assert (await db.get(SeoSite, 2)).site_settings["onsite_ai_quota"]["count"] == 1
            assert len(supplier) == 1
    asyncio.run(run())


def test_multiple_workers_claim_one_durable_nonce_only_once(monkeypatch, supplier):
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            async with sessions() as db:
                await api.ai_proposal(task["id"], req, db, ADVISOR)
            entered, release = asyncio.Event(), asyncio.Event()
            original = ai.deepseek.chat_json
            async def slow(*args, **kwargs):
                entered.set()
                await release.wait()
                return await original(*args, **kwargs)
            monkeypatch.setattr(ai.deepseek, "chat_json", slow)
            async def worker():
                return await jobs.execute_request(task["id"], 4, 2, str(req.request_id), sessions=sessions)
            first = asyncio.create_task(worker())
            await asyncio.wait_for(entered.wait(), 3)
            assert set(await asyncio.wait_for(asyncio.gather(*(worker() for _ in range(6))), 3)) <= {"running", None}
            release.set()
            assert await first == "ready"
            assert len(supplier) == 1
    asyncio.run(run())


@pytest.mark.parametrize("change", ["assignment", "user", "role", "binding", "module", "site", "pause", "fact", "page", "keyword", "revision", "cancel"])
def test_queue_revalidates_before_any_provider_call(change, supplier):
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            async with sessions() as db:
                await api.ai_proposal(task["id"], req, db, ADVISOR)
            async with sessions() as db:
                if change == "assignment": (await db.get(SeoSiteAdvisorAssignment, 3)).active = False
                elif change == "user": (await db.get(User, 7)).is_active = False
                elif change == "role": (await db.get(Role, 5)).permissions = {}
                elif change == "binding": (await db.get(User, 7)).tenant_id = 99
                elif change == "module": (await db.get(TenantModule, 1)).expires_at = date(2020, 1, 1)
                elif change == "site": (await db.get(SeoSite, 2)).status = "paused"
                elif change == "pause":
                    site = await db.get(SeoSite, 2)
                    site.site_settings = {**site.site_settings, "seo_service_plan": {"status": "paused"}}
                elif change == "fact": (await db.get(SeoQaFact, 30)).version += 1
                elif change == "page": (await db.get(SeoSitePage, 10)).meta_description = "changed"
                elif change == "keyword": (await db.get(SeoKeywordAsset, 20)).status = "inactive"
                elif change == "revision":
                    row = await db.get(SeoTask, task["id"])
                    row.params = {**row.params, "onsite": {**row.params["onsite"], "revision": 2}}
                else:
                    await onsite.act(task["id"], onsite.Update(tenant_id=4, site_id=2,
                        expected_revision=1, action="cancel", note="人工取消"), db, ADVISOR)
                await db.commit()
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            assert not supplier
            async with sessions() as db:
                row = await db.get(SeoTask, task["id"])
                assert row.params["onsite"]["ai_run"]["state"] == ("cancelled" if change == "cancel" else "stale")
                assert "ai_proposal" not in row.params["onsite"]
    asyncio.run(run())


def test_process_loss_after_dispatch_is_unknown_after_restart_and_get_is_readonly(monkeypatch):
    class WorkerLost(BaseException):
        pass
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            calls = []
            async def lost(*args, **kwargs):
                calls.append(1)
                raise WorkerLost()
            monkeypatch.setattr(ai.deepseek, "chat_json", lost)
            async with sessions() as db:
                await api.ai_proposal(task["id"], req, db, ADVISOR)
            with pytest.raises(WorkerLost):
                await jobs.execute_request(task["id"], 4, 2, str(req.request_id), sessions=sessions)
            async with sessions() as db:
                row = await db.get(SeoTask, task["id"])
                run = row.params["onsite_ai_requests"][str(req.request_id)]
                assert run["state"] == "running" and run["claim_id"]
                api.save_run(row, {**run, "started_at": (ai.now()-timedelta(minutes=3)).isoformat()})
                await db.commit()
            async with sessions() as db:
                before = deepcopy((await db.get(SeoTask, task["id"])).params)
                result = await api.proposal_status(task["id"], req.request_id, 4, 2, db, ADVISOR)
                assert result["request_run"]["state"] == "running"
                assert not db.dirty and before == (await db.get(SeoTask, task["id"])).params
            # Restart scans and reconciles without reclaiming a paid request.
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            async with sessions() as db:
                result = await api.ai_proposal(task["id"], req, db, ADVISOR)
                assert result["replayed"] and result["request_run"]["state"] == "unknown"
                assert result["workflow"]["revision"] == 1 and len(calls) == 1
                assert "claim_id" not in json.dumps(result)
    asyncio.run(run())


def test_worker_coroutine_cancellation_is_durable_unknown_without_retry(monkeypatch):
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            entered = asyncio.Event()
            calls = []
            async def slow(*args, **kwargs):
                calls.append(1)
                entered.set()
                await asyncio.Event().wait()
            monkeypatch.setattr(ai.deepseek, "chat_json", slow)
            async with sessions() as db:
                await api.ai_proposal(task["id"], req, db, ADVISOR)
            operation = asyncio.create_task(jobs.execute_request(task["id"], 4, 2, str(req.request_id), sessions=sessions))
            await asyncio.wait_for(entered.wait(), 3)
            operation.cancel()
            with pytest.raises(asyncio.CancelledError): await operation
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            async with sessions() as db:
                result = await api.proposal_status(task["id"], req.request_id, 4, 2, db, ADVISOR)
                assert result["request_run"]["state"] == "unknown" and len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize("running", [False, True])
def test_cancel_request_fences_late_output_and_preserves_original_plan(monkeypatch, supplier, running):
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            async with sessions() as db:
                await api.ai_proposal(task["id"], req, db, ADVISOR)
            entered, release = asyncio.Event(), asyncio.Event()
            original = ai.deepseek.chat_json
            async def slow(*args, **kwargs):
                entered.set()
                await release.wait()
                return await original(*args, **kwargs)
            monkeypatch.setattr(ai.deepseek, "chat_json", slow)
            if running:
                operation = asyncio.create_task(jobs.execute_request(task["id"], 4, 2, str(req.request_id), sessions=sessions))
                await asyncio.wait_for(entered.wait(), 3)
            async with sessions() as db:
                for action in ("save_proposal", "approve"):
                    with pytest.raises(HTTPException) as exc:
                        await onsite.act(task["id"], onsite.Update(tenant_id=4, site_id=2,
                            expected_revision=1, action=action, items=task["workflow"]["items"] if action=="save_proposal" else None), db, ADVISOR)
                    assert exc.value.detail["code"] == "onsite_ai_busy"
                cancelled = await api.cancel_proposal(task["id"], req.request_id, api.RunScope(tenant_id=4, site_id=2), db, ADVISOR)
                assert cancelled["request_run"]["state"] == ("unknown" if running else "cancelled")
            if running:
                release.set()
                assert await operation == "unknown"
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            async with sessions() as db:
                result = await api.proposal_status(task["id"], req.request_id, 4, 2, db, ADVISOR)
                assert result["workflow"]["items"] == task["workflow"]["items"]
                assert result["workflow"]["revision"] == 1 and len(supplier) == int(running)
    asyncio.run(run())


def test_old_request_poll_does_not_replace_current_run_and_scope_is_enforced(supplier):
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            async with sessions() as db:
                ready = await complete(sessions, task["id"], req, db, ADVISOR)
            newer = request(ready, mode="revise")
            async with sessions() as db:
                await api.ai_proposal(task["id"], newer, db, ADVISOR)
            async with sessions() as db:
                old = await api.proposal_status(task["id"], req.request_id, 4, 2, db, ADVISOR)
                assert old["request_run"]["state"] == "ready"
                assert old["workflow"]["ai_run"]["request_id"] == str(newer.request_id)
                assert old["workflow"]["ai_run"]["state"] == "queued"
                assert not db.dirty
                with pytest.raises(HTTPException) as exc:
                    await api.ai_proposal(task["id"], req, db, ADVISOR)
                assert exc.value.detail["code"] == "onsite_ai_request_superseded"
            for tenant, site, key in ((99,2,req.request_id), (4,99,req.request_id), (4,2,uuid4())):
                async with sessions() as db:
                    with pytest.raises(HTTPException):
                        await api.proposal_status(task["id"], key, tenant, site, db, ADVISOR)
            async with sessions() as db:
                (await db.get(SeoSiteAdvisorAssignment,3)).active = False
                await db.commit()
            async with sessions() as db:
                # Loss of edit assignment still allows the role's scoped reads.
                readonly = await api.proposal_status(task["id"], req.request_id, 4, 2, db, ADVISOR)
                assert readonly["allowed_actions"] == []
                assert readonly["links"]["cancel"] is None
    asyncio.run(run())


def test_result_commit_failure_leaves_running_for_reconciliation_not_retry(monkeypatch, supplier):
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            async with sessions() as db:
                await api.ai_proposal(task["id"], req, db, ADVISOR)
            @asynccontextmanager
            async def broken_sessions():
                async with sessions() as db:
                    original_commit = db.commit
                    async def fail_result_commit():
                        if any(isinstance(obj, SeoTask) and obj.params["onsite"].get("ai_run", {}).get("state") == "ready" for obj in db.dirty):
                            raise RuntimeError("synthetic database interruption")
                        await original_commit()
                    db.commit = fail_result_commit
                    yield db
            with pytest.raises(RuntimeError, match="synthetic database"):
                await jobs.execute_request(task["id"], 4, 2, str(req.request_id), sessions=broken_sessions)
            async with sessions() as db:
                row = await db.get(SeoTask, task["id"])
                run = row.params["onsite_ai_requests"][str(req.request_id)]
                assert run["state"] == "running" and row.params["onsite"]["revision"] == 1
                api.save_run(row, {**run, "started_at": (ai.now()-timedelta(minutes=3)).isoformat()})
                await db.commit()
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            async with sessions() as db:
                assert (await api.proposal_status(task["id"], req.request_id, 4, 2, db, ADVISOR))["request_run"]["state"] == "unknown"
            assert len(supplier) == 1
    asyncio.run(run())


@pytest.mark.parametrize("change,expected", [("expired", "stale"), ("route", "failed")])
def test_queued_expiry_or_provider_change_never_uses_another_model(monkeypatch, supplier, change, expected):
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            async with sessions() as db:
                await api.ai_proposal(task["id"], req, db, ADVISOR)
            if change == "expired":
                async with sessions() as db:
                    row = await db.get(SeoTask, task["id"])
                    run = row.params["onsite_ai_requests"][str(req.request_id)]
                    api.save_run(row, {**run, "queued_at": (ai.now()-timedelta(days=2)).isoformat()})
                    await db.commit()
            else:
                monkeypatch.setattr(ai.deepseek, "_resolve_creds", lambda: ("dummy", "https://api.deepseek.com", "different-model"))
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            async with sessions() as db:
                result = await api.proposal_status(task["id"], req.request_id, 4, 2, db, ADVISOR)
                assert result["request_run"]["state"] == expected and not supplier
    asyncio.run(run())


@pytest.mark.parametrize("disabled", ["seo_scheduler_enabled", "seo_external_actions_enabled", "seo_demo_mode"])
def test_disabled_worker_does_not_accept_new_requests_or_invoke_provider(monkeypatch, supplier, disabled):
    from types import SimpleNamespace
    async def run():
        async with fixture() as (sessions, task):
            settings = dict(app_env="test", seo_demo_mode=False, seo_scheduler_enabled=True, seo_external_actions_enabled=True)
            settings[disabled] = disabled == "seo_demo_mode"
            monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(**settings))
            monkeypatch.setattr(jobs, "get_settings", lambda: SimpleNamespace(**settings))
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await api.ai_proposal(task["id"], request(task), db, ADVISOR)
                assert exc.value.status_code == 503
                assert "onsite_ai_requests" not in (await db.get(SeoTask, task["id"])).params
                assert not supplier
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            assert not supplier
    asyncio.run(run())


@pytest.mark.parametrize("keyword_view", [False, True])
def test_customer_readonly_http_polling_scope_and_keyword_source_projection(monkeypatch, supplier, keyword_view):
    from fastapi import FastAPI
    async def run():
        async with fixture() as (sessions, task):
            permissions = {"seo.site": "view", "seo.content": "view"}
            if keyword_view:
                permissions["seo.keywords"] = "view"
            customer = AuthContext(8, "customer", "customer", 4, permissions)
            async with sessions() as db:
                db.add_all([Role(id=6, name="customer", permissions=permissions),
                            User(id=8, username="customer", role_id=6, tenant_id=4,
                                 password_hash="unused", is_active=True)])
                await db.commit()
            req = request(task)
            async with sessions() as db:
                await api.ai_proposal(task["id"], req, db, ADVISOR)
            app = FastAPI()
            app.include_router(api.router, prefix="/api/v1/seo")
            app.include_router(onsite.router, prefix="/api/v1/seo")
            async def db_dep():
                async with sessions() as db: yield db
            app.dependency_overrides[api.get_seo_session] = db_dep
            app.dependency_overrides[api.require_seo_scoped_auth] = lambda: customer
            stem = f"/api/v1/seo/workbench/onsite-tasks/{task['id']}/ai-requests/{req.request_id}"
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                async with sessions() as db:
                    before = deepcopy((await db.get(SeoTask, task["id"])).params)
                response = await client.get(stem, params={"tenant_id": 4, "site_id": 2})
                assert response.status_code == 200
                result = response.json()
                assert result["request_run"]["state"] == "queued" and result["workflow"]["ai_run"]["request_id"] == str(req.request_id)
                assert result["allowed_actions"] == [] and result["links"]["cancel"] is None
                assert not result["capabilities"]["ai_planning"]["can_generate"]
                assert bool(result["workflow"]["source"]["keywords"]) == keyword_view
                listing = await client.get("/api/v1/seo/workbench/onsite-tasks", params={"tenant_id": 4, "site_id": 2})
                assert listing.status_code == 200
                assert bool(listing.json()["items"][0]["workflow"]["source"]["keywords"]) == keyword_view
                assert (await client.get(stem, params={"tenant_id": 99, "site_id": 2})).status_code == 403
                assert (await client.get(stem, params={"tenant_id": 4, "site_id": 99})).status_code == 404
                assert (await client.post(stem+"/cancel", json={"tenant_id": 4, "site_id": 2})).status_code == 403
                assert (await client.post(f"/api/v1/seo/workbench/onsite-tasks/{task['id']}/ai-proposal", json=req.model_dump(mode="json"))).status_code == 403
                async with sessions() as db:
                    assert before == (await db.get(SeoTask, task["id"])).params
                assert not supplier
                original = ai.deepseek.chat_json
                async def with_keyword_refs(*args, **kwargs):
                    raw = await original(*args, **kwargs)
                    for item in raw["items"]:
                        item["source_refs"].append("keyword:20")
                    return raw
                monkeypatch.setattr(ai.deepseek, "chat_json", with_keyword_refs)
                await jobs.run_onsite_ai_jobs(sessions=sessions)
                ready = await client.get(stem, params={"tenant_id": 4, "site_id": 2})
                assert ready.status_code == 200 and ready.json()["request_run"]["state"] == "ready"
                assert ready.json()["allowed_actions"] == []
                if not keyword_view:
                    assert "keyword:20" not in ready.text and "keyword-20" not in ready.text
                    assert all(i["kind"] not in {"keyword", "meta_keywords"} for i in ready.json()["workflow"]["items"])
                async with sessions() as db:
                    stored = (await db.get(SeoTask, task["id"])).params
                    assert stored["onsite"]["source"]["keywords"]
                    assert any("keyword:20" in i["source_refs"] for i in stored["onsite"]["ai_proposal"]["items"])
                assert len(supplier) == 1
    asyncio.run(run())


def test_busy_site_is_skipped_then_claimed_on_next_durable_scan(supplier):
    async def run():
        async with fixture() as (sessions, task):
            req = request(task)
            async with sessions() as db:
                await api.ai_proposal(task["id"], req, db, ADVISOR)
            async with sessions() as holding:
                await holding.get(SeoSite, 2, with_for_update=True)
                state = await asyncio.wait_for(jobs.execute_request(task["id"], 4, 2, str(req.request_id), sessions=sessions), 3)
                assert state is None and not supplier
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            async with sessions() as db:
                assert (await api.proposal_status(task["id"], req.request_id, 4, 2, db, ADVISOR))["request_run"]["state"] == "ready"
            assert len(supplier) == 1
    asyncio.run(run())


async def install_guard_tables(sessions, *, controls_schema=True):
    from pathlib import Path
    async with sessions() as db:
        connection = (await (await db.connection()).get_raw_connection()).driver_connection
        root = Path(__file__).parents[1]
        await connection.execute((root / 'scripts/api_metering_schema.sql').read_text(encoding='utf-8'))
        if controls_schema:
            await connection.execute((root / 'scripts/api_controls_schema.sql').read_text(encoding='utf-8'))
        await db.commit()


def real_metered_supplier(monkeypatch, sessions, provider):
    from app import api_metering as meter, api_controls as controls
    original_client = httpx.AsyncClient
    monkeypatch.setattr(ai.deepseek, 'chat_json', REAL_CHAT_JSON)
    monkeypatch.setattr(ai.deepseek, '_resolve_creds', lambda **kwargs: ('synthetic-only', 'https://api.deepseek.com/v1', 'deepseek-v4-flash'))
    monkeypatch.setattr(ai.deepseek.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(meter, 'async_session_factory', sessions)
    monkeypatch.setattr(controls, 'async_session_factory', sessions)
    monkeypatch.setenv('API_METERING_ENABLED', 'true')
    monkeypatch.setenv('API_CONTROLS_ENABLED', 'true')
    monkeypatch.delenv('API_METERING_RATES_JSON', raising=False)
    return meter, controls


def guard_response(request):
    payload = json.loads(request.content)
    facts = json.loads(payload['messages'][1]['content'])
    return httpx.Response(200, json={'id': 'synthetic-response', 'model': 'deepseek-v4-flash',
        'choices': [{'message': {'content': json.dumps(answer(facts))}}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 10, 'prompt_tokens_details': {'cached_tokens': 0}}})


@pytest.mark.parametrize('mode', ['enabled', 'controls_off', 'all_off', 'schema_pending', 'partial_credentials', 'metering_off'])
def test_background_ai_real_metering_admission_and_legacy_modes(monkeypatch, mode):
    from sqlalchemy import text
    async def run():
        async with fixture() as (sessions, task):
            sent = []
            async def provider(request):
                sent.append(request)
                return guard_response(request)
            meter, controls = real_metered_supplier(monkeypatch, sessions, provider)
            if mode not in {'schema_pending', 'all_off', 'metering_off'}:
                await install_guard_tables(sessions, controls_schema=mode != 'controls_off')
            if mode in {'controls_off', 'all_off'}:
                monkeypatch.setenv('API_CONTROLS_ENABLED', 'false')
            if mode in {'all_off', 'metering_off'}:
                monkeypatch.setenv('API_METERING_ENABLED', 'false')
            if mode == 'partial_credentials':
                async with sessions() as db:
                    await db.execute(text('DROP TABLE api_control_credentials'))
                    await db.commit()
                    assert (await controls.read_controls(db))['state'] == 'schema_pending'
            req = request(task)
            async with sessions() as db:
                await api.ai_proposal(task['id'], req, db, ADVISOR)
            state = await jobs.execute_request(task['id'], 4, 2, str(req.request_id), sessions=sessions)
            permitted = mode in {'enabled', 'controls_off', 'all_off'}
            assert state == ('ready' if permitted else 'failed')
            assert len(sent) == int(permitted)
            async with sessions() as db:
                result = await api.proposal_status(task['id'], req.request_id, 4, 2, db, ADVISOR)
                assert 'synthetic-only' not in json.dumps(result)
                if mode in {'enabled', 'controls_off'}:
                    row = (await db.execute(text('SELECT * FROM api_usage_events'))).mappings().one()
                    assert (row['tenant_id'], row['user_id'], row['module']) == (4, 7, 'seo')
                    assert row['state'] == 'succeeded' and row['estimated_amount'] > 0
                    assert row['job_ref'] == f"site:2:onsite_ai_proposal:{task['id']}:{req.request_id}"
                    assert row['operation'] == 'chat.completions'
                    assert 'synthetic-only' not in str(dict(row))
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            assert len(sent) == int(permitted)
    asyncio.run(run())


@pytest.mark.parametrize('target', ['tenant:4', 'user:7', 'provider:api.deepseek.com'])
@pytest.mark.parametrize('cap', [0, 1])
def test_seo_background_guard_observes_other_module_in_shared_ledger(monkeypatch, target, cap):
    from sqlalchemy import text
    async def run():
        async with fixture() as (sessions, task):
            sent = []
            async def provider(request):
                sent.append(request)
                return guard_response(request)
            meter, controls = real_metered_supplier(monkeypatch, sessions, provider)
            await install_guard_tables(sessions)
            async with sessions() as db:
                await controls.mutate(db, actor_id=7, request_id=str(uuid4()), kind='budget', key='budget:'+target,
                    expected_revision=0, value={'daily_calls':None, 'monthly_calls':None, 'daily_cny':None,
                        'monthly_cny':None, 'warning_percent':80, 'max_concurrent':cap})
                if cap:
                    # Another service's already-committed dispatch occupies the same budget.
                    await db.execute(text("""INSERT INTO api_usage_events(id,tenant_id,user_id,origin,module,operation,
                        provider,endpoint,state) VALUES(CAST(:id AS uuid),4,7,'interactive','geo','chat.completions',
                        'display-alias','api.deepseek.com/v1/chat/completions','requested')"""), {'id':str(uuid4())})
                    await db.commit()
            req = request(task)
            async with sessions() as db:
                await api.ai_proposal(task['id'], req, db, ADVISOR)
            assert await jobs.execute_request(task['id'],4,2,str(req.request_id),sessions=sessions) == 'failed'
            assert not sent
            async with sessions() as db:
                assert await db.scalar(text('SELECT count(*) FROM api_usage_events')) == cap
                assert (await db.get(SeoTask,task['id'])).params['onsite']['revision'] == 1
    asyncio.run(run())


def test_background_timeout_keeps_unknown_charge_across_period_and_never_retries(monkeypatch):
    from sqlalchemy import text
    async def run():
        async with fixture() as (sessions, task):
            sent = []
            async def provider(request):
                sent.append(request)
                raise httpx.ReadTimeout('synthetic timeout', request=request)
            meter, controls = real_metered_supplier(monkeypatch, sessions, provider)
            await install_guard_tables(sessions)
            async with sessions() as db:
                await controls.mutate(db, actor_id=7, request_id=str(uuid4()), kind='budget', key='budget:tenant:4',
                    expected_revision=0, value={'daily_calls':None,'monthly_calls':None,'daily_cny':None,
                        'monthly_cny':'100','warning_percent':80,'max_concurrent':None})
            req = request(task)
            async with sessions() as db: await api.ai_proposal(task['id'],req,db,ADVISOR)
            assert await jobs.execute_request(task['id'],4,2,str(req.request_id),sessions=sessions) == 'unknown'
            async with sessions() as db:
                event = (await db.execute(text('SELECT state,estimated_amount,reserved_amount FROM api_usage_events'))).one()
                assert event.state == 'unknown' and event.estimated_amount is None and event.reserved_amount > 0
                await db.execute(text("UPDATE api_usage_events SET started_at=CURRENT_TIMESTAMP - INTERVAL '40 days'"))
                await db.commit()
                assert (await api.ai_proposal(task['id'],req,db,ADVISOR))['replayed']
            await jobs.run_onsite_ai_jobs(sessions=sessions)
            assert len(sent) == 1
            req2 = request(task)
            async with sessions() as db: await api.ai_proposal(task['id'],req2,db,ADVISOR)
            assert await jobs.execute_request(task['id'],4,2,str(req2.request_id),sessions=sessions) == 'failed'
            assert len(sent) == 1
            async with sessions() as db:
                assert (await controls.usage(db,'tenant:4'))['unresolved_calls'] == 1
    asyncio.run(run())
