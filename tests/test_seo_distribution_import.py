from __future__ import annotations

import io
import zipfile
from datetime import datetime

import pytest

from app.seo_distribution_import import (
    XlsxImportError,
    build_publication_template,
    normalize_content_id,
    normalize_publication_url,
    normalize_published_at,
    parse_publication_xlsx,
)


def test_generated_template_is_a_parseable_xlsx() -> None:
    rows = parse_publication_xlsx(build_publication_template())

    assert rows == [
        {
            "row_number": 2,
            "content_id": "123",
            "title": "示例文章（ID或标题至少填写一项）",
            "page_url": "https://example.com/article",
            "platform": "示例平台",
            "published_at": "2026-08-18 12:00:00",
        }
    ]


def test_normalizers_accept_excel_ids_dates_and_safe_http_urls() -> None:
    assert normalize_content_id("12.0") == 12
    assert normalize_publication_url("https://www.example.com/path") == (
        "https://www.example.com/path",
        "example.com",
    )
    assert normalize_published_at("2026/08/18 12:30") == datetime(2026, 8, 18, 12, 30)
    assert normalize_published_at("45567") == datetime(2024, 10, 2)


@pytest.mark.parametrize("value", ["ftp://example.com/a", "https://user:pass@example.com/a", "https://exa mple.com"])
def test_publication_url_rejects_unsupported_or_credentialed_urls(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_publication_url(value)


def test_parser_rejects_unsafe_xml() -> None:
    source = build_publication_template()
    with zipfile.ZipFile(io.BytesIO(source)) as original:
        files = {name: original.read(name) for name in original.namelist()}
    files["xl/workbook.xml"] = b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)

    with pytest.raises(XlsxImportError, match="不安全"):
        parse_publication_xlsx(stream.getvalue())


def test_distribution_frontend_uses_preview_before_commit() -> None:
    root = __import__("pathlib").Path(__file__).parents[1]
    api = (root / "frontend/src/api/seo.js").read_text(encoding="utf-8")
    view = (root / "frontend/src/views/seo/SeoDistributionView.vue").read_text(encoding="utf-8")

    assert "importSeoPublishedLinks" in api
    assert "dry_run: dryRun" in api
    assert "Excel 批量登记" in view
    assert "dryRun:true" in view
    assert "dryRun:false" in view
    assert "整批不会写入" in view
    assert "下载 Excel 模板" in view
