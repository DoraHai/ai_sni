from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 拓词 4 源（原型 03-optimize/01-keyword-expand）。url/cold 二期，本期只产出前两个
CANDIDATE_SOURCE_LABELS = {
    "planner": "百度规划师",
    "query": "搜索词转",
    "url": "URL 爬取",
    "cold": "冷门词",
}

# 建议分类：基于潜力分的启发式 v1（见 app/expansion.py），人工采纳时再定最终 5 类分级
SUGGESTED_CATEGORY_LABELS = {
    "brand": "品牌词",
    "focus": "重点词",
    "normal": "一般词",
    "longtail": "长尾精准",
    "observe": "新词观察",
    "negative": "建议否定",
}

# 本地处理状态。红线：百度只读——adopted 仅是"已线下采纳"的本地标记，
# 实际添加关键词由运营在百度后台手工完成（写回接口 M2 也不做）
CANDIDATE_STATUS_LABELS = {
    "pending": "待处理",
    "adopted": "已采纳",
    "ignored": "已忽略",
}

# AI 语义相关性研判（拓词智能评估，2026-06-15）。只加维度，不动启发式打分/建议分类。
# 核心治通用词噪音：generic = "设备""中心"、地名等通用词；irrelevant = 跑偏的不相关词
CANDIDATE_AI_RELEVANCE_LABELS = {
    "relevant": "业务相关",
    "generic": "通用噪音",
    "irrelevant": "不相关",
}
CANDIDATE_AI_RECOMMEND_LABELS = {
    "adopt": "建议拓展",
    "watch": "可观察",
    "drop": "建议忽略",
}


class KeywordCandidate(Base):
    """拓词候选词（聚合多源，只读百度，不写回）。

    唯一键 (tenant_id, word, source)：同词可从多源出现，各保留一行（各源指标不同）。
    同步 upsert 只刷新指标列，status/status_updated_at 人工字段永不覆盖。
    """

    __tablename__ = "keyword_candidates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    word: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # CANDIDATE_SOURCE_LABELS
    seed_word: Mapped[str | None] = mapped_column(Text)  # planner 源：种子词；null=账户主动推荐

    # ===== planner 源指标（KRService，文档 1019/1020） =====
    monthly_pv: Mapped[int | None] = mapped_column(BigInteger)  # 月均搜索量
    pc_pv: Mapped[int | None] = mapped_column(BigInteger)
    mobile_pv: Mapped[int | None] = mapped_column(BigInteger)
    competition: Mapped[int | None] = mapped_column(SmallInteger)  # 1低 2中 3高（文档 1020）
    recommend_price_pc: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    recommend_price_mobile: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    show_reasons: Mapped[list | None] = mapped_column(JSONB)  # 行业激增词/转化潜力词等

    # ===== query 源指标（搜索词报告 2307838，窗口内聚合） =====
    impression: Mapped[int | None] = mapped_column(BigInteger)
    click: Mapped[int | None] = mapped_column(BigInteger)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    matched_keyword: Mapped[str | None] = mapped_column(Text)  # 触发该搜索词的已购词

    potential_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))  # 0-10
    suggested_category: Mapped[str | None] = mapped_column(String(10))

    status: Mapped[str] = mapped_column(String(10), default="pending", nullable=False)
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    # ===== AI 语义相关性研判（迁移 0014，未配 DeepSeek 时全 NULL，降级不影响其余功能） =====
    ai_relevance: Mapped[str | None] = mapped_column(String(12))  # CANDIDATE_AI_RELEVANCE_LABELS
    ai_recommend: Mapped[str | None] = mapped_column(String(12))  # CANDIDATE_AI_RECOMMEND_LABELS
    ai_reason: Mapped[str | None] = mapped_column(Text)
    ai_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime)
    # AI 建议首次出价 + 理由（迁移 0022，加入计划时作默认出价 + 小字依据；新词无效果数据，依据指导价/竞争度/搜索量）
    ai_suggested_bid: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    ai_bid_reason: Mapped[str | None] = mapped_column(Text)

    raw: Mapped[dict | None] = mapped_column(JSONB)  # 百度原始行兜底
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "word", "source", name="uq_kw_candidates_tenant_word_src"),
    )
