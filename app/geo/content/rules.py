"""GEO 内容规则检查（纯函数，无 IO）。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class RuleInput:
    question: str
    title: str
    body_markdown: str
    outline: dict[str, Any]
    facts: list[dict[str, Any]]
    target_channels: list[str]
    variants: list[str]


@dataclass
class RuleCheck:
    code: str
    passed: bool
    message: str
    action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _faq_count(outline: dict[str, Any], body: str) -> int:
    faq = outline.get("faq") if isinstance(outline, dict) else None
    if isinstance(faq, list) and faq:
        return len(faq)
    # markdown fallback: lines like "Q:" / "**Q**" under FAQ heading
    section = re.search(
        r"(?is)##\s*faq.*?(?=##\s|\Z)", body or ""
    ) or re.search(r"(?is)##\s*常见问题.*?(?=##\s|\Z)", body or "")
    text = section.group(0) if section else (body or "")
    return len(re.findall(r"(?m)^\s*(?:[-*]\s*)?(?:\*\*)?Q[:：.]?", text))


def _has_definition(outline: dict[str, Any], body: str) -> bool:
    sections = outline.get("sections") if isinstance(outline, dict) else None
    if isinstance(sections, list):
        for sec in sections:
            if isinstance(sec, dict) and sec.get("type") == "definition" and (sec.get("body") or "").strip():
                return True
    return bool(re.search(r"(?is)##\s*(定义|是什么|简介)", body or ""))


def _has_conclusion(outline: dict[str, Any], body: str) -> bool:
    if isinstance(outline, dict):
        if (outline.get("conclusion") or "").strip():
            return True
        sections = outline.get("sections")
        if isinstance(sections, list):
            for sec in sections:
                if (
                    isinstance(sec, dict)
                    and sec.get("type") == "conclusion"
                    and (sec.get("body") or "").strip()
                ):
                    return True
    return bool(re.search(r"(?is)##\s*(结论|总结|一句话结论)", body or ""))


def _direct_answer_ok(question: str, title: str, body: str, outline: dict[str, Any]) -> bool:
    direct = ""
    if isinstance(outline, dict):
        direct = (outline.get("direct_answer") or "").strip()
    text = "\n".join([title or "", direct, (body or "")[:800]])
    if len(direct) >= 12:
        return True
    # first non-empty paragraph after title should be reasonably long
    paras = [p.strip() for p in re.split(r"\n\s*\n", body or "") if p.strip() and not p.strip().startswith("#")]
    if paras and len(paras[0]) >= 20:
        return True
    # title loosely related to question tokens
    q_tokens = [t for t in re.split(r"\W+", question or "") if len(t) >= 2][:4]
    return bool(q_tokens) and any(t in text for t in q_tokens)


def check_direct_answer(data: RuleInput) -> RuleCheck:
    ok = _direct_answer_ok(data.question, data.title, data.body_markdown, data.outline or {})
    return RuleCheck(
        code="direct_answer",
        passed=ok,
        message="首段/直接答案可回答目标问题" if ok else "缺少直接回答目标问题的段落",
        action="" if ok else "在文首补充一句直接答案",
    )


def check_definition(data: RuleInput) -> RuleCheck:
    ok = _has_definition(data.outline or {}, data.body_markdown or "")
    return RuleCheck(
        code="definition",
        passed=ok,
        message="已包含定义段" if ok else "缺少定义段",
        action="" if ok else "补一句话定义或「是什么」小节",
    )


def check_faq_min(data: RuleInput, min_items: int = 2) -> RuleCheck:
    n = _faq_count(data.outline or {}, data.body_markdown or "")
    ok = n >= min_items
    return RuleCheck(
        code="faq_min",
        passed=ok,
        message=f"FAQ {n}/{min_items}",
        action="" if ok else f"至少补充 {min_items} 个相关追问",
    )


def check_conclusion_extractable(data: RuleInput) -> RuleCheck:
    ok = _has_conclusion(data.outline or {}, data.body_markdown or "")
    return RuleCheck(
        code="conclusion_extractable",
        passed=ok,
        message="存在可摘取结论段" if ok else "缺少独立结论段",
        action="" if ok else "将关键结论改写为独立「结论」段落",
    )


def check_facts_bound_min(data: RuleInput, min_n: int = 3) -> RuleCheck:
    n = len(data.facts or [])
    ok = n >= min_n
    return RuleCheck(
        code="facts_bound_min",
        passed=ok,
        message=f"已绑定事实 {n}/{min_n}",
        action="" if ok else f"至少绑定 {min_n} 条事实卡",
    )


def check_facts_sourced(data: RuleInput) -> RuleCheck:
    facts = data.facts or []
    if not facts:
        return RuleCheck(
            code="facts_sourced",
            passed=False,
            message="无事实卡",
            action="先绑定带来源的事实卡",
        )
    missing = [f for f in facts if not str(f.get("source_name") or "").strip()]
    ok = not missing
    return RuleCheck(
        code="facts_sourced",
        passed=ok,
        message="全部事实均有来源" if ok else f"{len(missing)} 条事实缺来源",
        action="" if ok else "为事实卡补全来源名称",
    )


def check_updated_at_visible(data: RuleInput) -> RuleCheck:
    body = data.body_markdown or ""
    outline = data.outline or {}
    ok = bool(
        re.search(r"更新时间|更新日期|observed_at|20\d{2}[-/年]\d{1,2}", body)
        or outline.get("updated_at")
    )
    return RuleCheck(
        code="updated_at_visible",
        passed=ok,
        message="文中可见更新日期" if ok else "缺少更新日期",
        action="" if ok else "在文末插入更新日期",
    )


def check_channel_variant_ready(data: RuleInput) -> RuleCheck:
    targets = data.target_channels or []
    have = set(data.variants or [])
    missing = [c for c in targets if c not in have]
    ok = not missing
    return RuleCheck(
        code="channel_variant_ready",
        passed=ok,
        message="目标渠道版本齐全" if ok else f"缺少渠道版本: {', '.join(missing)}",
        action="" if ok else "生成对应渠道版本",
    )


def run_checks(data: RuleInput) -> list[RuleCheck]:
    return [
        check_direct_answer(data),
        check_definition(data),
        check_faq_min(data, min_items=2),
        check_conclusion_extractable(data),
        check_facts_bound_min(data, min_n=3),
        check_facts_sourced(data),
        check_updated_at_visible(data),
        check_channel_variant_ready(data),
    ]


def is_ready(checks: list[RuleCheck], *, require_channels: bool = False) -> bool:
    skip = set() if require_channels else {"channel_variant_ready"}
    return all(c.passed for c in checks if c.code not in skip)
