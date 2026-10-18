import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.geo.content import search_visibility as sv
from test_geo_search_visibility import client_case, offline


def test_response_stream_stops_before_reading_all_chunks_and_keeps_reservation(monkeypatch):
    monkeypatch.setattr(sv, 'MAX_PROVIDER_BYTES', 32)
    consumed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(10):
                consumed.append(1)
                yield b'x' * 20

    async def run():
        def handler(request):
            return httpx.Response(200, stream=Stream())
        async def operation(client):
            with pytest.raises(sv.StopRun, match='返回内容过大'):
                await client.request('POST', '/v1/tools/fetch', {'url': 'https://example.com'})
            assert client.result['summary']['reserved_cny'] == 0.005
            assert client.result['summary']['requests'] == 1
        await client_case(handler, operation)
    asyncio.run(run())
    assert len(consumed) == 2


def test_oversized_fetch_text_never_reaches_html_parser(monkeypatch):
    monkeypatch.setattr(sv, 'MAX_FETCH_CHARS', 32)
    parser = AsyncMock(side_effect=AssertionError('oversized HTML must not be parsed'))
    monkeypatch.setattr(sv, 'page_info', parser)
    async def run():
        def handler(request):
            return httpx.Response(200, json={'content': 'x' * 33})
        async def operation(client):
            with pytest.raises(sv.StopRun, match='返回正文过长'):
                await client.request('POST', '/v1/tools/fetch', {'url': 'https://example.com'})
            assert client.result['summary']['reserved_cny'] == 0.005
        await client_case(handler, operation)
    asyncio.run(run())
    parser.assert_not_called()
