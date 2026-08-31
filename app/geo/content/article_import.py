"""Extract imported articles into the content workbench's draft format."""

from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup


class ArticleImportError(ValueError):
    """Raised when an imported document cannot be converted into an article."""


SUPPORTED_FILE_EXTENSIONS = {".docx", ".html", ".htm", ".md", ".pdf", ".txt"}
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
        raise ArticleImportError("No readable article text was extracted")
    normalized_title = _clean_text(title).split("\n", 1)[0].strip()
    if not normalized_title:
        raise ArticleImportError("The imported article needs a title")
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
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is installed in deployments
        raise ArticleImportError("PDF import support is unavailable") from exc
    try:
        reader = PdfReader(io.BytesIO(raw))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        metadata = reader.metadata or {}
        title = getattr(metadata, "title", None) or metadata.get("/Title")
        return text, str(title).strip() if title else None
    except Exception as exc:  # noqa: BLE001
        raise ArticleImportError("Unable to read the PDF document") from exc


def _read_docx(raw: bytes) -> tuple[str, str | None]:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - dependency is installed in deployments
        raise ArticleImportError("DOCX import support is unavailable") from exc
    try:
        document = Document(io.BytesIO(raw))
        text = "\n\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())
        title = (document.core_properties.title or "").strip() or None
        return text, title
    except Exception as exc:  # noqa: BLE001
        raise ArticleImportError("Unable to read the DOCX document") from exc


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
        title=title or "Imported article",
        body_markdown=body,
        source_type="url",
        source_url=source_url,
    )


def preview_text_document(*, filename: str, raw: bytes) -> dict:
    """Preview a UTF-8 text or Markdown upload without persisting it."""
    extension = Path(filename or "").suffix.lower()
    if extension not in {".txt", ".md"}:
        raise ArticleImportError(f"Unsupported file type: {extension or 'unknown'}")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ArticleImportError("Text uploads must use UTF-8 encoding") from exc
    title = _filename_title(filename)
    body = text
    if extension == ".md":
        title, body = _markdown_title_and_body(text, fallback_title=title)
    return _preview(title=title, body_markdown=body, source_type="file", source_url=filename)


def preview_file_document(*, filename: str, raw: bytes) -> dict:
    """Preview a supported uploaded document without saving the raw source."""
    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_FILE_EXTENSIONS:
        raise ArticleImportError(f"Unsupported file type: {extension or 'unknown'}")
    if not raw:
        raise ArticleImportError("The uploaded file is empty")
    if extension in {".txt", ".md"}:
        return preview_text_document(filename=filename, raw=raw)
    if extension in {".html", ".htm"}:
        try:
            html = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ArticleImportError("HTML uploads must use UTF-8 encoding") from exc
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
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ArticleImportError("A complete http or https URL is required")
    if parsed.username or parsed.password:
        raise ArticleImportError("Article URLs cannot contain credentials")
    return url


async def preview_url_document(url: str) -> dict:
    """Fetch a public URL and return its article preview."""
    source_url = _validate_web_url(url)
    try:
        from app.geo.audit import GeoAuditError, safe_fetch

        document = await safe_fetch(source_url)
    except GeoAuditError as exc:
        raise ArticleImportError(str(exc)) from exc
    return preview_html_document(html=document.html, source_url=document.final_url)


# Compact aliases for route handlers and callers that use the feature name.
preview_file = preview_file_document
preview_url = preview_url_document
