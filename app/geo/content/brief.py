"""Structured content brief for GEO generation quality gate (v1 + strategy v2)."""

from __future__ import annotations

from typing import Any

CONTENT_TYPES = (
    "answer_guide",  # 选型/问答指南
    "comparison",  # 对比
    "howto",  # 操作步骤
    "faq_hub",  # FAQ 合集
    "thought_leadership",  # 观点/解读
)

INTENTS = (
    "recommend",  # 推荐
    "compare",  # 比较
    "substitute",  # 替代
    "pricing",  # 价格
    "risk",  # 风险
    "brand_validate",  # 品牌验证
    "scenario",  # 场景落地
)

REQUIRED_FIELDS = (
    "industry",
    "audience",
    "intent",
    "content_type",
    "cta",
)

INFO_GAPS = (
    "industry_positioning",
    "comparison",
    "customer_case",
    "authority_source",
    "pricing_transparency",
    "risk_compliance",
    "scenario_fit",
    "entity_clarity",
)

SOURCE_BARS = (
    "any",
    "verified_only",
    "verified_plus_authority",
)

# content_type → preferred section types (prompt guidance)
CONTENT_TYPE_SECTIONS: dict[str, list[str]] = {
    "answer_guide": ["definition", "comparison", "faq", "conclusion"],
    "comparison": ["definition", "comparison", "faq", "conclusion"],
    "howto": ["definition", "body", "faq", "conclusion"],
    "faq_hub": ["definition", "faq", "conclusion"],
    "thought_leadership": ["definition", "body", "conclusion"],
}

FIELD_LABELS = {
    "industry": "行业",
    "audience": "受众",
    "intent": "意图",
    "content_type": "内容类型",
    "cta": "CTA",
}

INTENT_LABELS = {
    "recommend": "推荐",
    "compare": "比较",
    "substitute": "替代",
    "pricing": "价格",
    "risk": "风险",
    "brand_validate": "品牌验证",
    "scenario": "场景",
}

CONTENT_TYPE_LABELS = {
    "answer_guide": "选型/问答指南",
    "comparison": "对比文",
    "howto": "操作指南",
    "faq_hub": "FAQ 合集",
    "thought_leadership": "观点解读",
}

INFO_GAP_LABELS = {
    "industry_positioning": "行业定位",
    "comparison": "竞品对比",
    "customer_case": "客户案例",
    "authority_source": "权威来源",
    "pricing_transparency": "价格透明度",
    "risk_compliance": "风险合规",
    "scenario_fit": "场景适配",
    "entity_clarity": "实体清晰度",
}

SOURCE_BAR_LABELS = {
    "any": "不限",
    "verified_only": "仅已核验",
    "verified_plus_authority": "已核验+权威源",
}


def _clean_str(value: Any, *, max_len: int = 200) -> str:
    return str(value or "").strip()[:max_len]


def _clean_list(value: Any, *, max_items: int = 12, max_len: int = 80) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("；", ",").split(",")]
        raw = parts
    elif isinstance(value, list):
        raw = value
    else:
        return []
    out: list[str] = []
    for item in raw:
        text = _clean_str(item, max_len=max_len)
        if text and text not in out:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def _clean_gap_list(value: Any) -> list[str]:
    """Keep only known info_gap keys (order preserved)."""
    raw = _clean_list(value, max_items=12, max_len=40)
    out: list[str] = []
    for item in raw:
        key = item.strip()
        if key in INFO_GAPS and key not in out:
            out.append(key)
            continue
        # allow Chinese labels
        reverse = {v: k for k, v in INFO_GAP_LABELS.items()}
        mapped = reverse.get(key)
        if mapped and mapped not in out:
            out.append(mapped)
    return out


