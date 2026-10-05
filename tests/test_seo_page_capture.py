import asyncio
import hashlib
from pathlib import Path
import struct
from types import SimpleNamespace
from contextlib import asynccontextmanager

import pytest

from app import seo_page_capture as capture


PNG = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 800, 600)


@pytest.fixture(autouse=True)
def fake_network(monkeypatch):
    @asynccontextmanager
    async def pinned(_url):
        yield "93.184.216.34"
    monkeypatch.setattr(capture, "pin_public_target", pinned)
    monkeypatch.setattr(capture, "pinned_async_client", lambda **_: FakeClient(FakeResponse()))
    monkeypatch.setattr(capture, "__file__", "C:/outside/app/seo_page_capture.py")


def settings(tmp_path, **changes):
    values = dict(seo_page_capture_enabled=True, seo_page_capture_storage_dir=str(tmp_path),
                  seo_page_capture_browser_channel="", seo_page_capture_executable_path="",
                  seo_page_capture_concurrency=2, seo_page_capture_timeout_seconds=5,
                  seo_page_capture_viewport_width=800, seo_page_capture_viewport_height=600,
                  seo_page_capture_max_height=12000, seo_page_capture_max_pixels=16_000_000,
                  seo_page_capture_max_response_bytes=1000, seo_page_capture_max_total_bytes=2000,
                  seo_page_capture_max_requests=10, seo_page_capture_max_image_bytes=1000,
                  seo_page_capture_max_redirects=5, seo_page_capture_settle_seconds=0.1,
                  seo_page_capture_per_host_concurrency=4)
    values.update(changes)
    return SimpleNamespace(**values)


class FakePage:
    def __init__(self, context):
        self.context = context
        self.url = "about:blank"
        self.main_frame = object()
        self.listeners = {}

    def on(self, event, callback):
        self.listeners[event] = callback

    async def goto(self, url, **_kwargs):
        route = FakeRoute(url, navigation=True, frame=self.main_frame)
        await self.context.routes[0][1](route)
        if route.aborted:
            raise RuntimeError("navigation aborted")
        assert route.continued and route.fulfilled is None
        while True:
            result = self.context.browser.owner.documents.get(url, (200, {}, b"body"))
            status, headers, body = result
            response = FakeBrowserResponse(url, status, headers, body, self.main_frame, route.request)
            self.listeners["response"](response)
            if status not in capture._REDIRECT:
                self.url = url
                if self.context.browser.owner.failed_navigation:
                    failed = self.context.browser.owner.failed_navigation
                    self.context.browser.owner.failed_navigation = None
                    self.listeners["requestfailed"](FakeRequest(failed, navigation=True, frame=self.main_frame))
                return response
            target = capture.urljoin(url, headers["location"])
            if capture._host(target) not in self.context.browser.owner.mapped_hosts:
                self.listeners["requestfailed"](FakeRequest(target, navigation=True, frame=self.main_frame))
                raise RuntimeError("net::ERR_NAME_NOT_RESOLVED")
            url = target
            route = FakeRoute(url, navigation=True, frame=self.main_frame)

    async def evaluate(self, expression):
        if "navigator.userAgent" in expression:
            return "Mock Chromium"
        return self.context.browser.owner.info

    async def screenshot(self, **_kwargs):
        return PNG


class FakeContext:
    def __init__(self, browser):
        self.browser = browser
        self.routes = []
        self.unrouted = False

    async def route(self, pattern, callback):
        self.routes.append((pattern, callback))

    async def route_web_socket(self, pattern, callback):
        self.routes.append((pattern, callback))

    async def new_page(self):
        return FakePage(self)

    async def unroute_all(self, **kwargs):
        assert kwargs == {"behavior": "ignoreErrors"}
        self.unrouted = True

    async def close(self):
        assert self.unrouted


class FakeBrowser:
    def __init__(self, owner):
        self.owner = owner

    async def new_context(self, **kwargs):
        assert kwargs["service_workers"] == "block"
        return FakeContext(self)

    async def close(self):
        pass


