"""AI 判断层：对规则筛出的候选建议，用 DeepSeek 做综合判断 + 仲裁 + 生成理由。

架构（见交接文档）：AI 直接判断方向 + 精确调价幅度 + 理由；规则只做兜底护栏
（±20% 封顶、长尾不降价、P0 保护）。AI 给出具体调价百分比，规则仅在越界时封顶。
AI 未配 key / 调用失败时降级，保留规则版。
"""
import logging

from app.ai.deepseek import DeepSeekError, chat_json, is_enabled
from app.suggestions.base import KeywordProfile, SuggestionDraft
from app.suggestions.guardrails import apply_guardrails, make_bid

logger = logging.getLogger(__name__)


def _parse_pct(v) -> float | None:
    """解析 AI 给的调价幅度（取绝对值，方向由 suggestion_type 定）。"""
    try:
        return abs(float(v))
    except (TypeError, ValueError):
        return None


SYSTEM_PROMPT = """你是资深 SEM 竞价优化专家，为工业品（工业泵 / 分离技术）账户做关键词出价决策。
你会收到一个关键词的完整画像和规则引擎的初步建议。你的任务是综合判断，而不是机械执行规则。

判断原则：
- 若关键词画像提供转化量，必须结合转化判断；没有转化时才按「流量获取效率 + 排名健康」层面判断
- 质量度低时优先建议优化创意 / 落地页，而不是盲目加价
- 高消费词可能是客户核心业务词，不能简单暂停或大幅降价；要结合分级、搜索词相关性、匹配模式、否词、转化周期和业务重要性判断
- 品牌词 / 重点词 / 长尾精准词出现高消费低效时，优先给“排查和优化”建议；除非证据很充分，不要给降价建议
- 高消费普通词低效时可保守止损降价，高潜力（点击率高 / 排名靠后但有量）可扩量加价
- 对照百度指导价：当前出价远低于指导价说明有空间，远高于则加价要谨慎
- 谨慎为先：错误的调价会让客户亏钱，拿不准就保守或否决
- 单次调价不超过 20%（这是硬上限，给的幅度不要超过 20）
- reason 必须同时说明“依据”和“风险/注意事项”，尤其是降价建议要提示可能压低有效流量

只返回 JSON（不要多余文字）：
{
  "decision": "confirm | adjust | reject",
  "suggestion_type": "raise | lower | optimize | keep",
  "adjust_pct": 5.0,
  "confidence": "high | mid | low",
  "reason": "给运营看的中文判断理由，说清依据和风险，80 字以内"
}
说明：
- adjust_pct = 你建议的调价幅度百分数（正数，0~20），raise/lower 时必填，方向由 suggestion_type 决定（如 lower + 5 表示降价 5%）；optimize/keep 时填 0。
- ⚠️ reason 里若提到具体幅度或目标价，必须与 adjust_pct 完全一致，不要写另一个数字。
- confirm=认同规则建议；adjust=调整方向或力度；reject=否决不该调（此时 suggestion_type=keep）。"""


def _build_user_prompt(
    p: KeywordProfile, draft: SuggestionDraft, customer_brief: str | None = None
) -> str:
    lines = []
    if customer_brief:
        lines.append("【客户画像】\n" + customer_brief + "\n")
    lines += [
        f"关键词：{p.keyword}（分级：{p.category}）",
        f"当前出价：{p.price}",
        f"质量度：{p.quality}",
        f"百度指导价：计算机 {p.left_price_guide}，移动 {p.m_price_guide}",
    ]
    if p.ctr is not None:
        lines.append(
            f"近 7 天：展现 {p.impression}，点击 {p.click}，消费 ¥{p.cost:.0f}，"
            f"转化 {p.conversions}，点击率 {p.ctr * 100:.2f}%，平均排名 {p.avg_rank}"
        )
    else:
        lines.append(f"近 7 天：展现 {p.impression}，点击 {p.click}，消费 ¥{p.cost:.0f}，转化 {p.conversions}")
    lines.append(
        f"规则初判：{draft.suggestion_type} {draft.change_pct}%"
        f"（当前 {draft.current_bid} → 建议 {draft.suggested_bid}）；理由：{draft.reason}"
    )
    return "\n".join(lines)


async def enhance_draft(
    p: KeywordProfile | None,
    draft: SuggestionDraft,
    customer_brief: str | None = None,
) -> SuggestionDraft | None:
    """用 AI 判断增强单条建议。返回增强后的 draft，或 None（AI 否决）。

    customer_brief = 客户画像摘要（让 AI 懂这个客户）；engine 每次跑算一次传入。
    AI 未配 / 失败 / p 缺失时原样返回规则版 draft（降级，不阻断）。
    """
    if p is None or not is_enabled():
        return draft
    try:
        out = await chat_json(SYSTEM_PROMPT, _build_user_prompt(p, draft, customer_brief))
    except DeepSeekError as e:
        logger.warning("AI 判断失败，降级规则版（词 %s）：%s", draft.keyword_id, e)
        return draft

    if out.get("decision") == "reject":
        return None
    if out.get("reason"):
        draft.reason = str(out["reason"])
    if out.get("confidence") in ("high", "mid", "low"):
        draft.confidence = out["confidence"]

    # 用 AI 给的方向 + 精确幅度定建议价（confirm/adjust 都按 AI 来，规则只做 ±20% 封顶兜底）
    stype = out.get("suggestion_type")
    if stype == "keep":
        return None  # AI 认为不该调
    if stype == "optimize":
        draft.suggestion_type = "optimize"
        draft.suggested_bid = None
        draft.change_pct = None
    elif stype in ("raise", "lower"):
        draft.suggestion_type = stype
        pct_abs = _parse_pct(out.get("adjust_pct"))
        if pct_abs is not None:
            # make_bid 内置 ±20% 封顶兜底；建议价与 reason 数字同源（AI 的 adjust_pct）
            draft.suggested_bid, draft.change_pct = make_bid(
                draft.current_bid, pct_abs * (1 if stype == "raise" else -1)
            )

    # 再过护栏（长尾不降价 / P0 保护 / ±20% 封顶），可能被否决
    return apply_guardrails(draft, p)
