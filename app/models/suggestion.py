from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 建议类型
SUGGESTION_TYPE_LABELS = {
    "raise": "加价",
    "lower": "降价",
    "optimize": "优化创意/落地页",
    "pause_warn": "暂停预警",
}
# 置信度：流量信号驱动为「中」，接入转化数据后可升「高」
CONFIDENCE_LABELS = {
    "high": "高",
    "mid": "中",
    "low": "低",
}


class Suggestion(Base):
    """AI 调价建议。

    架构：规则引擎预筛候选 + 全维数据 → AI 判断（方向/力度档位/理由/跨规则仲裁），
    规则层做安全护栏（单次 ±20% 硬上限、长尾精准词不暂停、P0 品牌词保护）。
    回写百度经 dry-run 安全网 + 20% 硬上限 + 台账留痕（app/baidu/writeback.py）；
    也可人工去百度后台操作后手动标 adopted。

    幂等键：(tenant_id, keyword_id, report_date) —— 同词同天一条主建议（engine 同词
    仲裁后只留优先级最高的一条），重跑引擎只刷新，不覆盖人工 adopted/ignored。
    status：pending=待处理 | adopted=已采纳 | ignored=已忽略 | expired=已过期。
    suggested_bid/change_pct 仅 raise/lower 类有值；optimize/pause_warn 类为空。
    """

    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)

    rule_code: Mapped[str] = mapped_column(String(30), nullable=False)
    suggestion_type: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[str] = mapped_column(String(4), nullable=False)  # P0~P5
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)  # high/mid/low

    # 出价建议（规则算，封顶 ±20%）
    current_bid: Mapped[float | None] = mapped_column(Numeric(8, 2))
    suggested_bid: Mapped[float | None] = mapped_column(Numeric(8, 2))
    change_pct: Mapped[float | None] = mapped_column(Numeric(6, 2))

    reason: Mapped[str] = mapped_column(Text, nullable=False)  # AI 生成的中文理由
    # 触发时的全维数据快照（词画像 + 客户画像 + 百度指导价），AI 判断依据 + 前端展示
    signals: Mapped[dict | None] = mapped_column(JSONB)

    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    keyword_id: Mapped[int | None] = mapped_column(BigInteger)
    keyword: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    adgroup_id: Mapped[int | None] = mapped_column(BigInteger)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    # 内部协作状态独立于建议结论（status）。不代表百度已经执行或回写成功。
    handling_status: Mapped[str] = mapped_column(
        String(24), default="todo", nullable=False, index=True
    )
    assignee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    workflow_updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    workflow_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "keyword_id",
            "report_date",
            name="uq_suggestions_tenant_kw_date",
        ),
    )
