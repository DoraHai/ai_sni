"""Extract imported articles into the content workbench's draft format."""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup


class ArticleImportError(ValueError):
    """Raised when an imported document cannot be converted into an article."""


SUPPORTED_FILE_EXTENSIONS = {".docx", ".html", ".htm", ".md", ".pdf", ".txt"}
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_DOCX_UNPACKED_BYTES = 32 * 1024 * 1024
MAX_DOCX_ENTRIES = 2000
PDF_TIMEOUT_SECONDS = 10
_PDF_SLOTS = threading.BoundedSemaphore(2)
_CJK_OR_WORD = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+")
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


def source_word_count(text: str) -> int:
    """Count Latin tokens and individual CJK characters for a useful preview size."""
    return len(_CJK_OR_WORD.findall(text or ""))


def _clean_text(text: str) -> str:
    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip())


def _preview(*, title: str, body_markdown: str, source_type: str, source_url: str) -> dict:
    body = _clean_text(body_markdown)
    if not body:
        raise ArticleImportError('文件里没有可读取的正文，请换成可复制文字的文件')
    normalized_title = _clean_text(title).split("\n", 1)[0].strip()
    if not normalized_title:
        raise ArticleImportError('文章缺少标题，请补充标题后再导入')
    return {
        "title": normalized_title[:300],
        "body_markdown": body,
        "source_type": source_type,
        "source_url": source_url,
        "word_count": source_word_count(body),
    }


def _filename_title(filename: str) -> str:
    return Path(filename or "imported-article").stem.strip() or "imported-article"


def _markdown_title_and_body(text: str, *, fallback_title: str) -> tuple[str, str]:
    lines = _clean_text(text).split("\n")
    for index, line in enumerate(lines):
        match = _MARKDOWN_HEADING.match(line)
        if match:
            return match.group(1).strip(), "\n".join(lines[:index] + lines[index + 1 :])
        if line.strip():
            break
    return fallback_title, text


def _read_pdf(raw: bytes) -> tuple[str, str | None]:
    # A small compressed stream can expand far beyond the upload/page limit.
    # The worker is disposable and has CPU/address-space limits on Linux.
    if not _PDF_SLOTS.acquire(blocking=False):
        raise ArticleImportError('PDF 预览正忙，请稍后重试')
    try:
        result = subprocess.run(
            [sys.executable, '-I', '-B', str(Path(__file__).with_name('pdf_import_worker.py')), str(MAX_PDF_PAGES)],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=PDF_TIMEOUT_SECONDS, check=False,
        )
        if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
            raise ArticleImportError('PDF 解析超出资源限制或文件损坏，请拆分或改用文字文件')
        data = json.loads(result.stdout)
        if data.get('error'):
            raise ArticleImportError(data['error'])
        return data['text'], data['title']
    except subprocess.TimeoutExpired as exc:
        raise ArticleImportError('PDF 解析超时，请拆分或改用文字文件') from exc
    except ArticleImportError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ArticleImportError('无法读取 PDF 文件，请检查文件是否完整') from exc
    finally:
        _PDF_SLOTS.release()


def _read_docx(raw: bytes) -> tuple[str, str | None]:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - dependency is installed in deployments
        raise ArticleImportError('暂时无法读取 DOCX 文件，请改用文字文件') from exc
    try:
        # Check both declared and actually expanded sizes before python-docx
        # loads XML/media. The compressed upload is separately bounded.
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (len(entries) > MAX_DOCX_ENTRIES
                    or sum(entry.file_size for entry in entries) > MAX_DOCX_UNPACKED_BYTES):
                raise ArticleImportError('DOCX 解压内容过大，请拆分后重试')
            expanded = 0
            for entry in entries:
                with archive.open(entry) as member:
                    while chunk := member.read(64 * 1024):
                        expanded += len(chunk)
                        if expanded > MAX_DOCX_UNPACKED_BYTES:
                            raise ArticleImportError('DOCX 解压内容过大，请拆分后重试')
        document = Document(io.BytesIO(raw))
        text = "\n\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())
        title = (document.core_properties.title or "").strip() or None
        return text, title
    except ArticleImportError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ArticleImportError('无法读取 DOCX 文件，请检查文件是否完整') from exc


def preview_html_document(*, html: str, source_url: str) -> dict:
    """Build a URL preview from the primary readable region of an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for node in soup.select("script, style, noscript, nav, footer, header, aside, form"):
        node.decompose()
    content = soup.select_one("article, main, [role='main']") or soup.body or soup
    heading = content.find(["h1", "h2"]) if content else None
    title = page_title or (heading.get_text(" ", strip=True) if heading else "")
    blocks = []
    if content is not None:
        for node in content.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "pre"]):
            text = node.get_text(" ", strip=True)
            if text:
                blocks.append(text)
    body = "\n\n".join(blocks) if blocks else (content.get_text("\n", strip=True) if content else "")
    return _preview(
        title=title or '导入文章',
        body_markdown=body,
        source_type="url",
        source_url=source_url,
    )


def preview_text_document(*, filename: str, raw: bytes) -> dict:
    """Preview a UTF-8 text or Markdown upload without persisting it."""
    extension = Path(filename or "").suffix.lower()
    if extension not in {".txt", ".md"}:
        raise ArticleImportError('不支持的文件类型，请选择文字或 Markdown 文件')
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ArticleImportError('文字文件请使用 UTF-8 编码保存后再上传') from exc
    title = _filename_title(filename)
    body = text
    if extension == ".md":
        title, body = _markdown_title_and_body(text, fallback_title=title)
    return _preview(title=title, body_markdown=body, source_type="file", source_url=filename)


def preview_file_document(*, filename: str, raw: bytes) -> dict:
    """Preview a supported uploaded document without saving the raw source."""
    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_FILE_EXTENSIONS:
        raise ArticleImportError('不支持的文件类型，请选择 PDF、DOCX、文字、Markdown 或 HTML 文件')
    if len(raw) > MAX_FILE_BYTES:
        raise ArticleImportError('导入文件不能超过 10 MiB，请拆分后上传')
    if not raw:
        raise ArticleImportError('上传文件为空，请重新选择文件')
    if extension in {".txt", ".md"}:
        return preview_text_document(filename=filename, raw=raw)
    if extension in {".html", ".htm"}:
        try:
            html = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ArticleImportError('HTML 文件请使用 UTF-8 编码保存后再上传') from exc
        preview = preview_html_document(html=html, source_url=filename)
        preview["source_type"] = "file"
        return preview
    text, extracted_title = _read_pdf(raw) if extension == ".pdf" else _read_docx(raw)
    return _preview(
        title=extracted_title or _filename_title(filename),
        body_markdown=text,
        source_type="file",
        source_url=filename,
    )


def _validate_web_url(value: str) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
        parsed.port  # Validate malformed/out-of-range explicit ports as input errors.
    except ValueError as exc:
        raise ArticleImportError("A complete http or https URL is required") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ArticleImportError('请填写完整的 http:// 或 https:// 文章链接')
    if parsed.username or parsed.password:
        raise ArticleImportError('文章链接不能包含账号或密码')
    return url


async def preview_url_document(url: str) -> dict:
    """Fetch a public URL and return its article preview."""
    source_url = _validate_web_url(url)
    try:
        from app.geo.audit import GeoAuditError, safe_fetch

        document = await safe_fetch(source_url, article_import=True)
    except GeoAuditError as exc:
        raise ArticleImportError(str(exc)) from exc
    return preview_html_document(html=document.html, source_url=document.final_url)


# Compact aliases for route handlers and callers that use the feature name.
preview_file = preview_file_document
preview_url = preview_url_document
