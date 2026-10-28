"""P3/P5/P6/P13：确定性合成规划及纯函数检查，不触发任何执行。"""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime

from app.sem_phase0.rules import BudgetNode, CheckInput, RuleConfig, TextLimit, TextRow, check_plan
from app.sem_phase1a.contracts import PlanRow


def generate(payload, sources, selected):
    by_id = {s.source_id: s for s in sources}

    def value(field):
        return by_id[selected[field]].value

    def refs(*fields):
        return list(dict.fromkeys(selected[f] for f in fields))

    rows = []

    def add(kind, parent, text, fields, inferred=False, budget=None):
        row_id = f"r-{len(rows)+1}"
        rows.append(PlanRow(row_id=row_id, parent_id=parent, kind=kind, text=text,
                            source_refs=refs(*fields), budget_cents=budget,
                            verification="pending_verification" if inferred else "source_confirmed"))
        return row_id

    project = add("project", None, value("product"), ["product", "budget_cents"], budget=payload.budget_cents)
    campaign = add("campaign", project, f"{value('product')}合成方案", ["product", "budget_cents"], True,
                   payload.budget_cents)
    unit = add("unit", campaign, f"{value('product')}合成单元", ["product", "budget_cents"], True,
               payload.budget_cents)
    for keyword in value("keywords").replace("，", ",").split(","):
        if keyword.strip():
            add("keyword", unit, keyword.strip(), ["keywords"], True)
    add("basic_creative", unit, f"{value('product')}：{value('benefit')}", ["product", "benefit"], True)
    add("advanced_creative_placeholder", unit, "高级创意占位，形式与素材待核实", ["product", "benefit"], True)
    for negative in payload.negative_keywords:
        add("negative_keyword", campaign, negative, ["negative_keywords"])
    if not payload.negative_keywords:
        # 空否词列表也是显式投放边界，不凭空编造否词。
        add("negative_keyword", campaign, "[]", ["negative_keywords"])
    for kind, field in (("budget", "budget_cents"), ("region", "regions"), ("schedule", "schedule"),
                        ("bid_cap", "bid_cap_cents"), ("brand_rule", "brand_rules"), ("goal", "goal")):
        fields = [field]
        if kind == "budget":
            fields += ["budget_period", "currency"]
        if kind == "schedule":
            fields += ["timezone"]
        add(kind, campaign, value(field), fields)
    add("timing", campaign, f"{value('starts_at')} 至 {value('ends_at')}", ["starts_at", "ends_at"])
    return rows


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def duplicates(rows, existing):
    issues, seen = [], {}
    for row in rows:
        if row.kind not in {"keyword", "basic_creative", "negative_keyword"} or row.text == "[]":
            continue
        key = row.kind, normalized(row.text)
        matches = ([seen[key]] if key in seen else []) + [a["asset_id"] for a in existing
                   if (a["kind"], normalized(a["text"])) == key]
        if matches:
            issues.append({"rule": "exact_duplicate", "row_id": row.row_id, "matches": matches,
                           "blocking": True})
        seen[key] = row.row_id
    return {"passed": not issues, "issues": issues, "scope": "batch_and_existing_synthetic_assets"}


def checks(rows, sources, budget_cap):
    source_ids = {s.source_id for s in sources}
    text_rows = [TextRow(row_id=r.row_id, limit_key=r.kind, text=r.text, source_refs=r.source_refs,
                        source_confirmed=(r.verification == "source_confirmed"
                                          and all(s in source_ids for s in r.source_refs))) for r in rows]
    budgets = [BudgetNode(row_id=r.row_id, parent_id=r.parent_id, cents=r.budget_cents,
                          reserved_cents=0, currency="CNY", period=next(
                              json.loads(s.value) for s in sources if s.field == "budget_period"))
               for r in rows if r.budget_cents is not None]
    negative = [normalized(r.text) for r in rows if r.kind == "negative_keyword" and r.text != "[]"]
    positives = [normalized(r.text) for r in rows if r.kind in {"keyword", "basic_creative"}]
    overlap_ok = not any(n in p for n in negative for p in positives)
    # 测试配置上限是内部演练保护值；平台核实始终false，不能充当百度限制。
    config = RuleConfig(version="phase1a-fixture-only-v1", platform_limits_verified=False,
                        text_limits={r.kind: TextLimit(maximum=2000, counting="unicode_codepoints",
                                                      evidence="本地合成保护值，非平台限制") for r in rows},
                        account_cap_cents=budget_cap)
    report = check_plan(CheckInput(budgets=budgets, texts=text_rows, negative_overlap_checked=overlap_ok,
                                   online_facts_verified=None, conflicts_resolved=True), config)
    # 本切片只有一个方案/单元，预算或结构边界变化必须显式回到P1，不能以Excel覆盖声明。
    declared_budget = next(json.loads(s.value) for s in sources if s.field == "budget_cents")
    roots = [r for r in rows if r.kind == "project"]
    boundary = next(r for r in rows if r.kind == "budget")
    if any(r.budget_cents != declared_budget for r in roots) or boundary.text != str(declared_budget):
        report["issues"].append({"rule": "declared_boundary", "row_id": boundary.row_id,
                                 "reason": "预算与P1声明不一致，须返回P1新增来源版本", "blocking": True})
        report["passed"] = False
    return report


def expiry_suggestions(payload, rows, now: datetime):
    if now.utcoffset() is None:
        raise ValueError("演练时钟须带时区")
    if payload.ends_at is None:
        return []
    timing = next(r for r in rows if r.kind == "timing")
    return [{"kind": "expiry_review_suggestion", "synthetic": True,
             "deadline": payload.ends_at.isoformat(), "due": now >= payload.ends_at,
             "text": "合成活动到期，请顾问审核是否暂停；不自动执行",
             "source_refs": timing.source_refs, "automatic_pause": False}]