def normalize_brief(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize free-form brief JSON into the constrained shape (v1 + v2 strategy)."""
    data = raw if isinstance(raw, dict) else {}
    intent = _clean_str(data.get("intent"), max_len=32)
    content_type = _clean_str(data.get("content_type"), max_len=32)
    if intent and intent not in INTENTS:
        reverse = {v: k for k, v in INTENT_LABELS.items()}
        intent = reverse.get(intent, intent)
    if content_type and content_type not in CONTENT_TYPES:
        reverse = {v: k for k, v in CONTENT_TYPE_LABELS.items()}
        content_type = reverse.get(content_type, content_type)

    source_bar = _clean_str(data.get("source_bar"), max_len=40) or "any"
    if source_bar not in SOURCE_BARS:
        reverse = {v: k for k, v in SOURCE_BAR_LABELS.items()}
        source_bar = reverse.get(source_bar, "any")
        if source_bar not in SOURCE_BARS:
            source_bar = "any"

    # schema_version: 2 if any strategy field present or explicit >=2
    strategy_keys = (
        "ai_question",
        "not_recommended_reasons",
        "info_gaps",
        "recommend_when",
        "competitors",
        "must_cover",
        "source_bar",
        "strategy_notes",
    )
    has_strategy = any(data.get(k) not in (None, "", [], {}) for k in strategy_keys)
    try:
        ver = int(data.get("schema_version") or 0)
    except (TypeError, ValueError):
        ver = 0
    schema_version = 2 if has_strategy or ver >= 2 else 1

    return {
        "industry": _clean_str(data.get("industry"), max_len=100),
        "audience": _clean_str(data.get("audience"), max_len=120),
        "intent": intent if intent in INTENTS else intent,
        "content_type": content_type if content_type in CONTENT_TYPES else content_type,
        "cta": _clean_str(data.get("cta"), max_len=160),
        "banned_claims": _clean_list(data.get("banned_claims")),
        "notes": _clean_str(data.get("notes"), max_len=500),
        # v2 strategy
        "ai_question": _clean_str(data.get("ai_question"), max_len=300),
        "not_recommended_reasons": _clean_list(
            data.get("not_recommended_reasons"), max_items=8, max_len=120
        ),
        "info_gaps": _clean_gap_list(data.get("info_gaps")),
        "recommend_when": _clean_str(data.get("recommend_when"), max_len=300),
        "competitors": _clean_list(data.get("competitors"), max_items=12, max_len=80),
        "must_cover": _clean_list(data.get("must_cover"), max_items=12, max_len=80),
        "source_bar": source_bar,
        "strategy_notes": _clean_str(data.get("strategy_notes"), max_len=500),
        "schema_version": schema_version,
    }


def missing_required_fields(brief: dict[str, Any] | None) -> list[str]:
    data = normalize_brief(brief)
    missing: list[str] = []
    for key in REQUIRED_FIELDS:
        value = data.get(key)
        if not value:
            missing.append(key)
            continue
        if key == "intent" and value not in INTENTS:
            missing.append(key)
        if key == "content_type" and value not in CONTENT_TYPES:
            missing.append(key)
    return missing


def brief_ready(brief: dict[str, Any] | None) -> bool:
    """v1 five fields still gate generation (backward compatible)."""
    return not missing_required_fields(brief)


def strategy_richness(brief: dict[str, Any] | None) -> float:
    """0..1 heuristic: how complete strategy layer is."""
    data = normalize_brief(brief)
    score = 0.0
    weights = [
        (bool(data.get("ai_question")), 0.15),
        (bool(data.get("not_recommended_reasons")), 0.2),
        (bool(data.get("info_gaps")), 0.2),
        (bool(data.get("recommend_when")), 0.15),
        (bool(data.get("competitors")), 0.15),
        (bool(data.get("must_cover")), 0.15),
    ]
    for ok, w in weights:
        if ok:
            score += w
    return round(min(1.0, score), 3)


def brief_blockers(brief: dict[str, Any] | None) -> tuple[bool, str, str]:
    missing = missing_required_fields(brief)
    if not missing:
        return True, "Brief 已填齐生成必填项", ""
    labels = [FIELD_LABELS.get(k, k) for k in missing]
    return (
        False,
        "Brief 缺少：" + "、".join(labels),
        "请在编辑器填写行业、受众、意图、内容类型与 CTA 后再生成",
    )


def brief_generation_error_message(brief: dict[str, Any] | None) -> str:
    ok, message, action = brief_blockers(brief)
    if ok:
        return ""
    return f"{message}。{action}" if action else message


def brief_prompt_block(brief: dict[str, Any] | None) -> str:
    """Compact instruction block injected into LLM / deterministic notes."""
    data = normalize_brief(brief)
    if not brief_ready(data):
        return ""
    lines = [
        f"行业：{data['industry']}",
        f"受众：{data['audience']}",
        f"意图：{INTENT_LABELS.get(data['intent'], data['intent'])}",
        f"内容类型：{CONTENT_TYPE_LABELS.get(data['content_type'], data['content_type'])}",
        f"CTA：{data['cta']}",
    ]
    if data["banned_claims"]:
        lines.append("禁用表述：" + "；".join(data["banned_claims"]))
    if data["notes"]:
        lines.append(f"备注：{data['notes']}")
    return "\n".join(lines)


def brief_strategy_block(brief: dict[str, Any] | None) -> str:
    """Strategy layer for GEO-oriented generation (optional fields)."""
    data = normalize_brief(brief)
    lines: list[str] = []
    if data.get("ai_question"):
        lines.append(f"目标 AI 问题：{data['ai_question']}")
    if data.get("not_recommended_reasons"):
        lines.append("AI 可能不推荐的原因：" + "；".join(data["not_recommended_reasons"]))
    if data.get("info_gaps"):
        labels = [INFO_GAP_LABELS.get(g, g) for g in data["info_gaps"]]
        lines.append("信息缺口（须用事实回应，禁止编造）：" + "、".join(labels))
    if data.get("recommend_when"):
        lines.append(f"应推荐本品牌的场景：{data['recommend_when']}")
    if data.get("competitors"):
        lines.append("须覆盖的对比对象：" + "、".join(data["competitors"]))
    if data.get("must_cover"):
        lines.append("必须点名的实体/论点：" + "、".join(data["must_cover"]))
    if data.get("source_bar") and data["source_bar"] != "any":
        lines.append(
            "来源门槛：" + SOURCE_BAR_LABELS.get(data["source_bar"], data["source_bar"])
        )
    if data.get("strategy_notes"):
        lines.append(f"策略备注：{data['strategy_notes']}")
    ct = data.get("content_type") or ""
    sections = CONTENT_TYPE_SECTIONS.get(ct)
    if sections:
        lines.append("建议章节顺序：" + " → ".join(sections))
    return "\n".join(lines)


def merge_brief(
    existing: dict[str, Any] | None,
    suggested: dict[str, Any] | None,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Merge suggested onto existing; empty existing fields filled unless overwrite."""
    base = normalize_brief(existing)
    sug = normalize_brief(suggested)
    if overwrite:
        return sug
    out = dict(base)
    for key, val in sug.items():
        if key == "schema_version":
            continue
        cur = out.get(key)
        empty = cur in (None, "", [], {})
        if empty and val not in (None, "", [], {}):
            out[key] = val
    return normalize_brief(out)


def catalog_payload() -> dict[str, Any]:
    return {
        "required_fields": list(REQUIRED_FIELDS),
        "field_labels": dict(FIELD_LABELS),
        "schema_version": 2,
        "intents": [{"key": k, "label": INTENT_LABELS[k]} for k in INTENTS],
        "content_types": [
            {"key": k, "label": CONTENT_TYPE_LABELS[k]} for k in CONTENT_TYPES
        ],
        "info_gaps": [{"key": k, "label": INFO_GAP_LABELS[k]} for k in INFO_GAPS],
        "source_bars": [
            {"key": k, "label": SOURCE_BAR_LABELS[k]} for k in SOURCE_BARS
        ],
        "content_type_sections": dict(CONTENT_TYPE_SECTIONS),
        "strategy_fields": [
            "ai_question",
            "not_recommended_reasons",
            "info_gaps",
            "recommend_when",
            "competitors",
            "must_cover",
            "source_bar",
            "strategy_notes",
        ],
    }
