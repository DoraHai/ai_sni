import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.seo_serp import (
    CHINAZ_MAX_ATTEMPTS,
    CHINAZ_MAX_CONCURRENCY,
    SerpProviderError,
    canonical_url,
    create_chinaz_client,
    deterministic_match,
    domain_matches,
    fetch_baidu_top50,
    fetch_baidu_top50_batch,
    parse_dataforseo_response,
    parse_top50_response,
    rank_number,
)


def test_parse_dataforseo_response_keeps_only_organic_results() -> None:
    parsed = parse_dataforseo_response({
        "tasks": [{
            "status_code": 20000,
            "result": [{
                "se_results_count": 99,
                "items": [
                    {"type": "paid", "rank_group": 1, "url": "https://ads.example/"},
                    {"type": "organic", "rank_group": 2, "title": "官网", "description": "说明", "url": "https://example.com/page", "domain": "example.com"},
                ],
            }],
        }],
    })

    assert parsed["site_count"] == 99
    assert parsed["items"] == [{
        "rank": 2,
        "rank_label": "2",
        "title": "官网",
        "description": "说明",
        "result_url": "https://example.com/page",
        "domain": "example.com",
    }]


def test_parse_dataforseo_response_rejects_failed_task_without_leaking_message() -> None:
    with pytest.raises(SerpProviderError) as exc:
        parse_dataforseo_response({"tasks": [{"status_code": 40100, "status_message": "secret details"}]})
    assert exc.value.code == "provider_rejected"
    assert "secret" not in exc.value.public_message


def _provider_settings() -> object:
    return type(
        "Settings",
        (),
        {
            "chinaz_api_enabled": True,
            "chinaz_baidu_pc_top50_api_key": "secret-api-key",
            "chinaz_baidu_mobile_top50_api_key": "mobile-key",
            "chinaz_api_key": "",
            "chinaz_api_base_url": "https://openapi.chinaz.net/v1/1001",
            "chinaz_api_timeout_seconds": 8,
        },
    )()


def test_top50_response_and_rank_label_are_normalized() -> None:
    result = parse_top50_response(
        {
            "StateCode": 1,
            "Result": {
                "SiteCount": 1200,
                "Ranks": [
                    {
                        "RankStr": "2-3",
                        "Title": "品牌文章",
                        "Url": "https://www.zhihu.com/p/123?utm_source=seo",
                        "Description": "文章摘要",
                    }
                ],
            },
        }
    )
    assert result["items"][0]["rank"] == 13
    assert result["items"][0]["domain"] == "www.zhihu.com"
    assert rank_number("5-10", 1) == 50


def test_deterministic_match_prefers_exact_content_url() -> None:
    item = {
        "result_url": "https://zhihu.com/p/123?utm_source=seo",
        "title": "品牌文章",
        "description": "",
    }
    result = deterministic_match(
        item,
        official_domains=set(),
        content_urls={canonical_url("https://zhihu.com/p/123")},
        account_patterns=[],
        explicit_assets=[],
    )
    assert result["ownership_type"] == "brand_content"
    assert result["match_method"] == "published_url"
    assert result["confidence"] == 100


def test_official_domain_match_ignores_www_and_case() -> None:
    result = deterministic_match(
        {
            "result_url": "https://WWW.NORD.CN/cn/home-cn.jsp",
            "title": "NORD",
            "description": "诺德传动",
        },
        official_domains={"nord.cn"},
        content_urls=set(),
        account_patterns=[],
        explicit_assets=[],
    )
    assert result["ownership_type"] == "official_site"
    assert result["match_method"] == "site_domain"
    assert result["confidence"] == 100
    assert domain_matches("support.nord.cn", "nord.cn") is True
    assert domain_matches("nord.cn.example.com", "nord.cn") is False


def test_shared_platform_domain_is_not_mistaken_for_brand() -> None:
    item = {
        "result_url": "https://zhihu.com/p/not-owned",
        "title": "其他账号文章",
        "description": "",
    }
    result = deterministic_match(
        item,
        official_domains={"brand.example.com"},
        content_urls=set(),
        account_patterns=[],
        explicit_assets=[],
    )
    assert result["ownership_type"] == "unresolved"


