"""Provider behavior without external requests."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.seo_site_analytics import (AnalyticsError, ProviderClient, authorization_url, normalize_config,
    fetch_provider, parse_baidu_result, parse_ga4, public_source, save_secrets, secrets_of, validate_month,
    validate_service_account, validate_template)


def test_encrypted_secret_round_trip_and_public_payload():
    row = SimpleNamespace(source="baidu_tongji", enabled=True, config={"api_key": "public"},
        secret_ciphertext=None, last_test_at=None, last_test_status=None, last_test_message=None, token_expires_at=None)
    save_secrets(row, {"secret_key": "private-1234", "refresh_token": "refresh-private"})
    assert "private-1234" not in row.secret_ciphertext
    assert secrets_of(row)["secret_key"] == "private-1234"
    assert "private-1234" not in json.dumps(public_source(row))
    assert public_source(row)["refresh_token_set"] is True


def test_validation_and_month_bounds():
    assert normalize_config("ga4", {"property_id": "properties/123"}) == {"property_id": "123"}
    assert validate_month("2026-09", datetime(2026, 10, 4, tzinfo=timezone.utc)) == ("2026-09-01", "2026-09-30", False)
    assert validate_month("2026-10", datetime(2026, 10, 4, tzinfo=timezone.utc))[2] is True
    with pytest.raises(AnalyticsError): validate_month("2026-11", datetime(2026, 10, 4, tzinfo=timezone.utc))
    with pytest.raises(AnalyticsError): validate_template([])
    with pytest.raises(AnalyticsError): validate_template([{"key": "title", "title": "a"}, {"key": "title", "title": "b"}])
    assert [c["key"] for c in validate_template([{"key": "image_key", "title": "缩略图"}, {"key": "number", "title": "序号"}])] == ["image_key", "number"]


def test_baidu_no_data_and_sum_fallback():
    assert parse_baidu_result({"fields": ["pv_count", "visitor_count"], "items": [[], [["--", "--"]]], "sum": [["--", "--"]]})[:2] == (None, None)
    assert parse_baidu_result({"fields": ["pv_count", "visitor_count"], "items": [], "sum": [["20", "10"]]})[:2] == (10, 20)
    assert parse_baidu_result({"fields": ["date", "pv_count", "visitor_count"], "items": [[], [["20", "10"]]]})[:2] == (10, 20)
    assert "redirect_uri=oob" in authorization_url("key")


def test_ga4_validation_and_parse():
    with pytest.raises(AnalyticsError): validate_service_account('{"token_uri":"http://evil"}')
    assert parse_ga4({"rows": []}) == (None, None)
    assert parse_ga4({"rows": [{"metricValues": [{"value": "9"}, {"value": "23"}]}]}) == (9, 23)


def test_baidu_exchange_refresh_rotation_and_business_error():
    calls = []
    def handler(request):
        calls.append(request)
        if "oauth" in str(request.url):
            return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600})
        return httpx.Response(200, json={"header": {"status": 1, "failures": [{"message": "bad"}]}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ProviderClient(http)
            exchanged = await client.exchange({"api_key": "key"}, {"secret_key": "secret"}, "code")
            assert exchanged["refresh_token"] == "new-refresh"
            refreshed = await client._refresh({"api_key": "key"}, exchanged)
            assert refreshed["access_token"] == "new-access"
            with pytest.raises(AnalyticsError, match="百度商业账号"):
                await client.baidu({"mode": "business", "username": "u", "tongji_site_id": "1"}, {"access_token": "t"}, "2026-09-01", "2026-09-30")
    asyncio.run(run())
    assert len(calls) == 3
    assert all(str(call.url).startswith(("https://openapi.baidu.com/", "https://api.baidu.com/")) for call in calls)


def test_ga4_mocked_token_and_403(monkeypatch):
    monkeypatch.setattr("app.seo_site_analytics.jwt.encode", lambda *a, **k: "assertion")
    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(403, json={})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AnalyticsError, match="媒体资源访问管理"):
                await ProviderClient(http).ga4({"property_id": "123"}, {"service_account_json": {"client_email": "test@example.com", "private_key": "mock"}}, "2026-09-01", "2026-09-30")
    asyncio.run(run())


def test_ga4_mocked_token_success_and_empty_rows(monkeypatch):
    monkeypatch.setattr("app.seo_site_analytics.jwt.encode", lambda *a, **k: "assertion")
    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token"})
        assert request.url.host == "analyticsdata.googleapis.com"
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(200, json={"rows": [{"metricValues": [{"value": "7"}, {"value": "19"}]}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            data = await ProviderClient(http).ga4({"property_id": "123"}, {"service_account_json": {
                "client_email": "test@example.com", "private_key": "mock"}}, "2026-09-01", "2026-09-30")
            assert parse_ga4(data) == (7, 19)
    asyncio.run(run())


def test_baidu_refresh_rotation_is_reencrypted_on_row():
    row = SimpleNamespace(source="baidu_tongji", config={"mode": "account", "api_key": "key", "tongji_site_id": "123"},
        secret_ciphertext=None, token_expires_at=None)
    save_secrets(row, {"secret_key": "secret", "refresh_token": "old-refresh"})
    def handler(request):
        if "oauth" in str(request.url):
            return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600})
        return httpx.Response(200, json={"result": {"fields": ["simple_date_title", "pv_count", "visitor_count"], "items": [[], [["2026-09", "9", "4"]]]}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            uv, pv, _ = await fetch_provider(ProviderClient(http), row, "2026-09-01", "2026-09-30")
            assert (uv, pv) == (4, 9)
            assert secrets_of(row)["refresh_token"] == "new-refresh"
            assert "new-refresh" not in row.secret_ciphertext
    asyncio.run(run())


def test_baidu_documented_business_result_and_both_site_lists():
    def row(mode):
        result = SimpleNamespace(source="baidu_tongji", config={"mode": mode, "tongji_site_id": "123", "api_key": "key", "username": "user"},
            secret_ciphertext=None, token_expires_at=None)
        save_secrets(result, {"secret_key": "secret", "refresh_token": "refresh", "access_token": "access"} if mode == "account" else {"access_token": "access"})
        return result
    def handler(request):
        sites = "getSiteList" in str(request.url)
        if request.url.host == "api.baidu.com":
            payload = {"list": [{"site_id": 123, "domain": "example.com"}]} if sites else {"result": {
                "fields": ["simple_date_title", "pv_count", "visitor_count"], "items": [[], [["2026-09", "19", "7"]]]}}
            return httpx.Response(200, json={"header": {"status": 0}, "body": {"data": [payload]}})
        return httpx.Response(200, json={"list": [{"site_id": 123, "domain": "example.com"}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            provider = ProviderClient(http)
            assert (await fetch_provider(provider, row("business"), "2026-09-01", "2026-09-30"))[:2] == (7, 19)
            assert (await fetch_provider(provider, row("business"), "2026-09-01", "2026-09-30", test=True))[2] == {"method": "getSiteList"}
            assert (await fetch_provider(provider, row("account"), "2026-09-01", "2026-09-30", test=True))[2] == {"method": "getSiteList"}
    asyncio.run(run())


def test_refresh_rotation_survives_later_api_error():
    row = SimpleNamespace(source="baidu_tongji", config={"mode": "account", "api_key": "key", "tongji_site_id": "123"},
        secret_ciphertext=None, token_expires_at=None)
    save_secrets(row, {"secret_key": "SECRET-SENTINEL", "refresh_token": "OLD-REFRESH-SENTINEL"})
    def handler(request):
        if request.url.host == "openapi.baidu.com" and "/oauth/" in request.url.path:
            return httpx.Response(200, json={"access_token": "NEW-ACCESS-SENTINEL", "refresh_token": "NEW-REFRESH-SENTINEL", "expires_in": 3600})
        return httpx.Response(200, json={"error_code": 403, "error_msg": "no permission NEW-ACCESS-SENTINEL"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AnalyticsError, match="无该站点权限") as failure:
                await fetch_provider(ProviderClient(http), row, "2026-09-01", "2026-09-30")
            assert "NEW-ACCESS-SENTINEL" not in str(failure.value)
            assert secrets_of(row)["refresh_token"] == "NEW-REFRESH-SENTINEL"
            assert row.token_expires_at is not None
    asyncio.run(run())


@pytest.mark.parametrize("grant,error,message", [
    ("authorization_code", "invalid_grant", "授权码无效或已过期"),
    ("authorization_code", "invalid_client", "API Key 或 Secret Key 不正确"),
    ("refresh_token", "invalid_grant", "百度授权已失效，请重新授权"),
])
def test_baidu_token_http_errors(grant, error, message):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(400, json={"error": error, "error_description": "SECRET-SENTINEL"}))) as http:
            with pytest.raises(AnalyticsError, match=message) as failure:
                if grant == "authorization_code":
                    await ProviderClient(http).exchange({"api_key": "key"}, {"secret_key": "SECRET-SENTINEL"}, "code")
                else:
                    await ProviderClient(http)._refresh({"api_key": "key"}, {"secret_key": "SECRET-SENTINEL", "refresh_token": "refresh"})
            assert "SECRET-SENTINEL" not in str(failure.value)
    asyncio.run(run())


@pytest.mark.parametrize("status,message", [(401, "服务账号 JSON 无效或已被禁用"), (429, "GA4 配额已用尽，请稍后再试")])
def test_ga4_report_status_messages(monkeypatch, status, message):
    monkeypatch.setattr("app.seo_site_analytics.jwt.encode", lambda *a, **k: "assertion")
    def handler(request):
        return httpx.Response(200, json={"access_token": "token"}) if request.url.host == "oauth2.googleapis.com" else httpx.Response(status, json={})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AnalyticsError, match=message):
                await ProviderClient(http).ga4({"property_id": "123"}, {"service_account_json": {"client_email": "a@example.com", "private_key": "secret"}}, "2026-09-01", "2026-09-30")
    asyncio.run(run())


def test_ga4_connection_test_uses_run_report():
    row = SimpleNamespace(source="ga4", config={"property_id": "123"}, secret_ciphertext=None)
    class Provider:
        async def ga4(self, config, secret, start, end, *, metadata=False):
            assert metadata is False and start == end == "2026-09-30"
            return {"rows": [{"metricValues": [{"value": "3"}, {"value": "8"}]}]}
    assert asyncio.run(fetch_provider(Provider(), row, "2026-09-30", "2026-09-30", test=True)) == (3, 8, {"method": "runReport"})


def test_baidu_openapi_error_messages_and_redaction():
    row = SimpleNamespace(source="baidu_tongji", config={"mode": "account", "api_key": "key", "tongji_site_id": "123"},
        secret_ciphertext=None, token_expires_at=None)
    save_secrets(row, {"secret_key": "SECRET-SENTINEL", "refresh_token": "REFRESH-SENTINEL", "access_token": "ACCESS-SENTINEL"})
    calls = 0
    def handler(request):
        nonlocal calls
        if "/oauth/" in request.url.path:
            return httpx.Response(200, json={"access_token": "NEW-ACCESS-SENTINEL", "refresh_token": "NEW-REFRESH-SENTINEL"})
        calls += 1
        if calls <= 2:
            return httpx.Response(200, json={"error_code": 110, "error_msg": "expired"})
        return httpx.Response(200, json={"error_code": 999, "error_msg": "x" * 120 + "NEW-ACCESS-SENTINEL"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AnalyticsError, match="百度授权已失效，请重新授权"):
                await fetch_provider(ProviderClient(http), row, "2026-09-01", "2026-09-30")
            with pytest.raises(AnalyticsError) as failure:
                await fetch_provider(ProviderClient(http), row, "2026-09-01", "2026-09-30")
            assert str(failure.value) == "百度统计接口返回错误：" + "x" * 100
            assert "NEW-ACCESS-SENTINEL" not in str(failure.value)
    asyncio.run(run())


def test_real_baidu_expired_token_code_and_ga4_network_failure_are_explained(monkeypatch):
    # Response shape captured from api.baidu.com on 2026-10-05 with an expired business token.
    expired = {"header": {"desc": "failure", "failures": [{"code": 894061, "position": "_user",
        "message": "The access token you provided is expried."}], "status": 2}, "body": {"data": [], "expand": {}}}
    monkeypatch.setattr("app.seo_site_analytics.jwt.encode", lambda *a, **k: "assertion")
    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(200, json=expired)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ProviderClient(http)
            with pytest.raises(AnalyticsError, match="Token 无效或已过期"):
                await client.baidu({"mode": "business", "username": "u", "tongji_site_id": "1"}, {"access_token": "t"}, "2026-09-01", "2026-09-30")
            with pytest.raises(AnalyticsError, match="无法连接 Google") as caught:
                await client.ga4({"property_id": "123"}, {"service_account_json": {"client_email": "a@b.c", "private_key": "k"}}, "2026-09-01", "2026-09-30")
            assert caught.value.code == "ga4_unreachable"
    asyncio.run(run())
