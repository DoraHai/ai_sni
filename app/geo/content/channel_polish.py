"""渠道稿 AI 润色：母稿草案 → 正式可发的渠道成稿。

无 LLM / 失败时回退确定性 adapt，并做发布向清洗（去草案标记、事实卡编号等）。
提示词默认见 channel_polish_defaults；租户覆盖经 prompts= 传入。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.geo.content.channel_polish_defaults import (
    DEFAULT_SYSTEM_PROMPT,
    default_min_body_chars,
    default_voice_for_channel,
)
from app.geo.content.channel_profiles import get_profile
from app.geo.content.variants import GeoContentError, adapt_for_channel, shorten_title

try:
    from app.ai.deepseek import DeepSeekError, chat_json, is_enabled
except Exception:  # pragma: no cover
    DeepSeekError = Exception  # type: ignore

    def is_enabled() -> bool:  # type: ignore
        return False

    async def chat_json(*args, **kwargs):  # type: ignore
        raise DeepSeekError("deepseek unavailable")


_DRAFT_TIP_RE = re.compile(
    r"(?ms)^\s*>\s*\*\*?草案提示\*\*?[^\n]*\n+(?:^\s*>[^\n]*\n+)*",
)
_DRAFT_DISCLAIMER_RE = re.compile(
    r"(?m)^.*(?:【草案】|须人工润色|仅供内部改稿|勿直接对外使用|待人工终审|需核验后方可发布).*$",
)
_FACT_REF_PAREN_RE = re.compile(r"[（(]\s*事实卡\s*#?\s*\d+\s*[）)]")
_FACT_REF_BARE_RE = re.compile(r"事实卡\s*#?\s*\d+")
_EN_HEADING_MAP = {
    "definition": "定义与背景",
    "comparison": "关键对比与考量",
    "faq": "常见问题",
    "conclusion": "结论与建议",
    "body": "正文",
}


def strip_draft_markers(md: str) -> str:
    """Remove draft banners / internal fact-card IDs so channel copy is outward-facing."""
    text = md or ""
    text = _DRAFT_TIP_RE.sub("", text)
    text = _DRAFT_DISCLAIMER_RE.sub("", text)
    text = _FACT_REF_PAREN_RE.sub("", text)
    text = _FACT_REF_BARE_RE.sub("", text)
    text = re.sub(r"[（(]\s*[）)]", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    for en, zh in _EN_HEADING_MAP.items():
        text = re.sub(rf"(?mi)^##\s*{en}\s*$", f"## {zh}", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + ("\n" if text else "")


def _body_char_count(md: str) -> int:
    return len(re.sub(r"\s+", "", md or ""))


def _resolve_prompt_bundle(
    channel: str, prompts: dict[str, Any] | None
) -> tuple[str, str, int]:
    prompts = prompts or {}
    system = (prompts.get("system_prompt") or "").strip() or DEFAULT_SYSTEM_PROMPT
    voice = (prompts.get("voice_prompt") or "").strip() or default_voice_for_channel(
        channel
    )
    raw_min = prompts.get("min_body_chars")
    if raw_min is None:
        min_chars = default_min_body_chars(channel)
    else:
        try:
            min_chars = int(raw_min)
        except (TypeError, ValueError):
            min_chars = default_min_body_chars(channel)
        min_chars = max(100, min(min_chars, 20000))
    return system, voice, min_chars


async def polish_for_channel(
    channel: str,
    title: str,
    body_md: str,
    outline: dict[str, Any] | None = None,
    *,
    llm: dict[str, str] | None = None,
    brand: str | None = None,
    prompts: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Return (title, body_markdown, meta). Raises GeoContentError on hard failure."""
    profile = get_profile(channel)
    if profile is None:
        raise GeoContentError(f"不支持的渠道: {channel}")

    outline = outline or {}
    clean_body = strip_draft_markers(body_md)
    use_ai = bool(llm) or is_enabled()
    if not use_ai:
        raise GeoContentError("未配置可用 LLM，无法渠道润色")

    system, voice, min_chars = _resolve_prompt_bundle(profile.key, prompts)
    user = json.dumps(
        {
            "channel": profile.key,
            "channel_name": profile.display_name,
            "voice": voice,
            "title_max": profile.title_max,
            "faq_limit": profile.faq_limit,
            "min_body_chars": min_chars,
            "brand": brand or "",
            "master_title": title,
            "direct_answer": outline.get("direct_answer") or "",
            "master_markdown": clean_body[:12000],
            "notes": profile.notes,
            "output_goal": "publish_ready_formal_copy",
        },
        ensure_ascii=False,
    )
    kwargs: dict[str, Any] = {}
    if llm:
        kwargs = {
            "api_key": llm.get("api_key"),
            "base_url": llm.get("base_url"),
            "model": llm.get("model"),
        }
    try:
        data = await chat_json(system, user, timeout=120, **kwargs)
    except DeepSeekError as exc:
        raise GeoContentError(f"渠道润色失败: {exc}") from exc

    if not isinstance(data, dict):
        raise GeoContentError("渠道润色返回格式无效")
    out_title = shorten_title(str(data.get("title") or title).strip(), profile.title_max)
    out_body = strip_draft_markers(str(data.get("body_markdown") or "").strip())
    if not out_title:
        raise GeoContentError("渠道润色缺少标题")
    out_body = re.sub(r"(?m)^##\s*FAQ\s*$", "## 常见问题", out_body)
    if "事实卡" in out_body:
        out_body = strip_draft_markers(out_body)
    chars = _body_char_count(out_body)
    if chars < max(40, min_chars // 2):
        raise GeoContentError(f"渠道润色结果过短（{chars} 字），未达正式成稿标准")
    if not out_body.endswith("\n"):
        out_body += "\n"
    meta = {
        "polish": "llm_v2",
        "engine": "llm_channel_polish_v2",
        "quality": "publish_ready",
        "fallback": False,
        "body_chars": chars,
        "provider": (llm or {}).get("provider") or "env",
        "prompt_source": "tenant" if prompts else "defaults",
    }
    return out_title, out_body, meta


async def adapt_or_polish_for_channel(
    channel: str,
    title: str,
    body_md: str,
    outline: dict[str, Any] | None = None,
    *,
    llm: dict[str, str] | None = None,
    brand: str | None = None,
    use_llm: bool = True,
    prompts: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Prefer LLM formal channel polish; fall back to deterministic adapt + sanitize."""
    outline = outline or {}
    if use_llm and (llm or is_enabled()):
        try:
            return await polish_for_channel(
                channel,
                title,
                body_md,
                outline,
                llm=llm,
                brand=brand,
                prompts=prompts,
            )
        except GeoContentError:
            pass

    cleaned = strip_draft_markers(body_md)
    t, b = adapt_for_channel(channel, title, cleaned, outline)
    b = strip_draft_markers(b)
    return (
        t,
        b,
        {
            "polish": "none",
            "engine": "deterministic_v1",
            "quality": "adapted_draft",
            "fallback": True,
        },
    )
