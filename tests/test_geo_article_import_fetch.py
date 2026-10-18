"""Bounded article fetching with mocked transport/DNS; no live web requests."""
import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest

from app.geo import audit


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks, self.reads, self.closed = chunks, 0, False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def install_transport(monkeypatch, handler, *, mock_dns=True):
    client_class = httpx.AsyncClient
    monkeypatch.setattr(audit.httpx, 'AsyncClient', lambda **kwargs:
        client_class(transport=httpx.MockTransport(handler), **kwargs))
    if mock_dns:
        monkeypatch.setattr(audit, '_ensure_public_host', AsyncMock(return_value=['93.184.216.34']))


def test_import_pins_ip_preserves_host_sni_and_requests_identity(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, headers={'content-type': 'text/html'}, content=b'<title>Fixture</title>')

    install_transport(monkeypatch, handler)
    doc = asyncio.run(audit.safe_fetch('https://public.test/article', article_import=True))
    assert doc.final_url == 'https://public.test/article'
    assert seen[0].url.host == '93.184.216.34'
    assert seen[0].headers['host'] == 'public.test'
    assert seen[0].extensions['sni_hostname'] == 'public.test'
    assert seen[0].headers['accept-encoding'] == 'identity'


@pytest.mark.parametrize('port', ['8080', '22', '0', '65536', 'bad'])
def test_import_rejects_ports_before_dns(monkeypatch, port):
    dns = AsyncMock()
    monkeypatch.setattr(audit, '_ensure_public_host', dns)
    with pytest.raises(audit.GeoAuditError, match='端口'):
        asyncio.run(audit.safe_fetch('https://public.test:' + port, article_import=True))
    dns.assert_not_awaited()


def test_legacy_fetch_keeps_nonstandard_public_ports(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url.port)
        return httpx.Response(200, headers={'content-type': 'text/html'}, content=b'<p>Fixture</p>')

    install_transport(monkeypatch, handler)
    asyncio.run(audit.safe_fetch('http://public.test:8080/article'))
    assert seen == [8080]


@pytest.mark.parametrize('url', ['https://[broken', 'https://public.test:65536/article',
    'https://fixture-user:fixture-password@public.test/article', 'file:///fixture.txt'])
def test_invalid_article_url_is_an_input_error_before_fetch(monkeypatch, url):
    from app.geo.content.article_import import ArticleImportError, preview_url_document
    fetch = AsyncMock(side_effect=AssertionError('invalid URL reached fetch'))
    monkeypatch.setattr(audit, 'safe_fetch', fetch)
    with pytest.raises(ArticleImportError):
        asyncio.run(preview_url_document(url))
    fetch.assert_not_awaited()


@pytest.mark.parametrize('headers', [
    {'content-length': str(audit.MAX_HTML_BYTES + 1)},
    {'content-length': '-1'}, {'content-length': 'invalid'}, {'content-encoding': 'gzip'},
])
def test_import_rejects_response_headers_before_reading_body(monkeypatch, headers):
    stream = Stream([b'fixture'])
    install_transport(monkeypatch, lambda _request: httpx.Response(200,
        headers={'content-type': 'text/html', **headers}, stream=stream))
    with pytest.raises(audit.GeoAuditError):
        asyncio.run(audit.safe_fetch('https://public.test/article', article_import=True))
    assert stream.reads == 0 and stream.closed


def test_import_stops_stream_without_length_header(monkeypatch):
    monkeypatch.setattr(audit, 'MAX_HTML_BYTES', 64 * 1024)
    stream = Stream([b'x' * (64 * 1024)] * 10)
    install_transport(monkeypatch, lambda _request: httpx.Response(200,
        headers={'content-type': 'text/html'}, stream=stream))
    with pytest.raises(audit.GeoAuditError, match='超过'):
        asyncio.run(audit.safe_fetch('https://public.test/article', article_import=True))
    assert stream.reads == 2 and stream.closed


@pytest.mark.parametrize('target', ['http://127.0.0.1/article', 'http://169.254.169.254/latest',
                                   'http://[::1]/article', 'https://public.test:8080/article'])
def test_import_revalidates_each_redirect(monkeypatch, target):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={'location': target})

    install_transport(monkeypatch, handler, mock_dns=False)

    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]))
        with pytest.raises(audit.GeoAuditError):
            await audit.safe_fetch('https://public.test/article', article_import=True)
    asyncio.run(run())
    assert len(seen) == 1


def test_import_rejects_mixed_public_and_private_dns_answers(monkeypatch):
    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))
            for ip in ('93.184.216.34', '10.0.0.1')]))
        with pytest.raises(audit.GeoAuditError, match='内网'):
            await audit.safe_fetch('https://public.test/article', article_import=True)
    asyncio.run(run())


@pytest.mark.parametrize('stage', ['dns', 'redirects', 'body'])
def test_one_import_deadline_covers_dns_redirects_and_body(monkeypatch, stage):
    monkeypatch.setattr(audit, 'ARTICLE_IMPORT_TIMEOUT', 0.02)

    async def handler(_request):
        if stage == 'redirects':
            await asyncio.sleep(0.01)
            return httpx.Response(302, headers={'location': '/next'})
        return httpx.Response(200, headers={'content-type': 'text/html'}, stream=SlowStream())

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield b'unreachable'

    install_transport(monkeypatch, handler)
    if stage == 'dns':
        async def slow_dns(_url):
            await asyncio.Event().wait()
        monkeypatch.setattr(audit, '_ensure_public_host', slow_dns)
    with pytest.raises(audit.GeoAuditError, match='总时长'):
        asyncio.run(audit.safe_fetch('https://public.test/article', article_import=True))
