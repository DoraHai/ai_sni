"""Bounded, SSRF-safe crawler for the SEO workspace."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
import hashlib
import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
import httpcore
from bs4 import BeautifulSoup


USER_AGENT = "GrowthSniperSEO/1.0"
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 3 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 15.0


class SeoCrawlError(Exception):
    pass


_PINNED_TARGETS: ContextVar[dict[tuple[str, int], str]] = ContextVar(
    "seo_pinned_targets",
    default={},
)


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect original HTTP origins to IPs already approved by SSRF checks."""

    def __init__(self, backend: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        connect_host = _PINNED_TARGETS.get().get((host.lower().rstrip("."), port))
        if connect_host is None:
            raise httpcore.ConnectError("Outbound host was not pinned by the SSRF validator")
        return await self._backend.connect_tcp(
            host=connect_host,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix sockets are not allowed for SEO HTTP fetching")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport whose TCP connects require a request-scoped pinned IP."""

    def __init__(self, *, limits: httpx.Limits | None = None) -> None:
        super().__init__(trust_env=False, limits=limits or httpx.Limits())
        self._pool._network_backend = _PinnedNetworkBackend()


def pinned_async_client(**kwargs: Any) -> httpx.AsyncClient:
    """Build an HTTP client that cannot perform an unvalidated DNS connection."""
    limits = kwargs.pop("limits", None)
    return httpx.AsyncClient(
        **kwargs,
        trust_env=False,
        transport=PinnedAsyncHTTPTransport(limits=limits),
    )


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int | None
    redirect_chain: list[str]
    content_type: str | None
    body: str
    content_length: int | None
    response_time_ms: int | None
    headers: dict[str, str]
    error_type: str | None = None
    fetch_error: str | None = None


def normalize_crawl_url(value: str) -> str:
    raw = value.strip()
    if not re.match(r"^https?://", raw, re.I):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SeoCrawlError("Invalid HTTP/HTTPS URL")
    if parsed.username or parsed.password:
        raise SeoCrawlError("URL credentials are not allowed")
    host = parsed.hostname.lower()
    port = parsed.port
    netloc = host if port is None else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


async def _ensure_public_host(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise SeoCrawlError("URL has no host")
    if host.lower() == "localhost" or host.lower().endswith((".local", ".internal")):
        raise SeoCrawlError("Private or local addresses are not allowed")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise SeoCrawlError(f"DNS lookup failed: {host}") from exc
        addresses = list(
            dict.fromkeys(ipaddress.ip_address(info[4][0]) for info in infos)
        )
    if not addresses or any(not address.is_global for address in addresses):
        raise SeoCrawlError("Private, local, or reserved addresses are not allowed")
    return str(addresses[0])


def classify_fetch_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.TooManyRedirects):
        return "too_many_redirects"
    text = str(exc).lower()
    if "dns" in text or "name or service" in text:
        return "dns_error"
    if "ssl" in text or "tls" in text or "certificate" in text:
        return "tls_error"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "redirect" in text:
        return "too_many_redirects"
    if "private" in text or "local" in text or "reserved" in text:
        return "blocked_address"
    return "connection_error"


async def fetch_url(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    allow_text: bool = False,
    allow_xml: bool = False,
) -> FetchResult:
    requested = normalize_crawl_url(url)
    current = requested
    redirects: list[str] = []
    owns_client = client is None
    http_client = client or pinned_async_client(
        timeout=FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xml,text/xml;q=0.9,text/plain;q=0.8",
        },
    )
    started = time.perf_counter()
    try:
        if not isinstance(getattr(http_client, "_transport", None), PinnedAsyncHTTPTransport):
            raise SeoCrawlError("SEO HTTP client must use the pinned transport")
        for _ in range(MAX_REDIRECTS + 1):
            parsed_current = urlparse(current)
            hostname = (parsed_current.hostname or "").lower().rstrip(".")
            port = parsed_current.port or (443 if parsed_current.scheme == "https" else 80)
            approved_ip = await _ensure_public_host(current)
            token = _PINNED_TARGETS.set({(hostname, port): approved_ip})
            try:
                async with http_client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise SeoCrawlError("Redirect response has no target")
                        current = normalize_crawl_url(urljoin(current, location))
                        redirects.append(current)
                        continue
                    content_type = response.headers.get("content-type", "").lower()
                    accepted = (
                        "text/html" in content_type
                        or (allow_text and "text/plain" in content_type)
                        or (allow_xml and "xml" in content_type)
                    )
                    chunks: list[bytes] = []
                    size = 0
                    if accepted:
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_RESPONSE_BYTES:
                                raise SeoCrawlError("Response exceeds 3MB")
                            chunks.append(chunk)
                    body = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                    elapsed = round((time.perf_counter() - started) * 1000)
                    error_type = None
                    if response.status_code >= 500:
                        error_type = "http_5xx"
                    elif response.status_code >= 400:
                        error_type = "http_4xx"
                    elif not accepted:
                        error_type = "non_html"
                    return FetchResult(
                        requested_url=requested,
                        final_url=str(response.url),
                        status_code=response.status_code,
                        redirect_chain=redirects,
                        content_type=content_type or None,
                        body=body,
                        content_length=size if accepted else None,
                        response_time_ms=elapsed,
                        headers={key.lower(): value for key, value in response.headers.items()},
                        error_type=error_type,
                        fetch_error=(
                            f"HTTP {response.status_code}" if response.status_code >= 400 else
                            (f"Unsupported content type: {content_type or 'unknown'}" if not accepted else None)
                        ),
                    )
            finally:
                _PINNED_TARGETS.reset(token)
        raise SeoCrawlError("Too many redirects")
    except (SeoCrawlError, httpx.HTTPError) as exc:
        return FetchResult(
            requested_url=requested,
            final_url=current,
            status_code=None,
            redirect_chain=redirects,
            content_type=None,
            body="",
            content_length=None,
            response_time_ms=round((time.perf_counter() - started) * 1000),
            headers={},
            error_type=classify_fetch_error(exc),
            fetch_error=str(exc),
        )
    finally:
        if owns_client:
            await http_client.aclose()


def _schema_types(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        item_type = value.get("@type")
        if isinstance(item_type, str):
            found.append(item_type)
        elif isinstance(item_type, list):
            found.extend(str(item) for item in item_type if item)
        for key in ("@graph", "mainEntity", "itemListElement"):
            found.extend(_schema_types(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            found.extend(_schema_types(item))
    return found


def analyze_html(result: FetchResult, *, robots_allowed: bool = True) -> dict[str, Any]:
    if result.error_type or not result.body:
        issue = "robots_blocked" if not robots_allowed else (result.error_type or "empty_response")
        return {
            "url": result.requested_url,
            "final_url": result.final_url,
            "status_code": result.status_code,
            "redirect_chain": result.redirect_chain,
            "fetch_error": result.fetch_error,
            "error_type": issue,
            "content_type": result.content_type,
            "content_length": result.content_length,
            "response_time_ms": result.response_time_ms,
            "raw_html_hash": None,
            "robots_allowed": robots_allowed,
            "indexable": False if not robots_allowed else None,
            "issue_codes": [issue],
            "internal_links": [],
        }

    soup = BeautifulSoup(result.body, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    description_node = soup.select_one('meta[name="description" i]')
    description = description_node.get("content", "").strip() if description_node else None
    h1_texts = [node.get_text(" ", strip=True) for node in soup.select("h1") if node.get_text(" ", strip=True)]
    canonical_node = soup.select_one('link[rel~="canonical" i]')
    canonical = urljoin(result.final_url, canonical_node.get("href", "").strip()) if canonical_node and canonical_node.get("href") else None
    robots_node = soup.select_one('meta[name="robots" i]')
    meta_robots = robots_node.get("content", "").strip() if robots_node else None
    x_robots = result.headers.get("x-robots-tag")
    directives = f"{meta_robots or ''},{x_robots or ''}".lower()
    indexable = robots_allowed and "noindex" not in directives
    html_lang = (soup.html.get("lang") or "").strip() if soup.html else None

    schema_types: list[str] = []
    schema_errors = 0
    schema_nodes = soup.select('script[type="application/ld+json"]')
    for node in schema_nodes:
        try:
            schema_types.extend(_schema_types(json.loads(node.get_text(strip=True))))
        except (json.JSONDecodeError, TypeError):
            schema_errors += 1

    for node in soup.select("script,style,noscript,template,svg"):
        node.decompose()
    main = soup.select_one("main, article, [role=main]") or soup.body or soup
    main_text = main.get_text(" ", strip=True)
    word_count = len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", main_text))
    internal_links: list[str] = []
    external_links_count = 0
    origin_host = (urlparse(result.final_url).hostname or "").lower()
    for node in soup.select("a[href]"):
        raw_href = str(node.get("href") or "").strip()
        if not raw_href or raw_href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        try:
            target = normalize_crawl_url(urljoin(result.final_url, raw_href))
        except SeoCrawlError:
            continue
        if (urlparse(target).hostname or "").lower() == origin_host:
            if target not in internal_links:
                internal_links.append(target)
        else:
            external_links_count += 1

    from app.seo_image_evidence import image_alt_evidence

    images = soup.select("img")
    missing_alt = sum(not str(node.get("alt") or "").strip() for node in images)
    hreflang_tags = [
        {
            "lang": str(node.get("hreflang") or "").strip(),
            "url": urljoin(result.final_url, str(node.get("href") or "").strip()),
        }
        for node in soup.select('link[rel~="alternate"][hreflang]')
        if node.get("href")
    ]

    issues: list[str] = []
    if result.status_code and result.status_code >= 400:
        issues.append("http_5xx" if result.status_code >= 500 else "http_4xx")
    if not indexable:
        issues.append("noindex")
    if not title:
        issues.append("title_missing")
    elif len(title) > 65:
        issues.append("title_too_long")
    if not description:
        issues.append("description_missing")
    if len(h1_texts) == 0:
        issues.append("h1_missing")
    elif len(h1_texts) > 1:
        issues.append("h1_multiple")
    if word_count < 100:
        issues.append("thin_content")
    if schema_errors:
        issues.append("schema_invalid")
    if missing_alt:
        issues.append("image_alt_missing")
    if not html_lang:
        issues.append("html_lang_missing")

    return {
        "url": result.requested_url,
        "final_url": result.final_url,
        "status_code": result.status_code,
        "redirect_chain": result.redirect_chain,
        "fetch_error": result.fetch_error,
        "error_type": result.error_type,
        "content_type": result.content_type,
        "content_length": result.content_length,
        "response_time_ms": result.response_time_ms,
        "raw_html_hash": hashlib.sha256(result.body.encode("utf-8")).hexdigest(),
        "robots_allowed": robots_allowed,
        "meta_robots": meta_robots,
        "x_robots_tag": x_robots,
        "canonical_url": canonical,
        "indexable": indexable,
        "title": title,
        "title_length": len(title) if title else 0,
        "meta_description": description,
        "description_length": len(description) if description else 0,
        "h1_texts": h1_texts,
        "h1_count": len(h1_texts),
        "html_lang": html_lang,
        "main_content_extractable": bool(main_text and word_count >= 20),
        "main_content_hash": hashlib.sha256(main_text.encode("utf-8")).hexdigest() if main_text else None,
        "word_count": word_count,
        "schema_types": sorted(set(schema_types)),
        "schema_jsonld_count": len(schema_nodes),
        "schema_parse_error": schema_errors > 0,
        "internal_links_count": len(internal_links),
        "external_links_count": external_links_count,
        "images_count": len(images),
        "images_missing_alt_count": missing_alt,
        "image_alt_evidence": image_alt_evidence(soup, result.final_url),
        "hreflang_tags": hreflang_tags,
        "issue_codes": issues,
        "internal_links": internal_links,
    }


def sitemap_urls(xml_text: str) -> tuple[list[str], list[str]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return [], []
    page_urls: list[str] = []
    child_sitemaps: list[str] = []
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() != "loc" or not (node.text or "").strip():
            continue
        if root_name == "sitemapindex":
            child_sitemaps.append((node.text or "").strip())
        else:
            page_urls.append((node.text or "").strip())
    return page_urls, child_sitemaps


FetchCallable = Callable[..., Awaitable[FetchResult]]


async def crawl_site(
    seed_url: str,
    *,
    max_urls: int = 50,
    max_depth: int = 3,
    extra_seeds: list[str] | None = None,
    fetcher: FetchCallable = fetch_url,
) -> dict[str, Any]:
    seed = normalize_crawl_url(seed_url)
    allowed_host = (urlparse(seed).hostname or "").lower()
    base = f"{urlparse(seed).scheme}://{urlparse(seed).netloc}"
    robots_url = urljoin(base, "/robots.txt")
    robot_parser = RobotFileParser()
    robot_parser.set_url(robots_url)
    robots_result = await fetcher(robots_url, allow_text=True)
    sitemap_candidates = [urljoin(base, "/sitemap.xml")]
    if robots_result.status_code == 200 and robots_result.body:
        robot_parser.parse(robots_result.body.splitlines())
        sitemap_candidates.extend(
            line.split(":", 1)[1].strip()
            for line in robots_result.body.splitlines()
            if line.lower().startswith("sitemap:") and ":" in line
        )
    else:
        robot_parser.parse([])

    discovered_from_sitemap: list[str] = []
    checked_sitemaps: set[str] = set()
    pending_sitemaps = list(dict.fromkeys(sitemap_candidates))[:5]
    while pending_sitemaps and len(checked_sitemaps) < 5 and len(discovered_from_sitemap) < max_urls:
        try:
            sitemap_url = normalize_crawl_url(pending_sitemaps.pop(0))
        except SeoCrawlError:
            continue
        if (urlparse(sitemap_url).hostname or "").lower() != allowed_host:
            continue
        if sitemap_url in checked_sitemaps:
            continue
        checked_sitemaps.add(sitemap_url)
        sitemap_result = await fetcher(sitemap_url, allow_xml=True, allow_text=True)
        if sitemap_result.status_code != 200 or not sitemap_result.body:
            continue
        pages, children = sitemap_urls(sitemap_result.body)
        discovered_from_sitemap.extend(pages)
        pending_sitemaps.extend(children[:5])

    queue: list[tuple[str, int, str]] = [(seed, 0, "seed")]
    for raw in [*(extra_seeds or []), *discovered_from_sitemap]:
        try:
            url = normalize_crawl_url(raw)
        except SeoCrawlError:
            continue
        if (urlparse(url).hostname or "").lower() == allowed_host:
            queue.append((url, 0, "sitemap" if raw in discovered_from_sitemap else "manual"))

    queued = {item[0] for item in queue}
    visited: set[str] = set()
    snapshots: list[dict[str, Any]] = []
    async with pinned_async_client(
        timeout=FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    ) as client:
        while queue and len(visited) < max_urls:
            batch: list[tuple[str, int, str]] = []
            while queue and len(batch) < 4 and len(visited) + len(batch) < max_urls:
                item = queue.pop(0)
                if item[0] not in visited:
                    batch.append(item)
            if not batch:
                continue

            async def process(item: tuple[str, int, str]) -> tuple[tuple[str, int, str], dict[str, Any]]:
                url, _, _ = item
                allowed = robot_parser.can_fetch(USER_AGENT, url)
                if not allowed:
                    result = FetchResult(url, url, None, [], None, "", None, None, {}, "robots_blocked", "Blocked by robots.txt")
                    return item, analyze_html(result, robots_allowed=False)
                result = await fetcher(url, client=client)
                return item, analyze_html(result, robots_allowed=True)

            processed = await asyncio.gather(*(process(item) for item in batch))
            for (url, depth, source), snapshot in processed:
                visited.add(url)
                snapshot["discovery_source"] = source
                snapshot["click_depth"] = depth
                snapshots.append(snapshot)
                if depth >= max_depth:
                    continue
                for target in snapshot.pop("internal_links", []):
                    if target not in queued and target not in visited and len(queued) < max_urls * 4:
                        queued.add(target)
                        queue.append((target, depth + 1, "internal_link"))

    return {
        "seed_url": seed,
        "robots_url": robots_url,
        "robots_status": robots_result.status_code,
        "sitemaps": sorted(checked_sitemaps),
        "discovered": len(queued),
        "snapshots": snapshots,
    }
