"""Structured content brief for GEO generation quality gate."""

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


def normalize_brief(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize free-form brief JSON into the constrained shape."""
    data = raw if isinstance(raw, dict) else {}
    intent = _clean_str(data.get("intent"), max_len=32)
    content_type = _clean_str(data.get("content_type"), max_len=32)
    if intent and intent not in INTENTS:
        # allow Chinese labels mapped back
        reverse = {v: k for k, v in INTENT_LABELS.items()}
        intent = reverse.get(intent, intent)
    if content_type and content_type not in CONTENT_TYPES:
        reverse = {v: k for k, v in CONTENT_TYPE_LABELS.items()}
        content_type = reverse.get(content_type, content_type)
    return {
        "industry": _clean_str(data.get("industry"), max_len=100),
        "audience": _clean_str(data.get("audience"), max_len=120),
        "intent": intent if intent in INTENTS else intent,
        "content_type": content_type if content_type in CONTENT_TYPES else content_type,
        "cta": _clean_str(data.get("cta"), max_len=160),
        "banned_claims": _clean_list(data.get("banned_claims")),
        "notes": _clean_str(data.get("notes"), max_len=500),
        "schema_version": 1,
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
    return not missing_required_fields(brief)


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


def catalog_payload() -> dict[str, Any]:
    return {
        "required_fields": list(REQUIRED_FIELDS),
        "field_labels": dict(FIELD_LABELS),
        "intents": [
            {"key": k, "label": INTENT_LABELS[k]} for k in INTENTS
        ],
        "content_types": [
            {"key": k, "label": CONTENT_TYPE_LABELS[k]} for k in CONTENT_TYPES
        ],
    }
