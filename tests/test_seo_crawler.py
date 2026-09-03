import asyncio
import ssl

import httpcore
import httpx
import pytest

from app.seo_crawler import (
    FetchResult,
    SeoCrawlError,
    _PINNED_TARGETS,
    _PinnedNetworkBackend,
    _ensure_public_host,
    PinnedAsyncHTTPTransport,
    analyze_html,
    classify_fetch_error,
    crawl_site,
    fetch_url,
    is_html_page_url,
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
    with pytest.raises(SeoCrawlError, match="Invalid URL port"):
        normalize_crawl_url("https://example.com:not-a-port/path")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/products/widget.jsp", True),
        ("https://example.com/products/", True),
        ("https://example.com/calendar/event.ics?download=1", False),
        ("https://example.com/media/photo.JPG", False),
        ("https://example.com/software/archive.zip", False),
        ("https://example.com/cdn-cgi/l/email-protection#abc123", False),
    ],
)
def test_is_html_page_url_rejects_known_file_assets(url: str, expected: bool) -> None:
    assert is_html_page_url(url) is expected


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
      <a href="/contact">Contact</a>
      <a href="/cdn-cgi/l/email-protection#abc123">Protected email</a>
      <img src="pump.jpg">
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
    assert {
        "source_url": "https://example.com/",
        "target_url": "https://example.com/contact",
        "anchor_text": "Contact",
    } in result["internal_link_edges"]


def test_crawl_site_deduplicates_seed_also_listed_in_sitemap() -> None:
    pages = {
        "https://example.com/robots.txt": _result(
            "https://example.com/robots.txt",
            "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml",
            "text/plain",
        ),
        "https://example.com/sitemap.xml": _result(
            "https://example.com/sitemap.xml",
            '<urlset><url><loc>https://example.com/</loc></url></urlset>',
            "application/xml",
        ),
        "https://example.com/": _result(
            "https://example.com/",
            "<html><head><title>Home</title></head><body><h1>Home</h1></body></html>",
        ),
    }
    fetch_counts: dict[str, int] = {}

    async def fake_fetch(url: str, **_: object) -> FetchResult:
        fetch_counts[url] = fetch_counts.get(url, 0) + 1
        return pages[url]

    result = asyncio.run(crawl_site("https://example.com", max_urls=3, fetcher=fake_fetch))

    assert [item["url"] for item in result["snapshots"]] == ["https://example.com/"]
    assert result["snapshots"][0]["discovery_source"] == "seed"
    assert fetch_counts["https://example.com/"] == 1


def test_crawl_site_isolates_one_page_failure_and_strips_internal_links() -> None:
    pages = {
        "https://example.com/robots.txt": _result(
            "https://example.com/robots.txt", "User-agent: *\nAllow: /", "text/plain"
        ),
        "https://example.com/sitemap.xml": FetchResult(
            "https://example.com/sitemap.xml", "https://example.com/sitemap.xml",
            404, [], "text/plain", "", 0, 1, {},
        ),
        "https://example.com/": _result(
            "https://example.com/",
            '<html><body><a href="/broken">broken</a><a href="https://example.com:bad/skip">bad</a></body></html>',
        ),
    }

    async def fake_fetch(url: str, **_: object) -> FetchResult:
        if url == "https://example.com/broken":
            raise RuntimeError("one page exploded")
        return pages[url]

    result = asyncio.run(
        crawl_site("https://example.com", max_urls=2, max_depth=1, fetcher=fake_fetch)
    )

    assert len(result["snapshots"]) == 2
    assert all("internal_links" not in item for item in result["snapshots"])
    assert all("internal_link_details" not in item for item in result["snapshots"])
    assert result["internal_link_edges"] == [
        {
            "source_url": "https://example.com/",
            "target_url": "https://example.com/broken",
            "anchor_text": "broken",
        }
    ]
    failed = next(item for item in result["snapshots"] if item["url"].endswith("/broken"))
    assert failed["error_type"] == "crawl_error"
    assert failed["fetch_error"] == "one page exploded"


def test_crawl_site_does_not_enqueue_binary_assets() -> None:
    pages = {
        "https://example.com/robots.txt": _result(
            "https://example.com/robots.txt", "User-agent: *\nAllow: /", "text/plain"
        ),
        "https://example.com/sitemap.xml": _result(
            "https://example.com/sitemap.xml",
            "<urlset><url><loc>https://example.com/download.zip</loc></url></urlset>",
            "application/xml",
        ),
        "https://example.com/": _result(
            "https://example.com/",
            '<html><body><a href="/photo.jpg">photo</a><a href="/page">page</a></body></html>',
        ),
        "https://example.com/page": _result(
            "https://example.com/page", "<html><body><h1>Page</h1></body></html>"
        ),
    }

    async def fake_fetch(url: str, **_: object) -> FetchResult:
        return pages[url]

    result = asyncio.run(
        crawl_site(
            "https://example.com",
            max_urls=5,
            extra_seeds=["https://example.com/calendar.ics"],
            fetcher=fake_fetch,
        )
    )

    assert {item["url"] for item in result["snapshots"]} == {
        "https://example.com/",
        "https://example.com/page",
    }


