"""Bounded XLSX parsing and template helpers for SEO publication imports."""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape


MAX_XLSX_BYTES = 3 * 1024 * 1024
MAX_ARCHIVE_BYTES = 12 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 200
MAX_IMPORT_ROWS = 1000
MAX_IMPORT_COLUMNS = 20

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REF_RE = re.compile(r"^([A-Z]+)")

_HEADER_ALIASES = {
    "content_id": {"contentid", "id", "内容id", "内容资产id", "资产id"},
    "title": {"title", "内容标题", "文章标题", "标题"},
    "page_url": {"pageurl", "url", "发布链接", "发布地址", "已发布链接", "链接"},
    "platform": {"platform", "发布平台", "平台", "渠道"},
    "published_at": {"publishedat", "发布时间", "发布日期", "发布日"},
}


class XlsxImportError(ValueError):
    """Raised when an import workbook is malformed or outside safe limits."""


def _normalized_header(value: object) -> str:
    return re.sub(r"[\s_\-（）()]+", "", str(value or "").strip()).casefold()


def _column_index(reference: str) -> int:
    match = _CELL_REF_RE.match(reference.upper())
    if not match:
        raise XlsxImportError("Excel 单元格位置无效")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - 64
    return result - 1


def _safe_xml(blob: bytes) -> ElementTree.Element:
    if b"<!DOCTYPE" in blob.upper() or b"<!ENTITY" in blob.upper():
        raise XlsxImportError("Excel 文件包含不安全的 XML 声明")
    try:
        return ElementTree.fromstring(blob)
    except ElementTree.ParseError as exc:
        raise XlsxImportError("Excel 文件结构损坏") from exc


def _archive(blob: bytes) -> zipfile.ZipFile:
    if not blob:
        raise XlsxImportError("请选择非空的 Excel 文件")
    if len(blob) > MAX_XLSX_BYTES:
        raise XlsxImportError("Excel 文件不能超过 3 MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise XlsxImportError("文件不是有效的 .xlsx 工作簿") from exc
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        archive.close()
        raise XlsxImportError("Excel 文件包含过多内部文件")
    total = 0
    for member in members:
        normalized = posixpath.normpath(member.filename.replace("\\", "/"))
        if normalized.startswith("../") or normalized.startswith("/"):
            archive.close()
            raise XlsxImportError("Excel 文件包含不安全的内部路径")
        total += member.file_size
    if total > MAX_ARCHIVE_BYTES:
        archive.close()
        raise XlsxImportError("Excel 解压后内容过大")
    return archive


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    names = set(archive.namelist())
    if "xl/workbook.xml" not in names:
        raise XlsxImportError("Excel 工作簿缺少 workbook.xml")
    workbook = _safe_xml(archive.read("xl/workbook.xml"))
    sheet = workbook.find(f".//{{{_MAIN_NS}}}sheet")
    relationship_id = sheet.get(f"{{{_REL_NS}}}id") if sheet is not None else None
    if relationship_id and "xl/_rels/workbook.xml.rels" in names:
        relationships = _safe_xml(archive.read("xl/_rels/workbook.xml.rels"))
        for relationship in relationships.findall(f".//{{{_PKG_REL_NS}}}Relationship"):
            if relationship.get("Id") == relationship_id:
                target = relationship.get("Target") or ""
                path = posixpath.normpath(posixpath.join("xl", target))
                if path in names and path.startswith("xl/worksheets/"):
                    return path
    if "xl/worksheets/sheet1.xml" in names:
        return "xl/worksheets/sheet1.xml"
    raise XlsxImportError("Excel 工作簿没有可读取的首个工作表")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _safe_xml(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(f".//{{{_MAIN_NS}}}t")) for item in root.findall(f"{{{_MAIN_NS}}}si")]