class FakePlaywright:
    chromium = None

    def __init__(self):
        self.chromium = self
        self.documents = {}
        self.info = {"height": 600, "title": "Article", "text": "Visible page", "password": False, "challenge": False}
        self.launches = []
        self.mapped_hosts = set()
        self.failed_navigation = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def launch(self, **kwargs):
        assert "proxy" not in kwargs
        args = kwargs["args"]
        rules = next(arg for arg in args if arg.startswith("--host-resolver-rules="))
        assert "MAP * ~NOTFOUND" in rules
        self.mapped_hosts = {rule.split()[1] for rule in rules.split("=", 1)[1].split(", ")
                             if rule != "MAP * ~NOTFOUND"}
        self.launches.append(kwargs)
        return FakeBrowser(self)

    async def launch_persistent_context(self, *_args, **_kwargs):
        pytest.fail("page capture must use a fresh browser context")


def attempt(service, url="https://example.com/start"):
    return asyncio.run(service.capture_page(tenant_id=1, site_id=2, relation_type="site_page",
                                            relation_id=3, url=url))


def test_success_writes_true_png_metadata_and_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "__file__", "C:/outside/app/seo_page_capture.py")
    fake = FakePlaywright()
    service = capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: fake)
    result = attempt(service)
    assert result.success and result.error_code is None
    assert (result.final_url, result.http_status) == ("https://example.com/start", 200)
    assert result.redirect_chain == [{"url": "https://example.com/start", "status_code": 200}]
    assert (result.image_width, result.image_height) == (800, 600)
    assert result.sha256 == hashlib.sha256(PNG).hexdigest()
    assert capture.capture_storage_path(str(tmp_path), result.storage_key).read_bytes() == PNG
    assert "MAP example.com 93.184.216.34" in fake.launches[0]["args"][0]


@pytest.mark.parametrize("url", ["http://127.0.0.1/a", "http://10.0.0.1/a",
                                   "http://[::1]/", "http://localhost/", "file:///etc/passwd"])
def test_local_and_non_http_urls_rejected_before_browser(tmp_path, url):
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=FakePlaywright), url)
    assert not result.success and result.storage_key is None
    assert result.error_code in {"blocked_address", "blocked_url"}
    assert not list(tmp_path.iterdir())


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"body"):
        self.status_code = status
        self.headers = headers or {"content-type": "text/html"}
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def aiter_bytes(self):
        yield self.body


class FakeClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    def stream(self, method, url, headers):
        assert "cookie" not in headers
        return self.response


class FakeRoute:
    def __init__(self, url, *, navigation=False, frame=None):
        self.request = FakeRequest(url, navigation=navigation, frame=frame)
        self.aborted = False
        self.fulfilled = None
        self.continued = False

    async def abort(self):
        self.aborted = True

    async def fulfill(self, **kwargs):
        self.fulfilled = kwargs

    async def continue_(self):
        self.continued = True


class FakeRequest:
    def __init__(self, url, *, navigation=False, frame=None):
        self.url, self.method, self.headers = url, "GET", {"cookie": "secret", "accept": "*/*"}
        self.navigation, self.frame = navigation, frame

    def is_navigation_request(self):
        return self.navigation


class FakeBrowserResponse:
    def __init__(self, url, status, headers, body, frame, request=None):
        self.url, self.status, self.headers, self._body = url, status, headers, body
        self.request = request or FakeRequest(url, navigation=True, frame=frame)

    async def body(self):
        return self._body


def response_map(monkeypatch, responses):
    class MappingClient(FakeClient):
        def stream(self, method, url, headers):
            assert method == "GET" and "cookie" not in headers
            return responses[url]
    monkeypatch.setattr(capture, "pinned_async_client", lambda **_: MappingClient(None))


