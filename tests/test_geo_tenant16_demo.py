import asyncio
from datetime import date
from unittest.mock import Mock
from unittest.mock import AsyncMock, patch
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.geo.demo_read_session import tenant_read_session
from app.geo.demo_fixture_manifest import COMPETITORS, TIGER_BRAND, TIGER_CHINA_HOMEPAGE
from app.geo.integration import metrics_snapshot
from app.geo.integration import router as integration_router
from app.geo.question_read_routes import list_questions
from app.geo.read_routes import (
    get_answer,
    get_answers,
    get_capabilities,
    get_content_task,
    get_content_tasks,
    get_demo_summary,
    get_period_context,
    get_scheduler_eligibility,
    simulate_action,
)
from app.geo.tenant16_demo import (
    DEMO_TENANT_ID,
    DEMO_USERNAME,
    DEMO_USER_ID,
    Tenant16DemoSession,
    answer_page,
    content_task_list,
    is_tenant16_demo,
)
from app.geo.tenant_scope import require_geo_request_entitlement
from app.geo.tenant_scope import require_geo_read_entitlement
from app.geo.tenant_scope import ensure_geo_background_execution_allowed
from app.security.auth import AuthContext, require_scoped_auth
from app.database import get_session


def context(**changes):
    values = dict(
        user_id=DEMO_USER_ID,
        username=DEMO_USERNAME,
        role_name="workbench-readonly",
        tenant_id=DEMO_TENANT_ID,
        permissions={"geo.content": "view"},
    )
    values.update(changes)
    return AuthContext(**values)


def request(method, path, query=b"tenant_id=16"):
    return Request({"type": "http", "method": method, "path": path,
                    "raw_path": path.encode(), "query_string": query,
                    "headers": [(b"content-type", b"text/plain")],
                    "scheme": "https", "server": ("test", 443)})


def test_adapter_is_bound_to_exact_identity_and_tenant():
    assert is_tenant16_demo(context(), 16)
    assert not is_tenant16_demo(context(user_id=6), 16)
    assert not is_tenant16_demo(context(username="other"), 16)
    assert not is_tenant16_demo(context(tenant_id=15), 16)
    assert not is_tenant16_demo(context(), 15)


def test_demo_read_session_never_opens_control_or_data_database():
    async def consume():
        values = []
        async for session in tenant_read_session(
            request("GET", "/api/v1/geo/integration/read/answers"),
            16,
            context(),
            Mock(side_effect=AssertionError("control DB touched")),
        ):
            values.append(session)
        return values

    sessions = asyncio.run(consume())
    assert len(sessions) == 1 and isinstance(sessions[0], Tenant16DemoSession)
    with pytest.raises(AssertionError, match="database operation"):
        sessions[0].execute


def test_questions_answers_and_detail_are_versioned_and_visibly_synthetic():
    sentinel = Tenant16DemoSession()
    questions = asyncio.run(list_questions(
        tenant_id=16, status=None, is_brand_probe=None, unit_id=None,
        business_id=None, limit=50, before_id=None, ctx=context(), session=sentinel,
    ))
    assert len(questions.items) == 12
    assert questions.demo["dataset_version"] == "tenant16-geo-demo-v2"
    assert all(item.source_classification == "simulated" and item.formal_metric_eligible is False
               for item in questions.items)
    question_texts = {item.current_text for item in questions.items}
    assert any("粉末涂料选型" in text for text in question_texts)
    assert any("建筑" in text for text in question_texts)
    assert any("汽车" in text for text in question_texts)
    assert any("耐候" in text for text in question_texts)
    assert any("色彩" in text for text in question_texts)
    assert any("可持续" in text for text in question_texts)

    answers = asyncio.run(get_answers(tenant_id=16, limit=200, ctx=context(), session=sentinel))
    assert len(answers["items"]) == 72
    assert answers["demo"]["official"] is False
    assert all(item["source_kind"] == "simulated" and item["formal_metric_eligible"] is False
               for item in answers["items"])
    mentioned = [item for item in answers["items"] if item["mentions_brand"]]
    assert mentioned and all(TIGER_BRAND in item["raw_text"] for item in mentioned)
    assert set(name for item in answers["items"] for name in item["competitors"]) == set(COMPETITORS)
    assert all(
        item["cited_urls"] == [TIGER_CHINA_HOMEPAGE]
        for item in answers["items"] if item["cited_urls"]
    )
    answer_id = answers["items"][0]["ref"]["id"]
    detail = asyncio.run(get_answer(answer_id, 16, None, context(), sentinel))
    assert "全虚拟演示" in detail["item"]["raw_text"]
    assert detail["item"]["engine"]["provider"]
    assert detail["item"]["engine"]["model"]


