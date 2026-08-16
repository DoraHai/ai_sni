"""Suggest a content brief draft from prompt question (heuristic; optional LLM later)."""

from __future__ import annotations

from typing import Any

from app.geo.content.brief import (
    CONTENT_TYPES,
    INTENTS,
    normalize_brief,
)


def _detect_intent(question: str) -> str:
    q = question.lower()
    pairs = [
        ("compare", ("对比", "比较", "vs", "versus", "哪个更好", "区别")),
        ("pricing", ("价格", "多少钱", "报价", "费用", "成本")),
        ("substitute", ("替代", "替换", "代替", "国产化替代")),
        ("risk", ("风险", "安全", "合规", "隐私", "漏洞")),
        ("brand_validate", ("靠谱吗", "怎么样", "口碑", "值得", "评价")),
        ("scenario", ("场景", "如何落地", "怎么用", "适用")),
        ("recommend", ("推荐", "哪个好", "有哪些", "选型", "名单", "厂商")),
    ]
    for intent, keys in pairs:
        if any(k in question or k in q for k in keys):
            return intent
    return "recommend"


def _detect_content_type(question: str, intent: str) -> str:
    if intent == "compare" or any(k in question for k in ("对比", "比较", "vs")):
        return "comparison"
    if any(k in question for k in ("怎么", "如何", "步骤", "部署", "接入")):
        return "howto"
    if any(k in question for k in ("FAQ", "常见问题", "问答")):
        return "faq_hub"
    if intent == "brand_validate":
        return "thought_leadership"
    return "answer_guide"


def _default_gaps(intent: str, content_type: str) -> list[str]:
    gaps = ["entity_clarity", "authority_source"]
    if intent in ("recommend", "compare", "substitute"):
        gaps.append("comparison")
        gaps.append("industry_positioning")
    if intent == "scenario" or content_type == "howto":
        gaps.append("scenario_fit")
        gaps.append("customer_case")
    if intent == "pricing":
        gaps.append("pricing_transparency")
    if intent == "risk":
        gaps.append("risk_compliance")
    # unique preserve order
    out: list[str] = []
    for g in gaps:
        if g not in out:
            out.append(g)
    return out[:6]


def _default_not_recommended(intent: str) -> list[str]:
    base = [
        "缺少清晰行业定位与实体定义",
        "缺少可核验的权威来源",
    ]
    if intent in ("recommend", "compare", "substitute"):
        base.append("缺少与竞品的可对比维度")
        base.append("缺少客户案例或落地场景")
    if intent == "pricing":
        base.append("价格与交付边界不透明")
    return base[:5]


def suggest_brief_heuristic(
    *,
    question: str,
    brand: str | None = None,
    industry_hint: str | None = None,
    existing: dict[str, Any] | None = None,
    profile_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rule-based brief draft. Does not require LLM."""
    q = (question or "").strip()
    brand_name = (brand or "本品牌").strip() or "本品牌"
    hints = profile_hints if isinstance(profile_hints, dict) else {}
    intent = _detect_intent(q)
    content_type = _detect_content_type(q, intent)
    if intent not in INTENTS:
        intent = "recommend"
    if content_type not in CONTENT_TYPES:
        content_type = "answer_guide"

    industry = (hints.get("industry") or industry_hint or "").strip()
    if not industry:
        if any(k in q for k in ("制造", "工业", "机器人", "CDMO", "泵")):
            industry = "先进制造 / 工业"
        elif any(k in q for k in ("SaaS", "数据", "BI", "分析", "软件", "客服")):
            industry = "B2B 软件 / 智能客服"
        else:
            industry = "B2B 专业服务"

    audience = str(hints.get("audience") or "").strip() or "企业采购 / 技术选型决策人"
    cta = str(hints.get("cta") or "").strip() or f"了解 {brand_name} 能力与案例"
    banned = list(hints.get("banned_claims") or []) or ["第一名", "保证被 AI 收录", "绝对领先"]
    competitors = [str(x) for x in (hints.get("competitors") or []) if str(x).strip()]
    must = list(hints.get("must_cover") or [])
    if brand_name and brand_name not in must:
        must = [brand_name] + must
    rec_when = str(hints.get("recommend_when") or "").strip() or (
        f"当买家在评估「{q[:40]}」且需要可核验能力与场景匹配时"
    )

    draft = {
        "industry": industry,
        "audience": audience,
        "intent": intent,
        "content_type": content_type,
        "cta": cta,
        "banned_claims": banned[:12],
        "notes": "自动草稿，已优先读取业务画像；请人工复核后再生成。",
        "ai_question": q,
        "not_recommended_reasons": _default_not_recommended(intent),
        "info_gaps": _default_gaps(intent, content_type),
        "recommend_when": rec_when,
        "competitors": competitors[:12],
        "must_cover": must[:10],
        "source_bar": "verified_only",
        "strategy_notes": "来自业务画像 + 启发式；竞品/必须覆盖以画像为准。",
        "schema_version": 2,
    }
    return normalize_brief(draft)


async def suggest_brief_for_task(
    *,
    question: str,
    brand: str | None,
    existing_brief: dict[str, Any] | None,
    overwrite: bool = False,
    llm: dict[str, str] | None = None,
    chat_json=None,
    profile_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return suggested brief; merge onto existing unless overwrite.

    LLM path is optional; on failure falls back to heuristic.
    """
    from app.geo.content.brief import merge_brief

    heuristic = suggest_brief_heuristic(
        question=question,
        brand=brand,
        industry_hint=(existing_brief or {}).get("industry") if isinstance(existing_brief, dict) else None,
        profile_hints=profile_hints,
    )
    suggested = heuristic

    if llm and chat_json is not None:
        try:
            system = (
                "你是 GEO 内容策略助手。根据用户问题与品牌，输出 JSON brief 草稿。"
                "字段：industry,audience,intent,content_type,cta,banned_claims,"
                "ai_question,not_recommended_reasons,info_gaps,recommend_when,"
                "competitors,must_cover,source_bar,strategy_notes。"
                "intent 仅限 recommend|compare|substitute|pricing|risk|brand_validate|scenario；"
                "content_type 仅限 answer_guide|comparison|howto|faq_hub|thought_leadership；"
                "info_gaps 使用枚举键 industry_positioning|comparison|customer_case|"
                "authority_source|pricing_transparency|risk_compliance|scenario_fit|entity_clarity；"
                "source_bar 用 any|verified_only|verified_plus_authority。"
                "禁止编造具体客户名与数据；competitors 未知则 []。"
            )
            user = (
                f"品牌/产品：{brand or '未知'}\n问题：{question}\n"
                f"业务画像：{profile_hints or {}}\n"
                f"可参考启发式：{heuristic}"
            )
            data = await chat_json(
                system,
                user,
                timeout=45.0,
                api_key=llm.get("api_key"),
                base_url=llm.get("base_url"),
                model=llm.get("model"),
            )
            if isinstance(data, dict):
                suggested = normalize_brief(data)
                # ensure ai_question
                if not suggested.get("ai_question"):
                    suggested["ai_question"] = question
        except Exception:  # noqa: BLE001 — fall back silently to heuristic
            suggested = heuristic

    return merge_brief(existing_brief, suggested, overwrite=overwrite)
