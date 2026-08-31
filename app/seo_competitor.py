"""Bounded manual competitor collection and SERP comparison helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
import math
import time
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from app.seo_crawler import (
    USER_AGENT,
    FetchResult,
    SeoCrawlError,
    analyze_html,
    fetch_url,
    normalize_crawl_url,
    pinned_async_client,
)
from app.seo_serp import domain_matches


COMPETITOR_MANUAL_COOLDOWN_SECONDS = 60 * 60
COMPETITOR_MAX_PAGES_PER_RUN = 10
COMPETITOR_FETCH_CONCURRENCY = 5
COMPETITOR_FETCH_TIMEOUT_SECONDS = 8.0
COMPETITOR_TOTAL_TIMEOUT_SECONDS = 25.0

_SKIPPED_SUFFIXES = {
    ".7z",
    ".avi",
    ".css",
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".rss",
    ".svg",
    ".tar",
    ".webp",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}


class CompetitorCollectionError(RuntimeError):
    """Safe failure exposed by the manual collection endpoint."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        error_type: str | None = None,
        status_code: int | None = None,
        timeout_phase: str | None = None,
        elapsed_ms: int | None = None,
        response_status: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.error_type = error_type
        self.status_code = status_code
        self.timeout_phase = timeout_phase
        self.elapsed_ms = elapsed_ms
        self.response_status = response_status


@dataclass(frozen=True)
class CompetitorContentPage:
    url: str
    title: str | None


@dataclass(frozen=True)
class CompetitorContentCollection:
    pages: list[CompetitorContentPage]
    attempted: int
    failed: int


def competitor_retry_after(
    last_checked_at: datetime | None,
    *,
    now: datetime | None = None,
) -> int:
    """Return the remaining manual-collection cooldown in whole seconds."""
    if last_checked_at is None:
        return 0
    current = now or datetime.utcnow()
    elapsed = (current - last_checked_at).total_seconds()
    return max(0, math.ceil(COMPETITOR_MANUAL_COOLDOWN_SECONDS - elapsed))


def _content_url(value: str) -> str:
    normalized = normalize_crawl_url(value)
    parsed = urlparse(normalized)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _is_content_candidate(value: str, competitor_domain: str) -> bool:
    try:
        normalized = _content_url(value)
    except (SeoCrawlError, ValueError):
        return False
    parsed = urlparse(normalized)
    if not domain_matches(parsed.hostname or "", competitor_domain):
        return False
    return PurePosixPath(parsed.path.lower()).suffix not in _SKIPPED_SUFFIXES


