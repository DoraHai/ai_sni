"""调价建议规则（首期 5 类，全用现有数据：展现/点击/CTR/排名/消费/CPC/质量度/指导价）。

每条规则是纯函数：(KeywordProfile, SuggestionContext) -> SuggestionDraft | None。
建议「值」由确定性规则算（make_bid 封顶 ±20%）；reason 是规则模板文案，
第 4 步 AI 层会基于全维数据替换为判断理由 + 跨规则仲裁。
规则层只挡明显矛盾/重复，真正需要权衡的（如高耗 vs 扩量冲突）留给 AI 仲裁。
系数超限预警（pause_warn）依赖 5 层系数峰值聚合，留作下一步补 → 计划 7 类。
"""
from app.suggestions.base import KeywordProfile, SuggestionContext, SuggestionDraft
from app.suggestions.guardrails import make_bid

# 阈值（推荐默认，跑通后按实际建议调）
MIN_IMP_RANK = 5  # 评估排名/扩量所需最小窗口展现
LOW_RANK = 5.0  # 排名靠后阈值
HIGH_CTR_FACTOR = 1.5  # CTR 高于账户均值倍数
HIGH_COST_MIN = 50.0  # 窗口高消费阈值
LOW_CTR = 0.005  # 极低 CTR
HIGH_CPC_FACTOR = 2.0  # CPC 高于账户均值倍数
LOW_QUALITY = 2  # 质量度低阈值（0-10）
LOW_IMP_PROBE = 5  # 极低展现试探阈值


def _base_kwargs(p: KeywordProfile) -> dict:
    return dict(
        keyword_id=p.keyword_id,
        keyword=p.keyword,
        campaign_id=p.campaign_id,
        campaign_name=p.campaign_name,
        adgroup_id=p.adgroup_id,
        current_bid=p.price,
    )


def _guide_signals(p: KeywordProfile) -> dict:
    return {
        "avg_rank": p.avg_rank,
        "ctr": p.ctr,
        "cpc": p.cpc,
        "impression": p.impression,
        "click": p.click,
        "cost": p.cost,
        "conversions": p.conversions,
        "conv_cost": round(p.cost / p.conversions, 2) if p.conversions else None,
        "quality": p.quality,
        "left_price_guide": p.left_price_guide,
        "m_price_guide": p.m_price_guide,
    }


def rule_rank_defense(p: KeywordProfile, ctx: SuggestionContext):
    """排名失守补价：品牌/重点词排名差于目标 + 有展现 → 加价抢回排名。"""
    if p.category not in ("brand", "focus"):
        return None
    if p.avg_rank is None or p.impression < MIN_IMP_RANK:
        return None
    target = ctx.brand_target_rank if p.category == "brand" else ctx.focus_target_rank
    if p.avg_rank <= target:
        return None
    gap = p.avg_rank - target
    pct = 8.0 if gap < 1 else (15.0 if gap <= 3 else 20.0)
    bid, pct = make_bid(p.price, pct)
    label = "品牌词首位" if p.category == "brand" else "重点词目标位"
    return SuggestionDraft(
        rule_code="S-RANK",
        suggestion_type="raise",
        priority="P0" if p.category == "brand" else "P1",
        confidence="high",
        reason=(
            f"「{p.keyword}」近 7 天平均排名 {p.avg_rank:.1f}，差于{label}（目标 ≤{target:g}），"
            f"建议加价 {pct:.0f}% 抢回排名，防止竞品截流。"
        ),
        suggested_bid=bid,
        change_pct=pct,
        signals=_guide_signals(p),
        **_base_kwargs(p),
    )


def rule_scale_up(p: KeywordProfile, ctx: SuggestionContext):
    """扩量加价：非品牌/重点/长尾、质量度不低、有量，且(排名靠后 或 CTR 高于均值) → 加价扩量。

    品牌/重点走排名补价；长尾零展现正常不主动扩量；低质量词应先优化而非盲目加量。
    """
    if p.category in ("brand", "focus", "longtail"):
        return None
    if p.quality is not None and p.quality <= LOW_QUALITY:
        return None
    if p.impression < MIN_IMP_RANK or p.click <= 0:
        return None
    rank_low = p.avg_rank is not None and p.avg_rank >= LOW_RANK
    ctr_high = (
        p.ctr is not None
        and ctx.avg_ctr is not None
        and ctx.avg_ctr > 0
        and p.ctr >= ctx.avg_ctr * HIGH_CTR_FACTOR
        and (p.avg_rank is None or p.avg_rank > 2)  # 已在前列没多少空间
    )
    if not (rank_low or ctr_high):
        return None
    bid, pct = make_bid(p.price, 10.0)
    if rank_low and ctr_high:
        why = f"点击率 {p.ctr * 100:.1f}% 高于均值、且排名 {p.avg_rank:.1f} 靠后量被压制"
    elif rank_low:
        why = f"有 {p.impression} 展现 {p.click} 点击但排名 {p.avg_rank:.1f} 靠后，量被压制"
    else:
        why = (
            f"点击率 {p.ctr * 100:.1f}% 明显高于账户均值 "
            f"{ctx.avg_ctr * 100:.1f}%，用户偏爱且排名仍有空间"
        )
    return SuggestionDraft(
        rule_code="S-SCALE",
        suggestion_type="raise",
        priority="P2",
        confidence="mid",
        reason=f"「{p.keyword}」近 7 天{why}，建议加价 {pct:.0f}% 扩量。",
        suggested_bid=bid,
        change_pct=pct,
        signals=_guide_signals(p),
        **_base_kwargs(p),
    )


