"""业务线画像：内容/策略/监测统一读取的上下文字段。"""

from __future__ import annotations

from typing import Any

PROFILE_KEYS = (
    "product_name",
    "website",
    "summary",
    "honors",
    "qualifications",
    "capabilities",
    "audience",
    "scenarios",
    "geo_scope",
    "industry",
    "competitors",
    "recommend_reasons",
    "banned_claims",
    "cta",
)


def normalize_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key in PROFILE_KEYS:
        val = data.get(key)
        if key in {
            "honors",
            "qualifications",
            "capabilities",
            "scenarios",
            "competitors",
            "recommend_reasons",
            "banned_claims",
        }:
            if isinstance(val, str):
                items = [p.strip() for p in val.replace("；", ",").replace("\n", ",").split(",") if p.strip()]
            elif isinstance(val, list):
                items = [str(x).strip() for x in val if str(x).strip()]
            else:
                items = []
            out[key] = items[:20]
        else:
            out[key] = str(val or "").strip()[:500]
    return out


def display_brand(profile: dict[str, Any] | None, *, fallback: str) -> str:
    p = normalize_profile(profile)
    return p.get("product_name") or fallback


def brand_names_for_profile(profile: dict[str, Any] | None, *, fallback: str) -> list[str]:
    """Probe / mention matching names. Prefer product, do not mix another brand."""
    product = display_brand(profile, fallback="")
    if product:
        return [product]
    fb = (fallback or "").strip()
    return [fb] if fb else []


def profile_brief_hints(profile: dict[str, Any] | None) -> dict[str, Any]:
    p = normalize_profile(profile)
    hints: dict[str, Any] = {}
    if p.get("industry"):
        hints["industry"] = p["industry"]
    if p.get("audience"):
        hints["audience"] = p["audience"]
    if p.get("cta"):
        hints["cta"] = p["cta"]
    if p.get("banned_claims"):
        hints["banned_claims"] = p["banned_claims"]
    if p.get("competitors"):
        hints["competitors"] = p["competitors"]
    must = list(p.get("capabilities") or []) + list(p.get("recommend_reasons") or [])
    if must:
        hints["must_cover"] = must[:8]
    if p.get("scenarios"):
        hints["recommend_when"] = "；".join(p["scenarios"][:3])
    return hints