def _candidate_urls(home: FetchResult, competitor_domain: str, max_pages: int) -> list[str]:
    soup = BeautifulSoup(home.body, "html.parser")
    candidates = [home.final_url]
    for node in soup.select("a[href]"):
        raw_href = str(node.get("href") or "").strip()
        if raw_href and not raw_href.startswith(("mailto:", "tel:", "javascript:")):
            candidates.append(urljoin(home.final_url, raw_href))
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not _is_content_candidate(candidate, competitor_domain):
            continue
        normalized = _content_url(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
        if len(unique) >= max_pages:
            break
    return unique


def _homepage_error(
    result: FetchResult,
    *,
    timeout_phase: str | None = None,
) -> CompetitorCollectionError:
    error_type = result.error_type or "empty_response"
    if error_type == "timeout":
        code, message, response_status = "homepage_timeout", "竞品网站响应较慢，请稍后重试", 504
    elif error_type == "tls_error":
        code, message, response_status = "homepage_tls_error", "竞品网站安全连接失败，请核对域名或证书配置", 502
    elif error_type in {"connection_error", "dns_error"}:
        code, message, response_status = "homepage_connection_error", "竞品网站暂时无法连接，请稍后重试", 502
    elif error_type == "blocked_address":
        code, message, response_status = "homepage_blocked_address", "竞品网站地址不符合公网采集要求", 400
    elif error_type == "http_4xx" and result.status_code in {401, 403, 429}:
        code, message, response_status = "homepage_access_denied", "竞品网站拒绝自动访问，请使用“记录动态”人工登记", 424
    elif error_type == "http_4xx":
        code, message, response_status = "homepage_http_4xx", "竞品网站拒绝了本次访问，请核对竞品域名", 424
    elif error_type == "http_5xx":
        code, message, response_status = "homepage_http_5xx", "竞品网站服务暂时异常，请稍后重试", 502
    elif error_type == "non_html":
        code, message, response_status = "homepage_unsupported_content", "竞品网站首页未返回可采集的 HTML 内容", 422
    else:
        code, message, response_status = "homepage_unavailable", "竞品网站暂时无法访问，请稍后重试", 502
    return CompetitorCollectionError(
        code,
        message,
        error_type=error_type,
        status_code=result.status_code,
        timeout_phase=timeout_phase if error_type == "timeout" else None,
        elapsed_ms=result.response_time_ms,
        response_status=response_status,
    )


async def collect_competitor_content(
    competitor_domain: str,
    *,
    max_pages: int = 10,
    fetcher: Callable[..., Awaitable[FetchResult]] = fetch_url,
) -> CompetitorContentCollection:
    """Fetch a competitor homepage and a bounded set of same-domain HTML pages."""
    max_pages = max(1, min(int(max_pages), COMPETITOR_MAX_PAGES_PER_RUN))
    homepage = f"https://{competitor_domain.strip().lower().rstrip('.')}/"
    started = time.perf_counter()

    async def run_collection() -> CompetitorContentCollection:
        limits = httpx.Limits(
            max_connections=COMPETITOR_FETCH_CONCURRENCY,
            max_keepalive_connections=COMPETITOR_FETCH_CONCURRENCY,
        )
        async with pinned_async_client(
            timeout=COMPETITOR_FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
            limits=limits,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xml,text/xml;q=0.9,text/plain;q=0.8",
            },
        ) as client:
            async def fetch(candidate: str) -> FetchResult:
                return await fetcher(candidate, client=client)

            home = await fetch(homepage)
            homepage_phase = "homepage_primary"
            if (home.error_type or not home.body) and not competitor_domain.startswith("www."):
                home = await fetch(f"https://www.{competitor_domain.strip().lower().rstrip('.')}/")
                homepage_phase = "homepage_www_fallback"
            if home.error_type or not home.body:
                raise _homepage_error(home, timeout_phase=homepage_phase)
            if not domain_matches(urlparse(home.final_url).hostname or "", competitor_domain):
                raise CompetitorCollectionError(
                    "cross_domain_redirect",
                    "竞品网站跳转到了未登记域名，请先核对竞品域名",
                )

            candidates = _candidate_urls(home, competitor_domain, max_pages)
            if not candidates:
                raise CompetitorCollectionError(
                    "no_content_pages",
                    "竞品网站没有返回可采集的公开页面",
                )

            semaphore = asyncio.Semaphore(COMPETITOR_FETCH_CONCURRENCY)

            async def inspect(candidate: str) -> CompetitorContentPage | None:
                result = home if _content_url(home.final_url) == candidate else None
                if result is None:
                    async with semaphore:
                        result = await fetch(candidate)
                if result.error_type or not result.body:
                    return None
                if not domain_matches(urlparse(result.final_url).hostname or "", competitor_domain):
                    return None
                analysis = analyze_html(result)
                return CompetitorContentPage(
                    url=_content_url(result.final_url),
                    title=str(analysis.get("title") or "").strip()[:500] or None,
                )

            inspected = await asyncio.gather(*(inspect(candidate) for candidate in candidates))
            pages: list[CompetitorContentPage] = []
            seen_pages: set[str] = set()
            for page in inspected:
                if page is None or page.url in seen_pages:
                    continue
                seen_pages.add(page.url)
                pages.append(page)
            if not pages:
                raise CompetitorCollectionError(
                    "collection_failed",
                    "竞品网站页面采集失败，请稍后重试",
                )
            return CompetitorContentCollection(
                pages=pages,
                attempted=len(candidates),
                failed=len(candidates) - len(pages),
            )

    try:
        return await asyncio.wait_for(
            run_collection(),
            timeout=COMPETITOR_TOTAL_TIMEOUT_SECONDS,
        )
    except CompetitorCollectionError as exc:
        if exc.elapsed_ms is None:
            exc.elapsed_ms = round((time.perf_counter() - started) * 1000)
        raise
    except TimeoutError as exc:
        raise CompetitorCollectionError(
            "collection_timeout",
            "竞品网站响应较慢，本次采集已在安全时限内停止",
            error_type="timeout",
            timeout_phase="collection_total",
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            response_status=504,
        ) from exc


def build_competitor_rank_matrix(
    keyword_ids: Iterable[int],
    competitors: Iterable[Any],
    serp_rows: Iterable[Any],
) -> list[dict[str, Any]]:
    """Build a per-keyword competitor matrix from each keyword's latest SERP batch."""
    rows_by_keyword: dict[int, list[Any]] = {}
    for row in serp_rows:
        rows_by_keyword.setdefault(int(row.keyword_id), []).append(row)

    matrix: list[dict[str, Any]] = []
    competitor_rows = list(competitors)
    for keyword_id in keyword_ids:
        rows = rows_by_keyword.get(int(keyword_id), [])
        captured_at = max((row.captured_at for row in rows), default=None)
        rankings: dict[str, dict[str, Any]] = {}
        for competitor in competitor_rows:
            matches = [
                row
                for row in rows
                if row.domain and domain_matches(row.domain, competitor.domain)
            ]
            best = min(matches, key=lambda row: row.rank) if matches else None
            rankings[str(competitor.id)] = {
                "state": (
                    "ranked"
                    if best is not None
                    else "outside_top50"
                    if rows
                    else "not_collected"
                ),
                "rank": None if best is None else int(best.rank),
                "domain": None if best is None else best.domain,
            }
        matrix.append(
            {
                "keyword_id": int(keyword_id),
                "captured_at": captured_at,
                "rankings": rankings,
            }
        )
    return matrix
