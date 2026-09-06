"""Render export content without mutating a channel draft or its review metadata."""
import hashlib
import json

from app.geo.content.md_to_html import markdown_to_publish_html, html_to_plain, ensure_comparison_table_hint


def export_revision(variant, current_article_id):
    meta = variant.adapt_meta or {}
    fields = [variant.id, variant.article_version_id, current_article_id, variant.title,
              variant.body_markdown, meta.get('body_html')]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def export_view(variant, current_article_id):
    meta = dict(variant.adapt_meta or {})
    html = meta.get('body_html') or markdown_to_publish_html(variant.body_markdown or '', wrap_article=True)
    return {
        'channel': variant.channel, 'title': variant.title,
        'variant_id': variant.id, 'article_version_id': variant.article_version_id,
        'export_revision': export_revision(variant, current_article_id),
        'body_html': html, 'body_plain': meta.get('body_plain') or html_to_plain(html),
        'body_markdown': variant.body_markdown, 'export_format': 'html',
        'has_table': bool(meta.get('has_table')) or ensure_comparison_table_hint(variant.body_markdown or ''),
        'quality': meta.get('quality') or 'unknown', 'status': variant.status,
        'copy_hint': '可复制 HTML 内容；导出不代表已通过审核或已发布',
    }
