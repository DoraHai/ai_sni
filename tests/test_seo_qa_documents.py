import asyncio
import io
import zipfile
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.seo_qa_documents import parse_document, preview_document, MAX_BYTES
from app.api.seo_qa import preview_research_file


def docx(text='使用前应确认设备型号和工作条件，并按照产品说明检查电压、功率及环境温度。'):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>额定功率 1.5kW</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    return stream.getvalue()


def pdf(encrypted=False, blank=False):
    writer = PdfWriter()
    page = writer.add_blank_page(600, 800)
    if not blank:
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 50 700 Td (Check model and operating conditions before use. Rated power is 1.5kW.) Tj ET')
        page[NameObject('/Contents')] = content
    if encrypted:
        writer.encrypt('password')
    stream = io.BytesIO(); writer.write(stream)
    return stream.getvalue()


def test_real_pdf_and_docx_preserve_text_and_boundaries():
    value = parse_document(pdf(), 'pdf')
    assert '1.5kW' in value['text'] and '第 1 页' in value['text']
    value = parse_document(docx(), 'docx')
    assert value['text'].endswith('额定功率 1.5kW')
    assert value['characters'] == len(value['text']) and value['warnings']
    assert asyncio.run(preview_document(docx(), 'docx')) == value
    assert '1.5kW' in asyncio.run(preview_document(pdf(), 'pdf'))['text']


@pytest.mark.parametrize('data,kind', [(b'wrong', 'pdf'), (pdf(encrypted=True), 'pdf'),
    (pdf(blank=True), 'pdf'), (docx('长'*30001), 'docx'), (b'x'*(MAX_BYTES+1), 'pdf'), (b'x', 'doc')], ids=['bad-signature','encrypted','scanned','too-long','oversize','old-doc'])
def test_unreliable_or_oversized_documents_rejected(data, kind):
    with pytest.raises(ValueError):
        parse_document(data, kind)


def test_corrupt_worker_returns_safe_error():
    with pytest.raises(ValueError, match='损坏'):
        asyncio.run(preview_document(b'not a zip', 'docx'))


def test_page_and_expansion_limits():
    writer = PdfWriter()
    for _ in range(101):
        writer.add_blank_page(100, 100)
    stream = io.BytesIO(); writer.write(stream)
    with pytest.raises(ValueError, match='100 页'):
        parse_document(stream.getvalue(), 'pdf')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', b'x' * (21 * 1024 * 1024))
    with pytest.raises(ValueError, match='解压后过大'):
        parse_document(stream.getvalue(), 'docx')


def test_timeout_and_cancellation_kill_parser():
    from types import SimpleNamespace
    from unittest.mock import Mock
    async def scenario(error):
        process = SimpleNamespace(returncode=None, communicate=AsyncMock(side_effect=error),
                                  kill=Mock(), wait=AsyncMock())
        with patch('app.seo_qa_documents.asyncio.create_subprocess_exec', AsyncMock(return_value=process)):
            with pytest.raises(ValueError if isinstance(error, asyncio.TimeoutError) else asyncio.CancelledError):
                await preview_document(b'', 'pdf')
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()
    asyncio.run(scenario(asyncio.TimeoutError()))
    asyncio.run(scenario(asyncio.CancelledError()))


def test_preview_checks_access_before_parsing_and_closes_upload():
    async def scenario():
        file = UploadFile(io.BytesIO(docx()), filename='手册.docx')
        with patch('app.api.seo_qa.access', AsyncMock(side_effect=HTTPException(403, 'denied'))), patch('app.seo_qa_documents.preview_document', AsyncMock()) as parser:
            with pytest.raises(HTTPException) as exc:
                await preview_research_file(1, 2, file, None, None)
            assert exc.value.status_code == 403
            parser.assert_not_called()
            assert file.file.closed
        with patch('app.api.seo_qa.access', AsyncMock()) as access:
            value = await preview_research_file(1, 2, UploadFile(io.BytesIO(docx()), filename='手册.DOCX'), None, None)
            assert '1.5kW' in value['text']
            assert access.await_args.kwargs['write'] is True
            for data, name, code in [(b'x'*(MAX_BYTES+1), 'big.pdf', 413), (b'x', 'old.doc', 422), (b'x', 'bad.pdf', 422)]:
                with pytest.raises(HTTPException) as exc:
                    await preview_research_file(1, 2, UploadFile(io.BytesIO(data), filename=name), None, None)
                assert exc.value.status_code == code
    asyncio.run(scenario())
