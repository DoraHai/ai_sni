"""Advisor AI: real mounted auth/SQL, synthetic data, no supplier calls."""
import asyncio
import copy
import os
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app.models import (GeoAsyncJob, GeoContentTask, GeoFact, GeoProject,
                        GeoTaskFact, Role, User)
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.security import advisor_write_ai as policy
from test_advisor_scoped_writes import (backend, fixture_token, mutate,
    no_external_http_or_background_dispatch, write_sandbox)

BRIEF = {"industry": "软件", "audience": "企业", "intent": "recommend", "content_type": "answer_guide", "cta": "了解产品"}


async def ready(env):
    async with env.factory() as session:
        task = await session.get(GeoContentTask, 10)
        task.brief = BRIEF.copy()
        for ident in (10, 11):
            fact = await session.get(GeoFact, ident)
            fact.trust_level = "verified"
        session.add(GeoFact(id=12, tenant_id=10, business_id=10, title="fact three",
                    statement="第三条合成事实", source_name="测试来源", trust_level="verified"))
        session.add_all([GeoTaskFact(task_id=10, fact_id=i) for i in (11, 12)])
        await session.commit()


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    async def none(*_a, **_k):
        return None
    monkeypatch.setattr("app.geo.content.ai_settings.resolve_llm_credentials", none)


@pytest.mark.parametrize("action", ["generate", "suggest-brief"])
@pytest.mark.parametrize("case", ["off", "unselected", "ungranted", "other-advisor", "inactive", "state", "patrol"])
def test_ai_denies_before_model_or_reservation(tmp_path, monkeypatch, action, case, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend, enabled=case != "off") as env:
            await ready(env)
            auth = None
            if case == "unselected":
                auth = fixture_token(native=True)
            if case == "ungranted":
                auth = fixture_token(tid=30, gid=999)
            if case in {"other-advisor", "inactive"}:
                async with env.factory() as session:
                    project = await session.get(GeoProject, 10)
                    settings = copy.deepcopy(project.project_settings)
                if case == "other-advisor":
                    settings["geo_service_plan"]["advisor_user_id"] = 2
                    await mutate(env, GeoProject, 10, project_settings=settings)
                else:
                    await mutate(env, GeoProject, 10, status="paused")
            if case == "state":
                await mutate(env, GeoContentTask, 10, status="ready")
            if case == "patrol":
                from app.models import GeoVisibilityPatrolSettings
                await mutate(env, GeoVisibilityPatrolSettings, 10, enabled=True)
            response = await env.request("POST", f"/content-tasks/10/{action}",
                    body={"overwrite": False, "use_llm": False} if action == "suggest-brief" else None, auth=auth)
            assert response.status_code in {401, 403, 409}, response.text
            async with env.factory() as session:
                assert not list(await session.scalars(select(GeoAsyncJob)))
    asyncio.run(run())


@pytest.mark.parametrize("action,params,raw", [
    ("generate", {"run_async": "1"}, b"null"),
    ("generate", {"run_async": "TRUE"}, b"null"),
    ("generate", {}, b"{}"), ("generate", {}, b'{"use_llm":true}'),
    ("generate", {"overwrite": "true"}, b"null"),
    ("suggest-brief", {}, b'{"use_llm":"true"}'),
    ("suggest-brief", {}, b'{"overwrite":1}'),
    ("suggest-brief", {}, b'{"use_llm":true,"use_llm":false}'),
    ("suggest-brief", {}, b'{"status":"ready"}'),
    ("suggest-brief", {"run_async": "true"}, b"{}"),
])
def test_ai_raw_contract_is_strict(tmp_path, monkeypatch, action, params, raw):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            response = await env.request("POST", f"/content-tasks/10/{action}", params=params, content=raw)
            assert response.status_code == 403, response.text
    asyncio.run(run())


