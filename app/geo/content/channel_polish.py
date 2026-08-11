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


def assess_article_quality(md: str, *, min_chars: int, channel: str = "") -> list[str]:
    """Reject outline-like or too-thin copy. Returns human-readable issue list (empty=ok)."""
    text = md or ""
    issues: list[str] = []
    chars = _body_char_count(text)
    if chars < min_chars:
        issues.append(f"字数不足（{chars}/{min_chars}），未达完整文章体量")

    # Long prose paragraphs (not headings / not pure bullets)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    long_paras: list[str] = []
    short_bold_leads = 0
    bullet_lines = 0
    for b in blocks:
        if re.match(r"^#{1,3}\s+", b):
            continue
        # multi-line block: count each bullet
        for ln in b.splitlines():
            s = ln.strip()
            if re.match(r"^[-*+]\s+", s) or re.match(r"^\d+[.)]\s+", s):
                bullet_lines += 1
            if re.match(r"^\*\*[^*]{2,40}\*\*", s) and _body_char_count(s) < 90:
                short_bold_leads += 1
        pure = re.sub(r"[#>*\-|\d.\s]", "", b)
        pure = re.sub(r"\*\*", "", pure)
        if len(pure) >= 80 and not re.match(r"^[-*+]\s", b):
            # skip pure table blocks
            if not (b.count("|") >= 2 and "---" in b):
                long_paras.append(b)

    headings = len(re.findall(r"(?m)^#{1,3}\s+\S", text))
    if len(long_paras) < 4:
        issues.append(
            f"完整论述段落不足（{len(long_paras)}/4）："
            "当前更像提纲，请把每个小标题写成至少两段完整叙述"
        )
    if headings >= 2 and len(long_paras) < headings + 1:
        issues.append("提纲感过重：小标题偏多而展开论述偏少")
    if short_bold_leads >= 3 and len(long_paras) < short_bold_leads:
        issues.append(
            "禁止连续「**加粗短句**」罗列维度；请改成连贯段落并配对比表"
        )
    if bullet_lines >= 8 and len(long_paras) < 3:
        issues.append("列表点过多、正文段落过少，不符合可发布完整文章")

    # comparison / multi-dimension keywords without table
    from app.geo.content.md_to_html import ensure_comparison_table_hint

    need_table_kw = bool(
        re.search(
            r"对比|选型|维度|参数|优劣|比较|评估维度|关键考量",
            text,
        )
    )
    if need_table_kw and not ensure_comparison_table_hint(text):
        # zhihu/wechat often need table when discussing multi-criteria
        if channel in {"zhihu", "wechat", "website", "baijiahao", ""}:
            issues.append("文中出现对比/选型/维度，但缺少 Markdown 表格，请补表并解读")

    return issues


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


def _finalize_publish_body(channel: str, body_md: str, *, quality: str) -> tuple[str, dict[str, Any]]:
    """Sanitize MD, convert to HTML for publish delivery."""
    from app.geo.content.md_to_html import (
        ensure_comparison_table_hint,
        html_to_plain,
        markdown_to_publish_html,
    )

    body = strip_draft_markers(body_md)
    body = re.sub(r"(?m)^##\s*FAQ\s*$", "## 常见问题", body)
    if "事实卡" in body:
        body = strip_draft_markers(body)
    if not body.endswith("\n"):
        body += "\n"
    body_html = markdown_to_publish_html(body, wrap_article=True)
    return body, {
        "body_html": body_html,
        "body_plain": html_to_plain(body_html),
        "export_format": "html",
        "has_table": ensure_comparison_table_hint(body),
        "quality": quality,
        "delivery": "html_publish_ready",
    }


async def _llm_channel_json(
    *,
    system: str,
    user_payload: dict[str, Any],
    llm: dict[str, str] | None,
    temperature: float = 0.55,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"timeout": 150, "temperature": temperature}
    if llm:
        kwargs.update(
            {
                "api_key": llm.get("api_key"),
                "base_url": llm.get("base_url"),
                "model": llm.get("model"),
            }
        )
    user = json.dumps(user_payload, ensure_ascii=False)
    data = await chat_json(system, user, **kwargs)
    if not isinstance(data, dict):
        raise GeoContentError("渠道润色返回格式无效")
    return data


