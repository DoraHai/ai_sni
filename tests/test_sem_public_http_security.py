import asyncio
import socket

import pytest

from app.security import public_http
from app.security.public_http import PublicHttpError, normalize_public_url
from app.urlwords import UrlFetchError, validate_url


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


def test_outbound_fetch_contract_pins_dns_checks_redirects_and_streams_body():
    source = open(public_http.__file__, encoding="utf-8").read()
    assert "follow_redirects=False" in source
    assert "hostname = _ascii_host(current)" in source
    assert "approved_ip = await _resolve_public_ip(current)" in source
    assert "_PINNED_TARGETS.set" in source
    assert "normalize_public_url(urljoin(current, location))" in source
    assert "async for chunk in response.aiter_bytes()" in source
    assert "if size > max_response_bytes" in source


def test_sem_url_fetchers_use_the_hardened_public_client():
    from app import urlwords
    from app.rules import site_health

    urlwords_source = open(urlwords.__file__, encoding="utf-8").read()
    site_health_source = open(site_health.__file__, encoding="utf-8").read()
    assert "await fetch_public_url(" in urlwords_source
    assert "await fetch_public_url(" in site_health_source
    assert "follow_redirects=True" not in urlwords_source
    assert "follow_redirects=True" not in site_health_source