def test_suggestions_ten_per_advisor_customer_across_tasks(tmp_path, monkeypatch, backend):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            async with env.factory() as session:
                session.add(GeoContentTask(id=13, tenant_id=10, business_id=10, prompt_id=10,
                            title="同客户另一篇", status="editing", brief={}))
                await session.commit()
            for i in range(10):
                response = await env.request("POST", f"/content-tasks/{10 if i % 2 else 13}/suggest-brief", body={"overwrite": False, "use_llm": False})
                assert response.status_code == 200, response.text
                assert response.json()["persisted"] is False
            response = await env.request("POST", "/content-tasks/10/suggest-brief", body={"use_llm": True})
            assert response.status_code == 429, response.text
            assert response.json()["detail"]["message"] == policy.QUOTA_MESSAGE
            await mutate(env, User, 1, tenant_id=20)
            response = await env.request("POST", "/content-tasks/20/suggest-brief", params={"tenant_id": 20},
                      auth=fixture_token(tid=20, gid=102), body={"use_llm": False})
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                session.add(User(id=4, username="other-fixture-advisor", password_hash="unused", role_id=1,
                                 tenant_id=10, is_active=True))
                await session.flush()
                session.add(Grant(id=104, user_id=4, tenant_id=10, grant_source="backfill"))
                project = await session.get(GeoProject, 10)
                settings = copy.deepcopy(project.project_settings)
                settings["geo_service_plan"]["advisor_user_id"] = 4
                project.project_settings = settings
                await session.commit()
            response = await env.request("POST", "/content-tasks/10/suggest-brief",
                       auth=fixture_token(uid=4, gid=104), body={"use_llm": False})
            assert response.status_code == 200, response.text
            async with env.factory() as session:
                records = list(await session.scalars(select(GeoAsyncJob)))
                assert len(records) == 12
                assert all(r.status == "succeeded" and r.kind == policy.SUGGEST_KIND for r in records)
    asyncio.run(run())


def test_shanghai_day_changes_at_1600_utc():
    before = policy.suggestion_day(datetime(2026, 1, 2, 15, 59, 59, tzinfo=timezone.utc))
    after = policy.suggestion_day(datetime(2026, 1, 2, 16, 0, tzinfo=timezone.utc))
    assert before == (datetime(2026, 1, 1, 16), datetime(2026, 1, 2, 16))
    assert after == (datetime(2026, 1, 2, 16), datetime(2026, 1, 3, 16))


def test_previous_day_attempts_do_not_consume_today(tmp_path, monkeypatch):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            start, _ = policy.suggestion_day(datetime.now(timezone.utc))
            from datetime import timedelta
            async with env.factory() as session:
                session.add_all([GeoAsyncJob(tenant_id=10, created_by=1, kind=policy.SUGGEST_KIND,
                    status="succeeded", created_at=start - timedelta(seconds=1)) for _ in range(10)])
                await session.commit()
            response = await env.request("POST", "/content-tasks/10/suggest-brief", body={"use_llm": False})
            assert response.status_code == 200, response.text
    asyncio.run(run())


@pytest.mark.parametrize("revoke_before_call", [False, True])
def test_suggestion_checks_before_llm_and_keeps_failed_attempt_count(tmp_path, monkeypatch, revoke_before_call):
    calls = []
    async def run():
        async with write_sandbox(tmp_path, monkeypatch) as env:
            async def credentials(*_a):
                if revoke_before_call:
                    await mutate(env, Grant, 101, revoked_at=datetime.now(timezone.utc), revoked_by=2, revoke_reason="fixture_revocation")
                return {"api_key": "synthetic-unused-key", "model": "fixture"}

            async def model(*_a, **_k):
                calls.append("model")
                raise RuntimeError("synthetic provider failure")

            monkeypatch.setattr("app.geo.content.ai_settings.resolve_llm_credentials", credentials)
            monkeypatch.setattr("app.ai.deepseek.chat_json", model)
            response = await env.request("POST", "/content-tasks/10/suggest-brief", body={"use_llm": True})
            assert response.status_code in ({401, 403} if revoke_before_call else {200}), response.text
            assert calls == ([] if revoke_before_call else ["model"])
            async with env.factory() as session:
                assert len(list(await session.scalars(select(GeoAsyncJob)))) == 1
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires isolated PostgreSQL")
@pytest.mark.parametrize("use_llm", [False, True])
def test_two_concurrent_suggestions_cannot_exceed_ten(tmp_path, monkeypatch, use_llm):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend="postgres") as env:
            for _ in range(9):
                response = await env.request("POST", "/content-tasks/10/suggest-brief", body={"use_llm": False})
                assert response.status_code == 200, response.text
            if use_llm:
                async def credentials(*_a):
                    return {"api_key": "synthetic-unused-key", "model": "fixture"}
                async def model(*_a, **_k):
                    await asyncio.sleep(0)
                    return BRIEF.copy()
                monkeypatch.setattr("app.geo.content.ai_settings.resolve_llm_credentials", credentials)
                monkeypatch.setattr("app.ai.deepseek.chat_json", model)
            results = await asyncio.wait_for(asyncio.gather(*[
                env.request("POST", "/content-tasks/10/suggest-brief", body={"use_llm": use_llm}) for _ in range(2)]), 15)
            assert sorted(r.status_code for r in results) == [200, 429]
            async with env.factory() as session:
                assert len(list(await session.scalars(select(GeoAsyncJob)))) == 10
    asyncio.run(run())


