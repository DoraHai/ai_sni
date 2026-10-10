"""Owned PostgreSQL proves project isolation, revisions and duplicate-request locking."""
import asyncio
from contextlib import asynccontextmanager
import json
from uuid import uuid4
import os
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, text, update
from sqlalchemy.exc import DBAPIError
from test_geo_project_scope_postgres import database
from app.geo import onsite_routes as api, onsite_jobs
from app.geo.content import async_jobs
from app.geo.project_workflows import save_plan
from app.models import GeoActionTicket, GeoAsyncJob, GeoFact, GeoProject
from app.security.auth import AuthContext
from app.models.user import User
from app.models.role import Role
from types import SimpleNamespace
from unittest.mock import patch

pytestmark = pytest.mark.skipif(not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated PostgreSQL")
ADVISOR = AuthContext(7, "advisor", "advisor", None, {"geo.assets":"edit", "geo.content":"edit"})
CUSTOMER = AuthContext(12, "customer", "customer", 1, {"geo.assets":"view", "geo.content":"view"})
OTHER_ADVISOR = AuthContext(8, "advisor2", "advisor", None, {"geo.assets":"edit", "geo.content":"edit"})


async def run_owned(sessions, job_id, tenant_id=1):
    @asynccontextmanager
    async def factory(*, bind=None):
        async with sessions() as db:
            yield db
    with patch("app.database.async_session_factory", factory):
        return await async_jobs._run_owned_job(job_id, tenant_id=tenant_id)

async def configured(sessions):
    async with sessions() as db:
        await save_plan(db, 1, 10, dict(enabled=False, status="active", prompt_ids=[], interval_days=7, advisor_user_id=7), 0, 7)
        await db.commit()

def test_project_task_is_idempotent_and_scope_or_legacy_writes_cannot_complete_it():
    async def run():
        async with database() as sessions:
            await configured(sessions)
            req=api.Create(tenant_id=1, project_id=10, request_id=uuid4(), work_type="startup", owner_name="维护人员")
            async def create():
                async with sessions() as db:
                    return await api.create(req, db, ADVISOR)
            rows=await asyncio.gather(*(create() for _ in range(5)))
            assert len({r["id"] for r in rows})==1
            assert rows[0]["workflow"].get("content_task_id") is None
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(GeoActionTicket))==1
                with pytest.raises(HTTPException) as err:
                    await api.act(rows[0]["id"], api.Update(tenant_id=1, project_id=11, action="accept", expected_revision=1, note="越界"), db, ADVISOR)
                assert err.value.status_code in {403,404}
            async with sessions() as db:
                from app.geo.routes import patch_action_ticket, TicketUpdate
                with pytest.raises(HTTPException) as err:
                    await patch_action_ticket(rows[0]["id"], TicketUpdate(manual_pass=True, verification_note="绕过"), 1, ADVISOR, db)
                assert err.value.status_code==409
            async with sessions() as db:
                result=await api.list_tasks(1, 10, None, db, CUSTOMER)
                assert len(result["items"])==1 and result["items"][0]["allowed_actions"]==[]
            async with sessions() as db:
                result=await api.list_tasks(1, 11, None, db, CUSTOMER)
                assert result["items"]==[]
    asyncio.run(run())

def test_website_only_geo_delivery_has_no_article_or_ai_effect_gate_and_rejects_stale_writes(monkeypatch):
    async def fetch(url, **kwargs):
        assert kwargs["allowed_hosts"]==frozenset({"p10.example","www.p10.example"})
        return SimpleNamespace(final_url=url,html='# 官网知识\n真实问答\n<script type="application/ld+json">{"@type":"Organization","name":"真实客户"}</script>')
    monkeypatch.setattr(api,"safe_fetch",fetch)
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                row=await api.create(api.Create(tenant_id=1,project_id=10,request_id=uuid4(),work_type="monthly",month="2026-10",owner_name="维护人员"),db,ADVISOR)
            items=[dict(i,expected='{"@type":"Organization","name":"真实客户"}' if i["kind"]=="schema" else '# 官网知识' if i["kind"]=="llms" else "真实问答") for i in row["workflow"]["items"]]
            async def act(row, action, **fields):
                async with sessions() as db:
                    return await api.act(row["id"],api.Update(tenant_id=1,project_id=10,action=action,
                        expected_revision=row["workflow"]["revision"],**fields),db,ADVISOR)
            old=row
            row=await act(row,"save_proposal",items=items)
            with pytest.raises(HTTPException) as err:
                await act(old,"save_proposal",items=items)
            assert err.value.status_code==409
            row=await act(row,"approve",note="事实、出处、适用条件已核对")
            row=await act(row,"implement",note="官网、知识库、FAQ、Schema 与文件已实施")
            row=await act(row,"recheck")
            assert row["workflow"]["phase"]=="acceptance"
            row=await act(row,"accept",note="人工核对页面事实与质量")
            assert row["workflow"]["phase"]=="done" and row["completion_evidence"]["recheck"]["passed"]
    asyncio.run(run())


