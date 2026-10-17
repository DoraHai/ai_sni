"""Synthetic evidence only. Every supplier and fallback call is mocked."""

import asyncio
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.geo.content import search_visibility as sv
from app.geo.content import search_visibility_routes as routes
from app.models import GeoAsyncJob, GeoProject, Tenant
from app.security.auth import AuthContext, require_scoped_auth
from app.database import get_session


def settings(**kw):
    return NS(**{"deepseek_search_api_key": "synthetic-only", "deepseek_search_base_url": "https://api.deepseek.com",
                 "deepseek_search_run_request_limit": 60, "deepseek_search_monthly_limit_cny": 30,
                 "deepseek_search_qps": 4, **kw})


def advisor():
    return AuthContext(7, "test", "advisor", 1, {"geo.assets": "edit", "geo.content": "edit"})


def customer():
    return AuthContext(8, "test", "customer", 1, {"geo.assets": "view", "geo.content": "view"})


def project(**kw):
    return NS(**{"id": 2, "tenant_id": 1, "tenant_module_id": 1, "primary_domain": "example.com",
                 "default_url": "https://example.com/cn", "brand_name": "品牌", "status": "active",
                 "project_settings": {}, **kw})


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # New code can never fall back to a real provider or local website in this suite.
    monkeypatch.setattr(sv.LIMITER, "wait", AsyncMock())
    monkeypatch.setattr(sv, "safe_fetch", AsyncMock(side_effect=AssertionError("unmocked fallback")))
    monkeypatch.setattr(sv, "get_settings", lambda: settings())
    monkeypatch.setattr(routes, "get_settings", lambda: settings())


def run(coro):
    return asyncio.run(coro)


async def client_case(handler, operation, *, config=None, options=None, used=None):
    config = config or sv.VisibilityConfig(enabled=True, domains=["example.com"])
    result = sv.empty_result(config, len(config.extra_article_urls))
    async def monthly(month):
        actual = sv.usage_from_results([result], month)
        if used:
            actual["cost_cny"] += used
        return actual
    async with httpx.AsyncClient(base_url="https://api.deepseek.com", transport=httpx.MockTransport(handler)) as http:
        checkpoint = AsyncMock()
        client = sv.SearchClient(http, config, result, settings=options or settings(), checkpoint=checkpoint, monthly_usage=monthly)
        output = await operation(client)
        return output, result, checkpoint


@pytest.mark.parametrize("status,retries", [(200, 0), (400, 0), (401, 0), (403, 0), (404, 0), (408, 2), (429, 2), (500, 2), (503, 2)])
def test_retry_status_and_reservations(status, retries):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"results": [{"url": "https://example.com"}]} if status == 200 else {})
    with patch.object(sv.asyncio, "sleep", new_callable=AsyncMock) as sleep:
        out, result, checkpoint = run(client_case(handler, lambda c: c.request("POST", "/v1/tools/search", {"query": "测试", "count": 20})))
    assert len(calls) == retries + 1
    assert out["retries"] == retries
    assert result["summary"]["requests"] == retries + 1
    assert result["summary"]["billable"] == (status == 200)
    assert result["summary"]["reserved_cny"] == 0
    assert checkpoint.await_count == (retries + 1) * 2
    assert [call.args[0] for call in sleep.await_args_list] == ([2, 5] if retries else [])


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError])
def test_disconnect_retry_unknown_cost_remains_reserved(error):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        if count < 3:
            raise error("synthetic secret must not be persisted")
        return httpx.Response(200, json={"results": []})
    with patch.object(sv.asyncio, "sleep", new_callable=AsyncMock):
        out, result, _ = run(client_case(handler, lambda c: c.request("POST", "/v1/tools/search", {})))
    assert out["retries"] == 2
    assert result["summary"]["billable"] == 0
    assert result["summary"]["reserved_cny"] == .01
    assert "synthetic secret" not in str(result)


