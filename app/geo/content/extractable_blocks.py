"""Extractable content-block detectors (GeoLook audit.py RE_* port).

Empirics (references/method.md): numbers +61.6%, definition +57.3%,
comparison +55.3%, how-to +41.2% citation-absorption lift.
"""

from __future__ import annotations

import re
from typing import Any

RE_DEFINITION = re.compile(
    r"(是一[款种个家类]|是指|指的是|定义为|全称[为是]|又称|简称为?|属于一[种类]"
    r"|とは|を指す|と呼ばれ|の略"
    r"|\bis an? \w+|\brefers to\b|\bis defined as\b|\bstands for\b)",
    re.I,
)
RE_NUMBER = re.compile(
    r"\d[\d,\.]*\s*(%|％|万|亿|千|倍|元|美元|人|家|个|天|周|小时|分钟|秒|次|条|款|年|月|"
    r"件|社|名|回|億|円|時間|"
    r"percent|x\b|hours?|days?|weeks?|users?|customers?)"
)
RE_COMPARE = re.compile(
    r"(对比|相比|区别|差异|优于|不如|竞品|替代|选型|哪个好|比較|違い|"
    r"\bvs\.?\b|\bversus\b|\balternatives?\b)",
    re.I,
)
RE_HOWTO = re.compile(
    r"(第[一二三四五六七八九十\d]+步|步骤\s*[一二三四五六七八九十\d]|操作流程|"
    r"手順|ステップ\s*\d|使い方|\bstep\s*\d|\bhow to\b)",
    re.I,
)
RE_HOWTO_SOFT = re.compile(r"(如何|怎么)")
RE_FAQ = re.compile(
    r"(常见问题|常见疑问|问答|よくある質問|\bFAQ\b|^\s*[问Q][:：]|答[:：])",
    re.I | re.M,
)

BLOCK_CODES = {
    "definition": "NO_DEFINITION",
    "numbers": "NO_NUMBERS",
    "comparison": "NO_COMPARISON",
    "howto": "NO_HOWTO",
    "faq": "NO_FAQ",
}

BLOCK_LABELS = {
    "definition": "定义",
    "numbers": "数字事实",
    "comparison": "对比",
    "howto": "操作步骤",
    "faq": "FAQ",
}


def count_list_items(text: str) -> int:
    return len(re.findall(r"(?m)^\s*([-*+]|\d+[.)])\s+\S", text or ""))


def detect_blocks(
    text: str,
    *,
    li_count: int | None = None,
    table_count: int = 0,
    schema_types: set[str] | list[str] | None = None,
) -> dict[str, bool]:
    """Return which of the five extractable blocks are present."""
    body = text or ""
    types = set(schema_types or [])
    lis = count_list_items(body) if li_count is None else int(li_count)
    howto = bool(RE_HOWTO.search(body)) or (
        bool(RE_HOWTO_SOFT.search(body)) and lis >= 3
    )
    definition_heading = bool(
        re.search(r"(?im)^#{1,6}\s*(?:定义|是什么|简介)\s*$", body)
    )
    return {
        "definition": definition_heading or bool(RE_DEFINITION.search(body)),
        "numbers": len(RE_NUMBER.findall(body)) >= 3,
        "comparison": bool(RE_COMPARE.search(body)) or table_count >= 1,
        "howto": howto,
        "faq": bool(RE_FAQ.search(body)) or "FAQPage" in types,
    }


def missing_blocks(blocks: dict[str, bool]) -> list[str]:
    return [key for key, ok in blocks.items() if not ok]


def block_findings(blocks: dict[str, bool]) -> list[dict[str, Any]]:
    """Map block presence to audit-style finding dicts."""
    deductions = {
        "definition": 6,
        "numbers": 6,
        "comparison": 5,
        "howto": 5,
        "faq": 3,
    }
    out: list[dict[str, Any]] = []
    for key, ok in blocks.items():
        label = BLOCK_LABELS[key]
        out.append(
            {
                "code": f"block_{key}",
                "issue_code": BLOCK_CODES[key],
                "title": f"可抽取块 · {label}",
                "category": "AI 可引用性",
                "severity": "high" if key in {"definition", "numbers"} else "medium",
                "passed": ok,
                "evidence": f"检测到「{label}」块" if ok else f"正文缺少「{label}」块",
                "recommendation": (
                    f"补充可独立摘取的「{label}」内容（定义/数字/对比/步骤/FAQ），"
                    "提高被生成式引擎吸收的概率。"
                    if not ok
                    else "保持该抽取块可见、可核验。"
                ),
                "deduction": 0 if ok else deductions[key],
                "automatable": True,
            }
        )
    return out


def blocks_payload(text: str, **kwargs: Any) -> dict[str, Any]:
    blocks = detect_blocks(text, **kwargs)
    missing = missing_blocks(blocks)
    return {
        "blocks": blocks,
        "missing": missing,
        "issue_codes": [BLOCK_CODES[k] for k in missing],
        "passed_count": sum(1 for ok in blocks.values() if ok),
        "total": len(blocks),
    }
