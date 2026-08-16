"""Markdown → 可粘贴发布的 HTML（支持 GFM 表格）。

渠道正稿对外交付用 HTML，不再以 MD 作为发布格式。
母稿/润色中间态仍可用 Markdown 编写。
"""

from __future__ import annotations

import html
import re
from typing import Iterable


def _escape(s: str) -> str:
    return html.escape(s or "", quote=True)


def _inline(text: str) -> str:
    """Bold / italic / code / links (simple)."""
    t = _escape(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" rel="noopener noreferrer">\1</a>',
        t,
    )
    return t


def _is_table_sep(line: str) -> bool:
    s = line.strip()
    if "|" not in s:
        return False
    # | --- | :---: | ---: |
    core = s.strip("|").strip()
    parts = [p.strip() for p in core.split("|")]
    if not parts:
        return False
    return all(re.fullmatch(r":?-{3,}:?", p or "") for p in parts)


def _split_row(line: str) -> list[str]:
    s = line.strip().strip("|")
    return [c.strip() for c in s.split("|")]


def _table_html(header: list[str], rows: list[list[str]]) -> str:
    ths = "".join(f"<th>{_inline(h)}</th>" for h in header)
    body_rows = []
    for row in rows:
        # pad/truncate to header width
        cells = (row + [""] * len(header))[: len(header)]
        body_rows.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
    return (
        '<table border="1" cellpadding="8" cellspacing="0" '
        'style="border-collapse:collapse;width:100%;margin:12px 0;">'
        f"<thead><tr>{ths}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>\n"
    )


def _flush_para(buf: list[str], out: list[str]) -> None:
    if not buf:
        return
    text = " ".join(x.strip() for x in buf if x.strip())
    if text:
        out.append(f"<p>{_inline(text)}</p>\n")
    buf.clear()


def _flush_list(items: list[str], ordered: bool, out: list[str]) -> None:
    if not items:
        return
    tag = "ol" if ordered else "ul"
    lis = "".join(f"<li>{_inline(i)}</li>" for i in items)
    out.append(f"<{tag}>{lis}</{tag}>\n")
    items.clear()


def markdown_to_publish_html(md: str, *, wrap_article: bool = True) -> str:
    """Convert channel markdown body to publish-ready HTML with tables."""
    text = (md or "").replace("\r\n", "\n").strip()
    if not text:
        return ""

    lines = text.split("\n")
    out: list[str] = []
    para: list[str] = []
    ul_items: list[str] = []
    ol_items: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # blank
        if not stripped:
            _flush_para(para, out)
            _flush_list(ul_items, False, out)
            _flush_list(ol_items, True, out)
            i += 1
            continue

        # GFM table: header + separator
        if (
            "|" in stripped
            and i + 1 < n
            and _is_table_sep(lines[i + 1])
        ):
            _flush_para(para, out)
            _flush_list(ul_items, False, out)
            _flush_list(ol_items, True, out)
            header = _split_row(stripped)
            i += 2
            rows: list[list[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                if _is_table_sep(lines[i]):
                    i += 1
                    continue
                rows.append(_split_row(lines[i]))
                i += 1
            out.append(_table_html(header, rows))
            continue

        # headings
        hm = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if hm:
            _flush_para(para, out)
            _flush_list(ul_items, False, out)
            _flush_list(ol_items, True, out)
            level = len(hm.group(1))
            out.append(f"<h{level}>{_inline(hm.group(2).strip())}</h{level}>\n")
            i += 1
            continue

        # blockquote
        if stripped.startswith(">"):
            _flush_para(para, out)
            _flush_list(ul_items, False, out)
            _flush_list(ol_items, True, out)
            q = stripped.lstrip(">").strip()
            out.append(f"<blockquote><p>{_inline(q)}</p></blockquote>\n")
            i += 1
            continue

        # unordered list
        um = re.match(r"^[-*+]\s+(.+)$", stripped)
        if um:
            _flush_para(para, out)
            _flush_list(ol_items, True, out)
            ul_items.append(um.group(1).strip())
            i += 1
            continue

        # ordered list
        om = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if om:
            _flush_para(para, out)
            _flush_list(ul_items, False, out)
            ol_items.append(om.group(1).strip())
            i += 1
            continue

        # hr
        if re.fullmatch(r"-{3,}|\*{3,}", stripped):
            _flush_para(para, out)
            out.append("<hr/>\n")
            i += 1
            continue

        para.append(stripped)
        i += 1

    _flush_para(para, out)
    _flush_list(ul_items, False, out)
    _flush_list(ol_items, True, out)

    body = "".join(out).strip()
    if wrap_article and body:
        return (
            '<div class="geo-channel-article" '
            'style="font-size:16px;line-height:1.75;color:#1f2937;">\n'
            f"{body}\n</div>\n"
        )
    return body + ("\n" if body else "")


def html_to_plain(html_text: str) -> str:
    """Rough plain text for digests."""
    t = re.sub(r"(?is)<script[^>]*>.*?</script>", "", html_text or "")
    t = re.sub(r"(?is)<style[^>]*>.*?</style>", "", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</p>", "\n", t)
    t = re.sub(r"(?i)</tr>", "\n", t)
    t = re.sub(r"(?i)</h[1-6]>", "\n", t)
    t = re.sub(r"(?i)<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def ensure_comparison_table_hint(md: str) -> bool:
    """Whether body already contains a markdown table."""
    lines = (md or "").splitlines()
    for i, line in enumerate(lines[:-1]):
        if "|" in line and _is_table_sep(lines[i + 1]):
            return True
    return False