def test_document_redirects_use_final_browser_url_and_record_chain(tmp_path, monkeypatch):
    fake = FakePlaywright()
    fake.documents = {
        "https://example.com/start": (301, {"location": "/de/home"}, b""),
        "https://example.com/de/home": (307, {"location": "home.jsp"}, b""),
    }
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: fake))
    assert result.success and result.final_url == "https://example.com/de/home.jsp"
    assert result.redirect_chain == [
        {"url": "https://example.com/start", "status_code": 301},
        {"url": "https://example.com/de/home", "status_code": 307},
        {"url": "https://example.com/de/home.jsp", "status_code": 200},
    ]


def test_document_redirect_limit(tmp_path, monkeypatch):
    fake = FakePlaywright()
    fake.documents = {"https://example.com/start": (301, {"location": "/next"}, b"")}
    result = attempt(capture.PageCaptureService(settings(
        tmp_path, seo_page_capture_max_redirects=0), playwright_factory=lambda: fake))
    assert result.error_code == "too_many_redirects"
    assert result.redirect_chain[0] == {"url": "https://example.com/start", "status_code": 301}


def test_subresource_block_does_not_fail_screenshot(tmp_path, monkeypatch):
    class AssetPage(FakePage):
        async def goto(self, url, **kwargs):
            response = await super().goto(url, **kwargs)
            asset = FakeRoute("http://127.0.0.1/private.png")
            await self.context.routes[0][1](asset)
            assert asset.aborted
            return response
    class AssetContext(FakeContext):
        async def new_page(self):
            return AssetPage(self)
    class AssetBrowser(FakeBrowser):
        async def new_context(self, **kwargs):
            return AssetContext(self)
    class AssetPlaywright(FakePlaywright):
        async def launch(self, **kwargs):
            await super().launch(**kwargs)
            return AssetBrowser(self)
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=AssetPlaywright))
    assert result.success
    assert result.warnings == {
        "blocked_subresources": 1, "failed_subresources": 0,
        "by_reason": {"blocked_private": 1}, "hosts": ["127.0.0.1"],
        "samples": ["blocked_address"],
    }


def test_main_document_fetch_failure_still_fails(tmp_path, monkeypatch):
    class FailedPage(FakePage):
        async def goto(self, *_args, **_kwargs):
            raise TimeoutError("main document timed out")
    class FailedContext(FakeContext):
        async def new_page(self):
            return FailedPage(self)
    class FailedBrowser(FakeBrowser):
        async def new_context(self, **_kwargs):
            return FailedContext(self)
    class FailedPlaywright(FakePlaywright):
        async def launch(self, **kwargs):
            await super().launch(**kwargs)
            return FailedBrowser(self)
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=FailedPlaywright))
    assert result.error_code == "timeout" and result.storage_key is None


@pytest.mark.parametrize("status, headers, code", [
    (503, {}, "http_error"),
    (200, {"content-length": "1001"}, "response_too_large"),
])
def test_main_document_status_and_size_fail(tmp_path, monkeypatch, status, headers, code):
    fake = FakePlaywright()
    fake.documents = {"https://example.com/start": (status, headers, b"body")}
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: fake))
    assert result.error_code == code and result.storage_key is None
    assert result.redirect_chain[0]["status_code"] == status


def test_subresource_http_error_is_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "pinned_async_client", lambda **_: FakeClient(FakeResponse(404)))
    state = capture._CaptureState()
    route = FakeRoute("https://example.com/missing.png")
    asyncio.run(capture.PageCaptureService(settings(tmp_path))._serve(route, state))
    assert route.aborted and state.warnings["failed_subresources"] == 1
    assert state.warnings["samples"] == ["http_error"]


def test_settle_calls_scroll_and_ignores_failure(tmp_path, monkeypatch):
    calls = []
    class SettlingPage(FakePage):
        async def evaluate(self, expression):
            calls.append(expression)
            if "window.scrollTo" in expression:
                raise RuntimeError("scroll script failed")
            return await super().evaluate(expression)
    class SettlingContext(FakeContext):
        async def new_page(self):
            return SettlingPage(self)
    class SettlingBrowser(FakeBrowser):
        async def new_context(self, **kwargs):
            return SettlingContext(self)
    class SettlingPlaywright(FakePlaywright):
        async def launch(self, **kwargs):
            await super().launch(**kwargs)
            return SettlingBrowser(self)
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=SettlingPlaywright))
    assert result.success and any("window.scrollTo" in call and "img.complete" in call for call in calls)