def _ai_result(items):
    values = {
        "structured_content": "示例品牌提供经过公开资料核验的工业产品。",
        "knowledge": "示例品牌工业产品知识与适用范围。",
        "faq": "示例品牌产品有哪些公开能力？请参考公开产品资料。",
    }
    return {"schema_version": 2, "summary": "基于已核验公开资料起草",
            "missing_information": ["缺少具体规格"],
            "items": [{"id": item["id"], "expected": values[item["id"]],
                       "reason": "使用获准公开来源", "fact_ids": [80],
                       "blocking_missing_information": [], "optional_information": []}
                      for item in items if item["kind"] in {"structured_content", "knowledge", "faq"}]}


async def _add_public_fact(db, *, fact_id=80, title="公开产品资料", expired=False):
    from datetime import date, timedelta
    db.add(GeoFact(id=fact_id, tenant_id=1, business_id=None, title=title,
        statement="该公开资料说明示例品牌工业产品具备经过验证的节能运行能力。",
        fact_type="product", source_name="客户官网",
        source_url="https://public.example/fact",
        expires_at=date.today()-timedelta(days=1) if expired else None,
        trust_level="verified", status="active",
        meta={"verification": {"verified_at": "2026-10-09T00:00:00Z",
              "excerpt": "公开产品说明", "excerpt_locator": "正文第1段"},
              "public_use": {"allowed": True, "authorized_by": 7,
                             "authorized_at": "2026-10-09T00:00:00Z"}}))
    await db.commit()


async def _add_nonpublic_fact(db, *, fact_id=81):
    db.add(GeoFact(id=fact_id, tenant_id=1, business_id=None, title="内部核验资料",
        statement="这条事实没有明确公开使用授权，不能进入站内模型快照。",
        fact_type="product", source_name="内部资料",
        source_url="https://private.example/fact", expires_at=None,
        trust_level="verified", status="active",
        meta={"verification": {"verified_at": "2026-10-09T00:00:00Z",
              "excerpt": "内部核验摘录", "excerpt_locator": "正文第1段"}}))
    await db.commit()


