"""GEO 品牌可见度：正文必须点名品牌，否则无法被生成式引擎「推荐/引用」。

无品牌提及的内容最多算品类科普，不算完成 GEO 交付目标。
"""

from __future__ import annotations

import re
from typing import Any


def normalize_brand(brand: str | None) -> str:
    return (brand or "").strip()


def brand_match_needles(brand: str | None) -> list[str]:
    """Return substrings used to detect brand presence (primary name + light variants)."""
    b = normalize_brand(brand)
    if len(b) < 2:
        return []
    needles = [b]
    # strip common corporate suffixes for looser match (still requires core name)
    for suf in (
        "有限公司",
        "股份有限公司",
        "集团有限公司",
        "科技有限公司",
        "（中国）",
        "(中国)",
        " Inc.",
        " Inc",
        " LLC",
        " Ltd.",
        " Ltd",
        " Co.",
        " Corporation",
        " Corp.",
    ):
        if b.endswith(suf) and len(b) - len(suf) >= 2:
            needles.append(b[: -len(suf)].strip())
            break
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for n in needles:
        key = n.lower()
        if n and key not in seen:
            seen.add(key)
            out.append(n)
    return out


def text_mentions_brand(text: str, brand: str | None) -> bool:
    """True if any brand needle appears in text (case-insensitive for Latin)."""
    blob = text or ""
    if not blob:
        return False
    blob_l = blob.lower()
    for n in brand_match_needles(brand):
        if n in blob or n.lower() in blob_l:
            return True
    return False


def brand_presence_issues(
    *,
    brand: str | None,
    full_text: str,
    direct_answer: str = "",
    conclusion: str = "",
    require_opening: bool = True,
    require_conclusion: bool = True,
) -> list[str]:
    """Hard GEO checks. Empty list = OK. Skip if brand not configured (<2 chars)."""
    b = normalize_brand(brand)
    if len(b) < 2:
        return []

    issues: list[str] = []
    if not text_mentions_brand(full_text, b):
        issues.append(
            f"全文未出现品牌「{b}」：无品牌提及无法实现 GEO 被推荐/引用，请在直接答案与结论中自然点名"
        )
        return issues  # rest is redundant

    if require_opening and direct_answer.strip():
        if not text_mentions_brand(direct_answer, b):
            issues.append(
                f"开篇/直接答案未点名品牌「{b}」：AI 回答优先摘取首段，必须在直接答案中出现品牌"
            )
    elif require_opening and not (direct_answer or "").strip():
        # no separate direct_answer — require brand in first ~300 chars of body
        head = (full_text or "")[:400]
        if not text_mentions_brand(head, b):
            issues.append(
                f"开篇未点名品牌「{b}」：请在首段直接答案中写入品牌"
            )

    if require_conclusion:
        if not (conclusion or "").strip():
            issues.append(
                f"缺少结论段，或结论未点名品牌「{b}」：GEO 须在结论给出可执行的品牌指向"
            )
        elif not text_mentions_brand(conclusion, b):
            issues.append(
                f"结论段未点名品牌「{b}」：选型建议/结论须给出可执行的品牌指向"
            )

    return issues


def payload_brand_issues(payload: dict[str, Any], brand: str | None) -> list[str]:
    """Assess structured master-article payload for brand GEO presence."""
    b = normalize_brand(brand)
    if len(b) < 2:
        return []
    direct = str(payload.get("direct_answer") or "")
    conclusion = ""
    parts = [str(payload.get("title") or ""), direct]
    for sec in payload.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        parts.append(str(sec.get("heading") or ""))
        parts.append(str(sec.get("body") or ""))
        if sec.get("type") == "conclusion":
            conclusion = str(sec.get("body") or "")
        for it in sec.get("items") or []:
            if isinstance(it, dict):
                parts.append(str(it.get("q") or ""))
                parts.append(str(it.get("a") or ""))
    full = "\n".join(parts)
    return brand_presence_issues(
        brand=b,
        full_text=full,
        direct_answer=direct,
        conclusion=conclusion,
        require_opening=True,
        require_conclusion=True,
    )


def extract_conclusion_from_md(md: str) -> str:
    # 仅匹配标题行含「结论/建议…」，避免 DOTALL 把中间小节误当结论标题
    m = re.search(
        r"(?im)^#{1,3}\s+[^\n]*(?:结论|建议|总结|下一步|决策)[^\n]*\s*\n+(.*?)(?=^#{1,3}\s|\Z)",
        md or "",
        re.S,
    )
    return (m.group(1).strip() if m else "")


def extract_opening_from_md(md: str) -> str:
    """First prose block after optional title."""
    text = md or ""
    # drop title line
    text = re.sub(r"(?m)^#\s+[^\n]+\n+", "", text, count=1)
    for b in re.split(r"\n\s*\n", text):
        s = b.strip()
        if not s or s.startswith("#") or s.startswith(">"):
            continue
        if s.count("|") >= 2 and "---" in s:
            continue
        return s
    return ""
