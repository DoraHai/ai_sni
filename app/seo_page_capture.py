"""Opt-in SEO page screenshots. Call only after checking tenant/site ownership.

Chromium loads documents itself using a public-IP pinned host resolver. Unmapped
hosts fail DNS; assets on them use the crawler's pinned transport.
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
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PNG = b"\x89PNG\r\n\x1a\n"
_REDIRECT = {301, 302, 303, 307, 308}
_RETRYABLE = {429, 503}
_MAX_SUBRESOURCE_RETRIES = 2
_SECOND_LEVEL_SUFFIXES = frozenset({
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn", "co.uk",
    "org.uk", "gov.uk", "ac.uk", "com.hk", "net.hk", "org.hk", "com.au",
    "net.au", "org.au", "co.jp", "com.tw",
})
_VALIDATION_HOSTS = frozenset({"wappass.baidu.com"})
_VALIDATION_PATH = re.compile(r"/(?:captcha|challenge|verify|verification|security-check)(?:/|$)", re.I)
_CAPTCHA_MARKERS = ("安全验证", "人机验证", "滑动验证", "验证码", "captcha", "verify you are human", "verification required", "cloudflare challenge")
_BLOCK_MARKERS = ("40362", "请求存在异常", "网络不给力", "access denied", "temporarily restricted")
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
    warnings: dict = field(default_factory=lambda: _empty_warnings())

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
    if re.search(r"[\x00-\x20\x7f]", url):
        raise CaptureError("blocked_url")
    try:
        parts = urlsplit(url)
        _ = parts.port
        host = parts.hostname
    except ValueError as exc:
        raise CaptureError("blocked_url") from exc
    if parts.scheme not in {"http", "https"} or not host or parts.username is not None or parts.password is not None:
        raise CaptureError("blocked_url")
    plain_host = host.lower().rstrip(".")
    if plain_host == "localhost" or plain_host.endswith((".local", ".internal")):
        raise CaptureError("blocked_address")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise CaptureError("blocked_url") from exc
        if len(ascii_host) > 253 or not all(_DNS_LABEL.fullmatch(label) for label in ascii_host.split(".")):
            # Host resolver rules are command-line syntax. Never interpolate a
            # hostname with spaces, commas, or other rule separators.
            raise CaptureError("blocked_url")
        return
    if not address.is_global:
        raise CaptureError("blocked_address")


async def _public(url: str) -> str:
    _check_url(url)
    try:
        async with pin_public_target(url) as approved_ip:
            return approved_ip
    except SeoCrawlError as exc:
        code = "blocked_address" if any(word in str(exc).lower() for word in ("private", "local", "reserved")) else "dns_error"
        raise CaptureError(code) from exc


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return host.encode("idna").decode("ascii").lower()


def _registrable_domain(url: str) -> str:
    """Conservative eTLD+1 approximation; intentionally does not use live PSL data."""
    host = _host(url)
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        labels = host.split(".")
        count = 3 if ".".join(labels[-2:]) in _SECOND_LEVEL_SUFFIXES else 2
        return ".".join(labels[-count:]) if len(labels) >= count else host


def _blocked_page_code(source_url: str, final_url: str, status: int, info: dict) -> str | None:
    """Inspect URL always; inspect text only on error, short pages, or short titles.

    Long ordinary articles may discuss CAPTCHAs, so their body is never scanned.
    """
    host = _host(final_url)
    path = urlsplit(final_url).path
    if host in _VALIDATION_HOSTS or host.startswith("passport.") or ".passport." in host or _VALIDATION_PATH.search(path):
        return "captcha_page"
    if _registrable_domain(source_url) != _registrable_domain(final_url):
        return "blocked_by_platform"
    title = str(info.get("title") or "").strip().lower()
    body = str(info.get("text") or "").strip().lower()
    challenge = bool(info.get("challenge"))
    inspect = (body if status in {403, 429} or len(body) <= 1200 else "")
    if challenge:
        return "captcha_page"
    if len(title) <= 120 and (len(body) <= 2000 or status in {403, 429}) and any(marker in title for marker in _CAPTCHA_MARKERS):
        return "captcha_page"
    if any(marker in inspect for marker in _CAPTCHA_MARKERS):
        return "captcha_page"
    if len(title) <= 120 and (len(body) <= 2000 or status in {403, 429}) and any(marker in title for marker in _BLOCK_MARKERS):
        return "blocked_by_platform"
    if any(marker in inspect for marker in _BLOCK_MARKERS):
        return "blocked_by_platform"
    return None


def _resolver_rules(hosts: dict[str, str]) -> str:
    # Pin validated DNS answers. DNS rebinding cannot change Chromium's TCP peer.
    rules = [f"MAP {host} {f'[{ip}]' if ':' in ip else ip}" for host, ip in sorted(hosts.items())]
    return ", ".join([*rules, "MAP * ~NOTFOUND"])


def _dimensions(png: bytes) -> tuple[int, int]:
    if len(png) < 24 or not png.startswith(_PNG) or png[12:16] != b"IHDR":
        raise CaptureError("invalid_image")
    return struct.unpack(">II", png[16:24])


def _empty_warnings() -> dict:
    return {"blocked_subresources": 0, "failed_subresources": 0,
            "by_reason": {}, "hosts": [], "samples": []}


def _warning_reason(code: str) -> str:
    if code == "blocked_address":
        return "blocked_private"
    if code == "too_many_requests":
        return "request_limit"
    if code.startswith("blocked_") or code in {
        "response_too_large", "resources_too_large", "too_many_redirects", "invalid_redirect",
    }:
        return "blocked_policy"
    if code in {"fetch_error", "connection_error"}:
        return "network_failed"
    return code


def _retry_delay(value: str | None, attempt: int) -> float:
    # Retry-After HTTP dates are intentionally ignored; only bounded seconds apply.
    if value is not None and re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", value):
        return min(float(value), 2.0)
    return min(0.2 * (2 ** attempt), 2.0)


@dataclass
class _CaptureState:
    traffic: dict[str, int] = field(default_factory=lambda: {"requests": 0, "bytes": 0})
    redirect_chain: list[dict[str, str | int]] = field(default_factory=list)
    warnings: dict = field(default_factory=_empty_warnings)
    host_semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    mapped_hosts: dict[str, str] = field(default_factory=dict)
    native_responses: list = field(default_factory=list)
    native_tasks: list[asyncio.Task] = field(default_factory=list)
    native_request_ids: set[int] = field(default_factory=set)
    fatal_error: CaptureError | None = None

    def warn(self, code: str, url: str | None = None) -> None:
        reason = _warning_reason(code)
        category = "blocked_subresources" if reason in {
            "blocked_private", "blocked_policy", "request_limit",
        } else "failed_subresources"
        self.warnings[category] += 1
        reasons = self.warnings["by_reason"]
        reasons[reason] = reasons.get(reason, 0) + 1
        if url:
            try:
                host = urlsplit(url).hostname
            except ValueError:
                host = None
            if host and len(host) <= 253:
                host = host.lower().rstrip(".")
                hosts = self.warnings["hosts"]
                if host not in hosts and len(hosts) < 10:
                    hosts.append(host)
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

    async def _fetch(self, url: str, headers: dict[str, str], state: _CaptureState
                     ) -> tuple[str, int, dict[str, str], bytes]:
        settings = self.settings
        current = url
        for redirects in range(settings.seo_page_capture_max_redirects + 1):
            _check_url(current)
            host = urlsplit(current).hostname or ""
            semaphore = state.host_semaphores.setdefault(
                host.lower().rstrip("."), asyncio.Semaphore(settings.seo_page_capture_per_host_concurrency))
            for attempt in range(_MAX_SUBRESOURCE_RETRIES + 1):
                retry_delay = None
                try:
                    await semaphore.acquire()
                    try:
                        state.traffic["requests"] += 1
                        if state.traffic["requests"] > settings.seo_page_capture_max_requests:
                            raise CaptureError("too_many_requests", current)
                        async with pin_public_target(current):
                            # A fresh pool prevents a connection pinned on an earlier DNS result
                            # from being reused after this request's validation.
                            async with pinned_async_client(timeout=settings.seo_page_capture_timeout_seconds,
                                                           follow_redirects=False) as client:
                                async with client.stream("GET", current, headers=headers) as response:
                                    status = response.status_code
                                    if status in _REDIRECT:
                                        location = response.headers.get("location")
                                        if not location:
                                            raise CaptureError("invalid_redirect", current, status)
                                        target = urljoin(current, location)
                                        await _public(target)
                                        if redirects >= settings.seo_page_capture_max_redirects:
                                            raise CaptureError("too_many_redirects", current, status)
                                        current = target
                                        break
                                    if status in _RETRYABLE:
                                        if attempt == _MAX_SUBRESOURCE_RETRIES:
                                            raise CaptureError("rate_limited", current, status)
                                        retry_delay = _retry_delay(response.headers.get("retry-after"), attempt)
                                    elif status >= 400:
                                        raise CaptureError("http_error", current, status)
                                    else:
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
                    finally:
                        semaphore.release()
                except CaptureError:
                    raise
                except Exception as exc:
                    raise CaptureError(_fetch_error(exc), current) from exc
                if retry_delay is not None:
                    await asyncio.sleep(retry_delay)
        raise CaptureError("too_many_redirects", current)

    async def _serve(self, route, state: _CaptureState) -> None:
        request = None
        try:
            request = route.request
            _check_url(request.url)
            if request.method != "GET":
                raise CaptureError("blocked_method")
            if request.is_navigation_request():
                if _host(request.url) not in state.mapped_hosts:
                    raise CaptureError("blocked_address", request.url)
                self._count_request(state, request.url)
                state.native_request_ids.add(id(request))
                await route.continue_()
                return
            if state.traffic["bytes"] >= self.settings.seo_page_capture_max_total_bytes:
                raise CaptureError("resources_too_large")
            if _host(request.url) in state.mapped_hosts:
                self._count_request(state, request.url)
                state.native_request_ids.add(id(request))
                await route.continue_()
                return
            headers = {name: value for name, value in request.headers.items()
                       if name.lower() in {"accept", "accept-language", "user-agent", "range"}}
            _final, status, safe_headers, body = await self._fetch(request.url, headers, state)
            await route.fulfill(status=status, headers=safe_headers, body=body)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _target_closed(exc):
                return
            code = exc.code if isinstance(exc, CaptureError) else _fetch_error(exc)
            if request is not None and request.is_navigation_request() and state.fatal_error is None:
                state.fatal_error = exc if isinstance(exc, CaptureError) else CaptureError(code, request.url)
            state.warn(code, request.url if request is not None else None)
            try:
                await route.abort()
            except Exception as closed:
                if not _target_closed(closed):
                    raise

    def _count_request(self, state: _CaptureState, url: str) -> None:
        state.traffic["requests"] += 1
        if state.traffic["requests"] > self.settings.seo_page_capture_max_requests:
            raise CaptureError("too_many_requests", url)

    async def _account_native_response(self, response, state: _CaptureState) -> None:
        # Playwright exposes completed bodies rather than a bounded stream. The
        # header is checked first; an absent/wrong length is only best effort.
        try:
            length = response.headers.get("content-length", "")
            if length.isdigit() and int(length) > self.settings.seo_page_capture_max_response_bytes:
                raise CaptureError("response_too_large", response.url, response.status)
            body = await response.body()
            size = len(body)
            state.traffic["bytes"] += size
            if size > self.settings.seo_page_capture_max_response_bytes:
                raise CaptureError("response_too_large", response.url, response.status)
            if state.traffic["bytes"] > self.settings.seo_page_capture_max_total_bytes:
                raise CaptureError("resources_too_large", response.url, response.status)
        except CaptureError as exc:
            if response.request.is_navigation_request() or exc.code == "resources_too_large":
                state.fatal_error = exc
            else:
                state.warn(exc.code, response.url)
        except Exception:
            # A navigation can be interrupted by a restart. Its response is
            # still captured in the redirect chain below.
            pass

    async def _drain_native_tasks(self, state: _CaptureState) -> None:
        while state.native_tasks:
            tasks, state.native_tasks = state.native_tasks, []
            await asyncio.gather(*tasks)
        if state.fatal_error is not None:
            raise state.fatal_error

    async def _render(self, url: str, state: _CaptureState) -> tuple[str, int, bytes, int, int]:
        _check_url(url)
        state.mapped_hosts[_host(url)] = await _public(url)
        channel = self.settings.seo_page_capture_browser_channel
        executable_path = self.settings.seo_page_capture_executable_path
        if channel and channel not in _BROWSER_CHANNELS:
            raise CaptureError("invalid_browser_channel")
        if executable_path and not Path(executable_path).is_file():
            raise CaptureError("browser_executable_missing")
        launch_options = {"headless": True}
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
            current = url
            while True:
                # Chrome reads these rules at process launch. A newly approved
                # redirect host therefore needs a new browser process.
                options = {**launch_options, "args": [
                    f"--host-resolver-rules={_resolver_rules(state.mapped_hosts)}",
                    "--no-proxy-server", "--disable-quic",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                ]}
                try:
                    browser = await playwright.chromium.launch(**options)
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
                        responses = []
                        failed_navigations = []

                        def on_response(item):
                            if (_host(item.url) in state.mapped_hosts and
                                    id(item.request) not in state.native_request_ids):
                                try:
                                    self._count_request(state, item.url)
                                except CaptureError as exc:
                                    state.fatal_error = exc
                                state.native_request_ids.add(id(item.request))
                            if item.request.is_navigation_request() and item.request.frame == page.main_frame:
                                responses.append(item)
                                state.redirect_chain.append({"url": item.url, "status_code": item.status})
                            if (item.request.is_navigation_request() or
                                    id(item.request) in state.native_request_ids):
                                state.native_tasks.append(asyncio.create_task(
                                    self._account_native_response(item, state)))

                        page.on("response", on_response)

                        def on_requestfailed(request):
                            if request.is_navigation_request() and request.frame == page.main_frame:
                                failed_navigations.append(request.url)

                        page.on("requestfailed", on_requestfailed)
                        navigation_error = None
                        try:
                            response = await page.goto(current, wait_until="domcontentloaded",
                                                       timeout=self.settings.seo_page_capture_timeout_seconds * 1000)
                        except Exception as exc:
                            response, navigation_error = None, exc
                        await self._drain_native_tasks(state)
                        last = responses[-1] if responses else None
                        if len(state.redirect_chain) - 1 > self.settings.seo_page_capture_max_redirects:
                            raise CaptureError("too_many_redirects", last.url if last else current,
                                               last.status if last else None)
                        # Playwright routes do not see redirect requests. DNS
                        # fails on an unmapped target, but the 3xx Location is
                        # observable; validate and pin it before retrying.
                        target = None
                        if response is None and last is not None and last.status in _REDIRECT:
                            location = last.headers.get("location")
                            if not location:
                                raise CaptureError("invalid_redirect", last.url, last.status)
                            target = urljoin(last.url, location)
                        elif response is None and failed_navigations:
                            target = failed_navigations[-1]
                        if target is not None:
                            if len(state.redirect_chain) > self.settings.seo_page_capture_max_redirects:
                                raise CaptureError("too_many_redirects", last.url if last else current,
                                                   last.status if last else None)
                            _check_url(target)
                            if _host(target) not in state.mapped_hosts:
                                state.mapped_hosts[_host(target)] = await _public(target)
                                current = target
                                continue
                        if response is None:
                            raise CaptureError(_fetch_error(navigation_error) if navigation_error else "empty_response", current)
                        final_url, http_status = page.url, response.status
                        _check_url(final_url)
                        if _host(final_url) not in state.mapped_hosts:
                            raise CaptureError("blocked_address", final_url, http_status)
                        await self._settle(page)
                        await self._drain_native_tasks(state)
                        if failed_navigations and _host(failed_navigations[-1]) not in state.mapped_hosts:
                            target = failed_navigations[-1]
                            if len(state.redirect_chain) > self.settings.seo_page_capture_max_redirects:
                                raise CaptureError("too_many_redirects", final_url, http_status)
                            state.mapped_hosts[_host(target)] = await _public(target)
                            current = target
                            continue
                        final_url = page.url
                        http_status = responses[-1].status if responses else response.status
                        _check_url(final_url)
                        if _host(final_url) not in state.mapped_hosts:
                            raise CaptureError("blocked_address", final_url, http_status)
                        if len(state.redirect_chain) - 1 > self.settings.seo_page_capture_max_redirects:
                            raise CaptureError("too_many_redirects", final_url, http_status)
                        info = await page.evaluate("""() => ({
                            height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0),
                            title: document.title || '',
                            text: (document.body?.innerText || '').trim(),
                            password: !!document.querySelector('input[type=password]'),
                            challenge: !!document.querySelector('[id*=captcha i], [class*=captcha i], [id*=challenge i], [class*=challenge i]')
                        })""")
                        blocked = _blocked_page_code(url, final_url, http_status, info)
                        if blocked:
                            raise CaptureError(blocked, final_url, http_status)
                        if http_status >= 400:
                            raise CaptureError("http_error", final_url, http_status)
                        if info["password"]:
                            raise CaptureError("login_wall", final_url, http_status)
                        if not info["text"]:
                            raise CaptureError("blank_page", final_url, http_status)
                        height = max(self.settings.seo_page_capture_viewport_height, int(info["height"]))
                        if (height > self.settings.seo_page_capture_max_height or
                                height * self.settings.seo_page_capture_viewport_width > self.settings.seo_page_capture_max_pixels):
                            raise CaptureError("page_too_large", final_url, http_status)
                        png = await page.screenshot(type="png", full_page=True, animations="disabled")
                        await self._drain_native_tasks(state)
                        if page.url != final_url:
                            changed = _blocked_page_code(url, page.url, http_status, info)
                            raise CaptureError(changed or "unexpected_navigation", page.url, http_status)
                        if len(png) > self.settings.seo_page_capture_max_image_bytes:
                            raise CaptureError("image_too_large")
                        width, image_height = _dimensions(png)
                        if width * image_height > self.settings.seo_page_capture_max_pixels:
                            raise CaptureError("image_too_large")
                        return final_url, http_status, png, width, image_height
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
