"""Draft fabrication-risk lint (GeoLook generate.lint_draft port)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# Note: avoid \b after Latin letters next to CJK (Python \w includes Han).
FAKE_HINTS: list[tuple[str, str]] = [
    (r"\[待填写[：:]", "存在未完成的内容结构，填写实际内容后才能发布"),
    (r"工具\s*[A-Z一二三四五六七八九十](?![A-Za-z0-9])", "出现「工具A/工具一」这类占位竞品名"),
    (r"某某|XX公司|xxx公司|示例公司", "出现占位公司名"),
    (r"(?i)\b(acme|foobar|example corp|competitor [a-z])\b", "出现占位英文品牌名"),
]

_NUMBER_IN_LINE = re.compile(
    r"[^\n|]*?(\d[\d,\.]*\s*(?:%|％|万|亿|倍|元|美元|港币|HK\$|\$|人|家|天|小时|分钟))"
    r"[^\n|]*"
)


def _known_number_tokens(facts: list[dict[str, Any]]) -> set[str]:
    known: set[str] = set()
    for fact in facts or []:
        blob = " ".join(
            str(fact.get(k) or "")
            for k in ("statement", "title", "source_name")
        )
        for m in re.finditer(
            r"\d[\d,\.]*\s*(?:%|％|万|亿|倍|元|美元|港币|HK\$|\$|人|家|天|小时|分钟)?",
            blob,
        ):
            raw = m.group(0).strip()
            known.add(raw)
            known.add(re.sub(r"\s+", "", raw))
    return known


def lint_draft(
    text: str,
    *,
    facts: list[dict[str, Any]] | None = None,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Return fabrication-risk issues. Prefer false positives over shipping fiction."""
    body = text or ""
    issues: list[dict[str, Any]] = []
    for pat, desc in FAKE_HINTS:
        for m in re.finditer(pat, body):
            issues.append(
                {
                    "level": "高",
                    "code": "fake_placeholder",
                    "type": "疑似编造",
                    "detail": desc,
                    "excerpt": body[max(0, m.start() - 30) : m.end() + 30].replace(
                        "\n", " "
                    ),
                }
            )

    from app.geo.content.claim_guard import ungrounded_claims

    for claim in ungrounded_claims(body, facts or []):
        kind = claim.get("kind")
        token = claim.get("token") or ""
        if kind == "number":
            issues.append(
                {
                    "level": "高",
                    "code": "unverified_number",
                    "type": "未核实数字",
                    "detail": f"`{token}` 不在绑定事实卡里，不得写成可发布数据",
                    "excerpt": (claim.get("excerpt") or token)[:90],
                }
            )
        elif kind == "performance":
            issues.append(
                {
                    "level": "高",
                    "code": "unverified_performance",
                    "type": "未核实性能",
                    "detail": f"出现「{token}」但事实卡未提供该指标",
                    "excerpt": token,
                }
            )
        elif kind == "qualitative":
            issues.append({"level": "高", "code": "unverified_qualitative",
                           "type": "待核实适用性或机理", "detail": f"「{token}」未能由绑定事实原文支撑，请删改或补核验资料",
                           "excerpt": claim.get("excerpt") or token})
        elif kind == "case":
            issues.append(
                {
                    "level": "高",
                    "code": "unverified_case",
                    "type": "未核实案例",
                    "detail": f"出现「{token}」但事实卡没有对应案例",
                    "excerpt": token,
                }
            )

    from app.geo.content.claim_guard import fact_number_allowlist, number_token_allowed

    known_values = _known_number_tokens(facts or [])
    allowed = fact_number_allowlist(facts or [])
    for m in _NUMBER_IN_LINE.finditer(body):
        val = m.group(1)
        if number_token_allowed(val, allowed) or number_token_allowed(val, known_values):
            continue
        start = max(0, m.start(1) - 18)
        end = min(len(body), m.end(1) + 18)
        excerpt = body[start:end].replace("\n", " ").strip()
        if "待确认" in excerpt or "待补" in excerpt:
            continue
        compact = re.sub(r"\s+", "", str(val or ""))
        if any(
            i.get("code") == "unverified_number" and compact in re.sub(r"\s+", "", i.get("detail") or "")
            for i in issues
        ):
            continue
        issues.append(
            {
                "level": "高",
                "code": "unverified_number",
                "type": "未核实数字",
                "detail": f"`{val}` 不在绑定事实卡里且未标注待确认",
                "excerpt": excerpt[:90],
            }
        )

    current_year = year or date.today().year
    for m in re.finditer(r"20\d{2}\s*年", body):
        if m.group(0).strip() != f"{current_year}年":
            issues.append(
                {
                    "level": "低",
                    "code": "suspicious_year",
                    "type": "年份存疑",
                    "detail": f"出现 {m.group(0)}，当前是 {current_year} 年",
                    "excerpt": body[max(0, m.start() - 25) : m.end() + 25].replace(
                        "\n", " "
                    ),
                }
            )

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in issues:
        key = (item["type"], item["detail"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def lint_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    high = sum(1 for i in issues if i.get("level") == "高")
    medium = sum(1 for i in issues if i.get("level") == "中")
    low = sum(1 for i in issues if i.get("level") == "低")
    return {
        "total": len(issues),
        "high": high,
        "medium": medium,
        "low": low,
        "blocks_ready": high == 0,
        "issues": issues,
    }