def test_closed_target_during_route_is_quiet(tmp_path):
    class TargetClosedError(Exception):
        pass
    class ClosedRoute(FakeRoute):
        async def abort(self):
            raise TargetClosedError()
    state = capture._CaptureState()
    asyncio.run(capture.PageCaptureService(settings(tmp_path))._serve(
        ClosedRoute("http://127.0.0.1/asset"), state))
    assert state.warnings["blocked_subresources"] == 1

    class ClosedBeforeRequest:
        @property
        def request(self):
            raise TargetClosedError()
    asyncio.run(capture.PageCaptureService(settings(tmp_path))._serve(ClosedBeforeRequest(), state))
    assert state.warnings["blocked_subresources"] == 1


def test_redirect_to_private_address_is_blocked(tmp_path, monkeypatch):
    fake = FakePlaywright()
    fake.documents = {"https://example.com/start": (302, {"location": "http://10.0.0.4/secret"}, b"")}
    service = capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: fake)
    result = attempt(service)
    assert result.error_code == "blocked_address"
    assert result.redirect_chain == [{"url": "https://example.com/start", "status_code": 302}]


def test_cross_host_redirect_restarts_with_approved_mapping(tmp_path):
    fake = FakePlaywright()
    fake.documents = {"https://example.com/start": (302, {"location": "https://other.example.com/story"}, b"")}
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: fake))
    assert result.success and result.final_url == "https://other.example.com/story"
    assert len(fake.launches) == 2
    assert "MAP other.example.com 93.184.216.34" in fake.launches[1]["args"][0]
    assert result.redirect_chain == [
        {"url": "https://example.com/start", "status_code": 302},
        {"url": "https://other.example.com/story", "status_code": 200},
    ]


def test_cross_host_redirect_limit(tmp_path):
    fake = FakePlaywright()
    fake.documents = {"https://example.com/start": (302, {"location": "https://other.example.com/story"}, b"")}
    result = attempt(capture.PageCaptureService(
        settings(tmp_path, seo_page_capture_max_redirects=0), playwright_factory=lambda: fake))
    assert result.error_code == "too_many_redirects" and len(fake.launches) == 1


def test_failed_client_navigation_to_new_host_restarts(tmp_path):
    fake = FakePlaywright()
    fake.failed_navigation = "https://other.example.com/article"
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: fake))
    assert result.success and result.final_url == "https://other.example.com/article"
    assert len(fake.launches) == 2


def test_private_dns_answer_is_rejected_before_browser(tmp_path, monkeypatch):
    @asynccontextmanager
    async def private(_url):
        raise capture.SeoCrawlError("Private, local, or reserved addresses are not allowed")
        yield
    monkeypatch.setattr(capture, "pin_public_target", private)
    fake = FakePlaywright()
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: fake),
                     "https://internal.example.com/start")
    assert result.error_code == "blocked_address" and fake.launches == []


def test_host_resolver_rule_injection_is_rejected(tmp_path):
    fake = FakePlaywright()
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: fake),
                     "https://example.com,MAP%20internal.local%20127.0.0.1/path")
    assert result.error_code == "blocked_url" and fake.launches == []


def test_subresources_continue_only_for_mapped_host(tmp_path):
    state = capture._CaptureState(mapped_hosts={"example.com": "93.184.216.34"})
    mapped = FakeRoute("https://example.com/a.css")
    other = FakeRoute("https://media.example.net/b.css")
    service = capture.PageCaptureService(settings(tmp_path))
    async def run():
        await service._serve(mapped, state)
        await service._serve(other, state)
    asyncio.run(run())
    assert mapped.continued and mapped.fulfilled is None
    assert other.fulfilled is not None and not other.continued