def test_generate_reserves_one_live_job_with_durable_authority(tmp_path, monkeypatch, backend):
    from starlette.background import BackgroundTasks
    queued = []
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda *_a, **_k: queued.append(_a[2:]))
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            await ready(env)
            response = await env.request("POST", "/content-tasks/10/generate", params={"run_async": "true"}, content=b"null")
            assert response.status_code == 200, response.text
            job = response.json()["job"]
            assert job["request_meta"]["advisor_authority"]["grant_id"] == 101
            assert len(queued) == 1
            response = await env.request("POST", "/content-tasks/10/generate")
            assert response.status_code == 409, response.text
            # Finished jobs do not impose any generation quota.
            for _ in range(11):
                async with env.factory() as session:
                    await session.execute(update(GeoAsyncJob).values(status="succeeded"))
                    await session.execute(update(GeoContentTask).where(GeoContentTask.id == 10).values(status="editing"))
                    await session.commit()
                response = await env.request("POST", "/content-tasks/10/generate")
                assert response.status_code == 200, response.text
    asyncio.run(run())


@pytest.mark.parametrize("when,change", [
    (when, change) for when in ("before-model", "before-save")
    for change in ("grant", "role", "user", "assignment", "inactive", "flag")
] + [("success", "none")])
def test_worker_revocation_fails_without_model_or_article(tmp_path, monkeypatch, when, change, backend):
    from app.geo.content import async_jobs, generate_article
    from starlette.background import BackgroundTasks
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda *_a, **_k: None)
    calls = []

    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            await ready(env)
            response = await env.request("POST", "/content-tasks/10/generate")
            assert response.status_code == 200, response.text
            job_id = response.json()["job"]["id"]
            before_articles = (await env.snapshot())["geo_article_versions"]

            async def revoke():
                if change == "grant":
                    await mutate(env, Grant, 101, revoked_at=datetime.now(timezone.utc), revoked_by=2, revoke_reason="fixture_revocation")
                elif change == "role":
                    await mutate(env, Role, 1, permissions={"geo.content": "view", "geo.assets": "edit"})
                elif change == "user":
                    await mutate(env, User, 1, is_active=False)
                elif change == "flag":
                    from app.config import get_settings
                    monkeypatch.setattr(get_settings(), "advisor_scoped_content_writes_enabled", False)
                elif change == "inactive":
                    await mutate(env, GeoProject, 10, status="paused")
                else:
                    async with env.factory() as session:
                        project = await session.get(GeoProject, 10)
                        settings = copy.deepcopy(project.project_settings)
                    settings["geo_service_plan"]["advisor_user_id"] = 2
                    await mutate(env, GeoProject, 10, project_settings=settings)

            async def model(**kwargs):
                await kwargs["before_model"]()
                calls.append("model")
                if when == "before-save":
                    await revoke()
                return generate_article.deterministic_article(
                    tenant_name=kwargs["tenant_name"], question=kwargs["question"], facts=kwargs["facts"])

            monkeypatch.setattr(generate_article, "generate_master_article", model)
            if when == "before-model":
                await revoke()
            async with env.engine.connect() as connection:
                result = await async_jobs._run_owned_job(job_id, tenant_id=10, connection=connection)
            assert result["status"] == ("succeeded" if when == "success" else "failed"), result
            if when != "success":
                assert result["error_type"] == "HTTPException", result
            assert calls == ([] if when == "before-model" else ["model"])
            snapshot = await env.snapshot()
            if when == "success":
                assert len(snapshot["geo_article_versions"]) == len(before_articles) + 1
            else:
                assert snapshot["geo_article_versions"] == before_articles
            job = next(j for j in snapshot["geo_async_jobs"] if j["id"] == job_id)
            assert job["status"] == ("succeeded" if when == "success" else "failed")
    asyncio.run(run())


@pytest.mark.parametrize("deny_attempt", [1, 2, 3])
def test_generation_rechecks_each_model_attempt_without_swallowing_denial(monkeypatch, deny_attempt):
    from app.geo.content import generate_article
    from tests.test_geo_h1_evidence import FACTS, payload
    model_calls, checks = [], []

    async def check():
        checks.append(1)
        if len(checks) == deny_attempt:
            raise HTTPException(403, "synthetic revocation")

    async def model(*_a, **_k):
        model_calls.append(1)
        result = payload("产品适用于矿业和港口。")
        if len(model_calls) == 1:
            result["direct_answer"] = "资料说明"
            result["sections"][-1]["body"] = "资料说明"
        return result

    monkeypatch.setattr(generate_article, "chat_json", model)
    with pytest.raises(HTTPException) as denied:
        asyncio.run(generate_article.generate_master_article(
            tenant_name="示例品牌", question="产品特点", facts=FACTS,
            brief=BRIEF, llm={"api_key": "synthetic-unused-key"}, before_model=check))
    assert denied.value.status_code == 403
    assert len(model_calls) == deny_attempt - 1