@pytest.mark.parametrize("path,body,billable", [
    ("search", {"results": []}, 0), ("search", {"results": [{"url": "https://example.com"}]}, 1),
    ("fetch", {"content": ""}, 0), ("fetch", {"content": "正文"}, 1),
])
def test_exact_billing(path, body, billable):
    out, result, _ = run(client_case(lambda r: httpx.Response(200, json=body),
                         lambda c: c.request("POST", "/v1/tools/" + path, {"url": "https://example.com"})))
    assert result["summary"]["billable"] == billable
    assert result["summary"]["cost_cny"] == billable * .005


def test_402_aborts_collect_immediately():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"is_available": True}) if request.method == "GET" else httpx.Response(402)
    with pytest.raises(sv.StopRun, match="余额不足"):
        run(client_case(handler, lambda c: sv.collect(c, [])))
    assert paths == ["/user/balance", "/v1/tools/search"]


@pytest.mark.parametrize("body", [{}, {"is_available": False}, {"is_available": "true"}])
def test_unavailable_balance_prevents_paid_calls(body):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=body)
    with pytest.raises(sv.StopRun, match="余额暂不可查询"):
        run(client_case(handler, lambda c: sv.collect(c, [])))
    assert paths == ["/user/balance"]


def test_month_budget_checks_next_request_not_after_spending():
    handler = MagicMock(return_value=httpx.Response(200, json={"results": [1]}))
    async def operation(client):
        await client.request("POST", "/v1/tools/search", {})
        with pytest.raises(sv.StopRun, match="本月额度已用完"):
            await client.request("POST", "/v1/tools/search", {})
    _, result, _ = run(client_case(handler, operation, used=29.995))
    assert handler.call_count == 1
    assert result["summary"]["cost_cny"] == .005


def test_run_limit_counts_balance_retries_and_empty_results():
    handler = MagicMock(return_value=httpx.Response(429))
    async def operation(client):
        with pytest.raises(sv.StopRun, match="本次请求已达上限"):
            await client.request("GET", "/user/balance")
    with patch.object(sv.asyncio, "sleep", new_callable=AsyncMock):
        _, result, _ = run(client_case(handler, operation, options=settings(deepseek_search_run_request_limit=2)))
    assert handler.call_count == 2
    assert result["summary"]["billable"] == 0


def test_checkpoint_failure_prevents_transport():
    async def operation(client):
        client.checkpoint = AsyncMock(side_effect=RuntimeError("storage unavailable"))
        with pytest.raises(RuntimeError):
            await client.request("POST", "/v1/tools/search", {})
    handler = MagicMock()
    run(client_case(handler, operation))
    handler.assert_not_called()


def test_collect_rank_zhihu_foreign_fallback_and_no_body_persistence():
    config = sv.VisibilityConfig(enabled=True, domains=["example.com"], zh_url="https://example.com/cn",
                                 brand_terms=["品牌"], core_terms=["工业"],
                                 extra_article_urls=["https://zhuanlan.zhihu.com/p/1", "https://media.example/article?id=5"])
    requests = []
    def handler(request):
        import json
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"is_available": True})
        payload = json.loads(request.content)
        if request.url.path.endswith("search"):
            return httpx.Response(200, json={"results": [
                {"url": "https://competitor.example/", "title": "前排", "summary": "DO NOT STORE"},
                {"url": "https://sub.example.com/cn", "title": "官网"},
                {"url": "https://media.example/article?id=5", "title": "文章"},
            ]})
        return httpx.Response(200, json={"title": "英文页面", "content": "This is an English language content page with many words " * 3})
    with patch.object(sv, "safe_fetch", AsyncMock(return_value=NS(html="<title>中文页</title>" + "中文正文" * 20))) as fallback:
        _, result, _ = run(client_case(handler, lambda c: sv.collect(c, config.extra_article_urls), config=config))
    assert result["summary"]["indexed"] is True
    assert result["summary"]["indexed_count"] == 1
    assert result["summary"]["brand_hit"] == result["summary"]["core_hit"] == 1
    assert [i["best_rank"] for i in result["items"] if i["kind"] in {"brand", "core"}] == [2, 2]
    assert result["summary"]["articles_alive"] == 1
    assert result["summary"]["articles_total"] == 2
    assert not any(b"zhihu" in r.content for r in requests)
    assert fallback.await_count == 2
    assert "DO NOT STORE" not in str(result)
    assert "many words" not in str(result)
    assert any(i.get("warning") == "被跳到外语版" for i in result["items"])