def test_block_pages_never_write_success_image(tmp_path):
    cases = [
        ("https://baijiahao.baidu.com/s?id=1", "https://wappass.baidu.com/static/captcha", 200,
         {"text": "网络不给力", "title": "安全验证"}, "captcha_page"),
        ("https://zhuanlan.zhihu.com/p/1", "https://zhuanlan.zhihu.com/p/1", 403,
         {"text": '{"code":40362,"message":"您当前请求存在异常，暂时限制本次访问"}', "title": ""}, "blocked_by_platform"),
        ("https://example.com/start", "https://example.com/start", 200,
         {"text": "Verify you are human", "title": "Cloudflare challenge"}, "captcha_page"),
    ]
    for source, final, status, info, expected in cases:
        fake = FakePlaywright()
        if source != final:
            fake.documents[source] = (302, {"location": final}, b"")
        fake.documents[final] = (status, {}, b"body")
        fake.info = {**fake.info, **info}
        result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: fake), source)
        assert result.status == "failed" and result.error_code == expected
        assert result.final_url == final and result.http_status == status and result.storage_key is None
    assert not list(tmp_path.iterdir())


def test_cross_registrable_domain_is_blocked_and_normal_article_is_not(tmp_path):
    fake = FakePlaywright()
    fake.documents = {"https://news.example.com/start": (302, {"location": "https://other.org/story"}, b"")}
    blocked = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: fake),
                      "https://news.example.com/start")
    assert blocked.error_code == "blocked_by_platform"
    normal = FakePlaywright()
    normal.info["title"] = "How CAPTCHA systems work"
    normal.info["text"] = "A long article about CAPTCHA design. " * 100
    okay = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=lambda: normal))
    assert okay.success


def test_native_total_bytes_over_limit_fails_capture(tmp_path):
    fake = FakePlaywright()
    fake.documents = {"https://example.com/start": (200, {}, b"x" * 11)}
    result = attempt(capture.PageCaptureService(
        settings(tmp_path, seo_page_capture_max_total_bytes=10), playwright_factory=lambda: fake))
    assert result.error_code == "resources_too_large" and result.storage_key is None


@pytest.mark.parametrize("url, expected", [
    ("https://a.example.com.cn/x", "example.com.cn"),
    ("https://b.example.co.uk/", "example.co.uk"),
    ("https://news.example.com/", "example.com"),
])
def test_registrable_domain(url, expected):
    assert capture._registrable_domain(url) == expected


@pytest.mark.parametrize("url", ["http://127.0.0.1/asset", "data:text/plain,secret", "http://192.168.1.1/"])
def test_subresource_request_is_aborted(tmp_path, url):
    service = capture.PageCaptureService(settings(tmp_path))
    route, state = FakeRoute(url), capture._CaptureState()
    asyncio.run(service._serve(route, state))
    assert route.aborted and route.fulfilled is None
    assert state.warnings["blocked_subresources"] == 1
    assert state.warnings["samples"][0] in {"blocked_address", "blocked_url"}


def test_subresource_redirect_to_private_is_warning(tmp_path, monkeypatch):
    response_map(monkeypatch, {
        "https://example.com/asset.css": FakeResponse(302, {"location": "http://10.1.2.3/asset.css"}),
    })
    state = capture._CaptureState()
    route = FakeRoute("https://example.com/asset.css")
    asyncio.run(capture.PageCaptureService(settings(tmp_path))._serve(route, state))
    assert route.aborted and state.warnings["blocked_subresources"] == 1


