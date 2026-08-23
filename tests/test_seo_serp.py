import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.seo_serp import (
    SerpProviderError,
    canonical_url,
    deterministic_match,
    fetch_baidu_top50,
    parse_top50_response,
    rank_number,
)


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
    settings = type(
        "Settings",
        (),
        {
            "chinaz_api_enabled": True,
            "chinaz_baidu_pc_top50_api_key": "pc-key",
            "chinaz_baidu_mobile_top50_api_key": "mobile-key",
            "chinaz_api_key": "",
            "chinaz_api_base_url": "https://openapi.chinaz.net/v1/1001",
            "chinaz_api_timeout_seconds": 8,
        },
    )()
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
        (429, "provider_rate_limited", False),
        (503, "provider_unavailable", True),
    ],
)
def test_provider_http_errors_never_expose_request_secrets(
    status_code: int,
    expected_code: str,
    retryable: bool,
) -> None:
    settings = type(
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
    settings = type(
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
    assert "secret-api-key" not in str(exc.value)
    assert "sensitive-keyword" not in str(exc.value)


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
