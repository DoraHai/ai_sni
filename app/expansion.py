"""拓词候选的潜力分、建议分类与冷门词识别（启发式 v1）。

潜力分 0-10：
  - planner/url 源：月均搜索量取对数定基础分，竞争度高减分/低加分，
    showReasons 含转化潜力类标签加分（原型口径：搜索量、竞争度、匹配度综合）
  - query 源：窗口内展现取对数 + 点击加成（已触发未添加，有真实流量背书）

建议分类（人工采纳时再定最终 5 类分级，这里只是预归类）：
  - 字面含品牌词根 → brand
  - 分数 ≥8 重点词 / ≥5 一般词 / ≥3 长尾精准
  - 更低：query 源归"建议否定"（已触发但低价值），其余归"新词观察"

冷门词（用户 2026-06-12 拍板，两路口径，命中即归 source='cold'）：
  ① 规划师/URL 候选：月搜索量 < 500 且（带转化潜力类标签 或 含商业意图后缀）
  ② 搜索词候选：窗口展现 < 50 但有点击（实锤流量的低展现词）
"""
import math
from typing import Any

# showReasons 里这些标签视为高转化信号（文档 1020 枚举样例）
HIGH_INTENT_REASONS = {"转化潜力词", "黑马词", "行业激增词"}

COLD_PV_THRESHOLD = 500
COLD_QUERY_IMPRESSION_THRESHOLD = 50

# 商业意图后缀/词缀：工业品采购场景的高转化信号
INTENT_TOKENS = (
    "价格", "多少钱", "报价", "厂家", "供应商", "哪家", "品牌",
    "选型", "型号", "规格", "参数", "定制", "批发", "采购",
)


def is_cold_pv_candidate(
    word: str, monthly_pv: int | None, show_reasons: list | None
) -> bool:
    """口径①：低搜索量 + 高转化信号（规划师/URL 源）。PV 未知不算冷门。"""
    if monthly_pv is None or monthly_pv >= COLD_PV_THRESHOLD:
        return False
    if show_reasons and HIGH_INTENT_REASONS & set(show_reasons):
        return True
    return any(t in (word or "") for t in INTENT_TOKENS)


def is_cold_query_candidate(impression: int | None, click: int | None) -> bool:
    """口径②：窗口展现 < 50 但有点击（搜索词源）。"""
    return (impression or 0) < COLD_QUERY_IMPRESSION_THRESHOLD and (click or 0) >= 1


def score_planner_candidate(
    monthly_pv: int | None, competition: int | None, show_reasons: list | None
) -> float:
    score = math.log10((monthly_pv or 0) + 1) * 2.5
    if competition == 3:
        score -= 1.0
    elif competition == 1:
        score += 0.5
    if show_reasons and HIGH_INTENT_REASONS & set(show_reasons):
        score += 0.5
    return round(min(max(score, 0.0), 10.0), 1)


def score_query_candidate(impression: int | None, click: int | None) -> float:
    score = math.log10((impression or 0) + 1) * 2.0 + min(click or 0, 10) * 0.4
    return round(min(max(score, 0.0), 10.0), 1)


def suggest_category(word: str, source: str, score: float, brand_terms: list[str]) -> str:
    text = (word or "").lower()
    if any(t.lower() in text for t in brand_terms if t):
        return "brand"
    if score >= 8:
        return "focus"
    if score >= 5:
        return "normal"
    if score >= 3:
        return "longtail"
    return "negative" if source == "query" else "observe"


def parse_query_status(v: Any) -> int | None:
    """搜索词报告 queryStatusName：文档说查询用 key 返回 value，实际形态防御解析。

    返回 0=已添加 1=未添加 2=不可添加，解析不出返回 None。
    """
    if v is None:
        return None
    s = str(v).strip()
    if s in ("0", "1", "2"):
        return int(s)
    return {"已添加": 0, "未添加": 1, "不可添加": 2}.get(s)
