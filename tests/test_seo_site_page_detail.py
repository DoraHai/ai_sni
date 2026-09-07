import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.seo import get_site_page_detail
from app.security.auth import _required


def _page(**changes):
    values = {
        "id": 31,
        "tenant_id": 7,
        "site_id": 9,
        "url": "https://example.com/article",
        "page_type": "article",
        "target_keyword_id": None,
        "title": "Article",
        "meta_description": None,
        "meta_keywords": None,
        "h1": "Article",
        "canonical": None,
        "indexable": True,
        "http_status": 200,
        "content_units": 300,
        "audit_score": 90,
        "issue_codes": [],
        "title_suggestion": None,
        "description_suggestion": None,
        "status": "healthy",
        "last_error": None,
        "last_checked_at": datetime(2026, 9, 7, 4, 0),
        "created_at": datetime(2026, 9, 7, 3, 0),
        "updated_at": datetime(2026, 9, 7, 4, 0),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _snapshot(snapshot_id, fetched_at):
    values = {
        "id": snapshot_id,
        "crawl_run_id": 41,
        "site_id": 9,
        "url": "https://example.com/article",
        "final_url": "https://example.com/article",
        "discovery_source": "internal_link",
        "click_depth": 1,
        "status_code": 200,
        "redirect_chain": [],
        "fetch_error": None,
        "error_type": None,
        "content_type": "text/html",
        "content_length": 1000,
        "response_time_ms": 50,
        "robots_allowed": True,
        "meta_robots": None,
        "x_robots_tag": None,
        "canonical_url": None,
        "indexable": True,
        "title": "Article",
        "title_length": 7,
        "meta_description": None,
        "description_length": 0,
        "h1_texts": ["Article"],
        "h1_count": 1,
        "html_lang": "zh-CN",
        "main_content_extractable": True,
        "word_count": 300,
        "schema_types": [],
        "schema_jsonld_count": 0,
        "schema_parse_error": False,
        "internal_links_count": 2,
        "external_links_count": 0,
        "images_count": 1,
        "images_missing_alt_count": 0,
        "hreflang_tags": [],
        "issue_codes": [],
        "fetched_at": fetched_at,
    }
    return SimpleNamespace(**values)


def test_page_detail_returns_only_stored_scoped_evidence():
    page = _page()
    latest = _snapshot(52, datetime(2026, 9, 7, 4, 0))
    previous = _snapshot(51, datetime(2026, 9, 6, 4, 0))
    edge = SimpleNamespace(
        id=61,
        source_page_id=32,
        anchor_text="详情",
        discovered_at=datetime(2026, 9, 7, 4, 0),
    )
    source = SimpleNamespace(id=32, url="https://example.com/", title="Home")
    rows = MagicMock()
    rows.all.return_value = [(edge, source)]
    session = AsyncMock()
    session.scalars.return_value = [latest, previous]
    session.scalar.side_effect = [1, 2]
    session.execute.return_value = rows

    with (
        patch("app.api.seo._site_page", new=AsyncMock(return_value=page)),
        patch("app.api.seo._seo_site", new=AsyncMock(return_value=SimpleNamespace(id=9))),
    ):
        result = asyncio.run(get_site_page_detail(31, 7, session))

    assert result["read_only"] is True
    assert result["page"]["id"] == 31 and result["page"]["site_id"] == 9
    assert result["latest_snapshot"]["id"] == 52
    assert result["previous_snapshot"]["id"] == 51
    assert result["internal_links"] == {
        "incoming": 1,
        "outgoing": 2,
        "incoming_sources": [
            {
                "source_page_id": 32,
                "source_url": "https://example.com/",
                "source_title": "Home",
                "anchor_text": "详情",
                "discovered_at": "2026-09-07T04:00:00+08:00",
            }
        ],
        "incoming_sources_truncated": False,
    }
    session.commit.assert_not_awaited()
    session.add.assert_not_called()


def test_page_detail_rejects_an_unbound_page_without_queries():
    session = AsyncMock()
    page = _page(site_id=None)
    with patch("app.api.seo._site_page", new=AsyncMock(return_value=page)):
        try:
            asyncio.run(get_site_page_detail(31, 7, session))
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 422
        else:
            raise AssertionError("unbound page must be rejected")
    session.scalars.assert_not_awaited()
    session.execute.assert_not_awaited()


def test_page_detail_route_requires_read_only_seo_site_permission():
    assert _required("/api/v1/seo/site-pages/31/detail", "GET") == (
        {"seo.site"},
        False,
    )
