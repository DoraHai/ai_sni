"""P3/P5/P6/P13：确定性合成规划及纯函数检查，不触发任何执行。"""
from __future__ import annotations

import json
import re
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
    add("timing", campaign, f"{value('starts_at')} 至 {'无截止' if payload.ends_at is None else value('ends_at')}", ["starts_at", "ends_at"])
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


def checks(rows, sources, budget_cap, selected=None, rulings=None):
    source_ids = {s.source_id for s in sources}
    text_rows = [TextRow(row_id=r.row_id, limit_key=r.kind, text=r.text, source_refs=r.source_refs,
                        source_confirmed=(r.verification == "source_confirmed"
                                          and all(s in source_ids for s in r.source_refs))) for r in rows]
    budgets = [BudgetNode(row_id=r.row_id, parent_id=r.parent_id, cents=r.budget_cents,
                          reserved_cents=0, currency="CNY", period=next(
                              json.loads(s.value) for s in sources if s.field.rsplit(":", 1)[-1] == "budget_period"))
               for r in rows if r.budget_cents is not None]
    overlap_ok = negative_overlap_ok(rows)
    # 测试配置上限是内部演练保护值；平台核实始终false，不能充当百度限制。
    config = RuleConfig(version="phase1a-fixture-only-v1", platform_limits_verified=False,
                        text_limits={r.kind: TextLimit(maximum=2000, counting="unicode_codepoints",
                                                      evidence="本地合成保护值，非平台限制") for r in rows},
                        account_cap_cents=budget_cap)
    report = check_plan(CheckInput(budgets=budgets, texts=text_rows, negative_overlap_checked=overlap_ok,
                                   online_facts_verified=None,
                                   conflicts_resolved=conflicts_adjudicated(sources, selected, rulings)), config)
    declared = {s.source_id: json.loads(s.value) for s in sources
                if s.field.rsplit(":", 1)[-1] == "budget_cents"}
    roots = [r for r in rows if r.kind == "project"]
    boundaries = [r for r in rows if r.kind == "budget"]
    boundary_refs = [ref for row in boundaries for ref in row.source_refs if ref in declared]
    if (len(roots) != 1 or roots[0].budget_cents != sum(declared.values())
            or sorted(boundary_refs) != sorted(declared)
            or any(not any(ref in declared and row.text == str(declared[ref]) for ref in row.source_refs)
                   for row in boundaries)):
        report["issues"].append({"rule": "declared_boundary", "row_id": None,
                                 "reason": "预算与P1声明不一致，须返回P1新增来源版本", "blocking": True})
        report["passed"] = False
    structural = structure_issues(rows)
    report["issues"].extend(structural)
    if structural:
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


def negative_matches(negative, positive):
    """Deterministic phrase boundaries, no Chinese segmentation service.

    A Han run is a token. Chinese phrases match whole Han runs bounded by spaces,
    punctuation or Latin/digits; embedded substrings (如“免费”于“免费试用”) do not.
    Latin/digit runs also require complete token boundaries. NFKC/casefold first.
    This conservative rule intentionally leaves unsegmented compound semantics unknown.
    """
    tokens = lambda text: re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+|[^\W_\u3400-\u4dbf\u4e00-\u9fff]+", normalized(text))
    needle, hay = tokens(negative), tokens(positive)
    return bool(needle) and any(hay[i:i+len(needle)] == needle for i in range(len(hay)-len(needle)+1))


def negative_overlap_ok(rows):
    by_id = {r.row_id: r for r in rows}
    for positive in (r for r in rows if r.kind in {"keyword", "basic_creative"}):
        ancestors, cursor = set(), positive
        while cursor and cursor.row_id not in ancestors:
            ancestors.add(cursor.row_id)
            cursor = by_id.get(cursor.parent_id)
        for negative in (r for r in rows if r.kind == "negative_keyword" and r.text != "[]"):
            if negative.parent_id in ancestors and negative_matches(negative.text, positive.text):
                return False
    return True


