import asyncio
import hashlib
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from app import seo_page_capture as capture


PNG = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 800, 600)


def settings(tmp_path, **changes):
    values = dict(seo_page_capture_enabled=True, seo_page_capture_storage_dir=str(tmp_path),
                  seo_page_capture_browser_channel="", seo_page_capture_executable_path="",
                  seo_page_capture_concurrency=2, seo_page_capture_timeout_seconds=5,
                  seo_page_capture_viewport_width=800, seo_page_capture_viewport_height=600,
                  seo_page_capture_max_height=12000, seo_page_capture_max_pixels=16_000_000,
                  seo_page_capture_max_response_bytes=1000, seo_page_capture_max_total_bytes=2000,
                  seo_page_capture_max_requests=10, seo_page_capture_max_image_bytes=1000)
    values.update(changes)
    return SimpleNamespace(**values)


class FakePage:
    url = "https://example.com/final"

    async def goto(self, *_args, **_kwargs):
        return SimpleNamespace(status=200)

    async def evaluate(self, *_args):
        return {"height": 600, "text": "Visible page", "password": False}

    async def screenshot(self, **_kwargs):
        return PNG


class FakeContext:
    def __init__(self):
        self.routes = []

    async def route(self, pattern, callback):
        self.routes.append((pattern, callback))

    async def route_web_socket(self, pattern, callback):
        self.routes.append((pattern, callback))

    async def new_page(self):
        return FakePage()

    async def close(self):
        pass


class FakeBrowser:
    async def new_context(self, **kwargs):
        assert kwargs["service_workers"] == "block"
        return FakeContext()

    async def close(self):
        pass


class FakePlaywright:
    chromium = None

    def __init__(self):
        self.chromium = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def launch(self, **kwargs):
        assert kwargs["proxy"]["server"] == "http://127.0.0.1:9"
        return FakeBrowser()

    async def launch_persistent_context(self, *_args, **_kwargs):
        pytest.fail("page capture must use a fresh browser context")


def attempt(service, url="https://example.com/start"):
    return asyncio.run(service.capture_page(tenant_id=1, site_id=2, relation_type="site_page",
                                            relation_id=3, url=url))


def test_success_writes_true_png_metadata_and_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "__file__", "C:/outside/app/seo_page_capture.py")
    async def public(_url):
        pass
    monkeypatch.setattr(capture, "_public", public)
    service = capture.PageCaptureService(settings(tmp_path), playwright_factory=FakePlaywright)
    result = attempt(service)
    assert result.success and result.error_code is None
    assert (result.final_url, result.http_status) == ("https://example.com/final", 200)
    assert (result.image_width, result.image_height) == (800, 600)
    assert result.sha256 == hashlib.sha256(PNG).hexdigest()
    assert capture.capture_storage_path(str(tmp_path), result.storage_key).read_bytes() == PNG


@pytest.mark.parametrize("url", ["http://127.0.0.1/a", "http://10.0.0.1/a",
                                   "http://[::1]/", "http://localhost/", "file:///etc/passwd"])
def test_local_and_non_http_urls_rejected_before_browser(tmp_path, url):
    result = attempt(capture.PageCaptureService(settings(tmp_path), playwright_factory=FakePlaywright), url)
    assert not result.success and result.storage_key is None
    assert result.error_code in {"blocked_address", "blocked_url"}
    assert not list(tmp_path.iterdir())


class FakeResponse:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {"content-type": "text/css"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def aiter_bytes(self):
        yield b"body"


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
    def __init__(self, url):
        self.request = SimpleNamespace(url=url, method="GET", headers={"cookie": "secret", "accept": "*/*"})
        self.aborted = False
        self.fulfilled = None

    async def abort(self):
        self.aborted = True

    async def fulfill(self, **kwargs):
        self.fulfilled = kwargs


def test_redirect_to_private_address_is_blocked(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def pinned(_url):
        yield
    monkeypatch.setattr(capture, "pin_public_target", pinned)
    monkeypatch.setattr(capture, "pinned_async_client", lambda **_: FakeClient(
        FakeResponse(302, {"location": "http://10.0.0.4/secret"})))
    service = capture.PageCaptureService(settings(tmp_path))
    route, failures = FakeRoute("https://example.com/start"), []
    asyncio.run(service._serve(route, failures, {"requests": 0, "bytes": 0, "redirects": 0}))
    assert route.aborted and route.fulfilled is None and failures == ["blocked_address"]


@pytest.mark.parametrize("url", ["http://127.0.0.1/asset", "data:text/plain,secret", "http://192.168.1.1/"])
def test_subresource_request_is_aborted(tmp_path, url):
    service = capture.PageCaptureService(settings(tmp_path))
    route, failures = FakeRoute(url), []
    asyncio.run(service._serve(route, failures, {"requests": 0, "bytes": 0, "redirects": 0}))
    assert route.aborted and route.fulfilled is None
    assert failures[0] in {"blocked_address", "blocked_url"}


def test_timeout_is_recorded_without_image(tmp_path):
    service = capture.PageCaptureService(settings(tmp_path))
    async def timeout(_url):
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
    async def public(_url):
        pass
    monkeypatch.setattr(capture, "_public", public)
    result = attempt(capture.PageCaptureService(settings(tmp_path)))
    assert result.error_code == "playwright_not_installed"


@pytest.mark.parametrize("channel", ["", "chrome"])
def test_missing_chromium_has_explicit_code(tmp_path, monkeypatch, channel):
    async def public(_url):
        pass
    monkeypatch.setattr(capture, "_public", public)
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
    async def public(_url):
        pass
    monkeypatch.setattr(capture, "_public", public)
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
        browser = RecordingBrowser()

        async def launch(self, **kwargs):
            self.launch_options = kwargs
            return self.browser

    fake = RecordingPlaywright()
    result = attempt(capture.PageCaptureService(settings(tmp_path, **browser_options),
                                                 playwright_factory=lambda: fake))
    assert result.success
    assert fake.launch_options == {
        "headless": True, "proxy": {"server": "http://127.0.0.1:9"}, **expected,
    }
    assert fake.browser.contexts == 1


def test_invalid_browser_channel_is_rejected(tmp_path, monkeypatch):
    async def public(_url):
        pass
    monkeypatch.setattr(capture, "_public", public)
    result = attempt(capture.PageCaptureService(
        settings(tmp_path, seo_page_capture_browser_channel="firefox"),
        playwright_factory=FakePlaywright))
    assert result.error_code == "invalid_browser_channel" and result.storage_key is None


def test_missing_browser_executable_is_rejected(tmp_path, monkeypatch):
    async def public(_url):
        pass
    monkeypatch.setattr(capture, "_public", public)
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
