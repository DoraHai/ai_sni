"""SEM-only landing-page fetcher with bounded, DNS-pinned public HTTP."""

import httpx
from bs4 import BeautifulSoup

from app.security.public_http import PublicHttpError, fetch_public_url, normalize_public_url
from app.urlwords import (
    FETCH_TIMEOUT,
    MAX_CONTENT_BYTES,
    UA,
    UrlFetchError,
    extract_words,
)


def validate_url(url: str) -> str:
    """Validate an SEM landing-page URL before the asynchronous DNS check."""
    value = url.strip()
    try:
        normalize_public_url(value)
    except PublicHttpError as exc:
        raise UrlFetchError(str(exc)) from exc
    return value


async def fetch_page_text(url: str) -> tuple[str, str]:
    """Fetch and extract SEM landing-page text without changing GEO fetch behavior."""
    url = validate_url(url)
    try:
        response = await fetch_public_url(
            url,
            timeout=FETCH_TIMEOUT,
            max_response_bytes=MAX_CONTENT_BYTES,
            headers={"User-Agent": UA},
        )
    except (PublicHttpError, httpx.HTTPError) as exc:
        raise UrlFetchError(f"抓取失败 {url}: {exc}") from exc
    if response.status_code != 200:
        raise UrlFetchError(f"抓取失败 {url}: HTTP {response.status_code}")

    soup = BeautifulSoup(response.body, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "iframe"]):
        tag.decompose()

    title = (soup.title.get_text(strip=True) if soup.title else "") or ""
    meta_parts = []
    for name in ("keywords", "description"):
        meta = soup.find("meta", attrs={"name": name})
        if meta and meta.get("content"):
            meta_parts.append(meta["content"])
    headings = " ".join(
        heading.get_text(" ", strip=True) for heading in soup.find_all(["h1", "h2", "h3"])
    )
    body = soup.get_text(" ", strip=True)
    text = " ".join([title] * 3 + meta_parts * 2 + [headings] * 2 + [body])
    return title, text


__all__ = ["UrlFetchError", "extract_words", "fetch_page_text", "validate_url"]
