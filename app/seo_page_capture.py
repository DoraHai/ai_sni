"""Opt-in SEO page screenshots. Call only after checking tenant/site ownership.

Chromium uses a deliberately unavailable proxy. Every HTTP request is fulfilled
through the crawler's pinned public-IP transport, including redirects and assets.
The SEO deployment should additionally deny direct browser network egress.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import struct
import uuid
from urllib.parse import urljoin, urlsplit

from app.config import get_settings
from app.seo_crawler import SeoCrawlError, pin_public_target, pinned_async_client

_KEY = re.compile(r"[0-9a-f]{32}\.png\Z")
_PNG = b"\x89PNG\r\n\x1a\n"
_REDIRECT = {301, 302, 303, 307, 308}
_BROWSER_CHANNELS = frozenset({
    "chrome", "chrome-beta", "chrome-dev", "chrome-canary",
    "msedge", "msedge-beta", "msedge-dev", "msedge-canary",
})


class CaptureError(Exception):
    def __init__(self, code: str, final_url: str | None = None, http_status: int | None = None):
        super().__init__(code)
        self.code, self.final_url, self.http_status = code, final_url, http_status


@dataclass(frozen=True)
class CaptureResult:
    tenant_id: int
    site_id: int
    relation_type: str
    relation_id: int
    source_url: str
    captured_at: datetime
    status: str
    viewport_width: int
    viewport_height: int
    final_url: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    sha256: str | None = None
    storage_key: str | None = None
    redirect_chain: list[dict[str, str | int]] = field(default_factory=list)
    warnings: dict = field(default_factory=lambda: {
        "blocked_subresources": 0, "failed_subresources": 0, "samples": [],
    })

    @property
    def success(self) -> bool:
        return self.status == "succeeded"


def capture_storage_path(directory: str, key: str) -> Path:
    """Only generated flat keys may resolve inside a persistent evidence root."""
    root = Path(directory)
    if not root.is_absolute() or not _KEY.fullmatch(key):
        raise ValueError("invalid capture storage root or key")
    root = root.resolve()
    source = Path(__file__).resolve().parents[1]
    if root == source or source in root.parents or "releases" in root.parts:
        raise ValueError("capture storage must be outside source and release directories")
    path = (root / key).resolve()
    if path.parent != root:
        raise ValueError("capture storage path escaped its root")
    return path


def _check_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        _ = parts.port
        host = parts.hostname
    except ValueError as exc:
        raise CaptureError("blocked_url") from exc
    if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
        raise CaptureError("blocked_url")
    if host.lower().rstrip(".") == "localhost" or host.lower().endswith((".local", ".internal")):
        raise CaptureError("blocked_address")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise CaptureError("blocked_address")


async def _public(url: str) -> None:
    _check_url(url)
    try:
        async with pin_public_target(url):
            pass
    except SeoCrawlError as exc:
        code = "blocked_address" if "private" in str(exc).lower() or "local" in str(exc).lower() else "dns_error"
        raise CaptureError(code) from exc


def _dimensions(png: bytes) -> tuple[int, int]:
    if len(png) < 24 or not png.startswith(_PNG) or png[12:16] != b"IHDR":
        raise CaptureError("invalid_image")
    return struct.unpack(">II", png[16:24])


@dataclass
class _CaptureState:
    traffic: dict[str, int] = field(default_factory=lambda: {"requests": 0, "bytes": 0})
    redirect_chain: list[dict[str, str | int]] = field(default_factory=list)
    warnings: dict = field(default_factory=lambda: {
        "blocked_subresources": 0, "failed_subresources": 0, "samples": [],
    })
    document_url: str | None = None
    document_status: int | None = None
    document_headers: dict[str, str] = field(default_factory=dict)
    document_body: bytes = b""
    document_pending: bool = True

    def warn(self, code: str) -> None:
        category = "blocked_subresources" if code.startswith(("blocked_", "too_many_")) or code in {
            "response_too_large", "resources_too_large",
        } else "failed_subresources"
        self.warnings[category] += 1
        if len(self.warnings["samples"]) < 5:
            self.warnings["samples"].append(code)


def _fetch_error(exc: Exception) -> str:
    if isinstance(exc, SeoCrawlError):
        return "blocked_address" if "private" in str(exc).lower() or "local" in str(exc).lower() else "dns_error"
    return "timeout" if "timeout" in type(exc).__name__.lower() else "fetch_error"


def _target_closed(exc: Exception) -> bool:
    return ("TargetClosed" in type(exc).__name__ or
            "Target page, context or browser has been closed" in str(exc))


class PageCaptureService:
    def __init__(self, settings=None, *, playwright_factory=None):
        self.settings = settings if settings is not None else get_settings()
        self.playwright_factory = playwright_factory
        self._semaphore = asyncio.Semaphore(self.settings.seo_page_capture_concurrency)

    async def _fetch(self, url: str, headers: dict[str, str], state: _CaptureState,
                     *, document: bool) -> tuple[str, int, dict[str, str], bytes]:
        settings = self.settings
        current = url
        for redirects in range(settings.seo_page_capture_max_redirects + 1):
            _check_url(current)
            state.traffic["requests"] += 1
            if state.traffic["requests"] > settings.seo_page_capture_max_requests:
                raise CaptureError("too_many_requests")
            try:
                async with pin_public_target(current):
                    # One client per hop prevents cookie sharing and implicit redirects.
                    async with pinned_async_client(timeout=settings.seo_page_capture_timeout_seconds,
                                                   follow_redirects=False) as client:
                        async with client.stream("GET", current, headers=headers) as response:
                            status = response.status_code
                            if document:
                                state.redirect_chain.append({"url": current, "status_code": status})
                            if status in _REDIRECT:
                                location = response.headers.get("location")
                                if not location:
                                    raise CaptureError("invalid_redirect", current, status)
                                target = urljoin(current, location)
                                await _public(target)
                                if redirects >= settings.seo_page_capture_max_redirects:
                                    raise CaptureError("too_many_redirects", current, status)
                                current = target
                                continue
                            if not document and status >= 400:
                                raise CaptureError("http_error", current, status)
                            length = response.headers.get("content-length", "0")
                            if length.isdigit() and int(length) > settings.seo_page_capture_max_response_bytes:
                                raise CaptureError("response_too_large", current, status)
                            chunks, size = [], 0
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                state.traffic["bytes"] += len(chunk)
                                if size > settings.seo_page_capture_max_response_bytes:
                                    raise CaptureError("response_too_large", current, status)
                                if state.traffic["bytes"] > settings.seo_page_capture_max_total_bytes:
                                    raise CaptureError("resources_too_large", current, status)
                                chunks.append(chunk)
                            safe_headers = {name: value for name, value in response.headers.items()
                                            if name.lower() in {"content-type", "cache-control"}}
                            return current, status, safe_headers, b"".join(chunks)
            except CaptureError:
                raise
            except Exception as exc:
                raise CaptureError(_fetch_error(exc), current) from exc
        raise CaptureError("too_many_redirects", current)

    async def _serve(self, route, state: _CaptureState) -> None:
        try:
            request = route.request
            if state.document_pending and request.url == state.document_url:
                state.document_pending = False
                await route.fulfill(status=state.document_status, headers=state.document_headers,
                                    body=state.document_body)
                return
            if request.method != "GET":
                raise CaptureError("blocked_method")
            if state.traffic["bytes"] >= self.settings.seo_page_capture_max_total_bytes:
                raise CaptureError("resources_too_large")
            headers = {name: value for name, value in request.headers.items()
                       if name.lower() in {"accept", "accept-language", "user-agent", "range"}}
            _final, status, safe_headers, body = await self._fetch(request.url, headers, state, document=False)
            await route.fulfill(status=status, headers=safe_headers, body=body)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _target_closed(exc):
                return
            code = exc.code if isinstance(exc, CaptureError) else _fetch_error(exc)
            state.warn(code)
            try:
                await route.abort()
            except Exception as closed:
                if not _target_closed(closed):
                    raise

    async def _render(self, url: str, state: _CaptureState) -> tuple[str, int, bytes, int, int]:
        await _public(url)
        channel = self.settings.seo_page_capture_browser_channel
        executable_path = self.settings.seo_page_capture_executable_path
        if channel and channel not in _BROWSER_CHANNELS:
            raise CaptureError("invalid_browser_channel")
        if executable_path and not Path(executable_path).is_file():
            raise CaptureError("browser_executable_missing")
        launch_options = {"headless": True, "proxy": {"server": "http://127.0.0.1:9"}}
        if executable_path:
            launch_options["executable_path"] = executable_path
        elif channel:
            launch_options["channel"] = channel
        factory = self.playwright_factory
        if factory is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise CaptureError("playwright_not_installed") from exc
            factory = async_playwright
        async with factory() as playwright:
            try:
                browser = await playwright.chromium.launch(**launch_options)
            except Exception as exc:
                raise CaptureError("chromium_unavailable") from exc
            try:
                context = await browser.new_context(
                    viewport={"width": self.settings.seo_page_capture_viewport_width,
                              "height": self.settings.seo_page_capture_viewport_height},
                    service_workers="block", accept_downloads=False)
                try:
                    await context.route("**/*", lambda route: self._serve(route, state))
                    await context.route_web_socket("**/*", lambda route: route.close())
                    page = await context.new_page()
                    user_agent = await page.evaluate("() => navigator.userAgent")
                    document_headers = {"accept": "text/html,application/xhtml+xml"}
                    if isinstance(user_agent, str):
                        document_headers["user-agent"] = user_agent
                    final_url, http_status, headers, body = await self._fetch(
                        url, document_headers, state, document=True)
                    state.document_url, state.document_status = final_url, http_status
                    state.document_headers, state.document_body = headers, body
                    if http_status >= 400:
                        raise CaptureError("http_error", final_url, http_status)
                    try:
                        response = await page.goto(final_url, wait_until="domcontentloaded",
                                                   timeout=self.settings.seo_page_capture_timeout_seconds * 1000)
                    except Exception as exc:
                        raise CaptureError(_fetch_error(exc), final_url) from exc
                    if response is None:
                        raise CaptureError("empty_response", final_url)
                    if page.url != final_url:
                        raise CaptureError("unexpected_navigation", page.url)
                    if state.document_pending:
                        raise CaptureError("empty_response", final_url)
                    if response.status >= 400:
                        raise CaptureError("http_error", final_url, response.status)
                    await self._settle(page)
                    info = await page.evaluate("""() => ({
                        height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0),
                        text: (document.body?.innerText || '').trim(),
                        password: !!document.querySelector('input[type=password]')
                    })""")
                    if info["password"]:
                        raise CaptureError("login_wall", final_url, response.status)
                    if "验证码" in info["text"] or "captcha" in info["text"].lower():
                        raise CaptureError("captcha", final_url, response.status)
                    if not info["text"]:
                        raise CaptureError("blank_page", final_url, response.status)
                    height = max(self.settings.seo_page_capture_viewport_height, int(info["height"]))
                    if (height > self.settings.seo_page_capture_max_height or
                            height * self.settings.seo_page_capture_viewport_width > self.settings.seo_page_capture_max_pixels):
                        raise CaptureError("page_too_large", final_url, response.status)
                    png = await page.screenshot(type="png", full_page=True, animations="disabled")
                    if len(png) > self.settings.seo_page_capture_max_image_bytes:
                        raise CaptureError("image_too_large")
                    width, image_height = _dimensions(png)
                    if width * image_height > self.settings.seo_page_capture_max_pixels:
                        raise CaptureError("image_too_large")
                    return final_url, response.status, png, width, image_height
                finally:
                    await context.unroute_all(behavior="ignoreErrors")
                    await context.close()
            finally:
                await browser.close()

    async def _settle(self, page) -> None:
        seconds = self.settings.seo_page_capture_settle_seconds
        if not seconds:
            return
        try:
            async with asyncio.timeout(seconds):
                await page.evaluate("""async () => {
                    const step = Math.max(window.innerHeight, 400);
                    const bottom = document.documentElement.scrollHeight;
                    for (let y = 0; y < bottom; y += step) {
                        window.scrollTo(0, y);
                        await new Promise(resolve => setTimeout(resolve, 80));
                    }
                    window.scrollTo(0, bottom);
                    await new Promise(resolve => setTimeout(resolve, 80));
                    window.scrollTo(0, 0);
                    await Promise.all(Array.from(document.images, img => img.complete
                        ? Promise.resolve() : new Promise(resolve => {
                            img.addEventListener('load', resolve, {once: true});
                            img.addEventListener('error', resolve, {once: true});
                        })));
                }""")
        except Exception:
            pass  # A partial lazy-load pass must not discard an otherwise valid page.

    async def capture_page(self, *, tenant_id: int, site_id: int, relation_type: str,
                           relation_id: int, url: str) -> CaptureResult:
        """Return success or a specific failed attempt; never fabricate an image."""
        if min(tenant_id, site_id, relation_id) <= 0 or relation_type not in {"site_page", "publication"}:
            raise ValueError("invalid capture association")
        common = dict(tenant_id=tenant_id, site_id=site_id, relation_type=relation_type,
                      relation_id=relation_id, source_url=url, captured_at=datetime.now(timezone.utc),
                      viewport_width=self.settings.seo_page_capture_viewport_width,
                      viewport_height=self.settings.seo_page_capture_viewport_height)
        if not self.settings.seo_page_capture_enabled:
            return CaptureResult(**common, status="failed", error_code="capture_disabled")
        state = _CaptureState()
        try:
            async with self._semaphore:
                final, status, png, width, height = await asyncio.wait_for(
                    self._render(url, state), timeout=self.settings.seo_page_capture_timeout_seconds)
            key = f"{uuid.uuid4().hex}.png"
            path = capture_storage_path(self.settings.seo_page_capture_storage_dir, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(png)
            except Exception:
                path.unlink(missing_ok=True)
                raise
            return CaptureResult(**common, status="succeeded", final_url=final, http_status=status,
                                 image_width=width, image_height=height, sha256=hashlib.sha256(png).hexdigest(),
                                 storage_key=key, redirect_chain=state.redirect_chain, warnings=state.warnings)
        except CaptureError as exc:
            return CaptureResult(**common, status="failed", error_code=exc.code,
                                 final_url=exc.final_url, http_status=exc.http_status,
                                 redirect_chain=state.redirect_chain, warnings=state.warnings)
        except asyncio.TimeoutError:
            return CaptureResult(**common, status="failed", error_code="timeout",
                                 redirect_chain=state.redirect_chain, warnings=state.warnings)
        except (OSError, ValueError):
            return CaptureResult(**common, status="failed", error_code="storage_error",
                                 redirect_chain=state.redirect_chain, warnings=state.warnings)
        except Exception as exc:
            code = "timeout" if "timeout" in type(exc).__name__.lower() else "browser_error"
            return CaptureResult(**common, status="failed", error_code=code,
                                 redirect_chain=state.redirect_chain, warnings=state.warnings)


async def persist_capture(session, result: CaptureResult):
    """Flush metadata in the caller's transaction; caller checks scope and commits."""
    from app.models.seo_page_capture import SeoPageCapture
    row = SeoPageCapture(**vars(result))
    # `success` is a computed property, not a mapped column.
    session.add(row)
    await session.flush()
    return row
