"""Owned PostgreSQL proves project isolation, revisions and duplicate-request locking."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from uuid import uuid4
import os
import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from starlette.responses import Response
from sqlalchemy import select, func, text, update
from sqlalchemy.exc import DBAPIError
from test_geo_project_scope_postgres import database
from app import api_controls, api_metering
from app.geo import ai_client, onsite_routes as api, onsite_jobs
from app.geo.content import async_jobs
from app.geo.project_workflows import save_plan
from app.models import GeoActionTicket, GeoAsyncJob, GeoFact, GeoProject
from app.security.auth import AuthContext
from app.models.user import User
from app.models.role import Role
from app.automation_project_contract import Configure as AutomationConfigure, Control as AutomationControl
from types import SimpleNamespace
from unittest.mock import patch

pytestmark = pytest.mark.skipif(not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated PostgreSQL")
ADVISOR = AuthContext(7, "advisor", "advisor", None, {"geo.assets":"edit", "geo.content":"edit"})
CUSTOMER = AuthContext(12, "customer", "customer", 1, {"geo.assets":"view", "geo.content":"view"})
OTHER_ADVISOR = AuthContext(8, "advisor2", "advisor", None, {"geo.assets":"edit", "geo.content":"edit"})
SUPERADMIN = AuthContext(None, "ops", "superadmin", None, {}, is_superadmin=True)


async def _ai_proposal(task_id, request, session, context, **kwargs):
    return await api.ai_proposal(
        task_id, request, session, context,
        protocol=api.ONSITE_PROTOCOL, **kwargs,
    )


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


async def _install_api_accounting(sessions):
    engine = sessions.kw["bind"]
    root = Path(__file__).parents[1]
    async with engine.connect() as connection:
        raw = (await connection.get_raw_connection()).driver_connection
        await raw.execute((root / "scripts/api_metering_schema.sql").read_text())
        await raw.execute((root / "scripts/api_controls_schema.sql").read_text())
        await raw.execute("""ALTER TABLE api_usage_events
            ADD COLUMN review_version integer NOT NULL DEFAULT 0,
            ADD COLUMN verified_amount numeric(24,12),
            ADD COLUMN verified_currency varchar(3),
            ADD COLUMN reviewed_at timestamptz""")


async def _install_automation_control(sessions):
    engine = sessions.kw["bind"]
    root = Path(__file__).parents[1]
    async with engine.connect() as connection:
        raw = (await connection.get_raw_connection()).driver_connection
        await raw.execute((root / "scripts/automation_projects_schema.sql").read_text())


@pytest.mark.parametrize(
    "verified_amount,budget_cap,expected_code",
    [("5", "4", "api_budget_exhausted"),
     (None, "100", "api_charge_unresolved")],
)
def test_real_onsite_executor_honors_reviewed_cost_before_provider(
        monkeypatch, verified_amount, budget_cap, expected_code):
    """Exercise GEO executor -> chat client -> metering -> native admission."""
    provider_calls = 0
    original_client = httpx.AsyncClient

    async def credentials(_session, _tenant_id):
        return {
            "api_key": "fixture-key",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "deepseek-v4-flash",
        }

    async def provider(_request):
        nonlocal provider_calls
        provider_calls += 1
        proposal = _ai_result([
            {"id": "structured_content", "kind": "structured_content"},
            {"id": "knowledge", "kind": "knowledge"},
            {"id": "faq", "kind": "faq"},
        ])
        return httpx.Response(200, json={
            "id": "fixture-request",
            "choices": [{"message": {"content": json.dumps(proposal)}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
        })

    def client_factory(*_args, **kwargs):
        return original_client(
            timeout=kwargs.get("timeout"), transport=httpx.MockTransport(provider)
        )

    monkeypatch.setenv("API_METERING_ENABLED", "true")
    monkeypatch.setenv("API_CONTROLS_ENABLED", "true")
    monkeypatch.delenv("API_METERING_RATES_JSON", raising=False)
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(ai_client.httpx, "AsyncClient", client_factory)

    async def run():
        async with database() as sessions:
            await _install_api_accounting(sessions)
            monkeypatch.setattr(api_metering, "async_session_factory", sessions)
            monkeypatch.setattr(api_controls, "async_session_factory", sessions)
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
                await api_controls.mutate(
                    db, actor_id=7, request_id=str(uuid4()), kind="budget",
                    key="budget:global", expected_revision=0,
                    value={
                        "daily_calls": None, "monthly_calls": None,
                        "daily_cny": None, "monthly_cny": "100",
                        "max_concurrent": None, "warning_percent": 80,
                    },
                )
            async with sessions() as db:
                task = await api.create(api.Create(
                    tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员",
                ), db, ADVISOR)
            first_request = api.AiProposal(
                tenant_id=1, project_id=10, expected_revision=1,
                request_id=uuid4(), mode="initial",
            )
            async with sessions() as db:
                queued = await _ai_proposal(task["id"], first_request, db, ADVISOR)
            completed = await run_owned(sessions, queued["request_run"]["job_id"])
            assert completed["result_meta"]["public_state"] == "ready"
            assert provider_calls == 1

            async with sessions() as db:
                event = (await db.execute(text(
                    "SELECT id,state,module,operation FROM api_usage_events"
                ))).one()
                assert event.state == "succeeded"
                assert event.module == "geo" and event.operation == "chat.completions"
                await db.execute(text("""UPDATE api_usage_events SET
                    review_version=1,verified_amount=:amount,
                    verified_currency=:currency,reviewed_at=CURRENT_TIMESTAMP
                    WHERE id=:id"""), {
                        "id": event.id,
                        "amount": verified_amount,
                        "currency": "CNY" if verified_amount is not None else None,
                    })
                await db.commit()
                await api_controls.mutate(
                    db, actor_id=7, request_id=str(uuid4()), kind="budget",
                    key="budget:global", expected_revision=1,
                    value={
                        "daily_calls": None, "monthly_calls": None,
                        "daily_cny": None, "monthly_cny": budget_cap,
                        "max_concurrent": 1, "warning_percent": 80,
                    },
                )
                spent = await api_controls.usage(db, "global")
                assert spent["active_calls"] == 0
                if verified_amount is None:
                    assert spent["unresolved_calls"] == 1
                else:
                    assert spent["monthly_cny"] == "5.000000000000"

            second_request = api.AiProposal(
                tenant_id=1, project_id=10, expected_revision=2,
                request_id=uuid4(), mode="revise",
            )
            async with sessions() as db:
                queued = await _ai_proposal(task["id"], second_request, db, ADVISOR)
            denied = await run_owned(sessions, queued["request_run"]["job_id"])
            assert denied["result_meta"]["public_state"] == "failed"
            assert denied["result_meta"]["error_category"] == "admission_denied"
            assert denied["result_meta"]["error_code"] == expected_code
            assert provider_calls == 1

    asyncio.run(run())


@pytest.mark.parametrize("protocol", [None, "legacy-v0"])
def test_ai_proposal_requires_durable_protocol_before_writes_or_quota(
        monkeypatch, protocol):
    credential_reads = provider_calls = 0

    async def credentials(*_args, **_kwargs):
        nonlocal credential_reads
        credential_reads += 1
        return {"api_key": "must-not-be-read"}

    async def provider(*_args, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {}

    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", provider)

    async def run():
        nonlocal credential_reads
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                task = await api.create(api.Create(
                    tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员",
                ), db, ADVISOR)
            # Task serialization advertises AI capability and may inspect whether
            # credentials exist. Measure only the rejected proposal endpoint.
            credential_reads = 0
            async with sessions() as db:
                project = await db.get(GeoProject, 10)
                settings_before = json.loads(json.dumps(project.project_settings or {}))
                jobs_before = await db.scalar(select(func.count()).select_from(GeoAsyncJob))
                rejected = await api.ai_proposal(
                    task["id"], api.AiProposal(
                        tenant_id=1, project_id=10, expected_revision=1,
                        request_id=uuid4(), mode="initial",
                    ), db, ADVISOR, protocol=protocol,
                )
                assert rejected.status_code == 409
                assert rejected.headers["cache-control"] == "no-store"
                assert json.loads(rejected.body) == {
                    "detail": "工作台版本过旧，请刷新页面后重试",
                    "code": "onsite_client_upgrade_required",
                }
            async with sessions() as db:
                project = await db.get(GeoProject, 10)
                stored = await db.get(GeoActionTicket, task["id"])
                assert (project.project_settings or {}) == settings_before
                assert await db.scalar(select(func.count()).select_from(GeoAsyncJob)) == jobs_before
                assert "ai_run" not in stored.progress["onsite"]
        assert credential_reads == 0
        assert provider_calls == 0

    asyncio.run(run())


def test_onsite_health_is_global_admin_read_only_real_queue_aggregate(monkeypatch):
    monkeypatch.setattr(onsite_jobs, "pending_worker_status", lambda: {
        "enabled": True, "state": "unverified", "verified": False,
        "evidence": None, "last_tick_at": None,
        "last_attempted": 0, "last_completed": 0, "last_error_code": None,
    })

    async def run():
        async with database() as sessions:
            async with sessions() as db:
                db.add_all([
                    GeoAsyncJob(tenant_id=1, kind=async_jobs.KIND_ONSITE_PROPOSAL,
                                status="pending", ref_type="onsite_task", ref_id=1),
                    GeoAsyncJob(tenant_id=1, kind=async_jobs.KIND_ONSITE_PROPOSAL,
                                status="running", ref_type="onsite_task", ref_id=2,
                                started_at=api.datetime(2026, 10, 10, 1, 2, 3)),
                    GeoAsyncJob(tenant_id=1, kind=async_jobs.KIND_ONSITE_PROPOSAL,
                                status="failed", ref_type="onsite_task", ref_id=3,
                                result_meta={"public_state": "unknown", "prompt": "secret"}),
                    GeoAsyncJob(tenant_id=1, kind=async_jobs.KIND_GENERATE,
                                status="pending", ref_type="content_task", ref_id=4),
                ])
                await db.commit()
            async with sessions() as db:
                response = Response()
                result = await api.onsite_ai_health(response, db, SUPERADMIN)
                assert response.headers["cache-control"] == "no-store"
                assert result["schema"] == 1 and result["module"] == "geo"
                assert result["worker"] == {
                    "scope": "this_process", "enabled": True,
                    "state": "unverified", "verified": False, "evidence": None,
                    "last_tick_at": None, "last_attempted": 0,
                    "last_completed": 0, "last_error_code": None,
                }
                assert result["queue"]["state"] == "available"
                assert result["queue"]["queued"] == 1
                assert result["queue"]["running"] == 1
                assert result["queue"]["unknown"] == 1
                assert result["queue"]["oldest_queued_at"]
                assert result["queue"]["oldest_running_at"] == "2026-10-10T01:02:03"
                assert "secret" not in str(result)
                with pytest.raises(HTTPException) as denied:
                    await api.onsite_ai_health(Response(), db, ADVISOR)
                assert denied.value.status_code == 403

    asyncio.run(run())


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
                result = await _ai_proposal(row["id"], req, db, ADVISOR)
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
                same = await _ai_proposal(row["id"], req, db, ADVISOR)
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
                    await _ai_proposal(row["id"], request, db, ADVISOR)
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
                    await _ai_proposal(row["id"], request, db, ADVISOR)
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
                    await _ai_proposal(row["id"], request, db, ADVISOR)
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
                    return await _ai_proposal(row["id"], req, db, ADVISOR)
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
                queued = await _ai_proposal(row["id"], req, db, ADVISOR)
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
                queued = await _ai_proposal(row["id"], api.AiProposal(
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
                queued = await _ai_proposal(row["id"], api.AiProposal(
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
                queued = await _ai_proposal(row["id"], api.AiProposal(
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
                queued = await _ai_proposal(row["id"], req, db, ADVISOR)
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
                queued = await _ai_proposal(row["id"], req, db, ADVISOR)
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
                queued = await _ai_proposal(row["id"], req, db, ADVISOR)
            result = await run_owned(sessions, queued["request_run"]["job_id"])
            assert result["result_meta"]["public_state"] == expected_state
            async with sessions() as db:
                retry = await _ai_proposal(row["id"], req, db, ADVISOR)
                assert retry["workflow"]["ai_run"]["state"] == expected_state
                assert "sensitive" not in retry["workflow"]["ai_run"]["error"]
                assert retry["workflow"]["ai_run"]["error_category"] == category
                if category == "model_not_found":
                    assert retry["workflow"]["ai_run"]["http_status"] == 404
            assert calls == 1
    asyncio.run(run())


def test_ai_admission_denial_is_definitive_failed_and_not_unknown(monkeypatch):
    attempts = 0

    async def credentials(session, tenant_id):
        return {"api_key": "test", "base_url": "https://provider.invalid/v1",
                "model": "test-model"}

    async def denied_before_provider(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        from app.api_controls import ControlDenied
        raise ControlDenied("controlled policy detail", code="api_concurrency_limit",
                            target="tenant:1")

    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", denied_before_provider)

    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            async with sessions() as db:
                row = await api.create(api.Create(
                    tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员",
                ), db, ADVISOR)
            request_id = uuid4()
            request = api.AiProposal(
                tenant_id=1, project_id=10, expected_revision=1,
                request_id=request_id, mode="initial",
            )
            async with sessions() as db:
                queued = await _ai_proposal(row["id"], request, db, ADVISOR)
            result = await run_owned(sessions, queued["request_run"]["job_id"])
            assert result["result_meta"]["public_state"] == "failed"
            async with sessions() as db:
                polled = await api.get_ai_request(
                    row["id"], request_id, 1, 10, db, ADVISOR,
                )
            run = polled["request_run"]
            assert run["state"] == "failed"
            assert run["error_category"] == "admission_denied"
            assert run["error_code"] == "api_concurrency_limit"
            assert run["error"] == "AI 请求未通过平台调用门禁，供应商未被调用"
            assert "controlled policy detail" not in str(run)
            assert attempts == 1

    asyncio.run(run())


@pytest.mark.parametrize("provider_attempted,expected_state,expected_category", [
    (False, "failed", "admission_unavailable"),
    (True, "unknown", "metering_finalize_unknown"),
])
def test_ai_metering_failure_uses_explicit_provider_attempt_marker(
        monkeypatch, provider_attempted, expected_state, expected_category):
    async def credentials(session, tenant_id):
        return {"api_key": "test", "base_url": "https://provider.invalid/v1",
                "model": "test-model"}

    async def metering_failure(*args, **kwargs):
        from app.api_metering import MeteringUnavailable
        raise MeteringUnavailable(
            "internal accounting detail", provider_attempted=provider_attempted,
        )

    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "chat_json", metering_failure)

    async def run():
        async with database() as sessions:
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            async with sessions() as db:
                row = await api.create(api.Create(
                    tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员",
                ), db, ADVISOR)
            request_id = uuid4()
            async with sessions() as db:
                queued = await _ai_proposal(row["id"], api.AiProposal(
                    tenant_id=1, project_id=10, expected_revision=1,
                    request_id=request_id, mode="initial",
                ), db, ADVISOR)
            result = await run_owned(sessions, queued["request_run"]["job_id"])
            assert result["result_meta"]["public_state"] == expected_state
            async with sessions() as db:
                polled = await api.get_ai_request(
                    row["id"], request_id, 1, 10, db, ADVISOR,
                )
            request_run = polled["request_run"]
            assert request_run["state"] == expected_state
            assert request_run["error_category"] == expected_category
            assert "internal accounting detail" not in str(request_run)

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


def test_project_control_drives_real_geo_queue_metering_and_shared_events(monkeypatch):
    """HTTP adapter -> durable child -> real executor -> metering -> shared result."""
    from app import automation_projects as control
    from app.geo import automation_routes

    provider_calls = 0
    original_client = httpx.AsyncClient

    async def credentials(_session, _tenant_id):
        return {
            "api_key": "fixture-key",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "deepseek-v4-flash",
        }

    async def provider(_request):
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={
            "id": "automation-fixture",
            "choices": [{"message": {"content": json.dumps(_ai_result([
                {"id": "structured_content", "kind": "structured_content"},
                {"id": "knowledge", "kind": "knowledge"},
                {"id": "faq", "kind": "faq"},
            ]))}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                      "prompt_tokens_details": {"cached_tokens": 0}},
        })

    def client_factory(*_args, **kwargs):
        return original_client(timeout=kwargs.get("timeout"), transport=httpx.MockTransport(provider))

    monkeypatch.setenv("API_METERING_ENABLED", "true")
    monkeypatch.setenv("API_CONTROLS_ENABLED", "false")
    monkeypatch.delenv("API_METERING_RATES_JSON", raising=False)
    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(onsite_jobs, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(ai_client.httpx, "AsyncClient", client_factory)

    async def run():
        async with database() as sessions:
            await _install_api_accounting(sessions)
            await _install_automation_control(sessions)
            monkeypatch.setattr(api_metering, "async_session_factory", sessions)
            monkeypatch.setattr(automation_routes, "async_session_factory", sessions)
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            async with sessions() as db:
                task = await api.create(api.Create(
                    tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员",
                ), db, ADVISOR)
            queued_ids = []

            async def owned(job_id, tenant_id):
                queued_ids.append((job_id, tenant_id))
                return None

            monkeypatch.setattr(automation_routes.async_jobs, "run_job_in_background", owned)
            from app.database import get_session
            from app.security.auth import require_scoped_auth
            web = FastAPI()
            web.include_router(automation_routes.router, prefix="/api/v1/geo")

            async def session_dependency():
                async with sessions() as db:
                    yield db

            web.dependency_overrides[get_session] = session_dependency
            web.dependency_overrides[require_scoped_auth] = lambda: ADVISOR
            async with original_client(
                transport=httpx.ASGITransport(app=web), base_url="http://automation.test"
            ) as client:
                configured_response = await client.put(
                    "/api/v1/geo/workbench/automation-projects/10/control",
                    json={
                        "tenant_id": 1, "request_id": str(uuid4()), "expected_version": 0,
                        "configuration": {
                            "task_ids": [task["id"]], "operations": ["onsite_ai"],
                            "cycle": {"mode": "once", "enabled": False},
                            "limits": {"max_dispatches_per_run": 1},
                            "stop_condition": "drafts_ready_or_blocked", "owner_user_id": 7,
                        },
                    },
                )
                assert configured_response.status_code == 200
                assert configured_response.headers["cache-control"] == "no-store"
                configured_project = configured_response.json()
                started_response = await client.post(
                    "/api/v1/geo/workbench/automation-projects/10/control",
                    json={
                        "tenant_id": 1, "request_id": str(uuid4()),
                        "expected_version": configured_project["version"], "action": "start",
                    },
                )
                assert started_response.status_code == 200
                assert started_response.headers["cache-control"] == "no-store"
                started = started_response.json()
            key = control.scope("geo", 1, 10)
            assert len(queued_ids) == 1
            async with sessions() as db:
                queued_job = await db.get(GeoAsyncJob, queued_ids[0][0], with_for_update=True)
                queued_job.request_meta = {
                    key: value for key, value in queued_job.request_meta.items()
                    if key != "automation_token"
                }
                await db.commit()
            await run_owned(sessions, *queued_ids[0])
            assert provider_calls == 1
            async with sessions() as db:
                jobs = list(await db.scalars(select(GeoAsyncJob)))
                assert len(jobs) == 1 and jobs[0].status == "succeeded"
                assert "automation_token" not in jobs[0].request_meta
                run_row = await control.read_run(db, key, started["current_run_id"])
                step = run_row["steps"][0]
                assert step["status"] == "succeeded"
                assert step["evidence_refs"] == [f"geo_ticket:{task['id']}"]
                assert step["result_links"][0].startswith("/api/v1/geo/")
                assert step["fee_state"] == "unverified"
                events = await control.events_page(db, key, started["current_run_id"])
                assert {event["code"] for event in events["items"]} >= {
                    "run_queued", "step_claimed", "dispatch_admitted", "step_succeeded",
                }
                usage = (await db.execute(text(
                    "SELECT state,module,operation FROM api_usage_events"
                ))).one()
                assert usage.state == "succeeded" and usage.module == "geo"
                assert usage.operation == "chat.completions"
                assert "fixture-key" not in str(events)
            # Recovery sees a terminal step and cannot create or repay it.
            await automation_routes.recover_automation_runs()
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(GeoAsyncJob)) == 1
            paths = [
                "/api/v1/geo/workbench/automation-projects?tenant_id=1",
                "/api/v1/geo/workbench/automation-projects/10/control?tenant_id=1",
                "/api/v1/geo/workbench/automation-projects/10/runs?tenant_id=1",
                f"/api/v1/geo/workbench/automation-projects/10/runs/{started['current_run_id']}?tenant_id=1",
                f"/api/v1/geo/workbench/automation-projects/10/runs/{started['current_run_id']}/events?tenant_id=1",
                "/api/v1/geo/workbench/automation-projects/10/events?tenant_id=1",
            ]
            responses = {}
            async with original_client(
                transport=httpx.ASGITransport(app=web), base_url="http://automation.test"
            ) as client:
                for path in paths:
                    response = await client.get(path)
                    assert response.status_code == 200
                    assert response.headers["cache-control"] == "no-store"
                    responses[path] = response.json()
            sample_path = os.getenv("GEO_AUTOMATION_SAMPLE_PATH")
            if sample_path:
                Path(sample_path).write_text(json.dumps({
                    "source": "isolated PostgreSQL + ASGI routes",
                    "responses": responses,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            async with sessions() as db:
                role = await db.get(Role, 5, with_for_update=True)
                role.permissions = {"geo.assets": "view", "geo.content": "view"}
                await db.commit()
            async with sessions() as db:
                project = await db.get(GeoProject, 10)
                assert not await api.can_operate(db, ADVISOR, project)
                payload = await automation_routes._project_payload(
                    db, key, live_project=project, actor_id=7
                )
                assert payload["scope_name"] == "project 10"
                assert payload["blocker"] == "automation_owner_mismatch"
                assert payload["allowed_actions"] == []
                assert payload["capabilities"]["can_control"] is False

    asyncio.run(run())


@pytest.mark.parametrize("action,final_state", [("pause", "paused"), ("takeover", "taken_over")])
def test_project_control_fences_inflight_geo_result_and_never_requeues(
        monkeypatch, action, final_state):
    from app import automation_projects as control
    from app.geo import automation_routes

    async def credentials(_session, _tenant_id):
        return {"api_key": "fixture-key", "base_url": "https://provider.invalid/v1",
                "model": "fixture-model"}

    async def no_worker(*_args, **_kwargs):
        return None

    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(automation_routes.async_jobs, "run_job_in_background", no_worker)
    monkeypatch.setattr(automation_routes, "run_automation", automation_routes.run_automation)

    async def run():
        async with database() as sessions:
            await _install_automation_control(sessions)
            monkeypatch.setattr(automation_routes, "async_session_factory", sessions)
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            async with sessions() as db:
                task = await api.create(api.Create(
                    tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员",
                ), db, ADVISOR)
            async with sessions() as db:
                configured_project = await automation_routes.configure(
                    10, AutomationConfigure(
                        tenant_id=1, request_id=uuid4(), expected_version=0,
                        configuration={
                            "task_ids": [task["id"]], "operations": ["onsite_ai"],
                            "cycle": {"mode": "once", "enabled": False},
                            "limits": {"max_dispatches_per_run": 1},
                            "stop_condition": "drafts_ready_or_blocked", "owner_user_id": 7,
                        },
                    ), Response(), db, ADVISOR,
                )
            async with sessions() as db:
                started = await automation_routes.act(
                    10, AutomationControl(
                        tenant_id=1, request_id=uuid4(),
                        expected_version=configured_project["version"], action="start",
                    ), Response(), BackgroundTasks(), db, ADVISOR,
                )
            key = control.scope("geo", 1, 10)
            await automation_routes.run_automation(key, started["current_run_id"])
            async with sessions() as db:
                job = await db.scalar(select(GeoAsyncJob).with_for_update())
                token = job.request_meta["automation_token"]
                assert await control.begin_dispatch(db, token)
                job.status = "running"
                job.request_meta = {
                    **{key: value for key, value in job.request_meta.items()
                       if key != "automation_token"},
                    "provider_started_at": "2026-10-11T00:00:00Z",
                }
                await db.commit()
            async with sessions() as db:
                stopped = await automation_routes.act(
                    10, AutomationControl(
                        tenant_id=1, request_id=uuid4(),
                        expected_version=started["version"], action=action,
                    ), Response(), BackgroundTasks(), db, ADVISOR,
                )
                assert stopped["state"] in {"pausing", "taking_over"}
            resumed = asyncio.Event()

            async def no_resume(*_args, **_kwargs):
                resumed.set()

            monkeypatch.setattr(automation_routes, "run_automation", no_resume)
            async with sessions() as db:
                job = await db.scalar(select(GeoAsyncJob).with_for_update())
                assert job.request_meta["cancel_requested"] is True
                assert await onsite_jobs._settle_automation(
                    db, job, status="succeeded", fee_state="recorded", success=True
                )
            await asyncio.wait_for(resumed.wait(), 1)
            async with sessions() as db:
                project = await control.read_project(db, key)
                run_row = await control.read_run(db, key, started["current_run_id"])
                assert project["state"] == final_state
                assert run_row["steps"][0]["status"] == "stale"
                assert run_row["steps"][0]["fee_state"] == "recorded"
                assert run_row["steps"][0]["result_links"] == []
                assert await db.scalar(select(func.count()).select_from(GeoAsyncJob)) == 1

    asyncio.run(run())


def test_recovery_filters_waiting_projects_before_limit(monkeypatch):
    from app.geo import automation_routes

    async def run():
        async with database() as sessions:
            await _install_automation_control(sessions)
            monkeypatch.setattr(automation_routes, "async_session_factory", sessions)
            captured = []

            async def capture(key, run_id):
                captured.append((key, run_id))

            monkeypatch.setattr(automation_routes, "run_automation", capture)
            config = json.dumps({
                "task_ids": [1], "operations": ["onsite_ai"],
                "cycle": {"mode": "once", "enabled": False},
                "limits": {"max_dispatches_per_run": 1},
                "stop_condition": "drafts_ready_or_blocked", "owner_user_id": 7,
            })
            async with sessions() as db:
                for scope_id in range(100, 121):
                    run_id = uuid4()
                    pending = scope_id == 120
                    steps = json.dumps([{
                        "step_key": f"onsite_ai:{scope_id}", "kind": "onsite_ai",
                        "task_id": scope_id, "status": "pending" if pending else "succeeded",
                        "started_at": None, "finished_at": None, "waiting_for": "system",
                        "blocker": None, "result_links": [], "error_code": None,
                        "request_id": str(uuid4()), "evidence_refs": [],
                        "fee_state": "not_called", "dispatched_at": None,
                    }])
                    await db.execute(text("""INSERT INTO automation_projects
                        (module,tenant_id,scope_id,owner_user_id,configuration,state)
                        VALUES('geo',1,:scope,7,CAST(:config AS jsonb),'active')"""),
                        {"scope": scope_id, "config": config})
                    await db.execute(text("""INSERT INTO automation_project_runs
                        (id,module,tenant_id,scope_id,generation,state,configuration,steps)
                        VALUES(CAST(:run AS uuid),'geo',1,:scope,1,:state,
                               CAST(:config AS jsonb),CAST(:steps AS jsonb))"""),
                        {"run": str(run_id), "scope": scope_id,
                         "state": "queued" if pending else "waiting_human",
                         "config": config, "steps": steps})
                    await db.execute(text("""UPDATE automation_projects
                        SET current_run_id=CAST(:run AS uuid),updated_at=CURRENT_TIMESTAMP
                        WHERE module='geo' AND tenant_id=1 AND scope_id=:scope"""),
                        {"run": str(run_id), "scope": scope_id})
                await db.commit()
            assert await automation_routes.recover_automation_runs(limit=20) == 1
            assert len(captured) == 1 and captured[0][0]["scope_id"] == 120

    asyncio.run(run())


def test_automation_preflight_block_is_atomic_bounded_and_free(monkeypatch):
    from app import automation_projects as control
    from app.geo import automation_routes

    async def no_credentials(_session, _tenant_id):
        return None

    monkeypatch.setattr(api, "resolve_llm_credentials", no_credentials)

    async def run():
        async with database() as sessions:
            await _install_automation_control(sessions)
            monkeypatch.setattr(automation_routes, "async_session_factory", sessions)
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            async with sessions() as db:
                task = await api.create(api.Create(
                    tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员",
                ), db, ADVISOR)
            async with sessions() as db:
                configured_project = await automation_routes.configure(
                    10, AutomationConfigure(
                        tenant_id=1, request_id=uuid4(), expected_version=0,
                        configuration={
                            "task_ids": [task["id"]], "operations": ["onsite_ai"],
                            "cycle": {"mode": "once", "enabled": False},
                            "limits": {"max_dispatches_per_run": 1},
                            "stop_condition": "drafts_ready_or_blocked", "owner_user_id": 7,
                        },
                    ), Response(), db, ADVISOR,
                )
            async with sessions() as db:
                started = await automation_routes.act(
                    10, AutomationControl(
                        tenant_id=1, request_id=uuid4(),
                        expected_version=configured_project["version"], action="start",
                    ), Response(), BackgroundTasks(), db, ADVISOR,
                )
            key = control.scope("geo", 1, 10)
            await asyncio.wait_for(
                automation_routes.run_automation(key, started["current_run_id"]), 2
            )
            async with sessions() as db:
                run_row = await control.read_run(db, key, started["current_run_id"])
                assert run_row["state"] == "waiting_input"
                assert run_row["dispatch_count"] == 1
                assert run_row["steps"][0]["status"] == "blocked"
                assert run_row["steps"][0]["fee_state"] == "not_called"
                assert await db.scalar(select(func.count()).select_from(GeoAsyncJob)) == 0
                events = await control.events_page(db, key, started["current_run_id"])
                assert [event["code"] for event in events["items"]].count("step_claimed") == 1
                assert [event["code"] for event in events["items"]].count("step_blocked") == 1

    asyncio.run(run())


def test_automation_never_revises_review_task_on_new_start_or_due_cycle(monkeypatch):
    from app import automation_projects as control
    from app.geo import automation_routes

    async def run():
        async with database() as sessions:
            await _install_automation_control(sessions)
            monkeypatch.setattr(automation_routes, "async_session_factory", sessions)
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            async with sessions() as db:
                task = await api.create(api.Create(
                    tenant_id=1, project_id=10, request_id=uuid4(),
                    work_type="startup", owner_name="维护人员",
                ), db, ADVISOR)
            async with sessions() as db:
                configured_project = await automation_routes.configure(
                    10, AutomationConfigure(
                        tenant_id=1, request_id=uuid4(), expected_version=0,
                        configuration={
                            "task_ids": [task["id"]], "operations": ["onsite_ai"],
                            "cycle": {"mode": "daily", "enabled": True},
                            "limits": {"max_dispatches_per_run": 1},
                            "stop_condition": "drafts_ready_or_blocked", "owner_user_id": 7,
                        },
                    ), Response(), db, ADVISOR,
                )
            async with sessions() as db:
                started = await automation_routes.act(
                    10, AutomationControl(
                        tenant_id=1, request_id=uuid4(),
                        expected_version=configured_project["version"], action="start",
                    ), Response(), BackgroundTasks(), db, ADVISOR,
                )
            key = control.scope("geo", 1, 10)
            async with sessions() as db:
                token = await control.claim_step(db, key)
                assert await control.settle_step(
                    db, token, status="succeeded", evidence_refs=[f"geo_ticket:{task['id']}"],
                    result_links=[f"/api/v1/geo/workbench/onsite-tasks/{task['id']}"],
                    fee_state="unverified",
                )
                row = await db.get(GeoActionTicket, task["id"], with_for_update=True)
                value = dict(row.progress["onsite"])
                value.update(
                    phase="review",
                    revision=int(value["revision"]) + 1,
                    ai_proposal={"schema": 2, "proposal_revision": int(value["revision"]) + 1},
                    ai_run={"request_id": token["request_id"], "state": "ready"},
                )
                row.progress = {**row.progress, "onsite": value}
                await db.commit()
            async with sessions() as db:
                ended = await automation_routes.act(
                    10, AutomationControl(
                        tenant_id=1, request_id=uuid4(), expected_version=started["version"],
                        action="end",
                    ), Response(), BackgroundTasks(), db, ADVISOR,
                )
                assert ended["state"] == "idle" and ended["next_due_at"] is not None
            async with sessions() as db:
                with pytest.raises(HTTPException) as error:
                    await automation_routes.act(
                        10, AutomationControl(
                            tenant_id=1, request_id=uuid4(),
                            expected_version=ended["version"], action="start",
                        ), Response(), BackgroundTasks(), db, ADVISOR,
                    )
                assert error.value.detail["code"] == "automation_task_not_draft"
                await db.rollback()
                assert await db.scalar(select(func.count()).select_from(GeoAsyncJob)) == 0
                assert await db.scalar(text("SELECT count(*) FROM automation_project_runs")) == 1
                await db.execute(text("""UPDATE automation_projects
                    SET next_due_at=CURRENT_TIMESTAMP-INTERVAL '1 second'
                    WHERE module='geo' AND tenant_id=1 AND scope_id=10"""))
                await db.commit()
            assert await automation_routes.recover_automation_runs() == 1
            async with sessions() as db:
                runs = list((await db.execute(text("""SELECT * FROM automation_project_runs
                    WHERE module='geo' AND tenant_id=1 AND scope_id=10
                    ORDER BY created_at,id"""))).mappings())
                assert len(runs) == 2
                assert runs[-1]["state"] == "waiting_input"
                assert runs[-1]["steps"][0]["status"] == "blocked"
                assert runs[-1]["steps"][0]["error_code"] == "automation_task_not_draft"
                assert runs[-1]["steps"][0]["fee_state"] == "not_called"
                assert await db.scalar(select(func.count()).select_from(GeoAsyncJob)) == 0
                row = await db.get(GeoActionTicket, task["id"])
                assert row.progress["onsite"]["phase"] == "review"
                assert row.progress["onsite"]["ai_proposal"]["proposal_revision"] == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutation,expected_code",
    [
        ("review", "automation_task_not_draft"),
        ("project", "automation_task_not_found"),
        ("prefix", "automation_task_not_found"),
    ],
)
def test_pending_automation_task_change_is_blocked_without_child_job(
        monkeypatch, mutation, expected_code):
    from app import automation_projects as control
    from app.geo import automation_routes

    async def credentials(_session, _tenant_id):
        return {"api_key": "fixture-key", "base_url": "https://provider.invalid/v1",
                "model": "fixture-model"}

    async def no_worker(*_args, **_kwargs):
        return None

    monkeypatch.setattr(api, "resolve_llm_credentials", credentials)
    monkeypatch.setattr(automation_routes.async_jobs, "run_job_in_background", no_worker)

    async def run():
        async with database() as sessions:
            await _install_automation_control(sessions)
            monkeypatch.setattr(automation_routes, "async_session_factory", sessions)
            await configured(sessions)
            async with sessions() as db:
                await _add_public_fact(db)
            tasks = []
            for owner in ("维护人员一", "维护人员二"):
                async with sessions() as db:
                    tasks.append(await api.create(api.Create(
                        tenant_id=1, project_id=10, request_id=uuid4(),
                        work_type="startup", owner_name=owner,
                    ), db, ADVISOR))
            async with sessions() as db:
                configured_project = await automation_routes.configure(
                    10, AutomationConfigure(
                        tenant_id=1, request_id=uuid4(), expected_version=0,
                        configuration={
                            "task_ids": [item["id"] for item in tasks],
                            "operations": ["onsite_ai"],
                            "cycle": {"mode": "once", "enabled": False},
                            "limits": {"max_dispatches_per_run": 2},
                            "stop_condition": "drafts_ready_or_blocked", "owner_user_id": 7,
                        },
                    ), Response(), db, ADVISOR,
                )
            async with sessions() as db:
                started = await automation_routes.act(
                    10, AutomationControl(
                        tenant_id=1, request_id=uuid4(),
                        expected_version=configured_project["version"], action="start",
                    ), Response(), BackgroundTasks(), db, ADVISOR,
                )
            key = control.scope("geo", 1, 10)
            await automation_routes.run_automation(key, started["current_run_id"])
            async with sessions() as db:
                first_job = await db.scalar(select(GeoAsyncJob))
                token = first_job.request_meta["automation_token"]
                assert await control.settle_step(
                    db, token, status="succeeded", evidence_refs=[f"geo_ticket:{tasks[0]['id']}"],
                    result_links=[f"/api/v1/geo/workbench/onsite-tasks/{tasks[0]['id']}"],
                    fee_state="unverified",
                )
                second = await db.get(GeoActionTicket, tasks[1]["id"], with_for_update=True)
                value = dict(second.progress["onsite"])
                if mutation == "review":
                    value.update(phase="review", revision=int(value["revision"]) + 1)
                elif mutation == "project":
                    value["project_id"] = 11
                else:
                    second.advice_code = "cockpit:v1:task"
                second.progress = {**second.progress, "onsite": value}
                await db.commit()
                expected_progress = json.loads(json.dumps(second.progress))
                expected_advice_code = second.advice_code
            await automation_routes.run_automation(key, started["current_run_id"])
            async with sessions() as db:
                run_row = await control.read_run(db, key, started["current_run_id"])
                assert run_row["steps"][0]["status"] == "succeeded"
                assert run_row["steps"][1]["status"] == "blocked"
                assert run_row["steps"][1]["error_code"] == expected_code
                assert run_row["steps"][1]["fee_state"] == "not_called"
                assert await db.scalar(select(func.count()).select_from(GeoAsyncJob)) == 1
                second = await db.get(GeoActionTicket, tasks[1]["id"])
                assert second.progress == expected_progress
                assert second.advice_code == expected_advice_code

    asyncio.run(run())