def test_mobile_provider_uses_official_top50_endpoint() -> None:
    settings = _provider_settings()
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"StateCode": 1, "Result": {"Ranks": []}}
    client = AsyncMock()
    client.get.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    with patch("app.seo_serp.get_settings", return_value=settings), patch(
        "app.seo_serp.httpx.AsyncClient", return_value=context
    ):
        asyncio.run(fetch_baidu_top50("智能客服", "mobile"))
    args, kwargs = client.get.call_args
    assert args[0].endswith("/baidumobile_keywordtop50")
    assert kwargs["params"]["keyword"] == "智能客服"
    assert kwargs["params"]["APIKey"] == "mobile-key"


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (401, "provider_auth_failed", False),
        (403, "provider_auth_failed", False),
        (429, "provider_rate_limited", True),
        (503, "provider_unavailable", True),
    ],
)
def test_provider_http_errors_never_expose_request_secrets(
    status_code: int,
    expected_code: str,
    retryable: bool,
) -> None:
    settings = _provider_settings()
    request = httpx.Request(
        "GET",
        "https://openapi.chinaz.net/v1/1001/baidupc_keywordtop50",
        params={"keyword": "sensitive-keyword", "APIKey": "secret-api-key"},
    )
    response = httpx.Response(status_code, request=request)
    client = AsyncMock()
    client.get.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client

    with patch("app.seo_serp.get_settings", return_value=settings), patch(
        "app.seo_serp.httpx.AsyncClient", return_value=context
    ), pytest.raises(SerpProviderError) as exc:
        asyncio.run(fetch_baidu_top50("sensitive-keyword", "desktop"))

    assert exc.value.code == expected_code
    assert exc.value.retryable is retryable
    assert exc.value.status_code == status_code
    public_error = str(exc.value)
    assert "secret-api-key" not in public_error
    assert "sensitive-keyword" not in public_error
    assert "http" not in public_error.lower()


def test_provider_timeout_is_safe_and_classified() -> None:
    settings = _provider_settings()
    request = httpx.Request("GET", "https://openapi.chinaz.net/private")
    client = AsyncMock()
    client.get.side_effect = httpx.ReadTimeout(
        "sensitive-keyword secret-api-key",
        request=request,
    )
    context = AsyncMock()
    context.__aenter__.return_value = client

    with patch("app.seo_serp.get_settings", return_value=settings), patch(
        "app.seo_serp.httpx.AsyncClient", return_value=context
    ), pytest.raises(SerpProviderError) as exc:
        asyncio.run(fetch_baidu_top50("sensitive-keyword", "desktop"))

    assert exc.value.code == "provider_timeout"
    assert exc.value.retryable is True
    assert exc.value.timeout_phase == "read"
    assert exc.value.elapsed_ms is not None
    assert "secret-api-key" not in str(exc.value)
    assert "sensitive-keyword" not in str(exc.value)


def test_chinaz_client_uses_separate_timeouts_and_bounded_pool() -> None:
    sentinel = MagicMock()
    with patch("app.seo_serp.get_settings", return_value=_provider_settings()), patch(
        "app.seo_serp.httpx.AsyncClient",
        return_value=sentinel,
    ) as client_factory:
        assert create_chinaz_client() is sentinel

    timeout = client_factory.call_args.kwargs["timeout"]
    limits = client_factory.call_args.kwargs["limits"]
    assert timeout.connect == 8
    assert timeout.read == 8
    assert timeout.write == 8
    assert timeout.pool == 2
    assert limits.max_connections == 2
    assert limits.max_keepalive_connections == 2


