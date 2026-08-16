import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.seo_serp import (
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
