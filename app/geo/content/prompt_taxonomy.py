"""Prompt taxonomy for visibility vs brand-probe hygiene (GeoLook D0)."""

from __future__ import annotations

QUESTION_GROUPS = (
    "推荐",
    "比较",
    "替代",
    "价格",
    "风险",
    "品牌验证",
    "场景",
)

MARKETS = ("cn", "global", "both")


def normalize_question_group(raw: str | None) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    return value if value in QUESTION_GROUPS else value[:32]


def normalize_market(raw: str | None) -> str:
    value = str(raw or "cn").strip().lower()
    return value if value in MARKETS else "cn"


def brand_names_from_tenant(*, name: str | None, brand_terms: list | None) -> list[str]:
    names: list[str] = []
    for item in list(brand_terms or []) + [name]:
        text = str(item or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def brand_in_question(question: str, brand_names: list[str]) -> bool:
    """True when the question itself names the brand (probe / 品牌验证).

    Such answers nearly always echo the brand name; counting them in category
    visibility mention_rate creates false 100% positives (GeoLook sample.py).
    """
    q = (question or "").lower()
    if not q:
        return False
    for name in brand_names:
        n = (name or "").strip().lower()
        if n and n in q:
            return True
    return False


def resolve_is_brand_probe(
    *,
    question: str,
    brand_names: list[str],
    explicit: bool | None = None,
    question_group: str | None = None,
) -> bool:
    if explicit is not None:
        return bool(explicit)
    if question_group == "品牌验证":
        return True
    return brand_in_question(question, brand_names)
