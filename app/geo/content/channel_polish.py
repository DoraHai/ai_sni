"""渠道稿 AI 润色：母稿草案 → 正式可发的渠道成稿。

无 LLM / 失败时回退确定性 adapt，并做发布向清洗（去草案标记、事实卡编号等）。
提示词默认见 channel_polish_defaults；租户覆盖经 prompts= 传入。

成文门控（full_article_v2）：任一 quality issue 在多轮重写后仍存在则硬失败，
不落库「伪正稿」、不标 publish_ready。
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


class ArticleQualityError(GeoContentError):
    """渠道成稿未达完整文章硬标准（应拦截，不得 soft-pass）。"""

    def __init__(self, issues: list[str]):
        self.issues = list(issues or [])
        msg = "渠道成稿未达完整文章标准：" + "；".join(self.issues[:6])
        super().__init__(msg)


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

# full_article_v2 thresholds
_MIN_LONG_PARAS = 5
_LONG_PARA_PURE_CHARS = 100
_OPENING_MIN_CHARS = 120
_MAX_QUALITY_RETRIES = 2  # total LLM attempts = 1 + retries


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


def _is_heading_block(b: str) -> bool:
    return bool(re.match(r"^#{1,3}\s+\S", (b or "").strip()))


def _is_table_block(b: str) -> bool:
    return (b or "").count("|") >= 2 and "---" in (b or "")


def _is_mostly_list_block(b: str) -> bool:
    lines = [ln.strip() for ln in (b or "").splitlines() if ln.strip()]
    if not lines:
        return False
    listish = sum(
        1
        for ln in lines
        if re.match(r"^[-*+]\s+", ln) or re.match(r"^\d+[.)]\s+", ln)
    )
    return listish >= max(1, int(len(lines) * 0.6))


def _pure_prose_len(b: str) -> int:
    pure = re.sub(r"[#>*\-|\d.\s]", "", b or "")
    pure = re.sub(r"\*\*", "", pure)
    return len(pure)


def assess_article_quality(
    md: str,
    *,
    min_chars: int,
    channel: str = "",
    brand: str | None = None,
    facts: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Hard full-article gate. Empty list = pass; any issue = must rewrite or reject."""
    text = md or ""
    issues: list[str] = []
    if facts is not None:
        from app.geo.content.claim_guard import format_ungrounded, ungrounded_claims

        claims = ungrounded_claims(text, facts)
        if claims:
            issues.append("无依据表述：" + format_ungrounded(claims))
    chars = _body_char_count(text)
    if chars < min_chars:
        issues.append(f"字数不足（{chars}/{min_chars}），未达完整文章体量")

    # GEO：无品牌提及则无法被引擎推荐/引用
    if brand and str(brand).strip():
        from app.geo.content.brand_geo import (
            brand_presence_issues,
            extract_conclusion_from_md,
            extract_opening_from_md,
        )

        issues.extend(
            brand_presence_issues(
                brand=brand,
                full_text=text,
                direct_answer=extract_opening_from_md(text),
                conclusion=extract_conclusion_from_md(text),
                require_opening=True,
                require_conclusion=True,
            )
        )

    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    long_paras: list[str] = []
    short_bold_leads = 0
    bullet_lines = 0
    prose_blocks: list[str] = []

    for b in blocks:
        if _is_heading_block(b):
            continue
        for ln in b.splitlines():
            s = ln.strip()
            if re.match(r"^[-*+]\s+", s) or re.match(r"^\d+[.)]\s+", s):
                bullet_lines += 1
            if re.match(r"^\*\*[^*]{2,48}\*\*", s) and _body_char_count(s) < 100:
                short_bold_leads += 1
        if _is_table_block(b) or _is_mostly_list_block(b):
            continue
        pure = _pure_prose_len(b)
        # skip single-line bold-only stubs
        if pure >= _LONG_PARA_PURE_CHARS and not re.match(r"^[-*+]\s", b.strip()):
            long_paras.append(b)
            prose_blocks.append(b)
        elif pure >= 40 and not re.match(r"^[-*+]\s", b.strip()):
            prose_blocks.append(b)

    headings = len(re.findall(r"(?m)^#{1,3}\s+\S", text))

    # Opening: first non-heading, non-table block must be a real paragraph
    opening = ""
    for b in blocks:
        if _is_heading_block(b) or _is_table_block(b):
            continue
        if _is_mostly_list_block(b):
            issues.append("开篇不能是列表/要点，须先写完整直接答案段落")
            break
        opening = b
        break
    if opening:
        open_chars = _pure_prose_len(opening)
        if open_chars < _OPENING_MIN_CHARS:
            issues.append(
                f"开篇直接答案过短（{open_chars}/{_OPENING_MIN_CHARS}字），"
                "请写成可摘取的完整首段"
            )
        if re.match(r"^\*\*[^*]{2,48}\*\*", opening.strip()) and open_chars < 160:
            issues.append("开篇禁止「加粗短句提纲」起手，请改为叙述段落")
    elif chars > 0:
        issues.append("缺少开篇正文段落")

    if len(long_paras) < _MIN_LONG_PARAS:
        issues.append(
            f"完整论述段落不足（{len(long_paras)}/{_MIN_LONG_PARAS}）："
            "每个小标题下至少两段完整叙述（每段约≥100字）"
        )

    # headings vs expansion density
    if headings >= 2 and len(long_paras) < headings + 2:
        issues.append("提纲感过重：小标题偏多而展开论述偏少")
    if headings < 2 and chars >= min_chars:
        # long free-form is ok without many H2; short free-form already fails min_chars/paras
        pass
    elif headings < 2 and len(long_paras) >= _MIN_LONG_PARAS:
        issues.append("缺少结构化小标题（至少 2 个中文小标题分段展开）")

    if short_bold_leads >= 2 and len(long_paras) <= short_bold_leads + 1:
        issues.append(
            "禁止连续「**加粗短句**」罗列维度；请改成连贯段落并配对比表"
        )
    if bullet_lines >= 6 and len(long_paras) < 4:
        issues.append("列表点过多、正文段落过少，不符合可发布完整文章")

    # comparison keywords → must have table + post-table interpretation
    from app.geo.content.md_to_html import ensure_comparison_table_hint

    need_table_kw = bool(
        re.search(
            r"对比|选型|维度|参数|优劣|比较|评估维度|关键考量",
            text,
        )
    )
    has_table = ensure_comparison_table_hint(text)
    if need_table_kw and not has_table:
        if channel in {"zhihu", "wechat", "website", "baijiahao", "toutiao", ""}:
            issues.append("文中出现对比/选型/维度，但缺少 Markdown 表格，请补表并解读")

    if has_table:
        # 表后紧邻须有解读段；若表后直接换小标题则不合格
        saw_table = False
        has_after = False
        for b in blocks:
            if _is_table_block(b):
                saw_table = True
                continue
            if not saw_table:
                continue
            if _is_heading_block(b):
                break
            if _pure_prose_len(b) >= 60 and not _is_mostly_list_block(b):
                has_after = True
            break
        if not has_after:
            issues.append("表格后缺少解读段落：请说明如何读表与适用建议")

    # conclusion-ish signal for longer channels
    if channel in {"zhihu", "wechat", "website"} and chars >= max(600, min_chars // 2):
        has_close = bool(
            re.search(
                r"(?m)^#{1,3}\s*.*(结论|建议|总结|下一步|决策)",
                text,
            )
            or re.search(r"建议|综上|因此在选型|下一步", text[-800:] if len(text) > 800 else text)
        )
        if not has_close:
            issues.append("文末缺少结论/可执行建议段落")

    # internal leak
    if re.search(r"事实卡|【草案】|待终审|仅供内部", text):
        issues.append("正文仍含内部草案用语，请清洗后再提交")

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


def _finalize_publish_body(
    channel: str, body_md: str, *, quality: str
) -> tuple[str, dict[str, Any]]:
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
        "delivery": (
            "html_publish_ready"
            if quality == "publish_ready"
            else "html_preview_only"
        ),
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


def _coerce_body(raw_body: str) -> str:
    if raw_body.lstrip().startswith("<") and "</" in raw_body:
        from app.geo.content.md_to_html import html_to_plain

        return html_to_plain(raw_body) + "\n"
    return strip_draft_markers(raw_body)


async def polish_for_channel(
    channel: str,
    title: str,
    body_md: str,
    outline: dict[str, Any] | None = None,
    *,
    llm: dict[str, str] | None = None,
    brand: str | None = None,
    prompts: dict[str, Any] | None = None,
    facts: list[dict[str, Any]] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Return (title, body_markdown, meta). meta includes body_html for publish.

    Enforces full_article_v2 hard gate. After up to 2 rewrite retries, any remaining
    quality issue raises ArticleQualityError (no soft-pass).
    """
    from app.geo.content.channel_registry import profile_key_for_registry_type

    profile = get_profile(channel) or get_profile(profile_key_for_registry_type(channel) or "")
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
        "hard_gate": True,
        "article_requirements": {
            "min_long_paragraphs": _MIN_LONG_PARAS,
            "long_paragraph_min_chars": _LONG_PARA_PURE_CHARS,
            "min_chars": min_chars,
            "opening_paragraph_min_chars": _OPENING_MIN_CHARS,
            "min_headings": 2,
            "no_bold_bullet_outline": True,
            "need_table_when_comparing": True,
            "need_table_interpretation": True,
            "need_conclusion": True,
            "fail_if_any_issue": True,
        },
        "brand_required": bool(brand),
        "facts": (facts or [])[:12],
        "delivery_note": (
            "写成可直接发表的完整文章；系统会严格门控，提纲体/过短/缺表一律驳回。"
            "禁止加粗短句罗列；每节至少两段完整叙述。"
            "只使用 facts 里的陈述；禁止编造数字、识别率、满意度、并发、成功案例、头部客户。"
            "事实卡没有的数据就不要写，不要补行业常见值。"
            + (
                f"GEO：开篇与结论必须自然点名品牌「{brand}」，禁止无品牌品类科普。"
                if brand
                else ""
            )
        ),
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
    out_body = _coerce_body(raw_body)

    issues = assess_article_quality(
        out_body, min_chars=min_chars, channel=profile.key, brand=brand, facts=facts
    )
    retry_used = 0
    while issues and retry_used < _MAX_QUALITY_RETRIES:
        retry_used += 1
        brand_fix = (
            f"开篇与结论必须写出品牌「{brand}」（GEO 硬标准）；"
            if brand
            else ""
        )
        fix_user = {
            **base_user,
            "rewrite_mode": True,
            "rewrite_attempt": retry_used,
            "previous_draft": out_body[:9000],
            "quality_issues": issues,
            "instruction": (
                f"第 {retry_used} 次硬性重写：上一版未过发布门控。"
                "请整篇重写为完整成文章（不是提纲、不是 Brief）："
                f"{brand_fix}"
                f"开篇直接答案≥{_OPENING_MIN_CHARS}字；"
                f"至少 {_MIN_LONG_PARAS} 个完整论述段（每段≥{_LONG_PARA_PURE_CHARS}字）；"
                "至少 2 个中文小标题；去掉连续加粗短句；"
                "有对比必须 GFM 表且表后解读；文末结论与可执行建议。"
                "仍只返回 JSON {title, body_markdown}。"
            ),
        }
        try:
            data2 = await _llm_channel_json(
                system=system,
                user_payload=fix_user,
                llm=llm,
                temperature=0.45 + 0.05 * retry_used,
            )
            out_title, raw_body = _parse_llm_body_title(
                data2, fallback_title=out_title, title_max=profile.title_max
            )
            out_body = _coerce_body(raw_body)
            issues = assess_article_quality(
                out_body,
                min_chars=min_chars,
                channel=profile.key,
                brand=brand,
                facts=facts,
            )
        except (DeepSeekError, GeoContentError):
            # keep previous issues; try next rewrite or hard-fail
            break

    if issues:
        raise ArticleQualityError(issues)

    out_body, fin = _finalize_publish_body(
        channel,
        out_body,
        quality="publish_ready",
    )
    chars = _body_char_count(out_body)
    meta = {
        "polish": "llm_v5",
        "engine": "llm_channel_polish_v5_hard_gate",
        "quality": "publish_ready",
        "fallback": False,
        "body_chars": chars,
        "provider": (llm or {}).get("provider") or "env",
        "prompt_source": "tenant" if prompts else "defaults",
        "quality_issues": [],
        "quality_retry": retry_used,
        "article_standard": "full_article_v2",
        "hard_gate": True,
        **fin,
    }
    return out_title, out_body, meta


def unpublished_adapt_fallback(
    channel: str,
    title: str,
    body_md: str,
    outline: dict[str, Any] | None,
    issues: list[str],
) -> tuple[str, str, dict[str, Any]]:
    """Keep a tab for every selected channel; never mark it publish_ready."""
    from app.geo.content.variants import adapt_for_channel

    cleaned = strip_draft_markers(body_md)
    t, b = adapt_for_channel(channel, title, cleaned, outline or {})
    b, fin = _finalize_publish_body(
        channel, b, quality="adapted_draft_not_publishable"
    )
    return (
        t,
        b,
        {
            "polish": "quality_fallback",
            "engine": "deterministic_v1",
            "quality": "adapted_draft_not_publishable",
            "publishable": False,
            "fallback": True,
            "hard_gate": True,
            "article_standard": "full_article_v2",
            "quality_issues": list(issues or [])[:8],
            **fin,
        },
    )


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
    facts: list[dict[str, Any]] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Prefer LLM formal channel polish with hard quality gate.

    ArticleQualityError always propagates (no silent fallback to pseudo-publishable draft).
    Other polish failures fall back to deterministic adapt, clearly marked not publishable.
    """
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
                facts=facts,
            )
        except ArticleQualityError as exc:
            t, b, meta = unpublished_adapt_fallback(
                channel, title, body_md, outline, list(exc.issues)
            )
            return t, b, meta
        except GeoContentError:
            pass

    cleaned = strip_draft_markers(body_md)
    t, b = adapt_for_channel(channel, title, cleaned, outline)
    b, fin = _finalize_publish_body(
        channel, b, quality="adapted_draft_not_publishable"
    )
    return (
        t,
        b,
        {
            "polish": "none",
            "engine": "deterministic_v1",
            "quality": "adapted_draft_not_publishable",
            "fallback": True,
            "hard_gate": True,
            "article_standard": "full_article_v2",
            "publishable": False,
            **fin,
        },
    )
