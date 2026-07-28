"""规则引擎基类。

每条规则一个 class，输入某租户某天的报告数据，输出 AlertDraft 列表。
规则只负责"判定 + 生成文案"，落库/去重由 engine 统一处理。

文案约束（见交接文档 §文案规范）：
  - title/message 全中文完整陈述句，让运营/客户看得懂
  - 不在 title/message 里出现内部规则编号（R-14 等），编号只存 rule_code 字段
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant


@dataclass
class AlertDraft:
    rule_code: str
    priority: str  # P0~P5
    title: str
    message: str
    report_date: date
    keyword_id: int | None = None
    keyword: str | None = None
    campaign_id: int | None = None
    campaign_name: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


class Rule(Protocol):
    code: str
    priority: str

    async def evaluate(
        self, session: AsyncSession, tenant: Tenant, target_date: date
    ) -> list[AlertDraft]: ...
