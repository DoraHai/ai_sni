"""演练数据模型；不接受任何客户确认或执行开关。"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.sem_phase0.contracts import Contract, Id, Text

WARNING = "内部规划/演练，不可上传百度"
Kind = Literal["project", "campaign", "unit", "keyword", "basic_creative",
               "advanced_creative_placeholder", "negative_keyword", "budget", "region",
               "schedule", "bid_cap", "brand_rule", "timing", "goal"]


class Source(Contract):
    source_id: Id
    field: Text
    value: Text
    origin: Literal["fixture_html", "fixture_ocr", "submission"]
    artifact_sha256: Text
    locator: Text


class PlanRow(Contract):
    row_id: Id
    parent_id: Id | None
    kind: Kind
    text: Text
    source_refs: list[Id] = Field(min_length=1, max_length=100)
    verification: Literal["source_confirmed", "pending_verification"]
    budget_cents: int | None = Field(default=None, strict=True, gt=0)

    @model_validator(mode="after")
    def shape(self):
        if (self.kind in {"project", "campaign", "unit"}) != (self.budget_cents is not None):
            raise ValueError("仅项目/方案/单元必须有整数分预算")
        return self


class CreateRequest(Contract):
    tenant_id: int = Field(strict=True, gt=0)
    account_id: int = Field(strict=True, gt=0)
    page_id: Id
    submission_revision: int = Field(strict=True, gt=0)
    fixture_id: Literal["launch", "fallback", "empty"] = "launch"


class RulingRequest(Contract):
    expected_version: int = Field(strict=True, gt=0)
    # 未列字段采用识别值优先的默认选择，仍必须由顾问明确提交本次裁定。
    choices: dict[str, str] = Field(default_factory=dict, max_length=50)
    reason: Text


class ApprovalRequest(Contract):
    expected_version: int = Field(strict=True, gt=0)
    row_ids: list[Id] = Field(min_length=1, max_length=1000)
    reason: Text


class ApplyRequest(Contract):
    expected_version: int = Field(strict=True, gt=0)
    preview_id: Id