def conflicts_adjudicated(sources, selected, rulings):
    from app.sem_phase1a.sources import comparisons

    selected, rulings = selected or {}, rulings or []
    by_id = {s.source_id: s for s in sources}
    latest = rulings[-1] if rulings else {}
    decisions = latest.get("decisions", {})
    for comparison in comparisons(sources):
        if not comparison["conflict"]:
            continue
        field = comparison["field"]
        source = by_id.get(selected.get(field))
        decision = decisions.get(field, {})
        if (source is None or source.field != field or decision.get("source_id") != source.source_id
                or decision.get("artifact_sha256") != source.artifact_sha256
                or not all(decision.get(k) for k in ("actor", "reason", "at"))):
            return False
    return True


def structure_issues(rows):
    by_id = {r.row_id: r for r in rows}
    issues = []
    allowed = {"campaign": {"project"}, "unit": {"campaign"}, "keyword": {"unit"},
               "basic_creative": {"unit"}, "advanced_creative_placeholder": {"unit"}}
    for row in rows:
        parent = by_id.get(row.parent_id)
        if ((row.kind == "project" and row.parent_id is not None)
                or (row.kind != "project" and (not parent or parent.kind not in
                    allowed.get(row.kind, {"campaign", "unit"})))
                or (row.kind == "project" and not any(r.kind == "campaign" for r in rows))
                or (row.kind == "campaign" and not any(r.parent_id == row.row_id and r.kind == "unit" for r in rows))):
            issues.append({"rule": "structure", "row_id": row.row_id,
                           "reason": "规划父子类型或方案单元不完整", "blocking": True})
    if len(by_id) != len(rows) or len([r for r in rows if r.kind == "project"]) != 1:
        issues.append({"rule": "structure", "row_id": None, "reason": "行ID或项目根不合法", "blocking": True})
    return issues


def generate_bundle(entries, sources, selected):
    """One project, one campaign per product line, one unit per submitted page.

    Every page has its own declared budget. All pages share currency/period; their
    declarations sum to the project budget. No invented allocation or new boundary.
    """
    if len(entries) == 1:
        return generate(entries[0][0], sources, selected)
    rows, campaigns = [], {}
    total = sum(payload.budget_cents for payload, _ in entries)
    project_refs = [s.source_id for s in sources if s.field.endswith(":budget_cents")]
    rows.append(PlanRow(row_id="bundle-root", parent_id=None, kind="project", text="合成多产品线规划",
                        source_refs=project_refs, verification="pending_verification", budget_cents=total))
    for index, (payload, prefix) in enumerate(entries, 1):
        local = [s.model_copy(update={"field": s.field[len(prefix):]}) for s in sources if s.field.startswith(prefix)]
        choices = {field[len(prefix):]: ref for field, ref in selected.items() if field.startswith(prefix)}
        generated = generate(payload, local, choices)
        campaign_key = payload.product_line_id
        if campaign_key not in campaigns:
            campaign = generated[1].model_copy(update={"row_id": f"campaign-{index}", "parent_id": "bundle-root"})
            campaigns[campaign_key] = campaign
            rows.append(campaign)
        else:
            campaign = campaigns[campaign_key]
            updated = campaign.model_copy(update={"budget_cents": campaign.budget_cents + payload.budget_cents,
                "source_refs": list(dict.fromkeys(campaign.source_refs + generated[1].source_refs))})
            rows[rows.index(campaign)] = updated
            campaigns[campaign_key] = updated
            campaign = updated
        ids = {r.row_id: f"p{index}-{r.row_id}" for r in generated}
        for row in generated[2:]:
            parent = campaign.row_id if row.kind == "unit" else ids[row.parent_id]
            # Per-page boundaries stay beside their page's unit, including declared budget.
            if row.kind != "unit" and row.parent_id == generated[1].row_id:
                parent = ids[generated[2].row_id]
            rows.append(row.model_copy(update={"row_id": ids[row.row_id], "parent_id": parent}))
    return rows