def test_total_bytes_cap_keeps_document_and_warns_on_assets(tmp_path, monkeypatch):
    response_map(monkeypatch, {
        "https://example.com/start": FakeResponse(body=b"document"),
        "https://example.com/asset": FakeResponse(body=b"12345"),
    })
    service = capture.PageCaptureService(settings(tmp_path, seo_page_capture_max_total_bytes=10))
    state = capture._CaptureState()
    async def scenario():
        await service._account_native_response(
            FakeBrowserResponse("https://example.com/start", 200, {}, b"document", object()), state)
        first = FakeRoute("https://example.com/asset")
        await service._serve(first, state)
        second = FakeRoute("https://example.com/asset")
        await service._serve(second, state)
        return first, second
    first, second = asyncio.run(scenario())
    assert first.aborted and second.aborted
    assert state.warnings["blocked_subresources"] == 2
    assert state.warnings["samples"] == ["resources_too_large", "resources_too_large"]


def test_timeout_is_recorded_without_image(tmp_path):
    service = capture.PageCaptureService(settings(tmp_path))
    async def timeout(_url, _state):
        raise asyncio.TimeoutError
    service._render = timeout
    result = attempt(service)
    assert result.error_code == "timeout" and result.storage_key is None


def test_missing_playwright_has_explicit_code(tmp_path, monkeypatch):
    import builtins
    original_import = builtins.__import__
    def without_playwright(name, *args, **kwargs):
        if name == "playwright.async_api":
            raise ImportError("simulated missing playwright")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_playwright)
    result = attempt(capture.PageCaptureService(settings(tmp_path)))
    assert result.error_code == "playwright_not_installed"


@pytest.mark.parametrize("channel", ["", "chrome"])
def test_missing_chromium_has_explicit_code(tmp_path, monkeypatch, channel):
    class NoChromium(FakePlaywright):
        async def launch(self, **_kwargs):
            raise RuntimeError("missing executable")
    result = attempt(capture.PageCaptureService(
        settings(tmp_path, seo_page_capture_browser_channel=channel),
        playwright_factory=NoChromium))
    assert result.error_code == "chromium_unavailable" and result.storage_key is None


@pytest.mark.parametrize("browser_options, expected", [
    ({}, {}),
    ({"seo_page_capture_browser_channel": "chrome"}, {"channel": "chrome"}),
    ({"seo_page_capture_executable_path": "installed-browser"},
     {"executable_path": "installed-browser"}),
    ({"seo_page_capture_browser_channel": "msedge",
      "seo_page_capture_executable_path": "installed-browser"},
     {"executable_path": "installed-browser"}),
])
def test_browser_launch_options_and_fresh_context(tmp_path, monkeypatch, browser_options, expected):
    monkeypatch.setattr(capture, "__file__", "C:/outside/app/seo_page_capture.py")
    if "seo_page_capture_executable_path" in browser_options:
        executable = tmp_path / "installed-browser"
        executable.touch()
        browser_options = {**browser_options, "seo_page_capture_executable_path": str(executable)}
        expected = {**expected, "executable_path": str(executable)}

    class RecordingBrowser(FakeBrowser):
        contexts = 0

        async def new_context(self, **kwargs):
            self.contexts += 1
            return await super().new_context(**kwargs)

    class RecordingPlaywright(FakePlaywright):
        launch_options = None

        async def launch(self, **kwargs):
            await super().launch(**kwargs)
            self.launch_options = kwargs
            self.browser = RecordingBrowser(self)
            return self.browser

    fake = RecordingPlaywright()
    result = attempt(capture.PageCaptureService(settings(tmp_path, **browser_options),
                                                 playwright_factory=lambda: fake))
    assert result.success
    assert {key: value for key, value in fake.launch_options.items() if key != "args"} == {
        "headless": True, **expected,
    }
    assert "--disable-quic" in fake.launch_options["args"]
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in fake.launch_options["args"]
    assert "--no-proxy-server" in fake.launch_options["args"]
    assert fake.browser.contexts == 1


def test_invalid_browser_channel_is_rejected(tmp_path, monkeypatch):
    result = attempt(capture.PageCaptureService(
        settings(tmp_path, seo_page_capture_browser_channel="firefox"),
        playwright_factory=FakePlaywright))
    assert result.error_code == "invalid_browser_channel" and result.storage_key is None