def test_ai_proposal_is_nonce_idempotent_meter_scoped_and_invalidates_review(monkeypatch):
    calls = []
    advisor_locks = []
    original_advisor_available = api.advisor_available
    async def credentials(session, tenant_id):
        return {"api_key": "test",
                "base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
                "model": "deepseek-v4-flash-0731", "provider": "dashscope"}
    async def provider(system, user, **kwargs):
        calls.append((system, user, kwargs))
        import json
        current = json.loads(user)["current_items"]
        return _ai_result(current)
    async def tracked_advisor_available(session, tenant_id, user_id, **kwargs):
        advisor_locks.append(bool(kwargs.get("lock")))
        return await original_advisor_available(session, tenant_id, user_id, **kwargs)
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    monkeypatch.setattr(api, "advisor_available", tracked_advisor_available)
    monkeypatch.setattr(api.onsite_ai, "get_settings", lambda: SimpleNamespace(
        geo_onsite_ai_provider="deepseek", geo_onsite_ai_model="deepseek-chat",
        deepseek_api_key="official-platform-key",
        deepseek_base_url="https://api.deepseek.com"))
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
                await _add_nonpublic_fact(db)
            async with sessions() as db:
                row = await api.create(api.Create(tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员"), db, ADVISOR)
            async with sessions() as db:
                stored = await db.get(GeoActionTicket, row["id"])
                project = await db.get(GeoProject, 10)
                snapshot = await api._proposal_snapshot(db, project, stored)
                assert [fact["fact_id"] for fact in snapshot["facts"]] == [80]
                assert snapshot["facts"][0]["statement_publicly_authorized"] is True
            rid = uuid4()
            req = api.AiProposal(tenant_id=1, project_id=10,
                expected_revision=row["workflow"]["revision"], request_id=rid, mode="initial")
            async with sessions() as db:
                result = await api.ai_proposal(row["id"], req, db, ADVISOR)
            assert result["request_run"]["state"] == "queued"
            assert result["workflow"]["phase"] == "draft"
            job_id = result["request_run"]["job_id"]
            completed = await run_owned(sessions, job_id)
            assert completed["result_meta"]["public_state"] == "ready"
            async with sessions() as db:
                result = await api.get_ai_request(row["id"], rid, 1, 10, db, ADVISOR)
            assert result["workflow"]["phase"] == "review"
            assert result["workflow"]["ai_run"]["request_id"] == str(rid)
            assert result["workflow"]["ai_run"]["state"] == "ready"
            assert result["workflow"]["ai_proposal"]["proposal_revision"] == result["workflow"]["revision"]
            public_item = result["workflow"]["ai_proposal"]["items"][0]
            assert public_item["id"] == public_item["item_id"]
            assert public_item["missing_information"] == public_item["blocking_missing_information"]
            assert "optional_information" in public_item
            assert public_item["source_refs"][0]["source_id"].startswith("geo-public-source:")
            assert "fact_id" not in public_item["source_refs"][0]
            assert result["capabilities"]["website_execution"]["enabled"] is False
            assert not any(key in result["workflow"] for key in ("approval", "implementation", "recheck", "acceptance"))
            async with sessions() as db:
                same = await api.ai_proposal(row["id"], req, db, ADVISOR)
            assert same["workflow"]["ai_run"]["state"] == "ready"
            assert len(calls) == 1
            sent_facts = json.loads(calls[0][1])["approved_public_facts"]
            assert [fact["fact_id"] for fact in sent_facts] == [80]
            assert all("statement_publicly_authorized" not in fact for fact in sent_facts)
            assert calls[0][2]["api_key"] == "official-platform-key"
            assert calls[0][2]["base_url"] == "https://api.deepseek.com"
            assert calls[0][2]["model"] == "deepseek-chat"
            assert calls[0][2]["max_tokens"] == 8192
            assert all(key not in calls[0][2] for key in (
                "enable_thinking", "reasoning_effort", "response_format"))
            assert "API" not in str(result["workflow"]["ai_proposal"])
            assert True in advisor_locks
            manual_items = [api.work.Item.model_validate(item) for item in same["workflow"]["items"]]
            async with sessions() as db:
                manual = await api.act(row["id"], api.Update(
                    tenant_id=1, project_id=10, action="save_proposal",
                    expected_revision=same["workflow"]["revision"], items=manual_items,
                    note="人工调整当前版本"), db, ADVISOR)
            assert "ai_proposal" not in manual["workflow"]
    asyncio.run(run())


def test_ai_proposal_rejects_full_history_before_quota_or_provider_call(monkeypatch):
    calls = 0
    async def credentials(session, tenant_id):
        return {"api_key": "test", "base_url": "https://provider.invalid/v1", "model": "test-model"}
    async def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {}
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                row = await api.create(api.Create(tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员"), db, ADVISOR)
            async with sessions() as db:
                stored = await db.get(GeoActionTicket, row["id"], with_for_update=True)
                onsite = dict(stored.progress["onsite"])
                onsite["history"] = [dict(action="save_proposal", actor=7, at=str(index))
                                     for index in range(100)]
                stored.progress = {**stored.progress, "onsite": onsite}
                await db.commit()
            request = api.AiProposal(tenant_id=1, project_id=10,
                expected_revision=1, request_id=uuid4(), mode="initial")
            async with sessions() as db:
                with pytest.raises(HTTPException) as error:
                    await api.ai_proposal(row["id"], request, db, ADVISOR)
                assert error.value.status_code == 409
            async with sessions() as db:
                project = await db.get(GeoProject, 10)
                assert "onsite_ai_quota" not in (project.project_settings or {})
            assert calls == 0
    asyncio.run(run())


def test_invalid_onsite_model_is_rejected_before_quota_or_provider_call(monkeypatch):
    calls = 0
    async def credentials(session, tenant_id):
        return {"api_key": "test",
                "base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
                "model": "deepseek-v4-flash-0731", "provider": "dashscope"}
    async def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {}
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    monkeypatch.setattr(api.onsite_ai, "get_settings", lambda: SimpleNamespace(
        geo_onsite_ai_provider="deepseek", geo_onsite_ai_model="deepseek-chat",
        deepseek_api_key="official-platform-key",
        deepseek_base_url="https://proxy.invalid/v1"))
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                row = await api.create(api.Create(
                    tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员"), db, ADVISOR)
            request = api.AiProposal(tenant_id=1, project_id=10,
                expected_revision=1, request_id=uuid4(), mode="initial")
            async with sessions() as db:
                with pytest.raises(HTTPException) as error:
                    await api.ai_proposal(row["id"], request, db, ADVISOR)
                assert error.value.status_code == 409
            async with sessions() as db:
                project = await db.get(GeoProject, 10)
                assert "onsite_ai_quota" not in (project.project_settings or {})
                stored = await db.get(GeoActionTicket, row["id"])
                projected = await api._public(db, stored, project, True)
                capability = projected["capabilities"]["ai_planning"]
                assert capability["can_generate"] is False
                assert "配置无效" in capability["reason"]
            assert calls == 0
    asyncio.run(run())


def test_missing_facts_stop_before_nonce_quota_or_official_provider_call(monkeypatch):
    calls = 0
    async def credentials(session, tenant_id):
        return {"api_key": "shared-default", "base_url":
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "deepseek-v4-flash-0731", "provider": "dashscope"}
    async def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {}
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    monkeypatch.setattr(api.onsite_ai, "get_settings", lambda: SimpleNamespace(
        geo_onsite_ai_provider="deepseek", geo_onsite_ai_model="deepseek-chat",
        deepseek_api_key="official-platform-key",
        deepseek_base_url="https://api.deepseek.com"))
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                row = await api.create(api.Create(
                    tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员"), db, ADVISOR)
            request = api.AiProposal(tenant_id=1, project_id=10,
                expected_revision=1, request_id=uuid4(), mode="initial")
            async with sessions() as db:
                with pytest.raises(HTTPException) as error:
                    await api.ai_proposal(row["id"], request, db, ADVISOR)
                assert error.value.status_code == 409
                assert "已核验且获准公开使用" in str(error.value.detail)
            async with sessions() as db:
                project = await db.get(GeoProject, 10)
                assert "onsite_ai_quota" not in (project.project_settings or {})
                assert "onsite_ai_requests" not in (project.project_settings or {})
                stored = await db.get(GeoActionTicket, row["id"])
                assert "ai_run" not in stored.progress["onsite"]
            assert calls == 0
    asyncio.run(run())


def test_same_nonce_concurrency_creates_one_durable_job_and_queued_cancel_is_free(monkeypatch):
    calls = 0
    async def credentials(session, tenant_id):
        return {"api_key": "ignored", "base_url": "https://ignored.invalid/v1",
                "model": "ignored", "provider": "ignored"}
    async def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {}
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    monkeypatch.setattr(api.onsite_ai, "get_settings", lambda: SimpleNamespace(
        geo_onsite_ai_provider="deepseek", geo_onsite_ai_model="deepseek-chat",
        deepseek_api_key="official-platform-key",
        deepseek_base_url="https://api.deepseek.com"))
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
                row = await api.create(api.Create(tenant_id=1, project_id=10,
                    request_id=uuid4(), work_type="startup", owner_name="维护人员"), db, ADVISOR)
            rid = uuid4()
            req = api.AiProposal(tenant_id=1, project_id=10, expected_revision=1,
                                 request_id=rid, mode="initial")
            async def enqueue():
                async with sessions() as db:
                    return await api.ai_proposal(row["id"], req, db, ADVISOR)
            results = await asyncio.gather(*(enqueue() for _ in range(5)))
            assert {item["request_run"]["job_id"] for item in results} == {
                results[0]["request_run"]["job_id"]}
            assert all(item["request_run"]["state"] == "queued" for item in results)
            assert results[0]["allowed_actions"] == []
            assert results[0]["request_run"]["can_cancel"] is True
            assert results[0]["capabilities"]["ai_planning"]["can_generate"] is False
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(GeoAsyncJob)) == 1
                blocked = [
                    api.Update(tenant_id=1, project_id=10, action="approve",
                               expected_revision=1, note="不应越过排队任务"),
                    api.Update(tenant_id=1, project_id=10, action="save_proposal",
                               expected_revision=1,
                               items=[api.work.Item.model_validate(item)
                                      for item in row["workflow"]["items"]]),
                ]
                for action in blocked:
                    with pytest.raises(HTTPException) as error:
                        await api.act(row["id"], action, db, ADVISOR)
                    assert error.value.status_code == 409
            async with sessions() as db:
                customer_read = await api.get_ai_request(row["id"], rid, 1, 10, db, CUSTOMER)
                assert customer_read["request_run"]["state"] == "queued"
                assert customer_read["request_run"]["can_cancel"] is False
                assert customer_read["allowed_actions"] == []
            async with sessions() as db:
                cancelled = await api.cancel_ai_request(row["id"], rid, 1, 10, db, ADVISOR)
                assert cancelled["request_run"]["state"] == "cancelled"
            outcome = await run_owned(sessions, results[0]["request_run"]["job_id"])
            assert outcome["status"] == "conflict"
            assert calls == 0
    asyncio.run(run())


def test_running_cancel_discards_late_result_without_second_provider_call(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    async def credentials(session, tenant_id):
        return {"api_key": "ignored", "base_url": "https://ignored.invalid/v1",
                "model": "ignored", "provider": "ignored"}
    async def provider(system, user, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return _ai_result(json.loads(user)["current_items"])
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    monkeypatch.setattr(api.onsite_ai, "get_settings", lambda: SimpleNamespace(
        geo_onsite_ai_provider="deepseek", geo_onsite_ai_model="deepseek-chat",
        deepseek_api_key="official-platform-key",
        deepseek_base_url="https://api.deepseek.com"))
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
                row = await api.create(api.Create(tenant_id=1, project_id=10,
                    request_id=uuid4(), work_type="startup", owner_name="维护人员"), db, ADVISOR)
            rid = uuid4()
            req = api.AiProposal(tenant_id=1, project_id=10, expected_revision=1,
                                 request_id=rid, mode="initial")
            async with sessions() as db:
                queued = await api.ai_proposal(row["id"], req, db, ADVISOR)
            worker = asyncio.create_task(run_owned(sessions, queued["request_run"]["job_id"]))
            await asyncio.wait_for(entered.wait(), 5)
            async with sessions() as db:
                cancelling = await api.cancel_ai_request(row["id"], rid, 1, 10, db, ADVISOR)
                assert cancelling["request_run"]["cancel_requested"] is True
            release.set()
            result = await asyncio.wait_for(worker, 10)
            assert result["status"] == "cancelled"
            async with sessions() as db:
                polled = await api.get_ai_request(row["id"], rid, 1, 10, db, ADVISOR)
                assert polled["request_run"]["state"] == "cancelled"
                assert polled["workflow"]["revision"] == 1
                assert "ai_proposal" not in polled["workflow"]
            assert calls == 1
    asyncio.run(run())


def test_pending_consumer_finishes_lost_http_callback_and_two_ticks_call_once(monkeypatch):
    calls = 0
    async def credentials(session, tenant_id):
        return {"api_key": "ignored", "base_url": "https://ignored.invalid/v1",
                "model": "ignored", "provider": "ignored"}
    async def provider(system, user, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return _ai_result(json.loads(user)["current_items"])
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    monkeypatch.setattr(api.onsite_ai, "get_settings", lambda: SimpleNamespace(
        geo_onsite_ai_provider="deepseek", geo_onsite_ai_model="deepseek-chat",
        deepseek_api_key="official-platform-key",
        deepseek_base_url="https://api.deepseek.com"))
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
                row = await api.create(api.Create(tenant_id=1, project_id=10,
                    request_id=uuid4(), work_type="startup", owner_name="维护人员"), db, ADVISOR)
            rid = uuid4()
            async with sessions() as db:
                queued = await api.ai_proposal(row["id"], api.AiProposal(
                    tenant_id=1, project_id=10, expected_revision=1,
                    request_id=rid, mode="initial"), db, ADVISOR)
            assert queued["request_run"]["state"] == "queued"
            async def runner(job_id, tenant_id):
                return await run_owned(sessions, job_id, tenant_id)
            ticks = await asyncio.gather(
                onsite_jobs.run_pending_batch(session_factory=sessions, runner=runner),
                onsite_jobs.run_pending_batch(session_factory=sessions, runner=runner),
            )
            assert sum(item["completed"] for item in ticks) == 1
            async with sessions() as db:
                polled = await api.get_ai_request(row["id"], rid, 1, 10, db, ADVISOR)
                assert polled["workflow"]["ai_run"]["state"] == "ready"
                assert polled["request_run"]["state"] == "ready"
                assert polled["workflow"]["ai_run"]["request_id"] == str(rid)
                assert polled["request_run"]["request_id"] == str(rid)
            assert calls == 1
    asyncio.run(run())


def test_interrupted_running_request_becomes_unknown_and_is_never_requeued(monkeypatch):
    calls = 0
    async def credentials(session, tenant_id):
        return {"api_key": "ignored", "base_url": "https://ignored.invalid/v1",
                "model": "ignored", "provider": "ignored"}
    async def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {}
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    monkeypatch.setattr(api.onsite_ai, "get_settings", lambda: SimpleNamespace(
        geo_onsite_ai_provider="deepseek", geo_onsite_ai_model="deepseek-chat",
        deepseek_api_key="official-platform-key",
        deepseek_base_url="https://api.deepseek.com"))
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
                row = await api.create(api.Create(tenant_id=1, project_id=10,
                    request_id=uuid4(), work_type="startup", owner_name="维护人员"), db, ADVISOR)
            rid = uuid4()
            async with sessions() as db:
                queued = await api.ai_proposal(row["id"], api.AiProposal(
                    tenant_id=1, project_id=10, expected_revision=1,
                    request_id=rid, mode="initial"), db, ADVISOR)
                job = await db.get(GeoAsyncJob, queued["request_run"]["job_id"])
                job.status = "running"
                job.started_at = datetime.utcnow()
                meta = dict(job.request_meta); meta["provider_started_at"] = onsite_jobs.onsite_ai.now_iso()
                job.request_meta = meta
                task = await db.get(GeoActionTicket, row["id"])
                value = dict(task.progress["onsite"]); run = dict(value["ai_run"])
                run.update(state="running", started_at=onsite_jobs.onsite_ai.now_iso())
                value["ai_run"] = run; task.progress = {**task.progress, "onsite":value}
                await db.commit()
            async with sessions() as db:
                job = await db.get(GeoAsyncJob, queued["request_run"]["job_id"])
                state = await onsite_jobs.recover_interrupted_job(db, job)
                assert state == "unknown"
            async with sessions() as db:
                polled = await api.get_ai_request(row["id"], rid, 1, 10, db, ADVISOR)
                assert polled["request_run"]["state"] == "unknown"
                assert "不会自动重试" in polled["request_run"]["error"]
                job = await db.get(GeoAsyncJob, queued["request_run"]["job_id"])
                assert job.status == "failed"
            assert calls == 0
    from datetime import datetime
    asyncio.run(run())


def test_provider_route_change_after_enqueue_stops_before_paid_call(monkeypatch):
    calls = 0
    route = {"base_url": "https://api.deepseek.com"}
    async def credentials(session, tenant_id):
        return {"api_key": "ignored", "base_url": "https://ignored.invalid/v1",
                "model": "ignored", "provider": "ignored"}
    async def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {}
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    monkeypatch.setattr(api.onsite_ai, "get_settings", lambda: SimpleNamespace(
        geo_onsite_ai_provider="deepseek", geo_onsite_ai_model="deepseek-chat",
        deepseek_api_key="official-platform-key", deepseek_base_url=route["base_url"]))
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
                row = await api.create(api.Create(tenant_id=1, project_id=10,
                    request_id=uuid4(), work_type="startup", owner_name="维护人员"), db, ADVISOR)
            rid = uuid4()
            async with sessions() as db:
                queued = await api.ai_proposal(row["id"], api.AiProposal(
                    tenant_id=1, project_id=10, expected_revision=1,
                    request_id=rid, mode="initial"), db, ADVISOR)
                job = await db.get(GeoAsyncJob, queued["request_run"]["job_id"])
                stored = job.request_meta["provider_route"]
                assert stored["host"] == "api.deepseek.com"
                assert stored["model"] == "deepseek-chat"
                assert "api_key" not in stored
            route["base_url"] = "https://api.deepseek.com/v1"
            result = await run_owned(sessions, queued["request_run"]["job_id"])
            assert result["result_meta"]["public_state"] == "stale"
            async with sessions() as db:
                polled = await api.get_ai_request(row["id"], rid, 1, 10, db, ADVISOR)
                assert polled["request_run"]["state"] == "stale"
                assert "路由已变化" in polled["request_run"]["error"]
                assert polled["workflow"]["ai_run"]["request_id"] == str(rid)
                assert polled["request_run"]["request_id"] == str(rid)
            assert calls == 0
    asyncio.run(run())


def test_final_advisor_read_lock_blocks_permission_change_until_commit():
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as checking:
                project = await checking.get(GeoProject, 10, with_for_update=True)
                assert await api.can_operate(checking, ADVISOR, project, lock_advisor=True)
                async with sessions() as revoking:
                    await revoking.execute(text("SET LOCAL lock_timeout = '100ms'"))
                    with pytest.raises(DBAPIError):
                        await revoking.execute(update(Role).where(Role.id == 5).values(
                            permissions={"geo.assets": "view", "geo.content": "view"}))
                    await revoking.rollback()
                await checking.commit()
            async with sessions() as revoking:
                role = await revoking.get(Role, 5, with_for_update=True)
                role.permissions = {"geo.assets": "view", "geo.content": "view"}
                await revoking.commit()
    asyncio.run(run())


def test_ai_proposal_late_result_cannot_overwrite_changed_fact_scope(monkeypatch):
    async def credentials(session, tenant_id):
        return {"api_key": "test", "base_url": "https://provider.invalid/v1", "model": "test-model"}
    sessions_ref = None
    async def provider(system, user, **kwargs):
        import json
        async with sessions_ref() as other:
            fact = await other.get(GeoFact, 80)
            fact.statement = "人工在 AI 调用期间更新了已核验事实。"
            await other.commit()
        return _ai_result(json.loads(user)["current_items"])
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    async def run():
        nonlocal sessions_ref
        async with database() as sessions:
            sessions_ref = sessions
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            async with sessions() as db:
                row = await api.create(api.Create(tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员"), db, ADVISOR)
            req = api.AiProposal(tenant_id=1, project_id=10,
                expected_revision=row["workflow"]["revision"], request_id=uuid4(), mode="initial")
            async with sessions() as db:
                queued = await api.ai_proposal(row["id"], req, db, ADVISOR)
            result = await run_owned(sessions, queued["request_run"]["job_id"])
            assert result["result_meta"]["public_state"] == "stale"
            async with sessions() as db:
                stored = await db.get(GeoActionTicket, row["id"])
                assert stored.progress["onsite"]["revision"] == 1
                assert stored.progress["onsite"]["ai_run"]["state"] == "stale"
    asyncio.run(run())


def test_ai_proposal_late_result_cannot_overwrite_after_role_permission_revoked(monkeypatch):
    async def credentials(session, tenant_id):
        return {"api_key": "test", "base_url": "https://provider.invalid/v1", "model": "test-model"}
    sessions_ref = None
    async def provider(system, user, **kwargs):
        import json
        async with sessions_ref() as other:
            role = await other.get(Role, 5)
            role.permissions = {"geo.assets": "view", "geo.content": "view"}
            await other.commit()
        return _ai_result(json.loads(user)["current_items"])
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    async def run():
        nonlocal sessions_ref
        async with database() as sessions:
            sessions_ref = sessions
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            async with sessions() as db:
                row = await api.create(api.Create(tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员"), db, ADVISOR)
            req = api.AiProposal(tenant_id=1, project_id=10,
                expected_revision=row["workflow"]["revision"], request_id=uuid4(), mode="initial")
            async with sessions() as db:
                queued = await api.ai_proposal(row["id"], req, db, ADVISOR)
            result = await run_owned(sessions, queued["request_run"]["job_id"])
            assert result["result_meta"]["public_state"] == "stale"
            async with sessions() as db:
                stored = await db.get(GeoActionTicket, row["id"])
                assert stored.progress["onsite"]["revision"] == 1
                assert stored.progress["onsite"]["ai_run"]["state"] == "stale"
                assert "ai_proposal" not in stored.progress["onsite"]
    asyncio.run(run())


@pytest.mark.parametrize("category, expected_state", [
    ("unknown", "unknown"), ("model_not_found", "failed"),
])
def test_ai_error_is_classified_and_same_nonce_never_calls_again(
        monkeypatch, category, expected_state):
    calls = 0
    async def credentials(session, tenant_id):
        return {"api_key": "test", "base_url": "https://provider.invalid/v1", "model": "test-model"}
    async def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        from app.geo.ai_client import DeepSeekError
        raise DeepSeekError("sensitive provider failure", category=category,
                            status_code=404 if category == "model_not_found" else None,
                            code=category if category == "model_not_found" else None)
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            async with sessions() as db:
                row = await api.create(api.Create(tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员"), db, ADVISOR)
            req = api.AiProposal(tenant_id=1, project_id=10,
                expected_revision=1, request_id=uuid4(), mode="initial")
            async with sessions() as db:
                queued = await api.ai_proposal(row["id"], req, db, ADVISOR)
            result = await run_owned(sessions, queued["request_run"]["job_id"])
            assert result["result_meta"]["public_state"] == expected_state
            async with sessions() as db:
                retry = await api.ai_proposal(row["id"], req, db, ADVISOR)
                assert retry["workflow"]["ai_run"]["state"] == expected_state
                assert "sensitive" not in retry["workflow"]["ai_run"]["error"]
                assert retry["workflow"]["ai_run"]["error_category"] == category
                if category == "model_not_found":
                    assert retry["workflow"]["ai_run"]["http_status"] == 404
            assert calls == 1
    asyncio.run(run())


def test_advisor_list_filters_assignment_before_pagination(monkeypatch):
    async def credentials(session, tenant_id):
        return None
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                db.add(Role(id=6, name="other advisor", permissions={"geo.assets":"edit", "geo.content":"edit"}))
                db.add(User(id=8, username="other advisor", role_id=6, password_hash="unused", is_active=True))
                await db.commit()
            async with sessions() as db:
                await save_plan(db, 1, 11, dict(enabled=False, status="active", prompt_ids=[],
                    interval_days=7, advisor_user_id=8), 0, 8)
                await db.commit()
            async with sessions() as db:
                own = await api.create(api.Create(tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="顾问一"), db, ADVISOR)
            async with sessions() as db:
                foreign = await api.create(api.Create(tenant_id=1, project_id=11, request_id=uuid4(),
                    work_type="startup", owner_name="顾问二"), db, OTHER_ADVISOR)
            async with sessions() as db:
                result = await api.advisor_tasks(None, None, 50, db, ADVISOR)
            assert result["schema"] == 1 and result["module"] == "geo"
            assert [item["id"] for item in result["items"]] == [own["id"]]
            assert foreign["id"] not in {item["id"] for item in result["items"]}
            item = result["items"][0]
            assert item["scope_name"] == "project 10" and item["tenant_name"] == "scope fixture"
            assert item["capabilities"]["ai_planning"]["enabled"] is False
    asyncio.run(run())
