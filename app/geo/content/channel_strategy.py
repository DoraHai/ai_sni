"""GEO publishing-channel strategy helpers stored in content_rules JSONB."""

from __future__ import annotations

from typing import Any

_CITATION_EN = {
    "high": "high",
    "medium": "medium",
    "low": "low",
    "高": "high",
    "中": "medium",
    "低": "low",
}
_CITATION_CN = {"high": "高", "medium": "中", "low": "低"}
_CATEGORY_BY_TYPE = {
    "website": "owned",
    "docs": "owned",
    "wechat": "content",
    "zhihu": "content",
    "baijiahao": "content",
    "toutiao": "content",
    "visual_content": "content",
    "industry_media": "news",
    "community_qa": "backlink",
    "encyclopedia": "backlink",
}

WORKBENCH_TAB_STATUSES = {
    "draft": ("draft", "editing", "facts_bound", "generating"),
    "polish": ("needs_fix",),
    "ready": ("ready", "exported"),
    "published": ("published",),
}


def default_channel_category(channel_type: str | None) -> str:
    return _CATEGORY_BY_TYPE.get(str(channel_type or ""), "content")


def citation_cn(value: str | None) -> str:
    key = _CITATION_EN.get(str(value or "").strip(), "")
    return _CITATION_CN.get(key, str(value or "").strip() or "—")


def merge_geo_profile(
    existing: dict[str, Any] | None,
    content_rules: dict[str, Any] | None,
    geo_profile: dict[str, Any] | None,
    *,
    channel_type: str | None = None,
) -> dict[str, Any]:
    rules = dict(existing or {})
    if content_rules:
        rules.update(content_rules)
    profile = dict(rules.get("geo_profile") or {})
    incoming = dict(geo_profile or {})
    if not incoming and any(rules.get(k) for k in ("source_role", "citation_potential", "strategy", "engines")):
        incoming = {
            "category": rules.get("category") or default_channel_category(channel_type),
            "source_role": str(rules.get("source_role") or "").strip(),
            "citation_potential": _CITATION_EN.get(str(rules.get("citation_potential") or ""), "medium"),
            "geo_strategy": str(rules.get("strategy") or rules.get("geo_strategy") or "").strip(),
            "adapted_engines": _as_str_list(rules.get("engines") or rules.get("adapted_engines")),
        }
    if incoming.get("source_role"):
        profile.update(incoming)
        profile["citation_potential"] = _CITATION_EN.get(
            str(profile.get("citation_potential") or "medium"),
            "medium",
        )
        profile["category"] = profile.get("category") or default_channel_category(channel_type)
        profile["adapted_engines"] = _as_str_list(profile.get("adapted_engines"))
        rules["geo_profile"] = profile
        rules["category"] = profile["category"]
        rules["source_role"] = profile["source_role"]
        rules["citation_potential"] = _CITATION_CN[profile["citation_potential"]]
        rules["strategy"] = profile.get("geo_strategy") or ""
        rules["engines"] = profile["adapted_engines"]
    return rules


def fold_publication_rows(rows: list[tuple[Any, Any, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for task_id, channel, count in rows:
        item = result.setdefault(int(task_id), {"channels": [], "count": 0})
        if channel and channel not in item["channels"]:
            item["channels"].append(channel)
        item["count"] += int(count or 0)
    return result


def task_engine_keys(brief: Any, rule_result: Any) -> list[str]:
    for src in (brief, rule_result):
        if not isinstance(src, dict):
            continue
        raw = src.get("engines") or src.get("engine_keys") or src.get("adapted_engines")
        values = _as_str_list(raw)
        if values:
            return values
    return []


def task_geo_score(rule_result: Any) -> int | None:
    if not isinstance(rule_result, dict):
        return None
    value = rule_result.get("geo_score")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()][:20]
    if isinstance(raw, str) and raw.strip():
        return [part.strip() for part in raw.replace("，", ",").split(",") if part.strip()][:20]
    return []
