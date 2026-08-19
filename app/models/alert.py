from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Alert(Base):
    """异常告警。规则引擎产出，运营处理后标记 resolved。

    rule_code 是内部规则编号（R-14 等），仅存库和日志用，
    返回给前端的 title/message 不暴露规则编号（文案规范）。
    幂等键：(tenant_id, rule_code, keyword_id, report_date) ——
    同一规则同一关键词同一天只产生一条，重复跑引擎只刷新 metrics。
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)

    rule_code: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[str] = mapped_column(String(4), nullable=False)  # P0~P5
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    keyword_id: Mapped[int | None] = mapped_column(BigInteger)
    keyword: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    entity_ref: Mapped[str | None] = mapped_column(String(100))

    # 触发时的关键指标快照（消费/排名/质量度等），前端展示用
    metrics: Mapped[dict | None] = mapped_column(JSONB)

    # open=未处理 | resolved=人工已处理 | merged=同词归并（同组存在更新日期的告警，系统自动收起）
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "rule_code",
            "keyword_id",
            "entity_ref",
            "report_date",
            name="uq_alerts_tenant_rule_kw_entity_date",
        ),
        Index(
            "ux_alerts_keyword_dedup",
            "tenant_id",
            "rule_code",
            "keyword_id",
            "report_date",
            unique=True,
            postgresql_where=keyword_id.isnot(None),
        ),
        Index(
            "ux_alerts_entity_dedup",
            "tenant_id",
            "rule_code",
            "entity_ref",
            "report_date",
            unique=True,
            postgresql_where=entity_ref.isnot(None),
        ),
    )
