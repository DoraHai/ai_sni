import asyncio
from pathlib import Path
import socket

import httpcore
import httpx
import pytest

from app import sem_urlwords
from app.security import public_http
from app.security.public_http import (
    PublicHttpError,
    PublicHttpResponse,
    fetch_public_url,
    normalize_public_url,
)
from app.sem_urlwords import UrlFetchError, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.8/admin",
        "http://[::1]/private",
        "http://localhost/private",
        "http://user:password@example.com/private",
    ],
)
def test_literal_private_and_credentialed_urls_are_rejected(url):
    with pytest.raises((PublicHttpError, UrlFetchError)):
        validate_url(url)


def test_public_url_normalization_removes_fragments_and_trailing_dns_dot():
    assert normalize_public_url("HTTPS://Example.COM./a?q=1#fragment") == "https://example.com/a?q=1"


def test_dns_result_is_rejected_when_any_address_is_not_global(monkeypatch):
    async def fake_getaddrinfo(self, host, port, **kwargs):
        assert host == "customer.example"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(PublicHttpError, match="内网|保留"):
        asyncio.run(public_http._resolve_public_ip("https://customer.example/landing"))


def test_idn_uses_the_same_punycode_host_for_dns_and_connection_pinning(monkeypatch):
    seen = []

    async def fake_getaddrinfo(self, host, port, **kwargs):
        seen.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    url = normalize_public_url("https://中国.cn/落地页")
    assert public_http._ascii_host(url) == "xn--fiqs8s.cn"
    assert asyncio.run(public_http._resolve_public_ip(url)) == "93.184.216.34"
    assert seen == ["xn--fiqs8s.cn"]


def test_pinned_backend_connects_to_only_the_approved_ip():
    class RecordingBackend:
        def __init__(self):
            self.calls = []
            self.stream = object()

        async def connect_tcp(self, **kwargs):
            self.calls.append(kwargs)
            return self.stream

    async def exercise():
        recording = RecordingBackend()
        backend = public_http._PinnedNetworkBackend(recording)
        token = public_http._PINNED_TARGETS.set(
            {("customer.example", 443): "93.184.216.34"}
        )
        try:
            stream = await backend.connect_tcp("customer.example", 443, timeout=3)
        finally:
            public_http._PINNED_TARGETS.reset(token)
        assert stream is recording.stream
        assert recording.calls == [
            {
                "host": "93.184.216.34",
                "port": 443,
                "timeout": 3,
                "local_address": None,
                "socket_options": None,
            }
        ]
        with pytest.raises(httpcore.ConnectError, match="not approved"):
            await backend.connect_tcp("unapproved.example", 443)

    asyncio.run(exercise())


def test_fetch_revalidates_redirects_and_rejects_private_targets(monkeypatch):
    async def public_ip(_url):
        return "93.184.216.34"

    async def redirect_to_private(_request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    monkeypatch.setattr(public_http, "_resolve_public_ip", public_ip)
    with pytest.raises(PublicHttpError, match="内网|保留"):
        asyncio.run(
            fetch_public_url(
                "https://customer.example/start",
                timeout=3,
                max_response_bytes=1024,
                _transport=httpx.MockTransport(redirect_to_private),
            )
        )


def test_fetch_follows_validated_redirect_and_returns_bounded_body(monkeypatch):
    async def public_ip(_url):
        return "93.184.216.34"

    async def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, content=b"sem-ok")

    monkeypatch.setattr(public_http, "_resolve_public_ip", public_ip)
    response = asyncio.run(
        fetch_public_url(
            "https://customer.example/start",
            timeout=3,
            max_response_bytes=1024,
            _transport=httpx.MockTransport(handler),
        )
    )
    assert response.status_code == 200
    assert response.body == b"sem-ok"
    assert response.final_url == "https://customer.example/final"
    assert response.redirect_chain == ("https://customer.example/final",)


def test_fetch_rejects_response_that_exceeds_streaming_limit(monkeypatch):
    async def public_ip(_url):
        return "93.184.216.34"

    async def oversized(_request):
        return httpx.Response(200, content=b"12345")

    monkeypatch.setattr(public_http, "_resolve_public_ip", public_ip)
    with pytest.raises(PublicHttpError, match="超过允许大小"):
        asyncio.run(
            fetch_public_url(
                "https://customer.example/large",
                timeout=3,
                max_response_bytes=4,
                _transport=httpx.MockTransport(oversized),
            )
        )


def test_sem_page_parser_uses_hardened_response(monkeypatch):
    async def fake_fetch(*_args, **_kwargs):
        return PublicHttpResponse(
            requested_url="https://customer.example/",
            final_url="https://customer.example/",
            status_code=200,
            headers={"content-type": "text/html"},
            body=(
                b"<html><head><title>SEM title</title></head>"
                b"<body><script>secret</script><h1>Landing page</h1></body></html>"
            ),
            redirect_chain=(),
        )

    monkeypatch.setattr(sem_urlwords, "fetch_public_url", fake_fetch)
    title, text = asyncio.run(sem_urlwords.fetch_page_text("https://customer.example"))
    assert title == "SEM title"
    assert "Landing page" in text
    assert "secret" not in text


def test_hardened_fetch_is_wired_only_to_sem_callers():
    root = Path(__file__).resolve().parents[1]
    assert "from app.sem_urlwords import" in (root / "app/baidu/sync.py").read_text(encoding="utf-8")
    assert "from app.sem_urlwords import" in (
        root / "app/api/onboarding_builder.py"
    ).read_text(encoding="utf-8")
    assert "fetch_public_url" in (root / "app/rules/site_health.py").read_text(encoding="utf-8")
    for geo_path in (
        "app/geo/sitemap_audit.py",
        "app/geo/content/competitor_web_search.py",
        "app/geo/content/onboarding.py",
    ):
        assert "from app.urlwords import" in (root / geo_path).read_text(encoding="utf-8")
