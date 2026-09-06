"""Bounded, text-only document preview; never calls AI or persists uploaded files."""
import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 30000
_slots = asyncio.Semaphore(2)


def parse_document(data: bytes, kind: str) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError('文件不能超过 5MB')
    parts = []
    warnings = []
    if kind == 'pdf':
        if not data.startswith(b'%PDF-'):
            raise ValueError('文件内容不是 PDF')
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError('暂不支持加密 PDF，请先导出未加密副本')
        if len(reader.pages) > 100:
            raise ValueError('PDF 最多 100 页，请按章节拆分')
        empty = []
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ''
            if text.strip():
                parts.append(f'【第 {index} 页】\n{text.strip()}')
            else:
                empty.append(index)
            if sum(map(len, parts)) > MAX_TEXT:
                raise ValueError('解析原文超过 3 万字，请按章节拆分后重新上传')
        if empty:
            warnings.append('以下页未提取到文字，可能为扫描页或空白页：' + '、'.join(map(str, empty)))
        warnings.append('PDF 阅读顺序、表格和公式可能失真；图片中的文字不会识别，请对照原文件核对。')
    elif kind == 'docx':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 2000 or sum(i.file_size for i in members) > 20 * 1024 * 1024:
                raise ValueError('Word 解压后过大，请按章节拆分')
            if len({i.filename for i in members}) != len(members):
                raise ValueError('Word 文件包含重复条目')
            raw = archive.read('word/document.xml')
            # No DTD/entities, external relationship resolution or filesystem extraction.
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                raise ValueError('不支持含实体声明的 Word 文件')
            root = ElementTree.fromstring(raw)
            ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            for paragraph in root.iter(ns + 'p'):
                text = ''.join(n.text or '' if n.tag == ns+'t' else '\t' if n.tag == ns+'tab' else '\n'
                               for n in paragraph.iter() if n.tag in {ns+'t', ns+'tab', ns+'br'})
                if text.strip():
                    parts.append(text.strip())
            warnings.append('仅提取 Word 正文和表格中的段落；图片、页眉页脚、批注和嵌入对象未导入。请核对表格关系及修订内容。')
    else:
        raise ValueError('仅支持 PDF 或 DOCX；旧版 DOC 请另存为 DOCX')
    text = '\n\n'.join(parts)
    if len(text) > MAX_TEXT:
        raise ValueError('解析原文超过 3 万字，请按章节拆分后重新上传')
    if len(text.strip()) < 30 or '\x00' in text or '\ufffd' in text:
        raise ValueError('未提取到足够的可靠文字；扫描件请先 OCR，并核对原文后再导入')
    return {'text': text, 'warnings': warnings, 'characters': len(text)}


async def preview_document(data: bytes, kind: str) -> dict:
    # A killed worker cannot keep consuming CPU after an HTTP timeout/cancellation.
    async with _slots:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).resolve()), kind,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(process.communicate(data), timeout=20)
            if process.returncode:
                raise ValueError('文件解析失败或超出资源限制，请导出为较小的 PDF/DOCX 后重试')
            result = json.loads(output)
            if 'error' in result:
                raise ValueError(result['error'])
            return result
        except asyncio.TimeoutError:
            raise ValueError('文件解析超时，请按章节拆分后重试') from None
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


if __name__ == '__main__':
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    try:
        value = parse_document(sys.stdin.buffer.read(MAX_BYTES + 1), sys.argv[1])
    except ValueError as exc:
        value = {'error': str(exc)}
    except Exception:
        value = {'error': '文件已损坏或格式不受支持，请重新导出 PDF/DOCX'}
    sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False).encode('utf-8'))
