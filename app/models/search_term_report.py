from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# query_status：0=已添加 1=未添加 2=不可添加（parse_query_status）
QUERY_STATUS_LABELS = {0: "已添加", 1: "未添加", 2: "不可添加"}


class SearchTermReport(Base):
    """搜索词报告（百度 reportType 2307838，最大 91 天窗口）全量落库快照。

    与拓词候选（keyword_candidate）区分：候选只留"未添加"的拓词机会词；本表存**全量**搜索词
    （含已添加），用于搜索词报告页 + 关键词详情触发搜索词下钻 + 加否词/转拓词数据源。
    百度搜索词报告不给触发关键词 ID，只给触发词名称（trigger_keyword=wInfoNameStatus）+
    计划/单元/匹配维度。每次同步按 (租户 + 百度账户) 全量覆盖该窗口快照。
    """

    __tablename__ = "search_term_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    query_word: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_keyword: Mapped[str | None] = mapped_column(Text)  # wInfoNameStatus 触发词（名称）
    query_status: Mapped[int | None] = mapped_column(SmallInteger)  # 0已加 1未加 2不可加

    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    adgroup_id: Mapped[int | None] = mapped_column(BigInteger)
    adgroup_name: Mapped[str | None] = mapped_column(Text)
    match_id: Mapped[int | None] = mapped_column(SmallInteger)  # wMatchId 匹配方式

    impression: Mapped[int | None] = mapped_column(BigInteger)
    click: Mapped[int | None] = mapped_column(BigInteger)
    cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    ctr: Mapped[float | None] = mapped_column(Numeric(8, 4))
    cpc: Mapped[float | None] = mapped_column(Numeric(10, 2))
    conversions: Mapped[int | None] = mapped_column(BigInteger)
    cvr: Mapped[float | None] = mapped_column(Numeric(8, 4))

    window_start: Mapped[date | None] = mapped_column(Date)
    window_end: Mapped[date | None] = mapped_column(Date)

    is_added: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否已加成关键词
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
