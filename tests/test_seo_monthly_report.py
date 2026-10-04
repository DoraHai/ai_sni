"""Monthly report facts, sections and HTML safety."""
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from app.seo_monthly_report import (DEFAULT_REPORT_SECTIONS, MAX_APPENDIX_IMAGES,
    build_report_context, render_report_html, validate_report_sections)


def context(**kwargs):
    return build_report_context(**{**{"site_name": "站点", "month": "2026-09", "rows": [],
        "generated_at": datetime(2026, 10, 1, tzinfo=timezone.utc)}, **kwargs})


def test_missing_traffic_and_kept_values():
    empty = context()
    assert [row["status"] for row in empty["traffic"]] == ["未配置", "未配置"]
    assert all(row["uv"] == "无数据" and row["pv"] == "无数据" for row in empty["traffic"])
    configured = context(sources=[SimpleNamespace(source="ga4", enabled=True)])
    assert [row["status"] for row in configured["traffic"]] == ["未配置", "未拉取"]
    disabled = context(sources=[SimpleNamespace(source="ga4", enabled=False)])
    assert disabled["traffic"][1]["status"] == "未拉取"
    monthly = SimpleNamespace(source="ga4", uv=0, pv=21, status="ok", fetched_at=None,
        raw_meta={"partial": True}, last_error_code="provider_error", last_error_message="连接失败")
    traffic = context(monthly_rows=[monthly])["traffic"][1]
    assert traffic["uv"] == "0" and traffic["pv"] == "21"
    assert traffic["status"] == "成功" and "最近一次拉取失败" in traffic["note"]
    assert "尚未结束" in traffic["note"]
    failed = SimpleNamespace(source="ga4", uv=8, pv=None, status="failed", fetched_at=None,
        error_message="连接失败", error_code="provider_error", raw_meta={},
        last_error_code=None, last_error_message=None)
    kept = context(monthly_rows=[failed])["traffic"][1]
    assert kept["uv"] == "8" and kept["pv"] == "无数据"
    assert "最近一次拉取失败" in kept["note"]


def test_section_order_visibility_and_escaping():
    data = context(rows=[{"title": "<script>alert(1)</script>", "platform": "平台",
        "page_url": "https://example.com/?a=<tag>", "capture_kind": "none", "capture_status": "无截图",
        "published_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "captured_at": datetime(2026, 10, 1, tzinfo=timezone.utc)}],
        sample_label="示例数据")
    sections = [dict(item) for item in reversed(DEFAULT_REPORT_SECTIONS)]
    sections[0]["enabled"] = False
    html = render_report_html(data, sections)
    assert html.index("发布明细") < html.index('section class="section cover"')
    assert "<h2>封面</h2>" not in html
    assert "@page detail{size:A4 landscape" in html
    assert ".publication_detail{page:detail}" in html
    assert "thead{display:table-header-group}" in html
    assert html.count('class="datetime">2026-10-01 08:00') == 2
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert "示例数据" in html and "截图附录</h2>" not in html
    assert "&lt;tag&gt;" in html


def test_appendix_cap_and_missing_reason():
    image = Image.new("RGB", (40, 20), "white")
    out = BytesIO(); image.save(out, "PNG")
    rows = [{"title": f"截图{i}", "image_key": str(i), "capture_kind": "auto",
             "capture_status": "自动截图", "page_url": "https://example.com", "captured_at": None}
            for i in range(MAX_APPENDIX_IMAGES + 2)]
    rows.append({"title": "失败记录", "image_key": None, "capture_kind": "failed",
                 "capture_status": "失败：超时", "page_url": "https://example.com"})
    html = render_report_html(context(rows=rows, images={str(i): out.getvalue() for i in range(MAX_APPENDIX_IMAGES)}),
        [{**item, "enabled": item["key"] == "screenshot_appendix"} for item in DEFAULT_REPORT_SECTIONS])
    assert html.count('src="data:image/jpeg;base64,') == MAX_APPENDIX_IMAGES
    assert "其余 2 张截图未收录" in html and "失败：超时" in html


def test_broken_stored_image_is_reported_as_unavailable():
    row = {"title": "旧截图", "image_key": "broken", "capture_kind": "auto",
           "capture_status": "自动截图", "page_url": "https://example.com"}
    html = render_report_html(context(rows=[row], images={"broken": b"not an image"}),
        [{**item, "enabled": item["key"] == "screenshot_appendix"} for item in DEFAULT_REPORT_SECTIONS])
    assert "失败：截图图片不可用" in html


@pytest.mark.parametrize("change", [
    lambda rows: rows.clear(),
    lambda rows: rows[0].update(enabled=False) or [row.update(enabled=False) for row in rows],
    lambda rows: rows[0].update(key="traffic"),
    lambda rows: rows[0].update(title=" "),
])
def test_template_validation(change):
    rows = [dict(item) for item in DEFAULT_REPORT_SECTIONS]
    change(rows)
    with pytest.raises(ValueError):
        validate_report_sections(rows)
    assert len(validate_report_sections([dict(item) for item in DEFAULT_REPORT_SECTIONS])) == 5