def test_demo_filters_and_ids_never_alias_real_task_14():
    all_answers = answer_page(limit=200)
    answer_ids = {row["ref"]["id"] for row in all_answers["items"]}
    assert answer_ids == set(range(16_010_001, 16_010_073))
    engine = all_answers["items"][0]["engine"]["key"]
    filtered = answer_page(limit=200, engine_key=engine)
    assert filtered["items"]
    assert {row["engine"]["key"] for row in filtered["items"]} == {engine}
    tasks = content_task_list(limit=20)
    assert len(tasks["items"]) == 2
    assert {row["ref"]["id"] for row in tasks["items"]} == {16_030_001, 16_030_002}
    assert 14 not in {row["ref"]["id"] for row in tasks["items"]}


def test_answer_cursor_reads_all_72_without_duplicates():
    session = Tenant16DemoSession()
    first = asyncio.run(get_answers(tenant_id=16, limit=50, ctx=context(), session=session))
    second = asyncio.run(get_answers(tenant_id=16, limit=50,
                                     cursor=first["pagination"]["next_cursor"],
                                     ctx=context(), session=session))
    ids = [row["ref"]["id"] for row in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == 72
    assert first["pagination"]["has_more"] is True
    assert second["pagination"]["has_more"] is False
    assert second["pagination"]["next_cursor"] is None


def test_week_metrics_are_separated_from_demo_trend_without_database_access():
    session = Tenant16DemoSession()
    formal = asyncio.run(metrics_snapshot(tenant_id=16, week_end=date(2026, 9, 7),
                                          ctx=context(), session=session))
    assert len(formal) == 3
    assert all(row["value"] is None and row["trend_7d"] is None for row in formal)

    summary = asyncio.run(get_demo_summary(16, date(2026, 9, 7), context(), session))
    assert summary["official"] is False
    assert summary["excluded_from_official_metrics"] is True
    assert summary["window"]["current"]["sample_count"] == 36
    assert summary["trend_7d"]["mention_count"]["direction"] in {"up", "down", "flat"}


def test_read_capabilities_period_scheduler_and_content_tasks_need_no_database():
    session = Tenant16DemoSession()
    capabilities = asyncio.run(get_capabilities(16, context(), session))
    assert capabilities["actions_enabled"] is False
    assert len(capabilities["engines"]) == 3
    assert all(not row["configured"] for row in capabilities["engines"])
    period = asyncio.run(get_period_context(16, date(2026, 9, 7), context(), session))
    assert period["official"] is False and period["reason_codes"] == ["simulated_sample"]
    scheduler = asyncio.run(get_scheduler_eligibility(16, context(), session))
    assert scheduler["execution_blocked"] and not scheduler["scheduler_eligible"]
    tasks = asyncio.run(get_content_tasks(16, 20, None, context(), session))
    detail = asyncio.run(get_content_task(tasks["items"][0]["ref"]["id"], 16, context(), session))
    assert len(detail["versions"]) == 2
    assert detail["publications"] == []
    assert all(item["publishable"] is False for item in detail["variants"])


def test_every_execution_request_returns_simulated_block_without_session_use():
    for method, path in (
        ("POST", "/api/v1/geo/integration/tasks"),
        ("POST", "/api/v1/geo/content-tasks/14/generate"),
        ("POST", "/api/v1/geo/visibility-patrol-runs"),
        ("POST", "/api/v1/geo/content-tasks/14/push"),
        ("GET", "/api/v1/geo/oauth/social/callback"),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(require_geo_request_entitlement(
                request=request(method, path), ctx=context(),
                session=Tenant16DemoSession(),
            ))
        assert exc.value.status_code == 403
        assert exc.value.detail["simulated"] is True
        assert exc.value.detail["would_execute"] is False


def test_explicit_demo_action_returns_result_without_executing():
    result = asyncio.run(simulate_action(
        tenant_id=16, action="recheck", target_ref="geo/content_task/16030001",
        ctx=context(), session=Tenant16DemoSession(),
    ))
    assert result["status"] == "simulated"
    assert result["simulated"] is True and result["would_execute"] is False


def test_wrong_demo_week_fails_before_any_data_access():
    with pytest.raises(HTTPException, match="2026-09-07"):
        asyncio.run(get_period_context(16, date(2026, 8, 31), context(), Tenant16DemoSession()))


def test_http_metric_contract_remains_exactly_five_fields_and_null():
    app = FastAPI()
    app.include_router(integration_router, prefix="/api/v1/geo")
    app.dependency_overrides[require_scoped_auth] = lambda: context()
    app.dependency_overrides[require_geo_read_entitlement] = lambda: context()
    app.dependency_overrides[get_session] = Tenant16DemoSession
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/geo/integration/metrics/snapshot",
            params={"tenant_id": 16, "week_end": "2026-09-07"},
        )
    assert response.status_code == 200
    assert all(set(row) == {"metric_key", "value", "unit", "as_of", "trend_7d"}
               for row in response.json())
    assert all(row["value"] is None and row["trend_7d"] is None for row in response.json())


def test_background_guard_rejects_tenant16_without_database_access():
    with pytest.raises(HTTPException) as exc:
        ensure_geo_background_execution_allowed(16)
    assert exc.value.status_code == 403
    ensure_geo_background_execution_allowed(15)


def test_async_recovery_scans_exclude_tenant16():
    from app.geo.content import async_jobs

    statements = []
    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=lambda statement: statements.append(statement) or []),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def factory():
        yield session

    with patch("app.database.async_session_factory", factory):
        asyncio.run(async_jobs.recover_jobs_on_startup())
    sql = "\n".join(str(statement.compile(compile_kwargs={"literal_binds": True}))
                    for statement in statements)
    assert "geo_async_jobs.tenant_id != 16" in sql
    assert "geo_content_tasks.tenant_id != 16" in sql
    session.commit.assert_awaited_once()


