"""Upload boundaries run before multipart parsing; PDFs run outside the API."""
import asyncio
import io
import sys
import zlib

import pytest

from app.geo.content import article_import as imports
from app.security import article_upload_limit as uploads


def request_scope(headers=()):
    return {'type': 'http', 'method': 'POST', 'path': uploads.PREVIEW_PATH, 'headers': list(headers)}


def test_declared_oversize_never_reads_or_enters_multipart_parser(monkeypatch):
    monkeypatch.setattr(uploads, 'MAX_BODY_BYTES', 32)
    async def check():
        sent = []
        async def forbidden(*args):
            pytest.fail('oversized upload reached the parser or body reader')
        async def send(message):
            sent.append(message)
        await uploads.ArticleUploadLimitMiddleware(forbidden)(
            request_scope([(b'content-length', b'33')]), forbidden, send)
        assert sent[0]['status'] == 413
    asyncio.run(check())


@pytest.mark.parametrize('headers', [[], [(b'content-length', b'1')]])
def test_streamed_oversize_never_enters_parser(monkeypatch, headers):
    monkeypatch.setattr(uploads, 'MAX_BODY_BYTES', 32)
    async def run():
        sent, reads = [], []
        chunks = iter([b'x' * 20, b'y' * 20])
        async def receive():
            reads.append(1)
            return {'type': 'http.request', 'body': next(chunks), 'more_body': True}
        async def parser(*args):
            pytest.fail('oversized upload reached multipart parsing')
        async def send(message):
            sent.append(message)
        await uploads.ArticleUploadLimitMiddleware(parser)(request_scope(headers), receive, send)
        assert sent[0]['status'] == 413 and len(reads) == 2
    asyncio.run(run())


def test_valid_stream_is_replayed_exactly(monkeypatch):
    monkeypatch.setattr(uploads, 'MAX_BODY_BYTES', 32)
    async def run():
        chunks = iter([{'type': 'http.request', 'body': b'first', 'more_body': True},
                       {'type': 'http.request', 'body': b'second', 'more_body': False}])
        async def receive():
            return next(chunks)
        async def parser(scope, replay, send):
            assert await replay() == {'type': 'http.request', 'body': b'firstsecond', 'more_body': False}
        await uploads.ArticleUploadLimitMiddleware(parser)(request_scope(), receive, None)
    asyncio.run(run())


def test_stalled_upload_times_out_before_parser(monkeypatch):
    monkeypatch.setattr(uploads, 'UPLOAD_TIMEOUT_SECONDS', 0.01)
    async def run():
        sent = []
        async def receive():
            await asyncio.sleep(1)
        async def parser(*args):
            pytest.fail('stalled upload reached multipart parsing')
        async def send(message):
            sent.append(message)
        await uploads.ArticleUploadLimitMiddleware(parser)(request_scope(), receive, send)
        assert sent[0]['status'] == 408
    asyncio.run(run())


def compressed_pdf(content):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, EncodedStreamObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica'),
        NameObject('/Encoding'): NameObject('/WinAnsiEncoding')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
        NameObject('/F1'): writer._add_object(font)})})
    stream = EncodedStreamObject()
    stream._data = content
    stream[NameObject('/Filter')] = NameObject('/FlateDecode')
    page[NameObject('/Contents')] = writer._add_object(stream)
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def test_small_pdf_round_trip():
    raw = compressed_pdf(zlib.compress(b'BT /F1 12 Tf (Fixture article.) Tj ET'))
    assert 'Fixture article.' in imports.preview_file_document(filename='fixture.pdf', raw=raw)['body_markdown']


def test_compressed_pdf_cannot_return_unbounded_text():
    raw = compressed_pdf(zlib.compress(b'BT /F1 12 Tf (' + b'A' * 2_000_000 + b') Tj ET'))
    assert len(raw) < 4096
    with pytest.raises(imports.ArticleImportError, match='正文过长|资源限制|超时'):
        imports.preview_file_document(filename='fixture.pdf', raw=raw)


@pytest.mark.skipif(sys.platform == 'win32', reason='Linux production address-space limit')
def test_pdf_expansion_is_killed_in_disposable_process():
    # Build nearly 1 GiB of decoded content without allocating it in pytest.
    compressor = zlib.compressobj()
    chunks = [compressor.compress(b'BT /F1 12 Tf (')]
    for _ in range(120_000):
        chunks.append(compressor.compress(b'A' * 8192))
    chunks.extend([compressor.compress(b') Tj ET'), compressor.flush()])
    raw = compressed_pdf(b''.join(chunks))
    assert len(raw) < 2 * 1024 * 1024
    with pytest.raises(imports.ArticleImportError, match='资源限制|超时'):
        imports.preview_file_document(filename='fixture.pdf', raw=raw)
    assert 'Fixture article.' in imports.preview_file_document(
        filename='fixture.pdf', raw=compressed_pdf(zlib.compress(b'BT /F1 12 Tf (Fixture article.) Tj ET'))
    )['body_markdown']


def test_pdf_timeout_releases_worker_slot(monkeypatch):
    import subprocess
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 10)
    monkeypatch.setattr(imports.subprocess, 'run', timed_out)
    for _ in range(3):
        with pytest.raises(imports.ArticleImportError, match='超时'):
            imports._read_pdf(b'fixture')


def test_independent_geo_app_installs_upload_guard():
    from app.geo_main import app
    assert any(m.cls is uploads.ArticleUploadLimitMiddleware for m in app.user_middleware)
