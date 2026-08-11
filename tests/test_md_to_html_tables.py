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