def rule_high_cost_low_eff(p: KeywordProfile, ctx: SuggestionContext):
    """高耗低效处理：先保护业务核心词，再按转化/点击质量决定优化或小幅降价。

    高消费词可能是客户核心业务词。品牌词、重点词、长尾精准词不直接降价，更不能暂停；
    先提示排查搜索词相关性、匹配模式、否词、创意落地页和转化周期。普通词只有在
    高消费且明显低效时，才给保守降价建议。
    """
    if p.cost < HIGH_COST_MIN:
        return None
    low_ctr = p.ctr is not None and p.ctr < LOW_CTR
    zero_conv = p.conversions == 0 and p.click > 0
    high_cpc = (
        p.cpc is not None
        and ctx.avg_cpc is not None
        and ctx.avg_cpc > 0
        and p.cpc > ctx.avg_cpc * HIGH_CPC_FACTOR
    )
    if not (low_ctr or high_cpc or zero_conv):
        return None

    signals = _guide_signals(p)
    signals["risk_note"] = "高消费词需先判断是否为核心业务词，并结合匹配模式、搜索词相关性、否词和转化周期再执行。"
    signals["risk_factors"] = {
        "core_keyword": p.category in ("brand", "focus", "longtail"),
        "zero_conversion": zero_conv,
        "low_ctr": low_ctr,
        "high_cpc": high_cpc,
    }
    if p.category in ("brand", "focus", "longtail"):
        label = {"brand": "品牌词", "focus": "重点词", "longtail": "长尾精准词"}.get(p.category, "核心词")
        return SuggestionDraft(
            rule_code="S-COST",
            suggestion_type="optimize",
            priority="P0" if p.category in ("brand", "focus") else "P1",
            confidence="mid",
            reason=(
                f"「{p.keyword}」近 7 天消费 ¥{p.cost:.0f}"
                f"{'、暂无转化' if zero_conv else ''}，但属于{label}。不建议直接暂停或大幅降价，"
                "需先核查搜索词相关性、匹配模式、否词、创意落地页和转化周期，避免误伤核心流量。"
            ),
            signals=signals,
            **_base_kwargs(p),
        )

    if p.conversions > 0 and not (low_ctr or high_cpc):
        return None
    change = -8.0 if p.conversions > 0 else -10.0
    bid, pct = make_bid(p.price, change)
    reasons = []
    if zero_conv:
        reasons.append("暂无转化")
    if low_ctr:
        reasons.append("点击率极低")
    if high_cpc:
        reasons.append("单次点击成本远高于账户均值")
    why = "、".join(reasons)
    return SuggestionDraft(
        rule_code="S-COST",
        suggestion_type="lower",
        priority="P1",
        confidence="mid",
        reason=(
            f"「{p.keyword}」近 7 天消费 ¥{p.cost:.0f}，{why}。建议先确认不是核心业务词，"
            f"并排查搜索词/匹配/否词后再小幅降价 {abs(pct):.0f}%；风险是可能压低有效流量。"
        ),
        suggested_bid=bid,
        change_pct=pct,
        signals=signals,
        **_base_kwargs(p),
    )


def rule_low_quality(p: KeywordProfile, ctx: SuggestionContext):
    """低质量度优化：质量度低导致 CPC 虚高 → 建议优化创意/落地页（治本，不只调价）。"""
    if p.quality is None or p.quality > LOW_QUALITY:
        return None
    if p.impression < MIN_IMP_RANK:
        return None
    return SuggestionDraft(
        rule_code="S-QUALITY",
        suggestion_type="optimize",
        priority="P1",
        confidence="mid",
        reason=(
            f"「{p.keyword}」质量度仅 {p.quality}，质量度低会抬高点击成本。比起加价，"
            f"更建议先优化创意相关性和落地页体验来降本，必要时再小幅调价。"
        ),
        signals=_guide_signals(p),
        **_base_kwargs(p),
    )


def rule_low_impression_probe(p: KeywordProfile, ctx: SuggestionContext):
    """极低展现试探：展现极低（非长尾/新词）→ 可能出价过低没进竞争，小幅加价试探。"""
    if p.category in ("longtail", "new"):
        return None  # 长尾零展现正常、新词不评估
    if p.impression >= LOW_IMP_PROBE or p.price is None:
        return None
    bid, pct = make_bid(p.price, 8.0)
    return SuggestionDraft(
        rule_code="S-PROBE",
        suggestion_type="raise",
        priority="P3",
        confidence="low",
        reason=(
            f"「{p.keyword}」近 7 天仅 {p.impression} 展现，可能出价过低没进入竞争，"
            f"建议小幅加价 {pct:.0f}% 试探流量（低置信度，观察后再定）。"
        ),
        suggested_bid=bid,
        change_pct=pct,
        signals=_guide_signals(p),
        **_base_kwargs(p),
    )


ALL_RULES = [
    rule_rank_defense,
    rule_scale_up,
    rule_high_cost_low_eff,
    rule_low_quality,
    rule_low_impression_probe,
]
