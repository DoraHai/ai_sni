import asyncio

import httpcore
import pytest

from app.seo_crawler import (
    FetchResult,
    SeoCrawlError,
    _PINNED_TARGETS,
    _PinnedNetworkBackend,
    analyze_html,
    crawl_site,
    fetch_url,
    normalize_crawl_url,
    sitemap_urls,
)


def _result(url: str, body: str, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=200,
        redirect_chain=[],
        content_type=content_type,
        body=body,
        content_length=len(body.encode()),
        response_time_ms=12,
        headers={},
    )


def test_normalize_crawl_url_removes_fragment_and_rejects_credentials() -> None:
    assert normalize_crawl_url("Example.com/products/#spec") == "https://example.com/products"
    with pytest.raises(SeoCrawlError):
        normalize_crawl_url("https://user:pass@example.com")


def test_sitemap_parser_supports_urlset_and_index() -> None:
    pages, children = sitemap_urls(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/a</loc></url></urlset>'
    )
    assert pages == ["https://example.com/a"]
    assert children == []
    pages, children = sitemap_urls(
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://example.com/products.xml</loc></sitemap></sitemapindex>'
    )
    assert pages == []
    assert children == ["https://example.com/products.xml"]


def test_html_analysis_extracts_seo_evidence_and_issues() -> None:
    html = """
    <html lang="en"><head>
      <title>Industrial Pump</title>
      <meta name="description" content="Reliable industrial pump for chemical processing.">
      <link rel="canonical" href="/pump">
      <script type="application/ld+json">{"@type":"Product","name":"Pump"}</script>
    </head><body><main><h1>Industrial Pump</h1>
      <p>Detailed product description with materials, applications, standards and technical specifications for buyers.</p>
      <a href="/contact">Contact</a><img src="pump.jpg">
    </main></body></html>
    """
    snapshot = analyze_html(_result("https://example.com/pump", html))
    assert snapshot["title"] == "Industrial Pump"
    assert snapshot["canonical_url"] == "https://example.com/pump"
    assert snapshot["schema_types"] == ["Product"]
    assert snapshot["internal_links_count"] == 1
    assert "image_alt_missing" in snapshot["issue_codes"]
    assert snapshot["raw_html_hash"]


def test_crawl_site_uses_robots_sitemap_and_internal_links() -> None:
    pages = {
        "https://example.com/robots.txt": _result(
            "https://example.com/robots.txt",
            "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml",
            "text/plain",
        ),
        "https://example.com/sitemap.xml": _result(
            "https://example.com/sitemap.xml",
            '<urlset><url><loc>https://example.com/product</loc></url></urlset>',
            "application/xml",
        ),
        "https://example.com/": _result(
            "https://example.com/",
            '<html lang="en"><head><title>Home</title></head><body><h1>Home</h1><a href="/contact">Contact</a></body></html>',
        ),
        "https://example.com/product": _result(
            "https://example.com/product",
            '<html lang="en"><head><title>Product</title></head><body><h1>Product</h1></body></html>',
        ),
        "https://example.com/contact": _result(
            "https://example.com/contact",
            '<html lang="en"><head><title>Contact</title></head><body><h1>Contact</h1></body></html>',
        ),
    }

    async def fake_fetch(url: str, **_: object) -> FetchResult:
        return pages[url]

    result = asyncio.run(crawl_site("https://example.com", max_urls=3, fetcher=fake_fetch))
    crawled = {item["url"] for item in result["snapshots"]}
    assert "https://example.com/" in crawled
    assert "https://example.com/product" in crawled
    assert result["robots_status"] == 200


def test_fetch_url_blocks_loopback_before_network_request() -> None:
    result = asyncio.run(fetch_url("http://127.0.0.1/admin"))
    assert result.status_code is None
    assert result.error_type == "blocked_address"


def test_pinned_backend_connects_only_to_the_validated_ip() -> None:
    class RecordingBackend:
        def __init__(self) -> None:
            self.hosts: list[str] = []

        async def connect_tcp(self, *, host: str, **_: object) -> object:
            self.hosts.append(host)
            return object()

        async def sleep(self, _: float) -> None:
            return None

    recording = RecordingBackend()
    backend = _PinnedNetworkBackend(recording)  # type: ignore[arg-type]
    token = _PINNED_TARGETS.set({("example.com", 443): "93.184.216.34"})
    try:
        asyncio.run(backend.connect_tcp("example.com", 443))
    finally:
        _PINNED_TARGETS.reset(token)
    assert recording.hosts == ["93.184.216.34"]


def test_pinned_backend_refuses_an_unvalidated_connection() -> None:
    backend = _PinnedNetworkBackend()
    with pytest.raises(httpcore.ConnectError, match="not pinned"):
        asyncio.run(backend.connect_tcp("example.com", 443))