def _parse_llm_body_title(
    data: dict[str, Any],
    *,
    fallback_title: str,
    title_max: int,
) -> tuple[str, str]:
    out_title = shorten_title(
        str(data.get("title") or fallback_title).strip(), title_max
    )
    raw_body = str(data.get("body_markdown") or data.get("body_html") or "").strip()
    if not out_title:
        raise GeoContentError("渠道润色缺少标题")
    if not raw_body:
        raise GeoContentError("渠道润色缺少正文")
    return out_title, raw_body


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
    """Return (title, body_markdown, meta). meta includes body_html for publish.

    Enforces article-level quality (paragraph density, anti-outline, tables) and
    retries once with explicit fix instructions when the first draft is thin.
    """
    profile = get_profile(channel)
    if profile is None:
        raise GeoContentError(f"不支持的渠道: {channel}")

    outline = outline or {}
    clean_body = strip_draft_markers(body_md)
    use_ai = bool(llm) or is_enabled()
    if not use_ai:
        raise GeoContentError("未配置可用 LLM，无法渠道润色")

    system, voice, min_chars = _resolve_prompt_bundle(profile.key, prompts)
    base_user: dict[str, Any] = {
        "channel": profile.key,
        "channel_name": profile.display_name,
        "voice": voice,
        "title_max": profile.title_max,
        "faq_limit": profile.faq_limit,
        "min_body_chars": min_chars,
        "brand": brand or "",
        "master_title": title,
        "direct_answer": outline.get("direct_answer") or "",
        "master_markdown": clean_body[:14000],
        "notes": profile.notes,
        "output_goal": "full_publishable_article_not_outline",
        "require_markdown_table_for_comparison": True,
        "article_requirements": {
            "min_long_paragraphs": 4,
            "min_chars": min_chars,
            "no_bold_bullet_outline": True,
            "need_table_when_comparing": True,
            "opening_paragraph_min_chars": 100,
        },
        "delivery_note": "写成可直接发表的完整文章；系统会转 HTML。禁止提纲体。",
    }

    try:
        data = await _llm_channel_json(
            system=system, user_payload=base_user, llm=llm, temperature=0.55
        )
    except DeepSeekError as exc:
        raise GeoContentError(f"渠道润色失败: {exc}") from exc

    out_title, raw_body = _parse_llm_body_title(
        data, fallback_title=title, title_max=profile.title_max
    )

    # HTML mistaken return
    if raw_body.lstrip().startswith("<") and "</" in raw_body:
        from app.geo.content.md_to_html import html_to_plain

        out_body = html_to_plain(raw_body) + "\n"
    else:
        out_body = strip_draft_markers(raw_body)

    issues = assess_article_quality(
        out_body, min_chars=min_chars, channel=profile.key
    )
    retry_used = False
    if issues:
        retry_used = True
        fix_user = {
            **base_user,
            "rewrite_mode": True,
            "previous_draft": out_body[:8000],
            "quality_issues": issues,
            "instruction": (
                "上一版不合格（提纲感/过短/缺表）。请整篇重写为完整文章："
                "加长论述段落、去掉连续加粗短句、补对比表并在表后解读。"
                "仍只返回 JSON {title, body_markdown}。"
            ),
        }
        try:
            data2 = await _llm_channel_json(
                system=system, user_payload=fix_user, llm=llm, temperature=0.5
            )
            out_title, raw_body = _parse_llm_body_title(
                data2, fallback_title=out_title, title_max=profile.title_max
            )
            if raw_body.lstrip().startswith("<") and "</" in raw_body:
                from app.geo.content.md_to_html import html_to_plain

                out_body = html_to_plain(raw_body) + "\n"
            else:
                out_body = strip_draft_markers(raw_body)
            issues = assess_article_quality(
                out_body, min_chars=min_chars, channel=profile.key
            )
        except (DeepSeekError, GeoContentError):
            # keep first draft issues
            pass

    if issues:
        # Hard fail only when severely thin; otherwise soft-pass with flags
        chars = _body_char_count(out_body)
        severe = chars < max(200, min_chars // 2) or len(issues) >= 3
        if severe:
            raise GeoContentError(
                "渠道成稿未达完整文章标准：" + "；".join(issues[:4])
            )

    out_body, fin = _finalize_publish_body(
        channel,
        out_body,
        quality="publish_ready" if not issues else "publish_ready_with_warnings",
    )
    chars = _body_char_count(out_body)
    meta = {
        "polish": "llm_v4",
        "engine": "llm_channel_polish_v4_article",
        "quality": "publish_ready" if not issues else "publish_ready_with_warnings",
        "fallback": False,
        "body_chars": chars,
        "provider": (llm or {}).get("provider") or "env",
        "prompt_source": "tenant" if prompts else "defaults",
        "quality_issues": issues,
        "quality_retry": retry_used,
        "article_standard": "full_article_v1",
        **fin,
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
    b, fin = _finalize_publish_body(channel, b, quality="adapted_publish_html")
    return (
        t,
        b,
        {
            "polish": "none",
            "engine": "deterministic_v1",
            "quality": fin.get("quality") or "adapted_publish_html",
            "fallback": True,
            **fin,
        },
    )
