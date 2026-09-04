import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.seo_crawler import FetchResult, SeoCrawlError, USER_AGENT
from app.urlwords import UA, UrlFetchError, extract_words, fetch_page_text


def test_legacy_geo_user_agent_alias_uses_hardened_crawler_identity() -> None:
    assert UA == USER_AGENT


def _fetch_result(*, error_type: str | None = None) -> FetchResult:
    return FetchResult(
        requested_url="https://example.com/",
        final_url="https://example.com/",
        status_code=None if error_type else 200,
        redirect_chain=[],
        content_type="text/html" if not error_type else None,
        body=(
            "<html><head><title>Safe page</title></head>"
            "<body><h1>NORDAC manual</h1></body></html>"
            if not error_type
            else ""
        ),
        content_length=90 if not error_type else None,
        response_time_ms=3,
        headers={},
        error_type=error_type,
        fetch_error="Private, local, or reserved addresses are not allowed"
        if error_type
        else None,
    )


def test_extract_words_filters_common_english_navigation_noise() -> None:
    with patch(
        "app.urlwords.jieba.analyse.extract_tags",
        return_value=["home", "About", "contact", "read", "NORDAC", "BU0000"],
    ):
        words = extract_words("NORDAC BU0000", "ignored")

    assert "home" not in words
    assert "About" not in words
    assert "contact" not in words
    assert "read" not in words
    assert words == ["NORDAC", "BU0000"]


def test_fetch_page_text_reuses_pinned_ssrf_safe_crawler() -> None:
    safe_fetch = AsyncMock(return_value=_fetch_result())
    with patch("app.urlwords.fetch_url", safe_fetch):
        title, text = asyncio.run(fetch_page_text("https://example.com/"))

    safe_fetch.assert_awaited_once_with("https://example.com/")
    assert title == "Safe page"
    assert "NORDAC manual" in text


def test_fetch_page_text_rejects_a_blocked_dns_or_redirect_target() -> None:
    safe_fetch = AsyncMock(return_value=_fetch_result(error_type="blocked_address"))
    with patch("app.urlwords.fetch_url", safe_fetch):
        with pytest.raises(UrlFetchError, match="Private, local, or reserved"):
            asyncio.run(fetch_page_text("https://example.com/"))


def test_fetch_page_text_keeps_invalid_crawler_urls_in_the_public_error_contract() -> None:
    safe_fetch = AsyncMock(side_effect=SeoCrawlError("URL credentials are not allowed"))
    with patch("app.urlwords.fetch_url", safe_fetch):
        with pytest.raises(UrlFetchError, match="URL credentials are not allowed"):
            asyncio.run(fetch_page_text("https://user:password@example.com/"))