def test_image_alt_evidence_distinguishes_states_and_keeps_occurrences():
    html = '''<html><head><base href="https://cdn.example.com/assets/"></head><body>
      <header><img id="logo" src="logo.png"></header><main>
      <a href="/product"><img src="same.png" alt=""></a>
      <img src="same.png" alt="  "><img src="good.png" alt="产品">
      <img src="placeholder.png" data-src="real.png" role="presentation">
      <img src="javascript:alert(1)"><img src="https://user:pass@example.com/a">
      <img srcset="one.png 1x, two.png 2x">
      </main></body></html>'''
    snapshot = analyze_html(_result("https://example.com/product", html))
    evidence = snapshot["image_alt_evidence"]
    assert evidence["images_count"] == 8
    assert evidence["candidate_count"] == snapshot["images_missing_alt_count"] == 7
    assert evidence["counts"] == {"missing": 5, "empty": 1, "whitespace": 1}
    items = evidence["items"]
    assert items[0]["section"] == "header" and items[0]["element_id"] == "logo"
    assert items[0]["source_url"] == "https://cdn.example.com/assets/logo.png"
    assert items[1]["in_link"] is True
    assert items[2]["position"] == 3
    assert items[3]["source_attribute"] == "data-src"
    assert items[3]["source_url"] == "https://cdn.example.com/assets/real.png"
    assert items[3]["role"] == "presentation"  # Evidence only; not auto-exempted.
    assert items[4]["source_url"] is None and items[5]["source_url"] is None
    assert items[6]["srcset"] == "one.png 1x, two.png 2x"
    assert evidence["truncated"] is False


def test_image_alt_evidence_is_bounded_and_empty_is_not_unknown():
    from app.models.seo import SeoPageSnapshot
    html = '<main>' + '<img src="/a.png">' * 205 + '</main>'
    evidence = analyze_html(_result("https://example.com", html))["image_alt_evidence"]
    assert len(evidence["items"]) == 200
    assert evidence["candidate_count"] == 205 and evidence["truncated"] is True
    snapshot = analyze_html(_result("https://example.com", '<img alt="Logo" src="/logo.png">'))
    assert snapshot["image_alt_evidence"]["items"] == []
    assert snapshot["image_alt_evidence"]["candidate_count"] == 0
    snapshot.pop("internal_links")
    snapshot.pop("internal_link_details")  # Production crawl_site stores link evidence separately.
    row = SeoPageSnapshot(tenant_id=1, site_id=1, crawl_run_id=1, **snapshot)
    assert row.image_alt_evidence["version"] == 1
    assert SeoPageSnapshot().image_alt_evidence is None


def test_image_evidence_bad_base_and_long_url_do_not_break_analysis():
    from bs4 import BeautifulSoup
    from app.seo_image_evidence import image_alt_evidence
    evidence = image_alt_evidence(BeautifulSoup('<base href="http://[bad"><img src="/logo.png">', "html.parser"), "https://example.com/page")
    assert evidence["items"][0]["source_url"] == "https://example.com/logo.png"
    evidence = image_alt_evidence(BeautifulSoup('<img src="https://example.com/' + 'a' * 3000 + '">', "html.parser"), "https://example.com")
    assert evidence["items"][0]["source_url_truncated"] is True
    assert len(evidence["items"][0]["source_url"]) == 2048


def test_fetch_url_blocks_loopback_before_network_request() -> None:
    result = asyncio.run(fetch_url("http://127.0.0.1/admin"))
    assert result.status_code is None
    assert result.error_type == "blocked_address"


@pytest.mark.parametrize(
    "exception_type",
    [
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    ],
)
def test_classify_fetch_error_recognizes_httpx_timeouts_with_empty_messages(
    exception_type: type[httpx.TimeoutException],
) -> None:
    assert classify_fetch_error(exception_type("")) == "timeout"