@pytest.mark.parametrize("url,hit", [
    ("https://example.com", True), ("https://a.example.com/page", True),
    ("https://example.com.evil.example", False), ("https://evil-example.com", False),
    ("https://media.example/a?id=1#x", True), ("https://media.example/a?id=2", False),
    ("https://media.example/another", False), ("javascript:alert(1)", False),
])
def test_domain_and_precise_article_identity(url, hit):
    assert sv.matches(url, ["example.com"], ["https://media.example/a?id=1"]) is hit


def test_defaults_customer_hidden_and_no_key():
    config = sv.resolve_config(project(), NS(brand_terms=["别名", "品牌"]))
    assert config.domains == ["example.com"]
    assert config.brand_terms == ["品牌", "别名"]
    assert config.zh_url == "https://example.com/cn"
    assert config.customer_visible is False
    assert sv.access_state(config, customer())["state"] == "not_open"
    assert sv.access_state(config, advisor())["state"] == "not_enabled"
    config.enabled = True
    assert sv.access_state(config, advisor(), settings(deepseek_search_api_key=""))["state"] == "not_enabled"


@pytest.mark.parametrize("bad", [
    {"domains": ["https://example.com"]}, {"domains": ["localhost"]},
    {"domains": ["127.0.0.1"]}, {"domains": ["a.com"] * 4},
    {"zh_url": "file:///tmp/file"}, {"zh_url": "http://user:password@example.com"},
    {"zh_url": "http://192.168.1.1"}, {"zh_url": "https://example.com:8080"},
    {"brand_terms": ["词"] * 6}, {"core_terms": ["词"] * 21},
    {"core_terms": ["词" * 129]}, {"core_terms": ["  "]},
    {"extra_article_urls": ["https://example.com"] * 21}, {"enabled": "yes"},
    {"api_key": "secret"},
])
def test_config_validation(bad):
    with pytest.raises(ValidationError):
        sv.VisibilityConfig(**bad)


def test_month_rollover_and_iso_week():
    assert sv.month_key(datetime(2026, 9, 30, 16, 1)) == "2026-10"
    assert sv.week_start(datetime(2026, 10, 18)) == datetime(2026, 10, 11, 16)
    assert sv.week_start(datetime(2026, 10, 18, 16)) == datetime(2026, 10, 18, 16)
    usage = sv.usage_from_results([{"monthly_usage": {
        "2026-09": {"requests": 20, "billable": 10},
        "2026-10": {"requests": 3, "billable": 1, "reserved_billable": 2}}}], "2026-10")
    assert usage["requests"] == 3 and usage["cost_cny"] == .005 and usage["reserved_cny"] == .01


def job(**kw):
    return NS(**{"id": 30, "tenant_id": 1, "kind": sv.KIND, "ref_type": "geo_project", "ref_id": 2,
                 "status": "succeeded", "created_at": datetime(2026, 10, 18), "finished_at": None,
                 "error": "详细失败原因", "result_meta": {"summary": {"stopped_reason": "余额不足", "requests": 1},
                    "items": [{"kind": "article", "url": "https://example.com", "error": "内部错误", "http_status": 404}]}, **kw})


def test_customer_payload_and_csv_do_not_expose_error_or_cost():
    payload = sv.run_payload(job(), advisor=False)
    assert "余额不足" not in str(payload)
    assert "内部错误" not in str(payload)
    assert "requests" not in str(payload)
    assert payload["created_at"] == "2026-10-18 08:00"
    assert sv.csv_text(payload).startswith("\ufeff类型,")


