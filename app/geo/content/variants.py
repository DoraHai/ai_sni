"""渠道版本改写：Channel Profile 驱动的确定性装配（不依赖平台 API / LLM）。"""

from __future__ import annotations

import re
from typing import Any

from app.geo.content.channel_profiles import (
    CHANNEL_PROFILES,
    SUPPORTED_CHANNELS,
    ChannelProfile,
    get_profile,
    normalize_channels,
)

__all__ = [
    "SUPPORTED_CHANNELS",
    "GeoContentError",
    "adapt_for_channel",
    "shorten_title",
    "rewrite_short_form",
    "normalize_channels",
]


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
    kept = lines[: max(4, limit * 2)]
    return "## FAQ\n\n" + "\n".join(kept) + "\n"


def _extract_section(body: str, heading_pat: str) -> str:
    match = re.search(
        rf"(?is)##\s*(?:{heading_pat})\s*\n(.*?)(?=\n##\s|\Z)", body or ""
    )
    if not match:
        return ""
    return match.group(0).strip() + "\n"


def _direct_answer(body_md: str, outline: dict[str, Any] | None) -> str:
    outline = outline or {}
    direct = (outline.get("direct_answer") or "").strip()
    if direct:
        return direct
    paras = [
        p.strip()
        for p in re.split(r"\n\s*\n", body_md or "")
        if p.strip() and not p.strip().startswith("#")
    ]
    return paras[0] if paras else ""


def _updated_line(body_md: str, outline: dict[str, Any] | None) -> str:
    outline = outline or {}
    updated = re.search(r"\*更新时间：.*?(\d{4}-\d{2}-\d{2}).*?\*", body_md or "")
    if updated:
        return f"*更新时间：{updated.group(1)}*"
    ua = outline.get("updated_at")
    if ua:
        return f"*更新时间：{ua}*"
    return ""


def _sources_block(body_md: str, *, wechat_style: bool = False) -> str:
    sources = re.findall(r"(?m)^.*来源[:：].*$", body_md or "")
    if not sources:
        return ""
    if wechat_style:
        lines = ["## 参考说明", ""]
        lines.extend(f"- {s.lstrip('- ').strip()}" for s in sources[:6])
        lines.append("")
        lines.append("（公众号环境外链可能不可点，请以官网原文为准。）")
        return "\n".join(lines) + "\n"
    lines = ["## 来源", ""]
    lines.extend(f"- {s.lstrip('- ').strip()}" for s in sources[:8])
    return "\n".join(lines) + "\n"


def rewrite_short_form(
    body_md: str,
    outline: dict[str, Any] | None = None,
    *,
    profile: ChannelProfile | None = None,
) -> str:
    profile = profile or CHANNEL_PROFILES["zhihu"]
    outline = outline or {}
    parts: list[str] = []
    direct = _direct_answer(body_md, outline)
    if direct:
        parts.extend([direct, ""])

    if profile.keep_definition:
        definition = _extract_section(body_md, r"定义|是什么|简介")
        if definition:
            parts.extend(definition.splitlines()[:8])
            parts.append("")

    faq = _extract_faq_block(body_md, limit=profile.faq_limit)
    if faq:
        parts.append(faq)

    if profile.keep_conclusion:
        conclusion = _extract_section(body_md, r"结论|总结|一句话结论")
        if conclusion:
            parts.append(conclusion)

    if profile.keep_sources:
        src = _sources_block(body_md, wechat_style=False)
        if src:
            parts.append(src)

    updated = _updated_line(body_md, outline)
    if updated:
        parts.append(updated)
    return "\n".join(parts).strip() + "\n"


def rewrite_wechat_form(
    body_md: str, outline: dict[str, Any] | None = None, *, profile: ChannelProfile
) -> str:
    """公众号：比知乎略长，保留定义与结论，来源改文末说明。"""
    outline = outline or {}
    parts: list[str] = []
    direct = _direct_answer(body_md, outline)
    if direct:
        parts.extend([direct, ""])

    definition = _extract_section(body_md, r"定义|是什么|简介")
    if definition:
        parts.extend(definition.splitlines()[:12])
        parts.append("")

    # keep a short middle section if present
    compare = _extract_section(body_md, r"对比|怎么选|选型|适用场景")
    if compare:
        lines = compare.splitlines()
        parts.extend(lines[:10])
        parts.append("")

    faq = _extract_faq_block(body_md, limit=profile.faq_limit)
    if faq:
        parts.append(faq)

    conclusion = _extract_section(body_md, r"结论|总结|一句话结论")
    if conclusion:
        parts.append(conclusion)

    src = _sources_block(body_md, wechat_style=True)
    if src:
        parts.append(src)

    updated = _updated_line(body_md, outline)
    if updated:
        parts.append(updated)
    return "\n".join(parts).strip() + "\n"


def adapt_for_channel(
    channel: str, title: str, body_md: str, outline: dict[str, Any] | None = None
) -> tuple[str, str]:
    profile = get_profile(channel)
    if profile is None:
        raise GeoContentError(f"不支持的渠道: {channel}")
    outline = outline or {}
    if profile.mode == "full":
        out_title = shorten_title(title, profile.title_max)
        return out_title, body_md
    out_title = shorten_title(title, profile.title_max)
    if profile.mode == "wechat":
        return out_title, rewrite_wechat_form(body_md, outline, profile=profile)
    return out_title, rewrite_short_form(body_md, outline, profile=profile)


def build_adapt_meta(
    channel: str,
    *,
    master_version_id: int | None,
    title: str,
    body_md: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = get_profile(channel)
    if profile is None:
        return {"channel": channel, "error": "unsupported"}
    dropped: list[str] = []
    if profile.mode != "full":
        if not profile.keep_definition:
            dropped.append("definition")
        if profile.faq_limit < 8:
            dropped.append(f"faq_trimmed_to_{profile.faq_limit}")
        if profile.mode == "short":
            dropped.append("long_body_sections")
        if profile.key == "wechat":
            dropped.append("clickable_external_links")
    meta = {
        "channel": channel,
        "profile_key": profile.key,
        "profile_mode": profile.mode,
        "display_name": profile.display_name,
        "master_version_id": master_version_id,
        "title_max": profile.title_max,
        "title_len": len(title or ""),
        "body_chars": len(body_md or ""),
        "dropped": dropped,
        "engine": "deterministic_v1",
        "quality": "adapted_draft",
    }
    if extra:
        meta.update(extra)
    return meta