def test_fetch_url_classifies_an_httpx_read_timeout(monkeypatch) -> None:
    class TimeoutTransport(PinnedAsyncHTTPTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("", request=request)

    async def validate(_: str) -> str:
        return "93.184.216.34"

    async def exercise() -> FetchResult:
        async with httpx.AsyncClient(transport=TimeoutTransport()) as client:
            return await fetch_url("https://example.com/", client=client)

    monkeypatch.setattr("app.seo_crawler._ensure_public_host", validate)
    result = asyncio.run(exercise())

    assert result.status_code is None
    assert result.error_type == "timeout"


def test_fetch_url_revalidates_a_private_redirect(monkeypatch) -> None:
    class RedirectTransport(PinnedAsyncHTTPTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1/private"},
                request=request,
            )

    checked: list[str] = []

    async def validate(url: str) -> str:
        checked.append(url)
        if url.startswith("http://127.0.0.1"):
            raise SeoCrawlError("Private, local, or reserved addresses are not allowed")
        return "93.184.216.34"

    monkeypatch.setattr("app.seo_crawler._ensure_public_host", validate)

    async def exercise() -> FetchResult:
        async with httpx.AsyncClient(
            transport=RedirectTransport(),
            follow_redirects=False,
        ) as client:
            return await fetch_url("https://example.com/", client=client)

    result = asyncio.run(exercise())

    assert checked == ["https://example.com/", "http://127.0.0.1/private"]
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


def test_dns_rebinding_cannot_change_the_validated_connect_target(monkeypatch) -> None:
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
    dns_answer = ["93.184.216.34"]
    dns_calls = 0

    async def scenario() -> None:
        nonlocal dns_calls

        async def fake_getaddrinfo(*_: object, **__: object) -> list[tuple[object, ...]]:
            nonlocal dns_calls
            dns_calls += 1
            return [(None, None, None, None, (dns_answer[0], 443))]

        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
        approved_ip = await _ensure_public_host("https://example.com/")
        dns_answer[0] = "127.0.0.1"
        token = _PINNED_TARGETS.set({("example.com", 443): approved_ip})
        try:
            await backend.connect_tcp("example.com", 443)
        finally:
            _PINNED_TARGETS.reset(token)

    asyncio.run(scenario())

    assert dns_calls == 1
    assert dns_answer == ["127.0.0.1"]
    assert recording.hosts == ["93.184.216.34"]


def test_concurrent_pinned_targets_do_not_leak_between_contexts() -> None:
    class RecordingBackend:
        def __init__(self) -> None:
            self.hosts: list[str] = []

        async def connect_tcp(self, *, host: str, **_: object) -> object:
            await asyncio.sleep(0)
            self.hosts.append(host)
            return object()

        async def sleep(self, _: float) -> None:
            return None

    recording = RecordingBackend()
    backend = _PinnedNetworkBackend(recording)  # type: ignore[arg-type]

    async def connect(logical_host: str, approved_ip: str) -> None:
        token = _PINNED_TARGETS.set({(logical_host, 443): approved_ip})
        try:
            await asyncio.sleep(0)
            await backend.connect_tcp(logical_host, 443)
        finally:
            _PINNED_TARGETS.reset(token)

    async def scenario() -> None:
        await asyncio.gather(
            connect("first.example", "93.184.216.34"),
            connect("second.example", "142.250.72.14"),
        )

    asyncio.run(scenario())

    assert sorted(recording.hosts) == ["142.250.72.14", "93.184.216.34"]


def test_https_pinning_preserves_host_sni_and_certificate_verification() -> None:
    class RecordingStream(httpcore.AsyncNetworkStream):
        def __init__(self) -> None:
            self.response = bytearray(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"
            )
            self.writes: list[bytes] = []
            self.server_names: list[str | None] = []
            self.verify_modes: list[ssl.VerifyMode] = []
            self.check_hostnames: list[bool] = []

        async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
            chunk = bytes(self.response[:max_bytes])
            del self.response[:max_bytes]
            return chunk

        async def write(self, buffer: bytes, timeout: float | None = None) -> None:
            self.writes.append(buffer)

        async def start_tls(
            self,
            ssl_context: ssl.SSLContext,
            server_hostname: str | None = None,
            timeout: float | None = None,
        ) -> httpcore.AsyncNetworkStream:
            self.server_names.append(server_hostname)
            self.verify_modes.append(ssl_context.verify_mode)
            self.check_hostnames.append(ssl_context.check_hostname)
            return self

        async def aclose(self) -> None:
            return None

        def get_extra_info(self, info: str) -> object:
            return None

    class RecordingBackend:
        def __init__(self, stream: RecordingStream) -> None:
            self.stream = stream
            self.hosts: list[str] = []

        async def connect_tcp(self, *, host: str, **_: object) -> RecordingStream:
            self.hosts.append(host)
            return self.stream

        async def sleep(self, _: float) -> None:
            return None

    stream = RecordingStream()
    recording = RecordingBackend(stream)
    transport = PinnedAsyncHTTPTransport()
    transport._pool._network_backend = _PinnedNetworkBackend(recording)  # type: ignore[arg-type]

    async def scenario() -> httpx.Response:
        token = _PINNED_TARGETS.set({("example.com", 443): "93.184.216.34"})
        try:
            async with httpx.AsyncClient(transport=transport) as client:
                return await client.get("https://example.com/probe")
        finally:
            _PINNED_TARGETS.reset(token)

    response = asyncio.run(scenario())

    assert response.status_code == 200
    assert recording.hosts == ["93.184.216.34"]
    assert stream.server_names == ["example.com"]
    assert stream.verify_modes == [ssl.CERT_REQUIRED]
    assert stream.check_hostnames == [True]
    assert b"Host: example.com\r\n" in b"".join(stream.writes)