def test_csv_bom_chinese_and_formula_injection():
    payload = {"result": {"items": [{"kind": "brand", "query": "=CMD()", "best_rank": 2,
                 "results": [{"title": " @danger", "url": "https://example.com"}]}]}}
    csv = sv.csv_text(payload)
    assert csv.encode("utf-8").startswith(b"\xef\xbb\xbf")
    assert "'=CMD()" in csv and "' @danger" in csv and "品牌词" in csv


@pytest.mark.parametrize("trigger,status,created,expected", [
    ("schedule", "succeeded", datetime(2026, 10, 18), "skip"),
    ("schedule", "failed", datetime(2026, 10, 18), "new"),
    ("manual", "succeeded", datetime(2026, 10, 18), "daily"),
    ("manual", "running", datetime(2026, 10, 1), "inflight"),
])
def test_admission_dedup(trigger, status, created, expected):
    session = AsyncMock()
    session.add = MagicMock()
    session.scalars.return_value = [job(status=status, created_at=created, request_meta={"trigger": "manual"})]
    config = sv.VisibilityConfig(enabled=True)
    with patch.object(sv, "now_utc", return_value=datetime(2026, 10, 18, 1)), patch.object(sv, "article_urls", AsyncMock(return_value=[])):
        async def execute():
            return await sv.create_run(session, project(), config, trigger=trigger, actor=7)
        if expected in {"daily", "inflight"}:
            with pytest.raises(sv.StopRun):
                run(execute())
        elif expected == "skip":
            assert run(execute()) is None
        else:
            assert run(execute()).kind == sv.KIND
    assert "FOR UPDATE" in str(session.execute.await_args.args[0])


@pytest.mark.parametrize("who,visible,state", [(advisor, False, "ready"), (customer, False, "not_open"), (customer, True, "ready")])
def test_http_overview_visibility_and_detail(who, visible, state):
    config = sv.VisibilityConfig(enabled=True, customer_visible=visible)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/geo")
    session = AsyncMock()
    session.scalars.return_value = [job()]
    session.get.return_value = job()
    app.dependency_overrides[require_scoped_auth] = who
    app.dependency_overrides[get_session] = lambda: session
    with patch.object(routes, "load_project", AsyncMock(return_value=(project(), config))):
        client = TestClient(app)
        response = client.get("/api/v1/geo/projects/2/search-visibility?tenant_id=1")
        assert response.status_code == 200
        assert response.json()["state"] == state
        detail = client.get("/api/v1/geo/projects/2/search-visibility/runs/30?tenant_id=1")
        assert detail.json()["state"] == state
        download = client.get("/api/v1/geo/projects/2/search-visibility/runs/30/csv?tenant_id=1")
        if state == "not_open":
            assert "latest" not in response.json()
            assert download.json()["state"] == "not_open"
            session.scalars.assert_not_awaited()
        else:
            assert response.json()["latest"]["id"] == 30
            assert download.content.startswith(b"\xef\xbb\xbf")


def test_customer_cannot_configure_run_or_see_global_usage():
    with pytest.raises(HTTPException) as err:
        routes.require_advisor(customer())
    assert err.value.status_code == 403
    with pytest.raises(HTTPException):
        run(routes.usage(customer(), AsyncMock()))
    assert sv.is_admin(AuthContext(None, "api-key", "admin", None, {}, True))


def test_cross_tenant_and_project_mismatch_rejected():
    session = AsyncMock()
    with patch.object(routes, "ensure_module_access", AsyncMock(side_effect=HTTPException(403))):
        with pytest.raises(HTTPException):
            run(routes.load_project(session, customer(), 2, 2))
    session.get.return_value = project(tenant_id=2)
    with patch.object(routes, "ensure_module_access", AsyncMock()):
        with pytest.raises(HTTPException) as err:
            run(routes.load_project(session, customer(), 1, 2))
        assert err.value.status_code == 404