def _cell_value(cell: ElementTree.Element, shared: list[str]) -> str:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{{{_MAIN_NS}}}t"))
    value = cell.find(f"{{{_MAIN_NS}}}v")
    raw = value.text if value is not None and value.text is not None else ""
    if cell_type == "s" and raw:
        try:
            return shared[int(raw)]
        except (ValueError, IndexError) as exc:
            raise XlsxImportError("Excel 共享文本索引无效") from exc
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def parse_publication_xlsx(blob: bytes) -> list[dict[str, str | int]]:
    """Read the first worksheet and return normalized publication rows."""
    with _archive(blob) as archive:
        shared = _shared_strings(archive)
        sheet = _safe_xml(archive.read(_first_sheet_path(archive)))
    table: list[tuple[int, list[str]]] = []
    for row in sheet.findall(f".//{{{_MAIN_NS}}}row"):
        try:
            row_number = int(row.get("r") or len(table) + 1)
        except ValueError as exc:
            raise XlsxImportError("Excel 行号无效") from exc
        values = [""] * MAX_IMPORT_COLUMNS
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            index = _column_index(cell.get("r") or "A1")
            if index < MAX_IMPORT_COLUMNS:
                values[index] = _cell_value(cell, shared).strip()
        if any(values):
            table.append((row_number, values))
    if not table:
        raise XlsxImportError("Excel 工作表为空")
    header_row, headers = table[0]
    mapped: dict[int, str] = {}
    mapped_fields: set[str] = set()
    for index, header in enumerate(headers):
        normalized = _normalized_header(header)
        for field, aliases in _HEADER_ALIASES.items():
            if normalized in aliases:
                if field in mapped_fields:
                    raise XlsxImportError(f"Excel 表头“{header}”对应的字段重复")
                mapped[index] = field
                mapped_fields.add(field)
                break
    if "page_url" not in mapped.values():
        raise XlsxImportError(f"第 {header_row} 行缺少“发布链接”列")
    if not {"content_id", "title"}.intersection(mapped.values()):
        raise XlsxImportError(f"第 {header_row} 行至少需要“内容资产ID”或“内容标题”列")
    if len(table) - 1 > MAX_IMPORT_ROWS:
        raise XlsxImportError(f"单次最多导入 {MAX_IMPORT_ROWS} 行")
    result: list[dict[str, str | int]] = []
    for row_number, values in table[1:]:
        record: dict[str, str | int] = {"row_number": row_number}
        for index, field in mapped.items():
            record[field] = values[index]
        if any(str(record.get(field) or "").strip() for field in ("content_id", "title", "page_url", "platform", "published_at")):
            result.append(record)
    if not result:
        raise XlsxImportError("Excel 中没有可导入的数据行")
    return result


def normalize_content_id(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError("内容资产ID必须是整数") from exc
    if number <= 0 or not number.is_integer():
        raise ValueError("内容资产ID必须是正整数")
    return int(number)


def normalize_publication_url(value: object) -> tuple[str, str]:
    url = str(value or "").strip()
    if not url:
        raise ValueError("发布链接不能为空")
    if len(url) > 2000 or any(character.isspace() for character in url):
        raise ValueError("发布链接格式无效")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("发布链接必须是无账号信息的 http 或 https 地址")
    return url, parsed.hostname.lower().removeprefix("www.")


def normalize_published_at(value: object, *, default: datetime | None = None) -> datetime:
    text = str(value or "").strip()
    if not text:
        return default or datetime.utcnow()
    try:
        serial = float(text)
        if 1 <= serial <= 2_958_465:
            return datetime(1899, 12, 30) + timedelta(days=serial)
    except ValueError:
        pass
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for pattern in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError("发布时间格式无效，建议使用 YYYY-MM-DD HH:MM:SS")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def build_publication_template() -> bytes:
    """Create a dependency-free XLSX template with one example row."""
    rows = [
        ["内容资产ID", "内容标题", "发布链接", "发布平台", "发布时间"],
        ["123", "示例文章（ID或标题至少填写一项）", "https://example.com/article", "示例平台", "2026-08-18 12:00:00"],
    ]
    row_xml = []
    for row_index, values in enumerate(rows, 1):
        cells = []
        for column_index, value in enumerate(values):
            column = chr(65 + column_index)
            cells.append(f'<c r="{column}{row_index}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{_MAIN_NS}" xmlns:r="{_REL_NS}"><sheets><sheet name="发布链接登记" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_PKG_REL_NS}"><Relationship Id="rId1" Type="{_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{_MAIN_NS}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>',
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))
    return stream.getvalue()
