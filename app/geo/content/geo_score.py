"""GEO quality score for master drafts (P2) — rule/heuristic, no LLM."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.geo.content.brief import normalize_brief
from app.geo.content.rules import (
    RuleCheck,
    RuleInput,
    _direct_answer_ok,
    _faq_count,
    _has_conclusion,
    _has_definition,
)

# domain heuristics for authority (substring match on source_url / source_name)
_AUTHORITY_HINTS = (
    ".gov",
    ".edu",
    "wikipedia",
    "zhihu.com",
    "xinhua",
    "people.com",
    "ieee.org",
    "nature.com",
    "sciencedirect",
    "白皮书",
    "国家标准",
    "工信部",
    "发改委",
)


def _body_blob(rule_input: RuleInput) -> str:
    outline = rule_input.outline or {}
    parts = [
        rule_input.title or "",
        str(outline.get("direct_answer") or ""),
        rule_input.body_markdown or "",
    ]
    if isinstance(outline.get("sections"), list):
        for sec in outline["sections"]:
            if not isinstance(sec, dict):
                continue
            parts.append(str(sec.get("heading") or ""))
            parts.append(str(sec.get("body") or ""))
            for it in sec.get("items") or []:
                if isinstance(it, dict):
                    parts.append(str(it.get("q") or ""))
                    parts.append(str(it.get("a") or ""))
    return "\n".join(parts)


def _sub_structure(rule_input: RuleInput) -> tuple[float, list[dict[str, str]]]:
    actions: list[dict[str, str]] = []
    checks = [
        ("definition", _has_definition(rule_input.outline or {}, rule_input.body_markdown or ""), "补定义段"),
        (
            "faq",
            _faq_count(rule_input.outline or {}, rule_input.body_markdown or "") >= 2,
            "至少 2 条 FAQ",
        ),
        (
            "conclusion",
            _has_conclusion(rule_input.outline or {}, rule_input.body_markdown or ""),
            "补独立结论段",
        ),
        (
            "direct_answer",
            _direct_answer_ok(
                rule_input.question,
                rule_input.title,
                rule_input.body_markdown,
                rule_input.outline or {},
            ),
            "补直接答案段",
        ),
    ]
    passed = sum(1 for _, ok, _ in checks if ok)
    for code, ok, action in checks:
        if not ok:
            actions.append(
                {
                    "code": f"geo_structure_{code}",
                    "message": f"结构缺失：{code}",
                    "action": action,
                }
            )
    return passed / max(len(checks), 1), actions


def _sub_evidence_use(
    rule_input: RuleInput, *, lint_ok: bool | None = None
) -> tuple[float, list[dict[str, str]]]:
    actions: list[dict[str, str]] = []
    facts = rule_input.facts or []
    body = _body_blob(rule_input)
    n = len(facts)
    if n <= 0:
        actions.append(
            {
                "code": "geo_evidence_none",
                "message": "未绑定事实卡",
                "action": "绑定至少 3 条可核验事实",
            }
        )
        return 0.0, actions

    # coverage: how many fact titles/source fragments appear
    hits = 0
    for f in facts:
        title = str(f.get("title") or "").strip()
        source = str(f.get("source_name") or "").strip()
        stmt = str(f.get("statement") or "").strip()[:24]
        if title and title in body:
            hits += 1
        elif source and source in body:
            hits += 1
        elif stmt and len(stmt) >= 6 and stmt in body:
            hits += 1
    cover = hits / n
    qty = min(1.0, n / 3.0)
    score = 0.55 * cover + 0.35 * qty
    if lint_ok is False:
        score *= 0.7
        actions.append(
            {
                "code": "geo_evidence_lint",
                "message": "编造风险扫描未通过",
                "action": "核对数字与事实卡一致",
            }
        )
    if cover < 0.34:
        actions.append(
            {
                "code": "geo_evidence_cover",
                "message": "正文较少点名事实标题/来源",
                "action": "在定义/结论中引用事实来源名",
            }
        )
    return min(1.0, score), actions


def _sub_authority(rule_input: RuleInput) -> tuple[float, list[dict[str, str]]]:
    actions: list[dict[str, str]] = []
    facts = rule_input.facts or []
    if not facts:
        return 0.0, [
            {
                "code": "geo_authority_none",
                "message": "无事实无法评估权威度",
                "action": "绑定带来源的事实",
            }
        ]
    pts = 0.0
    for f in facts:
        trust = str(f.get("trust_level") or "")
        if trust == "verified":
            pts += 1.0
        elif trust == "needs_review":
            pts += 0.4
        src = f"{f.get('source_name') or ''} {f.get('source_url') or ''}".lower()
        if any(h in src for h in _AUTHORITY_HINTS):
            pts += 0.5
        if str(f.get("source_name") or "").strip():
            pts += 0.2
    # max roughly 1.7 per fact
    score = min(1.0, pts / (len(facts) * 1.2))
    if score < 0.45:
        actions.append(
            {
                "code": "geo_authority_low",
                "message": "事实权威度偏低",
                "action": "优先绑定 verified 与权威域名来源",
            }
        )
    return score, actions


def _sub_comparison(
    rule_input: RuleInput, brief: dict[str, Any] | None
) -> tuple[float, list[dict[str, str]]]:
    actions: list[dict[str, str]] = []
    data = normalize_brief(brief)
    comps = data.get("competitors") or []
    body = _body_blob(rule_input)
    ct = data.get("content_type") or ""
    if not comps:
        # no expectation — neutral high if comparison section exists for compare intent
        if data.get("intent") == "compare" or ct == "comparison":
            has_comp = bool(
                re.search(r"(?is)对比|比较|vs|versus", body)
                or (
                    isinstance((rule_input.outline or {}).get("sections"), list)
                    and any(
                        isinstance(s, dict) and s.get("type") == "comparison"
                        for s in (rule_input.outline or {}).get("sections") or []
                    )
                )
            )
            if not has_comp:
                actions.append(
                    {
                        "code": "geo_comparison_missing",
                        "message": "对比类意图缺少对比段",
                        "action": "补充 comparison 段或竞品维度",
                    }
                )
            return (1.0 if has_comp else 0.35), actions
        return 0.85, actions  # N/A-ish

    hit = sum(1 for c in comps if c and c in body)
    score = hit / len(comps)
    if score < 1.0:
        missing = [c for c in comps if c and c not in body]
        actions.append(
            {
                "code": "geo_comparison_cover",
                "message": "竞品未完全覆盖：" + "、".join(missing[:5]),
                "action": "在对比段点名 brief.competitors",
            }
        )
    return score, actions


def _sub_gap_coverage(
    rule_input: RuleInput, brief: dict[str, Any] | None
) -> tuple[float, list[dict[str, str]]]:
    actions: list[dict[str, str]] = []
    data = normalize_brief(brief)
    gaps = data.get("info_gaps") or []
    reasons = data.get("not_recommended_reasons") or []
    body = _body_blob(rule_input)
    # keyword map for gaps
    gap_kw = {
        "industry_positioning": ("行业", "定位", "赛道"),
        "comparison": ("对比", "比较", "竞品"),
        "customer_case": ("案例", "客户", "落地"),
        "authority_source": ("来源", "白皮书", "标准", "权威"),
        "pricing_transparency": ("价格", "报价", "费用"),
        "risk_compliance": ("风险", "合规", "安全"),
        "scenario_fit": ("场景", "适用", "工况"),
        "entity_clarity": ("定义", "是什么", "实体"),
    }
    targets = list(gaps)
    if not targets and reasons:
        # fall back: half credit if any reason keyword appears
        hit_r = sum(1 for r in reasons if any(len(t) >= 2 and t in body for t in re.split(r"\W+", r) if t))
        score = min(1.0, hit_r / max(len(reasons), 1))
        if score < 0.5:
            actions.append(
                {
                    "code": "geo_gap_reasons",
                    "message": "未充分回应「不推荐原因」",
                    "action": "用事实回应 not_recommended_reasons",
                }
            )
        return score if reasons else 0.8, actions

    if not targets:
        return 0.8, actions

    hit = 0
    for g in targets:
        kws = gap_kw.get(g, (g,))
        if any(k in body for k in kws):
            hit += 1
    score = hit / len(targets)
    if score < 0.5:
        actions.append(
            {
                "code": "geo_gap_cover",
                "message": "信息缺口覆盖不足",
                "action": "按 brief.info_gaps 补章节",
            }
        )
    return score, actions


def _sub_extractability(rule_input: RuleInput) -> tuple[float, list[dict[str, str]]]:
    actions: list[dict[str, str]] = []
    outline = rule_input.outline or {}
    direct = str(outline.get("direct_answer") or "").strip()
    title_ok = bool((rule_input.title or "").strip())
    faq_ok = _faq_count(outline, rule_input.body_markdown or "") >= 2
    conclusion_ok = _has_conclusion(outline, rule_input.body_markdown or "")
    direct_ok = len(direct) >= 12 or _direct_answer_ok(
        rule_input.question,
        rule_input.title,
        rule_input.body_markdown,
        outline,
    )
    parts = [title_ok, faq_ok, conclusion_ok, direct_ok]
    score = sum(1 for p in parts if p) / len(parts)
    if not title_ok:
        actions.append({"code": "geo_extract_title", "message": "缺标题", "action": "补标题"})
    if not faq_ok:
        actions.append({"code": "geo_extract_faq", "message": "FAQ 不足", "action": "补 FAQ"})
    if not conclusion_ok:
        actions.append(
            {"code": "geo_extract_conclusion", "message": "结论不可抽取", "action": "补结论段"}
        )
    return score, actions


WEIGHTS = {
    "structure": 0.18,
    "evidence_use": 0.22,
    "authority": 0.12,
    "comparison": 0.12,
    "gap_coverage": 0.12,
    "extractability": 0.08,
    "brand_mention": 0.16,
}


def _sub_brand_mention(
    rule_input: RuleInput, brand: str | None
) -> tuple[float, list[dict[str, str]]]:
    """GEO core: brand must be citable in generative answers."""
    from app.geo.content.brand_geo import (
        brand_presence_issues,
        extract_conclusion_from_md,
        normalize_brand,
        text_mentions_brand,
    )

    actions: list[dict[str, str]] = []
    b = normalize_brand(brand) or normalize_brand(rule_input.default_author)
    if len(b) < 2:
        # no brand configured — neutral (don't tank score)
        return 0.75, actions

    body = _body_blob(rule_input)
    outline = rule_input.outline or {}
    direct = str(outline.get("direct_answer") or "")
    conclusion = ""
    for sec in outline.get("sections") or []:
        if isinstance(sec, dict) and sec.get("type") == "conclusion":
            conclusion = str(sec.get("body") or "")
    if not conclusion:
        conclusion = extract_conclusion_from_md(rule_input.body_markdown or "")

    issues = brand_presence_issues(
        brand=b,
        full_text=body,
        direct_answer=direct,
        conclusion=conclusion,
        require_opening=True,
        require_conclusion=bool(conclusion),
    )
    if not issues and text_mentions_brand(body, b):
        return 1.0, actions

    for iss in issues:
        actions.append(
            {
                "code": "geo_brand_mention",
                "message": iss,
                "action": f"在直接答案与结论中自然点名「{b}」",
            }
        )
        break
    if not text_mentions_brand(body, b):
        return 0.0, actions
    # partial (body only)
    return 0.4, actions


def compute_geo_score(
    rule_input: RuleInput,
    *,
    brief: dict[str, Any] | None = None,
    lint_ok: bool | None = None,
    rule_checks: list[RuleCheck] | list[dict[str, Any]] | None = None,
    brand: str | None = None,
) -> dict[str, Any]:
    """Return geo_score 0..100, subscores, actions."""
    _ = rule_checks  # reserved for future fusion with RuleCheck list
    s_struct, a1 = _sub_structure(rule_input)
    s_evi, a2 = _sub_evidence_use(rule_input, lint_ok=lint_ok)
    s_auth, a3 = _sub_authority(rule_input)
    s_comp, a4 = _sub_comparison(rule_input, brief)
    s_gap, a5 = _sub_gap_coverage(rule_input, brief)
    s_ext, a6 = _sub_extractability(rule_input)
    s_brand, a7 = _sub_brand_mention(rule_input, brand)

    subs = {
        "structure": round(s_struct, 3),
        "evidence_use": round(s_evi, 3),
        "authority": round(s_auth, 3),
        "comparison": round(s_comp, 3),
        "gap_coverage": round(s_gap, 3),
        "extractability": round(s_ext, 3),
        "brand_mention": round(s_brand, 3),
    }
    total = 0.0
    for k, w in WEIGHTS.items():
        total += w * float(subs[k])
    geo_score = int(round(100 * total))
    if lint_ok is False:
        geo_score = min(geo_score, 59)
        a2 = list(a2) + [
            {
                "code": "geo_evidence_ungrounded",
                "message": "存在未核实表述（含适用性或机理），不能标可发布",
                "action": "删改无依据表述或补核验资料后再检查",
            }
        ]
    actions = a1 + a2 + a3 + a4 + a5 + a6 + a7
    # de-dupe by code
    seen: set[str] = set()
    uniq: list[dict[str, str]] = []
    for a in actions:
        code = a.get("code") or ""
        if code in seen:
            continue
        seen.add(code)
        uniq.append(a)

    return {
        "geo_score": geo_score,
        "geo_subscores": subs,
        "geo_actions": uniq,
        "geo_weights": dict(WEIGHTS),
        "scored_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
    }


def score_blocks_ready(
    score_payload: dict[str, Any],
    *,
    threshold: int = 60,
    gate_enabled: bool = False,
) -> tuple[bool, str]:
    """If gate disabled, always ok. Else require geo_score >= threshold."""
    if not gate_enabled:
        return True, ""
    sc = int(score_payload.get("geo_score") or 0)
    if sc >= threshold:
        return True, ""
    return False, f"GEO Score {sc} < 阈值 {threshold}"