def test_scheduler_no_key_returns_without_db():
    from app.geo import scheduler
    with patch.object(scheduler, "get_settings", return_value=settings(deepseek_search_api_key="")), patch.object(scheduler, "async_session_factory") as sessions:
        run(scheduler.run_geo_search_visibility())
    sessions.assert_not_called()


def test_missing_search_key_does_not_block_production_startup():
    from app.security.prod_guard import collect_production_issues
    import base64
    s = NS(app_env="production", admin_api_key="synthetic-production-admin-credential", jwt_secret="synthetic-jwt-separate",
           crypto_master_key_b64=base64.b64encode(b"x" * 32).decode(), app_base_url="https://example.com",
           admin_api_key_query_enabled=False, cors_allowed_origins="https://example.com", deepseek_search_api_key="")
    assert collect_production_issues(s) == []


def test_process_limiter_spaces_all_requests_and_same_site_fetch(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(sv.time, "monotonic", lambda: clock[0])
    async def sleep(delay):
        clock[0] += delay
    monkeypatch.setattr(sv.asyncio, "sleep", sleep)
    async def scenario():
        limiter = sv.ProcessLimiter()
        await limiter.wait(4, "example.com")
        assert clock[0] == 10
        await limiter.wait(4, "other.example")
        assert clock[0] == 10.25
        await limiter.wait(4, "example.com")
        assert clock[0] == 11
        await limiter.wait(2)
        assert clock[0] == 11.5
    run(scenario())


def test_whole_run_preflight_budget_blocks_before_balance():
    handler = MagicMock()
    with pytest.raises(sv.StopRun, match="本月额度已用完"):
        run(client_case(handler, lambda c: sv.collect(c, []), used=29.998))
    handler.assert_not_called()


def test_malformed_200_is_failure_and_reservation_remains():
    out, result, _ = run(client_case(lambda r: httpx.Response(200, json={"results": "bad"}),
                         lambda c: c.request("POST", "/v1/tools/search", {})))
    assert not out["ok"] and "格式不正确" in out["error"]
    assert result["summary"]["billable"] == 0
    assert result["summary"]["reserved_cny"] == .005


def test_article_union_scoped_dedup_and_cap():
    config = sv.VisibilityConfig(extra_article_urls=["https://media.example/article?id=1", "https://media.example/article?id=2"])
    session = AsyncMock()
    session.scalars.side_effect = [["https://media.example/article?id=1", "https://media.example/article?id=1#duplicate"],
                                  ["https://media.example/placement", "https://zhuanlan.zhihu.com/p/1"]]
    result = run(sv.article_urls(session, 7, config))
    assert len(result) == 4
    assert "https://media.example/article?id=2" in result
    assert "geo_content_tasks.tenant_id" in str(session.scalars.await_args_list[0].args[0])
    assert "geo_media_placements.tenant_id" in str(session.scalars.await_args_list[1].args[0])


def test_general_async_job_entry_cannot_bypass_visibility_gate():
    from app.geo.content import routes as general
    session = AsyncMock()
    session.get.return_value = job()
    with pytest.raises(HTTPException):
        run(general.get_async_job(30, 1, customer(), session))
    with pytest.raises(HTTPException):
        run(general.cancel_async_job(30, 1, customer(), session))


def test_general_recovery_ignores_search_jobs():
    from app.geo.content.async_jobs import reconcile_stale_job
    row = job(status="running", created_at=datetime(2026, 1, 1))
    session = AsyncMock()
    assert run(reconcile_stale_job(session, row)) is row
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("url", ["https://zhihu.com./p/1", "https://ZHIHU.COM/p/1", "https://ZHUANLAN.ZHIHU.COM./p/1"])
def test_equivalent_zhihu_hosts_make_zero_fetch_requests(url):
    config = sv.VisibilityConfig(enabled=True, domains=["example.com"], zh_url=url, extra_article_urls=[url])
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={"is_available": True} if request.method == "GET" else {"results": []})
    _, result, _ = run(client_case(handler, lambda c: sv.collect(c, [url]), config=config))
    assert "/v1/tools/fetch" not in paths
    assert result["summary"]["billable"] == 0
    assert all(i.get("error") == "知乎暂不能自动核对" for i in result["items"] if i["kind"] in {"homepage", "article"})


