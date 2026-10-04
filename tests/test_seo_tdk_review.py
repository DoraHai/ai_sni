"""Stored-only TDK context, Word and HTML layout contracts."""
from io import BytesIO
from types import SimpleNamespace as Row

from docx import Document
import pytest

from app.seo_tdk_review import (DEFAULT_TDK_REVIEW_SECTIONS, build_tdk_review_context,
    render_tdk_review_docx, render_tdk_review_html, validate_tdk_review_template)
from scripts.generate_tdk_review_sample import sample_context


def _text(doc):
    return "\n".join([p.text for p in doc.paragraphs] + [c.text for table in doc.tables for row in table.rows for c in row.cells])


def test_context_uses_only_stored_suggestions_and_keyword_mapping():
    page = Row(id=1, url="https://example.invalid/a", title="A Keyword", meta_description="some content",
        meta_keywords=None, h1="KEYWORD", title_suggestion="new keyword", description_suggestion=None,
        target_keyword_id=5, status="proposed")
    context = build_tdk_review_context(site_name="site", pages=[page], batch_id=1,
        keywords=[Row(id=5, keyword="keyword", landing_page=None)], links=[])
    item = context["pages"][0]
    assert item["tdk"][1]["suggested"] == "暂无建议"
    assert item["tdk"][2]["suggested"] == "暂无建议"
    assert item["keywords"][0]["title"] and item["keywords"][0]["h1"]
    assert item["keywords"][0]["suggested_title"] and not item["keywords"][0]["description"]
    assert not item["links"]
    assert "暂无内链建议数据" in render_tdk_review_html(context)


def test_template_validates_keys_order_and_toggles():
    sections = list(DEFAULT_TDK_REVIEW_SECTIONS)[::-1]
    assert validate_tdk_review_template(sections)["sections"][0]["key"] == "client_comment"
    with pytest.raises(ValueError):
        validate_tdk_review_template(sections[:-1] + [sections[0]])
    with pytest.raises(ValueError):
        validate_tdk_review_template(sections, {"char_counts": "yes", "rationale": True})


def test_docx_opens_contains_image_annotations_and_header_label():
    context = sample_context()
    assert len(context["pages"]) == 3
    assert context["pages"][0]["links"] and not context["pages"][1]["links"]
    assert context["pages"][1]["tdk"][0]["suggested"] != "暂无建议"
    assert context["pages"][2]["tdk"][0]["suggested"] == "暂无建议"
    data = render_tdk_review_docx(context)
    doc = Document(BytesIO(data))
    text = _text(doc)
    assert "①" in text and "②" in text and "③" in text
    assert "暂无截图" in text and "暂无建议" in text
    assert "【示例数据】演示站点" in text
    assert "示例数据" in doc.sections[0].header.paragraphs[0].text
    assert len(doc.inline_shapes) == 1


def test_html_escapes_script_and_word_strips_xml_invalid_controls():
    context = sample_context()
    context["pages"][0]["title"] = "<script>alert(1)</script>\x01"
    context["pages"][0]["tdk"][0]["current"] = "unsafe\x02"
    html = render_tdk_review_html(context)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "\x01" not in html and "\x02" not in html
    doc = Document(BytesIO(render_tdk_review_docx(context)))
    assert "\x01" not in _text(doc) and "\x02" not in _text(doc)
