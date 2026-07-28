"""建议引擎基础结构。

KeywordProfile = 一个关键词的「完整画像」（属性 + 窗口指标 + 指导价），
规则和（后续的）AI 判断层都吃它。规则是纯函数：profile → SuggestionDraft | None，
落库/去重/护栏由 engine 统一处理。
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class KeywordProfile:
    """单关键词画像（窗口默认近 7 天聚合）。"""

    keyword_id: int
    keyword: str | None
    campaign_id: int | None
    campaign_name: str | None
    adgroup_id: int | None
    category: str | None  # brand/focus/normal/longtail/new
    price: float | None  # 当前真实出价
    quality: int | None  # 质量度 0-10
    left_price_guide: float | None  # 百度计算机指导价
    m_price_guide: float | None  # 百度移动指导价
    # 窗口聚合指标
    impression: int
    click: int
    cost: float
    conversions: int
    ctr: float | None
    cpc: float | None
    avg_rank: float | None


@dataclass
class SuggestionContext:
    """跑一轮建议的上下文（账户级参考值 + 目标位）。"""

    target_date: date  # 窗口锚定日（最近有数据日），作幂等键
    avg_ctr: float | None  # 账户窗口平均 CTR，「高 CTR」判断基准
    avg_cpc: float | None  # 账户窗口平均 CPC，「高 CPC」判断基准
    brand_target_rank: float = 1.5  # 品牌词目标位（业务规则）
    focus_target_rank: float = 3.0  # 重点词目标位


@dataclass
class SuggestionDraft:
    """一条建议草稿。reason 第 3 步是规则模板文案，第 4 步 AI 层会替换为判断理由。"""

    rule_code: str
    suggestion_type: str  # raise/lower/optimize/pause_warn
    priority: str  # P0~P5
    confidence: str  # high/mid/low
    reason: str
    keyword_id: int
    keyword: str | None = None
    campaign_id: int | None = None
    campaign_name: str | None = None
    adgroup_id: int | None = None
    current_bid: float | None = None
    suggested_bid: float | None = None
    change_pct: float | None = None  # 百分比，如 +12.0 / -15.0
    signals: dict[str, Any] = field(default_factory=dict)