def test_missing_browser_executable_is_rejected(tmp_path, monkeypatch):
    result = attempt(capture.PageCaptureService(
        settings(tmp_path, seo_page_capture_executable_path=str(tmp_path / "missing-browser")),
        playwright_factory=FakePlaywright))
    assert result.error_code == "browser_executable_missing" and result.storage_key is None


def test_storage_key_cannot_escape_root(tmp_path):
    for key in ("../outside.png", "a/b.png", "not-generated.png"):
        with pytest.raises(ValueError):
            capture.capture_storage_path(str(tmp_path), key)
    with pytest.raises(ValueError):
        capture.capture_storage_path("relative/path", "a" * 32 + ".png")


def test_disabled_switch_never_invokes_browser(tmp_path):
    result = attempt(capture.PageCaptureService(settings(tmp_path, seo_page_capture_enabled=False)))
    assert result.error_code == "capture_disabled" and not list(tmp_path.iterdir())


def test_warning_reasons_and_host_sampling():
    state = capture._CaptureState()
    state.warn("blocked_address", "http://10.0.0.1/private?token=secret")
    state.warn("blocked_method", "https://example.com/post?token=secret")
    state.warn("too_many_requests", "https://example.com/asset")
    state.warn("http_error", "https://cdn.example.com/missing")
    state.warn("fetch_error", "https://cdn.example.com/broken")
    for index in range(12):
        state.warn("dns_error", f"https://host{index}.example.com/path?secret=1")
    assert state.warnings["blocked_subresources"] == 3
    assert state.warnings["failed_subresources"] == 14
    assert state.warnings["by_reason"] == {
        "blocked_private": 1, "blocked_policy": 1, "request_limit": 1,
        "http_error": 1, "network_failed": 1, "dns_error": 12,
    }
    assert state.warnings["hosts"][:3] == ["10.0.0.1", "example.com", "cdn.example.com"]
    assert len(state.warnings["hosts"]) == 10
    assert all("/" not in host and "?" not in host for host in state.warnings["hosts"])


def test_subresource_429_retries_then_succeeds(tmp_path, monkeypatch):
    statuses = iter([429, 503, 200])
    attempts = []
    pins = []
    sleeps = []

    @asynccontextmanager
    async def pinned(url):
        pins.append(url)
        yield

    async def sleep(seconds):
        sleeps.append(seconds)

    def client(**_kwargs):
        status = next(statuses)
        attempts.append(status)
        return FakeClient(FakeResponse(status, {"retry-after": "0", "content-type": "image/png"}))

    monkeypatch.setattr(capture, "pin_public_target", pinned)
    monkeypatch.setattr(capture, "pinned_async_client", client)
    monkeypatch.setattr(capture.asyncio, "sleep", sleep)
    state = capture._CaptureState()
    route = FakeRoute("https://media.example.com/photo.webp")
    asyncio.run(capture.PageCaptureService(settings(tmp_path))._serve(route, state))
    assert route.fulfilled is not None and not route.aborted
    assert attempts == [429, 503, 200] and len(pins) == 3
    assert sleeps == [0, 0] and state.traffic["requests"] == 3
    assert state.warnings["failed_subresources"] == 0


@pytest.mark.parametrize("status", [429, 503])
def test_subresource_retry_exhaustion_is_rate_limited(tmp_path, monkeypatch, status):
    calls = []
    async def sleep(seconds):
        calls.append(seconds)
    monkeypatch.setattr(capture.asyncio, "sleep", sleep)
    monkeypatch.setattr(capture, "pinned_async_client", lambda **_: FakeClient(FakeResponse(status)))
    state = capture._CaptureState()
    route = FakeRoute("https://media.example.com/image.webp?secret=1")
    asyncio.run(capture.PageCaptureService(settings(tmp_path))._serve(route, state))
    assert route.aborted and state.traffic["requests"] == 3
    assert state.warnings["by_reason"] == {"rate_limited": 1}
    assert state.warnings["failed_subresources"] == 1
    assert state.warnings["hosts"] == ["media.example.com"]
    assert len(calls) == 2