@pytest.mark.parametrize(
    ("exception_type", "expected_phase"),
    [
        (httpx.ConnectTimeout, "connect"),
        (httpx.ReadTimeout, "read"),
        (httpx.WriteTimeout, "write"),
        (httpx.PoolTimeout, "pool"),
    ],
)
def test_provider_timeout_phase_is_classified_after_bounded_retries(
    exception_type: type[httpx.TimeoutException],
    expected_phase: str,
) -> None:
    request = httpx.Request("GET", "https://openapi.chinaz.net/private")
    client = AsyncMock()
    client.get.side_effect = exception_type(
        "sensitive-keyword secret-api-key",
        request=request,
    )

    with patch("app.seo_serp.get_settings", return_value=_provider_settings()), patch(
        "app.seo_serp.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock, pytest.raises(SerpProviderError) as exc:
        asyncio.run(
            fetch_baidu_top50(
                "sensitive-keyword",
                "desktop",
                client=client,
            )
        )

    assert exc.value.code == "provider_timeout"
    assert exc.value.timeout_phase == expected_phase
    assert exc.value.elapsed_ms is not None
    assert client.get.await_count == CHINAZ_MAX_ATTEMPTS
    assert sleep_mock.await_count == CHINAZ_MAX_ATTEMPTS - 1
    assert "secret-api-key" not in str(exc.value)
    assert "sensitive-keyword" not in str(exc.value)


def test_provider_transient_failure_recovers_on_retry() -> None:
    request = httpx.Request("GET", "https://openapi.chinaz.net/private")
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"StateCode": 1, "Result": {"Ranks": []}}
    client = AsyncMock()
    client.get.side_effect = [httpx.ConnectTimeout("temporary", request=request), response]

    with patch("app.seo_serp.get_settings", return_value=_provider_settings()), patch(
        "app.seo_serp.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        result = asyncio.run(fetch_baidu_top50("safe-keyword", "desktop", client=client))

    assert result["items"] == []
    assert client.get.await_count == 2
    sleep_mock.assert_awaited_once()


def test_provider_rate_limit_honors_retry_after() -> None:
    request = httpx.Request("GET", "https://openapi.chinaz.net/private")
    response = httpx.Response(429, request=request, headers={"Retry-After": "2"})
    client = AsyncMock()
    client.get.return_value = response

    with patch("app.seo_serp.get_settings", return_value=_provider_settings()), patch(
        "app.seo_serp.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock, pytest.raises(SerpProviderError) as exc:
        asyncio.run(fetch_baidu_top50("safe-keyword", "desktop", client=client))

    assert exc.value.code == "provider_rate_limited"
    assert exc.value.attempts == CHINAZ_MAX_ATTEMPTS
    assert all(call.args[0] >= 2 for call in sleep_mock.await_args_list)


def test_provider_batch_reuses_one_client_and_caps_concurrency() -> None:
    context = AsyncMock()
    provider_client = object()
    context.__aenter__.return_value = provider_client
    active = 0
    peak = 0
    seen_clients: list[object] = []

    async def fake_fetch(keyword: str, device: str, *, client: object) -> dict:
        nonlocal active, peak
        seen_clients.append(client)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"keyword": keyword, "device": device}

    requests = [(f"keyword-{index}", "desktop") for index in range(5)]
    with patch("app.seo_serp.create_chinaz_client", return_value=context) as factory, patch(
        "app.seo_serp.fetch_baidu_top50",
        side_effect=fake_fetch,
    ) as fetch:
        results = asyncio.run(fetch_baidu_top50_batch(requests))

    assert CHINAZ_MAX_CONCURRENCY == 2
    assert peak == 2
    assert fetch.await_count == len(requests)
    assert seen_clients == [provider_client] * len(requests)
    assert all(error is None for _, error in results)
    factory.assert_called_once_with()


def test_provider_rejection_reason_is_not_returned() -> None:
    with pytest.raises(SerpProviderError) as exc:
        parse_top50_response(
            {
                "StateCode": 0,
                "Reason": "sensitive-keyword secret-api-key",
            }
        )

    assert exc.value.code == "provider_rejected"
    assert "secret-api-key" not in str(exc.value)
    assert "sensitive-keyword" not in str(exc.value)


def test_malformed_provider_state_is_classified_safely() -> None:
    with pytest.raises(SerpProviderError) as exc:
        parse_top50_response({"StateCode": "sensitive-keyword secret-api-key"})

    assert exc.value.code == "invalid_response"
    assert "secret-api-key" not in str(exc.value)
    assert "sensitive-keyword" not in str(exc.value)