def test_patrol_recovery_scan_and_execution_exclude_tenant16_before_lock_or_write():
    from app.geo.content import patrol

    statements = []
    scan_session = SimpleNamespace(
        scalars=AsyncMock(side_effect=lambda statement: statements.append(statement) or []),
    )

    @asynccontextmanager
    async def factory():
        yield scan_session

    with patch("app.database.async_session_factory", factory):
        asyncio.run(patrol.recover_patrol_runs_on_startup())
    sql = "\n".join(str(statement.compile(compile_kwargs={"literal_binds": True}))
                    for statement in statements)
    assert "geo_visibility_patrol_runs.tenant_id != 16" in sql

    row = SimpleNamespace(id=7, tenant_id=16, status="pending")
    execution_session = SimpleNamespace(
        get=AsyncMock(return_value=row), refresh=AsyncMock(), commit=AsyncMock()
    )

    @asynccontextmanager
    async def forbidden_lock(_run_id):
        raise AssertionError("demo patrol must stop before advisory lock")
        yield

    with patch.object(patrol, "patrol_execution_lock", forbidden_lock):
        with pytest.raises(HTTPException):
            asyncio.run(patrol.execute_patrol_run_owned(execution_session, row.id, 16))
    execution_session.refresh.assert_not_awaited()
    execution_session.commit.assert_not_awaited()


