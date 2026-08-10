"""Wave C+ snapshot field suggestions from answer text (human confirm)."""

from __future__ import annotations

from typing import Any

from app.geo.content.snapshots import (
    extract_cited_urls_from_text,
    normalize_brand_position,
    normalize_citation_accuracy,
    normalize_competitors,
    normalize_sentiment,
    resolve_citation_format,
)


def brand_mentioned_in_text(text: str, brand_names: list[str]) -> bool | None:
    """Heuristic mention check; None when no brand names configured."""
    body = (text or "").lower()
    names = [n.strip().lower() for n in brand_names if str(n or "").strip()]
    if not body or not names:
        return None
    return any(n in body for n in names)


def normalize_suggest_payload(
    data: dict[str, Any] | None,
    *,
    raw_text: str,
    brand_names: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize LLM/heuristic suggest output for the visibility form."""
    payload = data if isinstance(data, dict) else {}
    brands = list(brand_names or [])
    heuristic = brand_mentioned_in_text(raw_text, brands)

    if "suggested_mentions_brand" in payload:
        mentions = bool(payload.get("suggested_mentions_brand"))
    elif heuristic is not None:
        mentions = heuristic
    else:
        mentions = False

    competitors = normalize_competitors(payload.get("competitors"))
    # Drop brand self-names from competitor suggestions.
    brand_lower = {b.strip().lower() for b in brands if str(b or "").strip()}
    competitors = [c for c in competitors if c.lower() not in brand_lower]

    position = normalize_brand_position(payload.get("brand_position"))
    if position == "unknown" and mentions:
        # Soft default when model omits position but affirms mention.
        if str(payload.get("brand_position") or "").strip() == "":
            position = "mentioned"

    sentiment = normalize_sentiment(payload.get("sentiment"))
    urls = extract_cited_urls_from_text(raw_text)
    citation_format = resolve_citation_format(
        payload.get("citation_format") or payload.get("suggested_citation_format"),
        cited_urls=urls,
        raw_text=raw_text,
        mentions_brand=mentions,
    )
    citation_accuracy = normalize_citation_accuracy(
        payload.get("citation_accuracy") or payload.get("suggested_citation_accuracy")
    )

    return {
        "suggested_mentions_brand": mentions,
        "suggested_competitors": competitors,
        "suggested_brand_position": position,
        "suggested_sentiment": sentiment,
        "suggested_cited_urls": urls,
        "suggested_citation_format": citation_format,
        "suggested_citation_accuracy": citation_accuracy,
        "source": "llm" if isinstance(data, dict) and data else "heuristic",
    }


def suggest_system_prompt(brand: str) -> str:
    return (
        "你是 GEO 可见度标注助手。根据给定的 AI 回答正文，抽取结构化标注。"
        "只返回 JSON："
        '{"suggested_mentions_brand": true/false, '
        '"competitors": ["竞品名"], '
        '"brand_position": "first|alternative|mentioned|absent|unknown", '
        '"sentiment": "positive|neutral|negative|unknown", '
        '"citation_format": "linked|plaintext|mixed|none|unknown", '
        '"citation_accuracy": "accurate|partial|inaccurate|unknown"}。'
        f"品牌参考名：「{brand}」。"
        "competitors 不要包含该品牌自身；没有竞品就返回 []。"
        "brand_position：品牌在回答中的位置——最先推荐用 first，备选/次选用 alternative，"
        "被提及用 mentioned，未出现用 absent，无法判断用 unknown。"
        "citation_format：有可点击链接用 linked，仅品牌/来源纯文本用 plaintext，"
        "两者兼有用 mixed，无引用用 none。"
        "citation_accuracy：引用内容与事实相符用 accurate，部分不准用 partial，"
        "明显错误用 inaccurate；无法判断用 unknown。"
        "sentiment 指对品牌的评价倾向；未提及时用 unknown。"
        "不要编造正文中不存在的竞品名。"
    )


def suggest_user_prompt(*, brand: str, question: str | None, raw_text: str) -> str:
    q = (question or "").strip() or "（未提供原问题）"
    return f"品牌参考名：{brand}\n用户问题：{q}\n\n回答正文：\n{raw_text.strip()}"