def test_retry_after_seconds_are_capped(tmp_path, monkeypatch):
    sleeps = []
    async def sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(capture.asyncio, "sleep", sleep)
    monkeypatch.setattr(capture, "pinned_async_client", lambda **_: FakeClient(
        FakeResponse(429, {"retry-after": "120"})))
    route = FakeRoute("https://media.example.com/image.webp")
    asyncio.run(capture.PageCaptureService(settings(tmp_path))._serve(route, capture._CaptureState()))
    assert route.aborted and sleeps == [2.0, 2.0]


def test_per_host_concurrency_applies_to_subresources(tmp_path, monkeypatch):
    active = 0
    peak = 0
    class SlowResponse(FakeResponse):
        async def __aenter__(self):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            return self

        async def __aexit__(self, *_args):
            nonlocal active
            active -= 1

        async def aiter_bytes(self):
            await asyncio.sleep(0.01)
            yield b"image"

    monkeypatch.setattr(capture, "pinned_async_client", lambda **_: FakeClient(SlowResponse()))
    state = capture._CaptureState()
    routes = [FakeRoute(f"https://media.example.com/{i}.webp") for i in range(8)]
    service = capture.PageCaptureService(settings(tmp_path, seo_page_capture_per_host_concurrency=2))
    async def run():
        await asyncio.gather(*(service._serve(route, state) for route in routes))
    asyncio.run(run())
    assert peak == 2 and all(route.fulfilled is not None for route in routes)


def test_request_limit_default_and_private_warning(tmp_path):
    from app.config import Settings
    assert Settings.model_fields["seo_page_capture_max_requests"].default == 300
    assert Settings.model_fields["seo_page_capture_per_host_concurrency"].default == 4
    route = FakeRoute("http://192.168.1.1/private.png")
    state = capture._CaptureState()
    asyncio.run(capture.PageCaptureService(settings(tmp_path))._serve(route, state))
    assert route.aborted and state.warnings["by_reason"] == {"blocked_private": 1}


def test_request_limit_is_counted_as_its_own_reason(tmp_path):
    service = capture.PageCaptureService(settings(tmp_path, seo_page_capture_max_requests=1))
    state = capture._CaptureState()
    first = FakeRoute("https://example.com/first.png")
    second = FakeRoute("https://example.com/second.png")
    async def run():
        await service._serve(first, state)
        await service._serve(second, state)
    asyncio.run(run())
    assert first.fulfilled is not None and second.aborted
    assert state.warnings["by_reason"] == {"request_limit": 1}
    assert state.warnings["blocked_subresources"] == 1

# Regression: /health/seo must read capture constraints from a real CursorResult.
# SQLAlchemy CursorResult exposes keys() without __getitem__, so dict(result) fails.
# Production revision 0104 hit this on 2026-10-05.
import asyncio as _health_asyncio

from app import seo_main as _health_seo_main


class _HealthCursorLikeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def keys(self):  # mapping trap, like sqlalchemy CursorResult
        return ["name", "definition"]

    def all(self):
        return list(self._rows)

    def scalars(self):
        return iter([row[0] for row in self._rows])


class _HealthCaptureConn:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, *_args, **_kwargs):
        return self._results.pop(0)


def test_capture_structure_accepts_cursor_like_results():
    columns = [(name, kind, not_null) for name, (kind, not_null) in _health_seo_main.SEO_CAPTURE_COLUMNS.items()]
    conn = _HealthCaptureConn([
        _HealthCursorLikeResult(columns),
        _HealthCursorLikeResult([("CHECK (status IN ('pending', 'running', 'succeeded', 'failed'))",)]),
        _HealthCursorLikeResult([
            ("ck_seo_page_captures_source", "CHECK (source IN ('auto', 'manual'))"),
            ("ck_seo_page_captures_manual_upload", "CHECK (source <> 'manual' OR (uploaded_by IS NOT NULL AND uploaded_at IS NOT NULL))"),
        ]),
    ])
    _health_asyncio.run(_health_seo_main._check_capture_structure(conn))