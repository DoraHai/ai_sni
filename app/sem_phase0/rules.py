"""P6可扩展纯函数规则。金额使用整数分，未知限制/占位检查均阻断。"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.sem_phase0.contracts import Contract, Id, Text

Nonnegative = Annotated[int, Field(strict=True, ge=0)]


class BudgetNode(Contract):
    row_id: Id
    parent_id: Id | None
    cents: Nonnegative
    reserved_cents: Nonnegative
    currency: Literal["CNY"]
    period: Literal["daily", "total"]


class TextRow(Contract):
    row_id: Id
    limit_key: Id
    text: Text
    source_refs: list[Text]
    source_confirmed: bool = Field(strict=True)


class TextLimit(Contract):
    maximum: int = Field(strict=True, gt=0)
    counting: Literal["unicode_codepoints", "ascii1_other2"]
    evidence: Text


class RuleConfig(Contract):
    version: Id
    # 必须由未来官方限制核实适配器填入；合成测试值不构成平台证据。
    platform_limits_verified: bool = Field(strict=True)
    limits_evidence: Text | None = None
    text_limits: dict[str, TextLimit]
    account_cap_cents: Nonnegative | None

    @model_validator(mode="after")
    def evidence_required(self):
        if self.platform_limits_verified and not self.limits_evidence:
            raise ValueError("已核实限制须附官方证据")
        return self


class CheckInput(Contract):
    budgets: list[BudgetNode] = Field(min_length=1)
    texts: list[TextRow] = Field(min_length=1)
    negative_overlap_checked: bool | None
    online_facts_verified: bool | None
    conflicts_resolved: bool | None


RULE_CATALOG = (
    {"id": "platform_limits", "kind": "hard", "description": "平台限制与计数口径须核实"},
    {"id": "text_length", "kind": "hard", "description": "按显式配置检查字数，不内置猜测平台上限"},
    {"id": "budget_tree", "kind": "hard", "description": "同币种/周期，父=子合计+显式预留，误差0分"},
    {"id": "account_cap", "kind": "hard", "description": "根预算不越账户帽，未知帽阻断"},
    {"id": "source_complete", "kind": "hard", "description": "逐行来源非空且已复核；线上事实另查"},
    {"id": "negative_overlap", "kind": "placeholder", "description": "否词误伤待1a实现，未知/未通过阻断"},
    {"id": "online_facts", "kind": "placeholder", "description": "线上一致性待1a实现，未知/未通过阻断"},
    {"id": "conflicts", "kind": "placeholder", "description": "来源冲突裁定待1a实现，未知/未通过阻断"},
)


def check_plan(plan: CheckInput, config: RuleConfig) -> dict:
    plan = CheckInput.model_validate(plan.model_dump())
    config = RuleConfig.model_validate(config.model_dump())
    issues = []

    def block(rule, row, reason):
        issues.append({"rule": rule, "row_id": row, "reason": reason, "blocking": True})

    if not config.platform_limits_verified:
        block("platform_limits", None, "平台限制待核实")
    for row in plan.texts:
        limit = config.text_limits.get(row.limit_key)
        if limit is None:
            block("text_length", row.row_id, "该类字数限制未知")
        else:
            count = (len(row.text) if limit.counting == "unicode_codepoints"
                     else sum(1 if ord(c) < 128 else 2 for c in row.text))
            if count > limit.maximum:
                block("text_length", row.row_id, "超出配置字数上限")
        if not row.source_refs or not row.source_confirmed:
            block("source_complete", row.row_id, "来源缺失或未复核")
    if len({r.row_id for r in plan.texts}) != len(plan.texts):
        block("source_complete", None, "文本行ID重复")

    nodes = {node.row_id: node for node in plan.budgets}
    if len(nodes) != len(plan.budgets):
        block("budget_tree", None, "预算行ID重复")
    roots = [node for node in plan.budgets if node.parent_id is None]
    if len(roots) != 1:
        block("budget_tree", None, "预算树必须恰有一个根")
    for node in plan.budgets:
        if node.reserved_cents > node.cents:
            block("budget_tree", node.row_id, "预留不得超过本层预算")
        if node.parent_id is not None:
            parent = nodes.get(node.parent_id)
            if parent is None:
                block("budget_tree", node.row_id, "预算父行缺失")
            elif (node.currency, node.period) != (parent.currency, parent.period):
                block("budget_tree", node.row_id, "预算币种或周期不一致")
        children = [child for child in plan.budgets if child.parent_id == node.row_id]
        if children and sum(child.cents for child in children) + node.reserved_cents != node.cents:
            block("budget_tree", node.row_id, "父子预算合计不等，误差须为0分")
        visited = set()
        cursor = node
        while cursor is not None:
            if cursor.row_id in visited:
                block("budget_tree", node.row_id, "预算依赖成环")
                break
            visited.add(cursor.row_id)
            cursor = nodes.get(cursor.parent_id)
    if config.account_cap_cents is None:
        block("account_cap", None, "账户预算帽未知")
    elif any(root.cents > config.account_cap_cents for root in roots):
        block("account_cap", None, "超出账户预算帽")
    for rule, state in (("negative_overlap", plan.negative_overlap_checked),
                        ("online_facts", plan.online_facts_verified),
                        ("conflicts", plan.conflicts_resolved)):
        if state is not True:
            block(rule, None, "占位检查未知或未通过")
    return {"rules_version": config.version, "passed": not issues, "issues": issues,
            "execution_export_enabled": False, "customer_confirmation": "pending"}
