"""Real document limits plus a bounded UploadFile read contract."""
import asyncio
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.geo.content import article_import as imports


@pytest.mark.parametrize('extension', ['txt', 'md', 'html', 'htm'])
def test_supported_text_files(extension):
    raw = b'<html><title>Fixture</title><article><p>Article body.</p></article></html>' if extension in {'html', 'htm'} else b'Article body.'
    assert imports.preview_file_document(filename='fixture.' + extension, raw=raw)['source_type'] == 'file'


def test_real_docx_round_trip():
    from docx import Document
    document = Document()
    document.add_paragraph('Imported fixture article.')
    raw = io.BytesIO()
    document.save(raw)
    assert 'Imported fixture article.' in imports.preview_file_document(filename='fixture.docx', raw=raw.getvalue())['body_markdown']


def test_pdf_page_limit_precedes_text_extraction():
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(imports.MAX_PDF_PAGES + 1):
        writer.add_blank_page(width=100, height=100)
    raw = io.BytesIO()
    writer.write(raw)
    with pytest.raises(imports.ArticleImportError, match='cannot exceed 100 pages'):
        imports.preview_file_document(filename='fixture.pdf', raw=raw.getvalue())


@pytest.mark.parametrize('limit', ['expanded', 'entries'])
def test_compressed_docx_limits_before_document_parser(monkeypatch, limit):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(3):
            archive.writestr(f'fixture-{index}.xml', b'a' * 2000)
    assert len(raw.getvalue()) < 1000
    monkeypatch.setattr(imports, 'MAX_DOCX_UNPACKED_BYTES' if limit == 'expanded' else 'MAX_DOCX_ENTRIES',
                        1000 if limit == 'expanded' else 2)
    with pytest.raises(imports.ArticleImportError, match='expanded content exceeds'):
        imports.preview_file_document(filename='fixture.docx', raw=raw.getvalue())


def test_file_handler_reads_only_limit_plus_one_and_returns_413(monkeypatch):
    from app.geo.content import routes
    monkeypatch.setattr(routes, '_ensure_tenant_exists', AsyncMock())
    monkeypatch.setattr(routes, 'MAX_FILE_BYTES', 16)
    reads = []

    async def read(size):
        reads.append(size)
        return b'x' * size

    async def run():
        with pytest.raises(HTTPException) as error:
            await routes.preview_article_import_file(tenant_id=10,
                file=SimpleNamespace(filename='fixture.txt', read=read),
                ctx=SimpleNamespace(ensure_tenant=lambda _tid: None), session=object())
        assert error.value.status_code == 413
        assert reads == [17]
    asyncio.run(run())
