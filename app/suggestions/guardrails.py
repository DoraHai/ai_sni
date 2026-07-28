"""调价建议安全护栏（业务规则 #2 渐进调价硬上限 + #4 优先级仲裁的硬约束部分）。

规则/AI 提议建议 → 这里硬校验：越界的截断、违规的否决。
这是「AI 判断 + 规则护栏」架构里的护栏层，绝不让建议闯祸。
"""
from app.suggestions.base import KeywordProfile, SuggestionDraft

MAX_CHANGE_PCT = 20.0  # 单次调价绝对上限（业务规则 #2，前后端都拦）


def make_bid(current: float | None, change_pct: float) -> tuple[float | None, float]:
    """按目标幅度算建议出价，幅度封顶 ±20%。返回 (建议出价, 实际生效幅度%)。"""
    capped = max(-MAX_CHANGE_PCT, min(MAX_CHANGE_PCT, change_pct))
    if current is None:
        return None, capped
    return round(current * (1 + capped / 100), 2), capped


def apply_guardrails(
    draft: SuggestionDraft, p: KeywordProfile
) -> SuggestionDraft | None:
    """硬护栏。返回修正后的 draft，或 None（建议被否决）。

    - 长尾精准词：永不降价 / 暂停（业务规则：长尾永不暂停）
    - 品牌词：不出降价建议（P0 品牌词保护）
    - 幅度封顶 ±20%（双保险，即便规则/AI 给了越界值也截断）
    """
    if p.category == "longtail" and draft.suggestion_type in ("lower", "pause_warn"):
        return None
    if p.category == "brand" and draft.suggestion_type == "lower":
        return None
    if draft.change_pct is not None and abs(draft.change_pct) > MAX_CHANGE_PCT:
        clamped = MAX_CHANGE_PCT if draft.change_pct > 0 else -MAX_CHANGE_PCT
        draft.suggested_bid, draft.change_pct = make_bid(draft.current_bid, clamped)
    return draft
