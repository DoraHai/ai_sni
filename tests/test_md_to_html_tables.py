"""Markdown → HTML publish conversion (tables + headings)."""

from __future__ import annotations

from app.geo.content.md_to_html import (
    ensure_comparison_table_hint,
    html_to_plain,
    markdown_to_publish_html,
)


def test_table_renders_html():
    md = """## 对比

| 维度 | 方案A | 方案B |
| --- | --- | --- |
| 价格 | 低 | 高 |
| 部署 | 云 | 本地 |

结论：按预算选择。
"""
    html = markdown_to_publish_html(md)
    assert "<table" in html
    assert "<th>" in html
    assert "方案A" in html
    assert "<h2>" in html
    assert ensure_comparison_table_hint(md) is True


def test_no_table():
    md = "只有段落。\n\n第二段。"
    html = markdown_to_publish_html(md)
    assert "<p>" in html
    assert "<table" not in html
    assert ensure_comparison_table_hint(md) is False


def test_faq_answers_stay_after_their_questions():
    md = "- **Q：** 问题一\n答案一\n- **Q：** 问题二\n答案二"
    rendered = markdown_to_publish_html(md)
    positions = [rendered.index(text) for text in ("问题一", "答案一", "问题二", "答案二")]
    assert positions == sorted(positions)


def test_indented_answer_stays_inside_its_list_item():
    rendered = markdown_to_publish_html("- 问题一\n  答案一\n- 问题二\n  答案二")
    assert "<li>问题一 答案一</li><li>问题二 答案二</li>" in rendered


def test_ordered_list_precedes_following_paragraph():
    rendered = markdown_to_publish_html("1. 步骤一\n操作说明")
    assert rendered.index("步骤一") < rendered.index("操作说明")


def test_list_precedes_horizontal_rule():
    for marker in ("-", "1."):
        rendered = markdown_to_publish_html(f"{marker} 核对项\n---\n说明")
        assert rendered.index("核对项") < rendered.index("<hr/>") < rendered.index("说明")


def test_html_to_plain():
    plain = html_to_plain("<p>你好<strong>世界</strong></p>")
    assert "你好" in plain
    assert "世界" in plain


def test_finalize_via_polish_helper():
    from app.geo.content.channel_polish import _finalize_publish_body

    body, meta = _finalize_publish_body(
        "wechat",
        "## 选型\n\n| 项 | 值 |\n| --- | --- |\n| a | 1 |\n",
        quality="publish_ready",
    )
    assert meta["export_format"] == "html"
    assert meta["has_table"] is True
    assert "<table" in meta["body_html"]
