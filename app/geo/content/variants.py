"""渠道版本改写（Demo：确定性规则，不依赖外部平台 API）。"""

from __future__ import annotations

import re
from typing import Any

SUPPORTED_CHANNELS = ("website", "zhihu", "baijiahao")


class GeoContentError(ValueError):
    """内容域业务错误（路由层转 HTTPException）。"""


def shorten_title(title: str, max_len: int = 40) -> str:
    title = (title or "").strip()
    if len(title) <= max_len:
        return title
    return title[: max_len - 1] + "…"


def _extract_faq_block(body: str, limit: int = 3) -> str:
    match = re.search(r"(?is)##\s*FAQ\s*\n(.*?)(?=\n##\s|\Z)", body or "")
    if not match:
        match = re.search(r"(?is)##\s*常见问题\s*\n(.*?)(?=\n##\s|\Z)", body or "")
    if not match:
        return ""
    lines = [ln for ln in match.group(1).splitlines() if ln.strip()]
    # keep roughly first N Q/A pairs (2 lines each)
    kept = lines[: max(4, limit * 2)]
    return "## FAQ\n\n" + "\n".join(kept) + "\n"


def _extract_section(body: str, heading_pat: str) -> str:
    match = re.search(
        rf"(?is)##\s*(?:{heading_pat})\s*\n(.*?)(?=\n##\s|\Z)", body or ""
    )
    if not match:
        return ""
    return match.group(0).strip() + "\n"


def rewrite_short_form(body_md: str, outline: dict[str, Any] | None = None) -> str:
    outline = outline or {}
    direct = (outline.get("direct_answer") or "").strip()
    if not direct:
        paras = [
            p.strip()
            for p in re.split(r"\n\s*\n", body_md or "")
            if p.strip() and not p.strip().startswith("#")
        ]
        direct = paras[0] if paras else ""

    parts = [direct, ""]
    definition = _extract_section(body_md, r"定义|是什么|简介")
    if definition:
        # keep short
        lines = definition.splitlines()
        parts.extend(lines[:8])
        parts.append("")
    faq = _extract_faq_block(body_md, limit=3)
    if faq:
        parts.append(faq)
    conclusion = _extract_section(body_md, r"结论|总结|一句话结论")
    if conclusion:
        parts.append(conclusion)
    # sources list from bullet lines containing 来源
    sources = re.findall(r"(?m)^.*来源[:：].*$", body_md or "")
    if sources:
        parts.append("## 来源")
        parts.append("")
        parts.extend(f"- {s.lstrip('- ').strip()}" for s in sources[:8])
        parts.append("")
    updated = re.search(r"\*更新时间：.*?(\d{4}-\d{2}-\d{2}).*?\*", body_md or "")
    if updated:
        parts.append(f"*更新时间：{updated.group(1)}*")
    else:
        ua = outline.get("updated_at")
        if ua:
            parts.append(f"*更新时间：{ua}*")
    return "\n".join(parts).strip() + "\n"


def adapt_for_channel(
    channel: str, title: str, body_md: str, outline: dict[str, Any] | None = None
) -> tuple[str, str]:
    if channel not in SUPPORTED_CHANNELS:
        raise GeoContentError(f"不支持的渠道: {channel}")
    if channel == "website":
        return title, body_md
    return shorten_title(title), rewrite_short_form(body_md, outline)
