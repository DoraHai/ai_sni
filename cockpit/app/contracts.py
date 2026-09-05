"""驾驶舱共享契约的 Pydantic 定义。

这份契约同时也发给了 SEM / SEO / GEO 三个开发窗口，字段必须保持一致。
后续任何一方要改字段形状，先改这里，再同步到三边，不要三边各自变形。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Module = Literal["sem", "seo", "geo"]
TaskStatus = Literal["open", "in_progress", "done", "cancelled"]
TrendDirection = Literal["up", "down", "flat"]


class Trend7d(BaseModel):
    """相对 7 天前的变化。数据不足 7 天历史时，整个对象应为 None，不要填 0。"""

    direction: TrendDirection
    change_pct: float | None = None
    change_abs: float | None = None


class Metric(BaseModel):
    """一条指标快照。metric_key 命名规范：模块.类别.名称。"""

    metric_key: str = Field(..., examples=["sem.spend.budget_utilization_pct"])
    value: float
    unit: str = Field(..., examples=["pct", "count", "cny", "score"])
    as_of: datetime
    trend_7d: Trend7d | None = None
    definition: str = Field(..., description="一句话说明这个数字怎么算的")


class CompletionEvidence(BaseModel):
    """任务完成的判定依据：必须指向一次真实的指标变化，不接受人工自报完成。"""

    metric_key: str
    observed_value: float
    observed_at: datetime
    note: str | None = None


class Task(BaseModel):
    id: str
    module: Module
    action_type: str
    title: str
    params: dict = Field(default_factory=dict)
    status: TaskStatus = "open"
    created_by: str = Field(..., description="'cockpit' 或具体 user_id")
    assignee_role: str
    completion_evidence: CompletionEvidence | None = None
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    module: Module
    action_type: str
    title: str
    params: dict = Field(default_factory=dict)
    created_by: str
    assignee_role: str


class Signal(BaseModel):
    """信号引擎产出的一条跨模块关联发现（当前先用人工规则 + 假数据代替真正的信号引擎）。"""

    id: str
    modules: list[Module]
    headline: str = Field(..., description="给 CEO 看的一句话")
    basis: list[str] = Field(..., description="支撑这条信号的具体依据，逐条列出")
    confidence: Literal["high", "medium", "low"]
    detected_at: datetime
    related_metric_keys: list[str]
