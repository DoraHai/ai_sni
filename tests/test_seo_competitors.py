import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.seo import CompetitorCollectRequest, CompetitorCreate, router
from app.seo_competitor import (
    COMPETITOR_FETCH_CONCURRENCY,
    COMPETITOR_FETCH_TIMEOUT_SECONDS,
    COMPETITOR_MANUAL_COOLDOWN_SECONDS,
    COMPETITOR_TOTAL_TIMEOUT_SECONDS,
    CompetitorCollectionError,
    build_competitor_rank_matrix,
    collect_competitor_content,
    competitor_retry_after,
)
from app.seo_crawler import FetchResult


ROOT = Path(__file__).resolve().parents[1]


def _fetch_result(url: str, body: str, *, final_url: str | None = None, error_type: str | None = None) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=final_url or url,
        status_code=None if error_type else 200,
        redirect_chain=[],
        content_type="text/html",
        body=body,
        content_length=len(body),
        response_time_ms=10,
        headers={},
        error_type=error_type,
        fetch_error="failed" if error_type else None,
    )


def test_manual_competitor_collection_is_site_scoped_and_bounded() -> None:
    request = CompetitorCollectRequest(tenant_id=1, site_id=9, max_pages=10)
    assert request.site_id == 9
    assert request.max_pages == 10
    assert COMPETITOR_MANUAL_COOLDOWN_SECONDS == 3600
    assert COMPETITOR_FETCH_CONCURRENCY == 5
    assert COMPETITOR_FETCH_TIMEOUT_SECONDS == 8.0
    assert COMPETITOR_TOTAL_TIMEOUT_SECONDS == 25.0
    with pytest.raises(ValidationError):
        CompetitorCollectRequest(tenant_id=1, site_id=0, max_pages=10)
    with pytest.raises(ValidationError):
        CompetitorCollectRequest(tenant_id=1, site_id=9, max_pages=11)
    with pytest.raises(ValidationError):
        CompetitorCreate(tenant_id=1, name="Competitor", domain="example.com")


def test_manual_competitor_collection_cooldown_is_one_hour() -> None:
    now = datetime(2026, 8, 25, 12, 0, 0)
    assert competitor_retry_after(None, now=now) == 0
    assert competitor_retry_after(now - timedelta(minutes=30), now=now) == 1800
    assert competitor_retry_after(now - timedelta(hours=1), now=now) == 0


def test_manual_collection_discovers_only_same_domain_html_pages() -> None:
    homepage = "https://example.com/"
    bodies = {
        homepage: """
            <html><head><title>Example</title></head><body>
              <a href="/news/a?utm_source=test">A</a>
              <a href="https://www.example.com/news/b">B</a>
              <a href="https://evil-example.com/lookalike">Wrong</a>
              <a href="/brochure.pdf">PDF</a>
            </body></html>
        """,
        "https://example.com/news/a": "<html><head><title>News A</title></head><body>A</body></html>",
        "https://www.example.com/news/b": "<html><head><title>News B</title></head><body>B</body></html>",
    }

    clients = []

    async def fetcher(url: str, *, client=None) -> FetchResult:
        clients.append(client)
        return _fetch_result(url, bodies[url])

    result = asyncio.run(
        collect_competitor_content("example.com", max_pages=10, fetcher=fetcher)
    )
    assert result.attempted == 3
    assert result.failed == 0
    assert clients and all(client is clients[0] for client in clients)
    assert clients[0] is not None
    assert [(page.url, page.title) for page in result.pages] == [
        ("https://example.com/", "Example"),
        ("https://example.com/news/a", "News A"),
        ("https://www.example.com/news/b", "News B"),
    ]


def test_manual_collection_rejects_cross_domain_homepage_redirect() -> None:
    async def fetcher(url: str, *, client=None) -> FetchResult:
        return _fetch_result(
            url,
            "<html><title>Wrong site</title></html>",
            final_url="https://unrelated.test/",
        )

    with pytest.raises(CompetitorCollectionError) as exc:
        asyncio.run(
            collect_competitor_content("example.com", max_pages=1, fetcher=fetcher)
        )
    assert exc.value.code == "cross_domain_redirect"


def test_manual_collection_returns_structured_total_timeout(monkeypatch) -> None:
    async def fetcher(url: str, *, client=None) -> FetchResult:
        await asyncio.sleep(0.05)
        return _fetch_result(url, "<html><title>Slow</title></html>")

    monkeypatch.setattr("app.seo_competitor.COMPETITOR_TOTAL_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(CompetitorCollectionError) as exc:
        asyncio.run(
            collect_competitor_content("example.com", max_pages=1, fetcher=fetcher)
        )
    assert exc.value.code == "collection_timeout"
    assert "安全时限" in exc.value.public_message


def test_competitor_rank_matrix_uses_latest_scoped_batch_rows() -> None:
    captured = datetime(2026, 8, 25, 2, 16, 15)
    competitors = [
        SimpleNamespace(id=7, domain="example.com"),
        SimpleNamespace(id=8, domain="other.test"),
    ]
    rows = [
        SimpleNamespace(keyword_id=2, captured_at=captured, domain="news.example.com", rank=6),
        SimpleNamespace(keyword_id=2, captured_at=captured, domain="www.example.com", rank=3),
        SimpleNamespace(keyword_id=2, captured_at=captured, domain="evil-example.com", rank=1),
    ]
    matrix = build_competitor_rank_matrix([2, 3], competitors, rows)
    assert matrix[0]["rankings"]["7"] == {
        "state": "ranked",
        "rank": 3,
        "domain": "www.example.com",
    }
    assert matrix[0]["rankings"]["8"]["state"] == "outside_top50"
    assert matrix[1]["rankings"]["7"]["state"] == "not_collected"


def test_competitor_routes_and_frontend_are_manual_only() -> None:
    paths = {route.path for route in router.routes}
    assert "/api/v1/seo/competitors/rankings" in paths
    assert "/api/v1/seo/competitors/{competitor_id}/collect" in paths

    view = (ROOT / "frontend/src/views/seo/SeoCompetitorsView.vue").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api/seo.js").read_text(encoding="utf-8")
    backend = (ROOT / "app/api/seo.py").read_text(encoding="utf-8")
    scheduler = (ROOT / "app/seo_scheduler.py").read_text(encoding="utf-8")
    assert "手动采集" in view
    assert "不会自动运行" in view
    assert "最近采集尝试" in view
    assert "本次尝试已进入 1 小时冷却" in view
    assert "collectionOutcome.failed" in view
    assert "[SEO][COMPETITOR] manual collection failed" in backend
    assert "fetchSeoCompetitorRankings" in view
    assert "site_id: siteId" in api
    assert "competitor" not in scheduler.lower()