def test_tenant16_oauth_is_not_blocked_without_a_proven_demo_principal():
    from app.geo.content.oauth_public import oauth_social_callback

    session = SimpleNamespace(get=AsyncMock(return_value=None))
    entitlement = AsyncMock()
    with patch("app.geo.content.connectors.oauth2.parse_oauth_state",
               return_value={"tenant_id": 16, "account_id": 91}), patch(
        "app.geo.tenant_scope.ensure_geo_entitlement", entitlement
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(oauth_social_callback(code="code", state="signed", session=session))
    assert exc.value.status_code == 404
    entitlement.assert_awaited_once_with(session, 16)


def test_patrol_background_rejects_before_lock_session_or_failure_write():
    from app.geo.content import patrol

    @asynccontextmanager
    async def forbidden_lock(_run_id):
        raise AssertionError("patrol lock touched")
        yield

    with patch.object(patrol, "patrol_execution_lock", forbidden_lock), patch(
        "app.database.async_session_factory", side_effect=AssertionError("session opened")
    ), patch.object(patrol, "mark_patrol_run_failed", AsyncMock(
        side_effect=AssertionError("failure persisted")
    )):
        with pytest.raises(HTTPException):
            asyncio.run(patrol.run_patrol_in_background(77, 16))

    session = SimpleNamespace(
        get=AsyncMock(side_effect=AssertionError("patrol queried")),
        refresh=AsyncMock(side_effect=AssertionError("patrol row locked")),
        commit=AsyncMock(side_effect=AssertionError("patrol committed")),
    )
    with pytest.raises(HTTPException):
        asyncio.run(patrol.execute_patrol_run(session, 77, tenant_id=16))


def test_async_wrappers_reject_before_job_lock_session_or_executor():
    from app.geo.content import async_jobs

    @asynccontextmanager
    async def forbidden_lock(_job_id):
        raise AssertionError("job lock touched")
        yield

    with patch.object(async_jobs, "job_execution_lock", forbidden_lock), patch(
        "app.database.async_session_factory", side_effect=AssertionError("session opened")
    ), patch.object(async_jobs, "_run_owned_job", AsyncMock(
        side_effect=AssertionError("executor called")
    )):
        with pytest.raises(HTTPException):
            asyncio.run(async_jobs.run_job_in_background(88, 16))
        with pytest.raises(HTTPException):
            asyncio.run(async_jobs.run_job_synchronously(88, 16))


def test_direct_recovery_and_metric_entries_reject_before_query_or_commit():
    from app.geo.content import async_jobs, daily_metrics
    from app.geo.outcome_review import update_outcome_review

    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=AssertionError("query issued")),
        scalars=AsyncMock(side_effect=AssertionError("query issued")),
        refresh=AsyncMock(side_effect=AssertionError("row lock issued")),
        commit=AsyncMock(side_effect=AssertionError("commit issued")),
    )
    row = SimpleNamespace(id=9, tenant_id=16, status="pending")
    for operation in (
        async_jobs.reconcile_stale_job(session, row),
        async_jobs.reconcile_stale_content_tasks(session, tenant_id=16),
        update_outcome_review(session, 9, tenant_id=16),
    ):
        with pytest.raises(HTTPException):
            asyncio.run(operation)

    with patch("app.database.async_session_factory",
               side_effect=AssertionError("metric session opened")):
        with pytest.raises(HTTPException):
            asyncio.run(daily_metrics.safe_rebuild_day(16))


def test_direct_owned_job_rejects_before_session_or_transport():
    from app.geo.content import async_jobs

    with patch("app.database.async_session_factory",
               side_effect=AssertionError("job session opened")), patch.object(
        async_jobs, "_execute_generate", AsyncMock(side_effect=AssertionError("transport called"))
    ):
        with pytest.raises(HTTPException):
            asyncio.run(async_jobs._run_owned_job(99, tenant_id=16))