@pytest.mark.parametrize("domain,expected", [("https://example.com/cn", ["example.com"]), (None, []), ("", []), ("https://", [])])
def test_legacy_project_domain_defaults_do_not_crash(domain, expected):
    config = sv.resolve_config(project(primary_domain=domain), NS(brand_terms=[]))
    assert config.domains == expected


def test_markdown_language_ignores_link_destinations_and_code():
    page = sv.page_info("# 中文标题\n" + "[中文正文](https://example.com/" + "english" * 100 + ")\n```python\nprint('english words')\n```", markdown=True)
    assert page["foreign_language"] is False
    assert page["body_chars"] < 30


def test_scheduler_has_monday_beijing_trigger_and_recovery():
    from app.geo import scheduler
    fake = MagicMock(running=False)
    with patch.object(scheduler, "geo_scheduler", fake), patch.object(scheduler, "_acquire_scheduler_lock", return_value=True):
        scheduler.start_geo_scheduler()
    calls = {c.kwargs["id"]: c.args for c in fake.add_job.call_args_list}
    trigger = calls["geo_search_visibility_weekly"][1]
    assert str(trigger.timezone) == "Asia/Shanghai"
    assert str(trigger) == "cron[day_of_week='mon', hour='6', minute='0']"
    assert "geo_search_visibility_recovery" in calls


@pytest.mark.parametrize("path,method", [
    ("/api/v1/geo/projects/2/search-visibility", "GET"),
    ("/api/v1/geo/projects/2/search-visibility/config", "GET"),
    ("/api/v1/geo/projects/2/search-visibility/config", "PUT"),
    ("/api/v1/geo/projects/2/search-visibility/run", "POST"),
    ("/api/v1/geo/projects/2/search-visibility/runs/3/csv", "GET"),
    ("/api/v1/geo/search-visibility/usage", "GET"),
])
def test_global_settings_admin_passes_only_exact_visibility_menu_gate(path, method):
    from starlette.requests import Request
    from app.security.auth import require_scoped_auth
    ctx = AuthContext(7, "synthetic", "admin", None, {"settings.accounts": "edit", "settings.customers": "edit", "geo.assets": "view", "geo.content": "view"})
    request = Request({"type": "http", "method": method, "path": path, "query_string": b"tenant_id=1", "headers": []})
    assert run(require_scoped_auth(request, ctx, AsyncMock())) is ctx


@pytest.mark.parametrize("path,method", [
    ("/api/v1/geo/projects/2", "PATCH"),
    ("/api/v1/geo/projects/2/search-visibility/config/other", "PUT"),
    ("/api/v1/manage/campaigns", "POST"),
])
def test_visibility_admin_exception_never_extends_to_other_routes(path, method):
    from starlette.requests import Request
    from app.security.auth import require_scoped_auth
    ctx = AuthContext(7, "synthetic", "admin", None, {"settings.accounts": "edit", "settings.customers": "edit"})
    request = Request({"type": "http", "method": method, "path": path, "query_string": b"", "headers": []})
    with pytest.raises(HTTPException) as error:
        run(require_scoped_auth(request, ctx, AsyncMock()))
    assert error.value.status_code == 403


def test_bound_or_partial_settings_role_cannot_use_global_visibility_exception():
    from starlette.requests import Request
    from app.security.auth import require_scoped_auth
    for tenant, permissions in [(1, {"settings.accounts": "edit", "settings.customers": "edit"}), (None, {"settings.accounts": "edit"})]:
        ctx = AuthContext(7, "synthetic", "partial", tenant, permissions)
        request = Request({"type": "http", "method": "PUT", "path": "/api/v1/geo/projects/2/search-visibility/config", "query_string": b"tenant_id=1", "headers": []})
        with pytest.raises(HTTPException):
            run(require_scoped_auth(request, ctx, AsyncMock()))
