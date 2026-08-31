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
    """公众号成稿：保留母稿全文，来源改为文末参考说明。"""
    return assemble_channel_article(body_md, outline, profile=profile)


def _strip_leading_h1(body: str) -> str:
    return re.sub(r"^#\s+[^\n]+\n+", "", (body or "").lstrip(), count=1)


def _replace_faq_section(body: str, limit: int) -> str:
    trimmed = _extract_faq_block(body, limit=limit)
    if not trimmed:
        return body
    if re.search(r"(?im)^##\s*常见问题", body):
        trimmed = trimmed.replace("## FAQ", "## 常见问题", 1)
    replaced, n = re.subn(
        r"(?is)##\s*(?:FAQ|常见问题)\s*\n.*?(?=\n##\s|\Z)",
        trimmed.rstrip() + "\n\n",
        body,
        count=1,
    )
    return replaced if n else body


def assemble_channel_article(
    body_md: str,
    outline: dict[str, Any] | None = None,
    *,
    profile: ChannelProfile,
) -> str:
    """把母稿装配成可复制的渠道成稿（全文，不是抽三段提纲）。"""
    outline = outline or {}
    body = _strip_leading_h1(body_md or "").strip()
    direct = _direct_answer(body_md, outline)
    if direct:
        head = body[:360]
        if direct not in head:
            body = f"{direct}\n\n{body}".strip()

    if profile.faq_limit:
        body = _replace_faq_section(body, profile.faq_limit)

    if profile.mode == "wechat" or profile.key == "wechat":
        body = re.sub(r"(?is)##\s*来源\s*\n.*?(?=\n##\s|\Z)", "", body).strip()
        src = _sources_block(body_md, wechat_style=True)
        if src:
            body = f"{body.rstrip()}\n\n{src.strip()}".strip()
    elif profile.keep_sources and "## 来源" not in body and "## 参考说明" not in body:
        src = _sources_block(body_md, wechat_style=False)
        if src:
            body = f"{body.rstrip()}\n\n{src.strip()}".strip()

    updated = _updated_line(body_md, outline)
    if updated and "更新时间" not in body:
        body = f"{body.rstrip()}\n\n{updated}".strip()
    return body.strip() + "\n"


def adapt_for_channel(
    channel: str, title: str, body_md: str, outline: dict[str, Any] | None = None
) -> tuple[str, str]:
    profile = get_profile(channel)
    if profile is None:
        raise GeoContentError(f"不支持的渠道: {channel}")
    outline = outline or {}
    out_title = shorten_title(title, profile.title_max)
    if profile.mode == "full":
        body = (body_md or "").strip()
        return out_title, body + ("\n" if body else "")
    # 公众号 / 知乎等「必须渠道」出全文成稿；信息流短渠道仍压缩。
    if profile.mode == "wechat" or profile.keep_definition:
        return out_title, assemble_channel_article(body_md, outline, profile=profile)
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
        if profile.mode == "short" and not profile.keep_definition:
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
        "export_format": profile.export_format or "html",
    }
    if extra:
        # prefer publish-ready html from polish pipeline
        for k in (
            "body_html",
            "body_plain",
            "has_table",
            "delivery",
            "polish",
            "fallback",
            "quality",
            "engine",
            "body_chars",
            "export_format",
        ):
            if k in extra and extra[k] is not None:
                meta[k] = extra[k]
    if extra:
        meta.update(extra)
    return meta
