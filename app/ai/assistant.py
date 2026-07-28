"""AI 对话助手编排（欢迎页对话框）。

设计要点（应对"对话变长会丢信息"的担心）：
- 业务数据：每轮从库实时算客户态摘要，塞进 system，不靠对话记忆 → 永远最新、不丢。
- 关键信息（KPI/约束/偏好/决策）：不硬加字段、不留对话里，存开放记忆表 tenant_memories，
  AI 抽取→人确认→落库，每轮全量喂回。
- 对话历史：滑动窗口（只带最近 N 轮）。普通闲聊滑走无所谓。
直接复用 app/ai/deepseek（不引 LangChain，第一版单次调用够用）。
"""
import logging
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import DeepSeekError, chat_messages, is_enabled
from app.models import (
    MEMORY_TYPE_LABELS,
    Alert,
    AssistantMessage,
    KeywordCandidate,
    KwReportSnapshot,
    Lead,
    TenantMemory,
)

logger = logging.getLogger(__name__)

HISTORY_WINDOW = 16  # 滑动窗口：喂 LLM 最多带最近 16 条对话（约 8 轮）
ZERO_CONV_MIN_COST = 30.0  # 烧钱零转化阈值（当前统计区间消费 ≥ 此值且转化=0）
MESSAGE_RETAIN_DAYS = 90  # 对话保留天数（超过定时清理）

SYSTEM_PROMPT = """你是赛珀 SEM 智投平台的优化助手，服务百度搜索推广的代运营。\
基于下面提供的【客户数据】和【已知客户目标/约束】回答问题、解读表现、给优化建议。

规则：
1. 只依据提供的数据说话，不编造数字；数据没有就说"暂无数据"。
1a. 用户指定了近一年、半年、季度、若干天/月或某个自然月时，必须按【客户数据】中的请求区间回答。\
若数据覆盖不足，要明确说明“请求区间”和“数据库实际可用区间”，并基于两者的重叠区间回答；\
不要笼统说“更长时间数据暂无”，也不要把较短区间冒充完整请求区间。
1b. 用户问“哪些词带来了转化/线索”时，优先使用「转化 Top 词」逐项回答，并说明这里归因的是\
关键词电话点击转化；不要把累计真线索强行归因到关键词。
2. 给建议要具体到关键词/计划，并说明依据（如"消费 ¥186 零转化"）。
3. 不直接执行任何操作；涉及调价/砍词时，用 suggestions 给出跳转建议，由人去工作台确认执行。
3b. 若【客户数据】里有「拓词候选」，可主动给拓词建议：在 reply 里点出值得拓的词，并用 \
suggestions 给一个 target=expand 的跳转（拓词需人工在拓词页选计划/单元/出价，故只跳转、不放进 actions 一键执行）。
4. 若用户表达了一个值得长期记住的目标/约束/偏好/决策（如线索成本目标、预算、主推产品线、\
不投某类词），放进 memories 待用户确认；不要把闲聊或一次性问题当记忆。
5. 记忆里涉及时间的，一律换算成绝对年月（按下方给的"今天"换算，例如"下个月"→"2026年7月"），\
不要用"下个月/这周/明天"这类相对词，否则日后会失真。
6. 【已知客户目标/约束】按设定时间排列；若有冲突，以最近设定的为准。
7. 回答用简体中文，简明、先结论。

8. 若给出可直接执行的低风险优化动作（调价/加否词/设日预算），放进 actions 供用户一键采纳。\
actions 里的 keywords 必须是上面【客户数据】里真实出现的词，绝不可编造；没把握就不要给 action。\
adjust_pct 负数=降价（如 -20 表示降 20%）；negative=加否词；set_budget=设账户日预算（带 budget 数字，单位元）。\
执行由用户点「采纳」确认，你只负责建议。每个 action 的 reason 必须说明依据和风险；\
高消费词可能是核心业务词，不要生成 pause/暂停类 action；遇到“烧钱、零转化、没线索、该砍的词”这类问题，\
只能在 reply 中提示需核查匹配模式、搜索词相关性、否词、转化周期和业务重要性，并用 suggestions 跳转到 workbench/search_terms/negatives 让人工确认。\
降价前也必须提示风险，依据不足时只给 suggestions，不给 actions。

9. 【智能投放引导】当客户问"怎么提升线索/要不要用智能投放/线索太少"等，或【客户数据】显示\
转化充足度为"偏少/几乎没有"时，按这个节奏引导：
  a. 第一步先确认/设「账户日预算」——这是每天花费上限、账户的安全总闸，先有它客户才敢放开投。\
若客户给了一个能接受的每日金额，用 set_budget action 帮他设。
  b. 再建议开「智能出价」：优化目标先设成"客户点电话或在线咨询就算达成一次"（容易快速积累），\
并在现有关键词出价基础上让系统自动加出价系数；等有效线索多了，再升级到"有效成交线索"目标。
  c. 金额引导：上面 b 这种方式不用填"每个转化多少钱"，沿用现有点击出价即可；只有升级到\
"有效成交线索"时才需要客户报目标成本，那时你基于真线索成本（消费÷有效线索）给建议区间，不让客户瞎报。
10. 【对客户说人话】绝不向客户使用 "OCPC / 增强模式 / 浅层转化 / 一阶段 / 学习期" 等术语缩写，\
一律用中文解释：OCPC→智能投放/智能出价；增强模式→智能辅助出价；目标转化成本→全自动按成本投放；\
浅层目标→以"客户来电/在线咨询"为目标；深层→以"有效成交线索"为目标。

11. 【智能搭建】当用户明确表达“新建推广计划 / 搭建账户 / 根据落地页生成关键词和创意”等意图时，\
进入智能搭建引导，并返回 builder 对象；普通优化问答的 builder 必须为 null。
  a. 当前版本只支持已有落地页链接，必须收集 landing_url 和 business_summary；缺少时在 reply 中一次问清，\
builder.intent=true、builder.ready=false，并在 missing 里列出缺项。
  b. goal 未提供时默认“获取高意向线索”；budget 可为空；regions 为空表示不限；schedule_preset 默认 all；\
device_preference 默认“不限”。schedule_preset 只能是 all（全天）、workday（工作日9-18）或 daytime（每天9-22）。
  c. 信息完整后 builder.ready=true，并从本轮及最近对话中准确回填字段。不要自行编造落地页链接、预算或地域。
  d. 智能搭建只生成可编辑草案，不在对话里直接写入百度；不要为搭建意图生成 actions。

必须返回 JSON，格式：
{
  "reply": "给用户看的自然语言回答",
  "suggestions": [{"label": "按钮文案", "target": "workbench|leads|negatives|search_terms|expand|dashboard|builder", "reason": "为什么"}],
  "actions": [{"type": "adjust_bid|negative|set_budget", "label": "采纳按钮文案", "reason": "依据", "keywords": ["词1","词2"], "adjust_pct": -20, "match_mode": "exact", "budget": 300}],
  "memories": [{"type": "goal|constraint|preference|background|decision", "content": "要记住的一句话"}],
  "builder": {
    "intent": true,
    "ready": false,
    "missing": ["landing_url", "business_summary"],
    "landing_url": "https://...",
    "business_summary": "主营业务、核心产品、目标客户和服务范围",
    "goal": "获取高意向线索",
    "budget": null,
    "regions": "",
    "schedule_preset": "all",
    "device_preference": "不限"
  }
}
suggestions/actions/memories 没有就给空数组；没有智能搭建意图时 builder 必须为 null。\
adjust_pct 仅 adjust_bid 用，match_mode 仅 negative 用，budget 仅 set_budget 用。"""


BUILDER_MISSING_FIELDS = ("landing_url", "business_summary")
BUILDER_SCHEDULE_PRESETS = {"all", "workday", "daytime"}
ASSISTANT_BLOCKED_ACTION_TYPES = {"pause"}


def _builder_text(value: Any, limit: int) -> str:
    return str(value).strip()[:limit] if value is not None else ""


def _normalize_builder_request(raw: Any) -> dict[str, Any] | None:
    """收紧模型返回的搭建请求，避免前端直接信任自由格式 JSON。"""
    if not isinstance(raw, dict) or not raw.get("intent"):
        return None

    landing_url = _builder_text(raw.get("landing_url"), 500)
    business_summary = _builder_text(raw.get("business_summary"), 2000)
    goal = _builder_text(raw.get("goal"), 120) or "获取高意向线索"
    regions = _builder_text(raw.get("regions"), 500)
    device_preference = _builder_text(raw.get("device_preference"), 50) or "不限"
    schedule_preset = _builder_text(raw.get("schedule_preset"), 20)
    if schedule_preset not in BUILDER_SCHEDULE_PRESETS:
        schedule_preset = "all"

    budget = None
    try:
        candidate = float(raw.get("budget")) if raw.get("budget") not in (None, "") else None
        if candidate is not None and 0 < candidate <= 10000000:
            budget = round(candidate, 2)
    except (TypeError, ValueError):
        pass

    missing = []
    if not landing_url:
        missing.append("landing_url")
    if not business_summary:
        missing.append("business_summary")

    return {
        "intent": True,
        "ready": bool(raw.get("ready")) and not missing,
        "missing": missing,
        "landing_url": landing_url,
        "business_summary": business_summary,
        "goal": goal,
        "budget": budget,
        "regions": regions,
        "schedule_preset": schedule_preset,
        "device_preference": device_preference,
    }


def _sanitize_assistant_output(out: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep chat-side one-click actions inside the product risk boundary."""
    suggestions = [s for s in (out.get("suggestions") or []) if isinstance(s, dict)]
    actions: list[dict[str, Any]] = []
    blocked_pause_keywords: list[str] = []

    for raw in out.get("actions") or []:
        if not isinstance(raw, dict):
            continue
        action_type = str(raw.get("type") or "").strip()
        if action_type in ASSISTANT_BLOCKED_ACTION_TYPES:
            for kw in raw.get("keywords") or []:
                keyword = str(kw or "").strip()
                if keyword and keyword not in blocked_pause_keywords:
                    blocked_pause_keywords.append(keyword)
            continue
        actions.append(raw)

    if blocked_pause_keywords and not any(s.get("target") == "workbench" for s in suggestions):
        shown = "、".join(blocked_pause_keywords[:6])
        suffix = f" 等 {len(blocked_pause_keywords)} 个词" if len(blocked_pause_keywords) > 6 else ""
        suggestions.append({
            "label": "去关键词工作台排查",
            "target": "workbench",
            "reason": (
                f"暂停前需确认「{shown}{suffix}」是否为核心业务词，并核查匹配模式、"
                "搜索词相关性、否词、转化周期和业务重要性。"
            ),
        })

    return actions, suggestions


def _f(v) -> float:
    return float(v) if v is not None else 0.0


@dataclass(frozen=True)
class RequestedReportPeriod:
    label: str
    start: date
    end: date


def _shift_months(value: date, months: int) -> date:
    """按自然月回退，月底日期自动收敛到目标月最后一天。"""
    target = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(target, 12)
    month = month_index + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _recent_months_period(label: str, months: int, end: date) -> RequestedReportPeriod:
    return RequestedReportPeriod(
        label=label,
        start=_shift_months(end, months) + timedelta(days=1),
        end=end,
    )


def _requested_report_period(
    user_message: str,
    available_start: date,
    available_end: date,
) -> RequestedReportPeriod:
    """从最新问题识别统计区间；未指定时仍使用近 30 天。"""
    text = re.sub(r"\s+", "", user_message or "")

    explicit_month = re.search(r"(20\d{2})年(1[0-2]|0?[1-9])月?", text)
    if explicit_month:
        year, month = int(explicit_month.group(1)), int(explicit_month.group(2))
        return RequestedReportPeriod(
            label=f"{year}年{month}月",
            start=date(year, month, 1),
            end=date(year, month, monthrange(year, month)[1]),
        )

    if "上个月" in text or "上月" in text:
        previous = _shift_months(available_end.replace(day=1), 1)
        return RequestedReportPeriod(
            label="上月",
            start=previous,
            end=date(previous.year, previous.month, monthrange(previous.year, previous.month)[1]),
        )
    if "本月" in text or "这个月" in text:
        return RequestedReportPeriod(
            label="本月",
            start=available_end.replace(day=1),
            end=available_end,
        )
    if "去年" in text:
        year = available_end.year - 1
        return RequestedReportPeriod(
            label=f"{year}年",
            start=date(year, 1, 1),
            end=date(year, 12, 31),
        )
    if "今年" in text:
        return RequestedReportPeriod(
            label=f"{available_end.year}年至今",
            start=date(available_end.year, 1, 1),
            end=available_end,
        )

    day_match = re.search(r"(?:近|过去|最近)(\d{1,4})天", text)
    if day_match:
        days = min(max(int(day_match.group(1)), 1), 3650)
        return RequestedReportPeriod(
            label=f"近{days}天",
            start=available_end - timedelta(days=days - 1),
            end=available_end,
        )

    month_match = re.search(r"(?:近|过去|最近)(\d{1,3})个?月", text)
    if month_match:
        months = min(max(int(month_match.group(1)), 1), 120)
        return _recent_months_period(f"近{months}个月", months, available_end)

    if re.search(r"(?:近|过去|最近)一年|一年内", text):
        return _recent_months_period("近一年", 12, available_end)
    if re.search(r"(?:近|过去|最近)?半年", text):
        return _recent_months_period("近半年", 6, available_end)
    if re.search(r"(?:近|过去|最近)?(?:一?季度|三个月)", text):
        return _recent_months_period("近一季度", 3, available_end)
    if any(word in text for word in ("全历史", "全部历史", "所有历史", "历史以来", "全部数据", "所有数据")):
        return RequestedReportPeriod("全部可用历史", available_start, available_end)

    return RequestedReportPeriod(
        label="近30天",
        start=available_end - timedelta(days=29),
        end=available_end,
    )


async def build_context_summary(
    session: AsyncSession,
    tenant_id: int,
    user_message: str = "",
) -> str:
    """按用户问题所需区间组装客户态数据摘要，文本塞进 prompt。"""
    min_date, max_date = (await session.execute(
        select(
            func.min(KwReportSnapshot.report_date),
            func.max(KwReportSnapshot.report_date),
        ).where(KwReportSnapshot.tenant_id == tenant_id)
    )).one()
    if max_date is None:
        return "【客户数据】暂无报告数据（还没同步关键词报告）。"
    period = _requested_report_period(user_message, min_date, max_date)
    start = max(period.start, min_date)
    end = min(period.end, max_date)
    if start > end:
        return (
            f"【客户数据】（用户请求：{period.label}，"
            f"{period.start.isoformat()} ~ {period.end.isoformat()}）\n"
            f"- 数据覆盖提示：数据库实际可用区间为 {min_date.isoformat()} ~ "
            f"{max_date.isoformat()}，与请求区间没有重叠。回答时请明确告知实际可用范围，"
            "不要改用其他时间段的数据代替。"
        )

    coverage_limited = start != period.start or end != period.end
    base = (KwReportSnapshot.tenant_id == tenant_id,
            KwReportSnapshot.report_date >= start,
            KwReportSnapshot.report_date <= end)

    agg = (await session.execute(
        select(
            func.coalesce(func.sum(KwReportSnapshot.cost), 0),
            func.coalesce(func.sum(KwReportSnapshot.click), 0),
            func.coalesce(func.sum(KwReportSnapshot.impression), 0),
            func.coalesce(func.sum(KwReportSnapshot.conversions), 0),
        ).where(*base)
    )).one()
    cost, click, imp, conv = _f(agg[0]), int(agg[1]), int(agg[2]), int(agg[3])

    # 近 7 天电话转化（判断智能投放数据是否喂得动：经验门槛 ~15/周）
    conv7 = int(await session.scalar(
        select(func.coalesce(func.sum(KwReportSnapshot.conversions), 0)).where(
            KwReportSnapshot.tenant_id == tenant_id,
            KwReportSnapshot.report_date >= max_date - timedelta(days=6),
            KwReportSnapshot.report_date <= max_date,
        )
    ) or 0)
    adequacy = "充足" if conv7 >= 15 else ("偏少" if conv7 > 0 else "几乎没有")

    # top 烧钱词
    top_rows = (await session.execute(
        select(KwReportSnapshot.keyword, func.sum(KwReportSnapshot.cost),
               func.sum(KwReportSnapshot.conversions))
        .where(*base, KwReportSnapshot.keyword.isnot(None))
        .group_by(KwReportSnapshot.keyword)
        .order_by(func.sum(KwReportSnapshot.cost).desc()).limit(8)
    )).all()
    top_spend = [(r[0], _f(r[1]), int(r[2])) for r in top_rows]
    zero_conv = [t for t in top_spend if t[1] >= ZERO_CONV_MIN_COST and t[2] == 0]

    # 转化词：优先回答“哪些词带来了线索/转化”类问题
    conversion_rows = (await session.execute(
        select(
            KwReportSnapshot.keyword,
            func.sum(KwReportSnapshot.conversions),
            func.sum(KwReportSnapshot.cost),
            func.sum(KwReportSnapshot.click),
        )
        .where(
            *base,
            KwReportSnapshot.keyword.isnot(None),
            KwReportSnapshot.keyword != "",
        )
        .group_by(KwReportSnapshot.keyword)
        .having(func.sum(KwReportSnapshot.conversions) > 0)
        .order_by(
            func.sum(KwReportSnapshot.conversions).desc(),
            func.sum(KwReportSnapshot.cost).desc(),
        )
        .limit(10)
    )).all()
    top_conversions = [
        (row[0], int(row[1] or 0), _f(row[2]), int(row[3] or 0))
        for row in conversion_rows
    ]

    # 真线索（leads 表，累计有效）
    lead_total = int(await session.scalar(
        select(func.count()).select_from(Lead).where(
            Lead.tenant_id == tenant_id, Lead.status != "invalid"
        )
    ) or 0)
    # 计划级线索分布
    camp_leads = (await session.execute(
        select(Lead.campaign_name, func.count())
        .where(Lead.tenant_id == tenant_id, Lead.status != "invalid",
               Lead.campaign_name.isnot(None))
        .group_by(Lead.campaign_name).order_by(func.count().desc()).limit(6)
    )).all()

    open_alerts = int(await session.scalar(
        select(func.count()).select_from(Alert).where(
            Alert.tenant_id == tenant_id, Alert.status == "open"
        )
    ) or 0)

    lines = [
        f"【客户数据】（用户请求：{period.label}；本次统计 {start.isoformat()} ~ {end.isoformat()}）",
    ]
    if coverage_limited:
        covered_days = (end - start).days + 1
        lines.append(
            f"- 数据覆盖提示：请求区间为 {period.start.isoformat()} ~ {period.end.isoformat()}，"
            f"数据库实际可用区间仅为 {min_date.isoformat()} ~ {max_date.isoformat()}；"
            f"本次按重叠的 {start.isoformat()} ~ {end.isoformat()}（{covered_days}个自然日）汇总，"
            f"不足以代表完整的“{period.label}”。回答时必须明确说明这一限制。"
        )
    lines.extend([
        f"- 消费 ¥{cost:.2f}｜点击 {click}｜展现 {imp}｜转化(电话点击) {conv}"
        + (f"｜单次转化成本 ¥{cost/conv:.2f}" if conv else "｜转化为 0"),
        f"- 真线索累计 {lead_total} 条" + (
            "（按计划：" + "，".join(f"{n} {c}条" for n, c in camp_leads) + "）" if camp_leads else ""
        ),
        f"- 近 7 天电话转化 {conv7} 个，智能投放数据充足度：{adequacy}"
        + "（学习参考门槛约 15/周）",
        f"- 未处理异常提醒 {open_alerts} 条",
    ])
    if top_conversions:
        lines.append("- 转化 Top 词（按转化量排序）：" + "；".join(
            f"{kw} {cv}转化/点击{clk}/消费¥{c:.2f}"
            for kw, cv, c, clk in top_conversions
        ))
    elif conv:
        lines.append("- 转化词明细：该区间有转化，但快照中没有可归属的关键词名称。")
    else:
        lines.append("- 转化词明细：该统计区间没有产生转化的关键词。")
    if top_spend:
        lines.append("- 消费 Top 词：" + "；".join(
            f"{kw} ¥{c:.0f}/{cv}转化" for kw, c, cv in top_spend[:6]))
    if zero_conv:
        lines.append("- ⚠️ 烧钱零转化词（消费≥¥30 且 0 转化）："
                     + "；".join(f"{kw} ¥{c:.0f}" for kw, c, _ in zero_conv))

    # 拓词候选：AI 评估「建议拓展」的待处理候选（给拓词建议用）
    cand_rows = (await session.execute(
        select(KeywordCandidate.word, KeywordCandidate.ai_suggested_bid, KeywordCandidate.ai_reason)
        .where(
            KeywordCandidate.tenant_id == tenant_id,
            KeywordCandidate.status == "pending",
            KeywordCandidate.ai_recommend == "adopt",
        )
        .order_by(KeywordCandidate.potential_score.desc().nullslast())
        .limit(8)
    )).all()
    if cand_rows:
        lines.append("- 🌱 拓词候选（AI 评估建议拓展，去拓词页加入计划）："
                     + "；".join(
                         f"{w}" + (f" 建议价¥{float(b):.2f}" if b is not None else "")
                         for w, b, _ in cand_rows))
    return "\n".join(lines)


async def get_active_memories(session: AsyncSession, tenant_id: int) -> list[TenantMemory]:
    return list((await session.scalars(
        select(TenantMemory).where(
            TenantMemory.tenant_id == tenant_id,
            TenantMemory.active.is_(True),
            TenantMemory.confirmed.is_(True),
        ).order_by(TenantMemory.id)
    )).all())


def _memories_block(mems: list[TenantMemory]) -> str:
    if not mems:
        return "【已知客户目标/约束】（暂无，可在对话中告诉我并确认记住）"
    lines = ["【已知客户目标/约束】（按设定时间先后；若有冲突以最近设定的为准）"]
    for m in mems:
        d = m.created_at.date().isoformat() if m.created_at else "?"
        lines.append(f"- [{MEMORY_TYPE_LABELS.get(m.mem_type, m.mem_type)}] {m.content}（{d} 设定）")
    return "\n".join(lines)


async def run_chat(
    session: AsyncSession, tenant_id: int, history: list[dict]
) -> dict[str, Any]:
    """history = [{role:'user'|'assistant', content}]，最后一条是用户最新问题。

    返回 {reply, suggestions, memories}。memories 为 AI 抽取的待确认条目。
    """
    if not is_enabled():
        return {"reply": "AI 助手未启用（未配置 DEEPSEEK_API_KEY）。", "suggestions": [], "memories": []}

    latest_user_message = next(
        (str(item.get("content") or "") for item in reversed(history) if item.get("role") == "user"),
        "",
    )
    summary = await build_context_summary(session, tenant_id, latest_user_message)
    mems = await get_active_memories(session, tenant_id)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    system = (
        SYSTEM_PROMPT
        + f"\n\n今天是 {today}（北京时间）。涉及时间的回答与记忆都据此换算成绝对日期。"
        + "\n\n" + summary + "\n\n" + _memories_block(mems)
    )

    window = history[-HISTORY_WINDOW:]
    messages = [{"role": "system", "content": system}] + [
        {"role": m["role"], "content": m["content"]} for m in window
    ]
    try:
        out = await chat_messages(messages, json_mode=True, temperature=0.5)
    except DeepSeekError as e:
        logger.warning("助手对话失败 tenant=%s: %s", tenant_id, e)
        return {"reply": f"抱歉，AI 暂时没能回答（{e}）。请稍后再试。",
                "suggestions": [], "memories": []}

    if not isinstance(out, dict):
        return {"reply": str(out), "suggestions": [], "memories": []}
    actions, suggestions = _sanitize_assistant_output(out)
    return {
        "reply": out.get("reply") or "（无回答）",
        "suggestions": suggestions,
        "actions": actions,
        "memories": out.get("memories") or [],
        "builder": _normalize_builder_request(out.get("builder")),
    }


# ===== 对话持久化（按用户隔离，保留近 MESSAGE_RETAIN_DAYS 天） =====


def _message_owner_filter(user_id: int | None):
    return (
        AssistantMessage.user_id.is_(None)
        if user_id is None
        else AssistantMessage.user_id == user_id
    )


async def load_history(
    session: AsyncSession,
    tenant_id: int,
    user_id: int | None,
    limit: int = 200,
) -> list[AssistantMessage]:
    """读最近的对话历史（保留期内），按时间正序返回给前端渲染。"""
    rows = (await session.scalars(
        select(AssistantMessage)
        .where(
            AssistantMessage.tenant_id == tenant_id,
            _message_owner_filter(user_id),
        )
        .order_by(AssistantMessage.id.desc())
        .limit(limit)
    )).all()
    return list(reversed(rows))


async def save_message(
    session: AsyncSession,
    tenant_id: int,
    user_id: int | None,
    role: str,
    content: str,
) -> None:
    session.add(
        AssistantMessage(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            content=content,
        )
    )
    await session.commit()


async def chat_turn(
    session: AsyncSession,
    tenant_id: int,
    user_id: int | None,
    user_message: str,
) -> dict[str, Any]:
    """一轮对话：存用户消息 → 读最近窗口 → 调 LLM → 存回复。前端只需传新问题。"""
    await save_message(session, tenant_id, user_id, "user", user_message)
    recent = (await session.scalars(
        select(AssistantMessage)
        .where(
            AssistantMessage.tenant_id == tenant_id,
            _message_owner_filter(user_id),
        )
        .order_by(AssistantMessage.id.desc())
        .limit(HISTORY_WINDOW)
    )).all()
    history = [{"role": m.role, "content": m.content} for m in reversed(recent)]
    result = await run_chat(session, tenant_id, history)
    await save_message(session, tenant_id, user_id, "assistant", result["reply"])
    return result


MAX_ADOPT_KEYWORDS = 50  # 一键采纳单次最多处理词数（护栏，防 AI 给一大串）
ADOPT_TYPES = ("pause", "adjust_bid", "negative", "set_budget")


async def adopt_action(
    session: AsyncSession,
    tenant_id: int,
    atype: str,
    keywords: list[str],
    *,
    adjust_pct: float | None = None,
    match_mode: str = "exact",
    budget: float | None = None,
    operator_user_id: int | None = None,
    operator_name: str | None = None,
) -> dict[str, Any]:
    """一键采纳 AI 建议：按词名反查 keyword_id/adgroup_id，硬校验后调现有写回（受 dry-run +
    护栏 + 台账保护）。AI 只建议、这里只执行库里真实存在的词，编造/越界的跳过。逐词返回结果。
    set_budget 是账户级（无关键词），单独走账户日预算写回。
    """
    from app.baidu.writeback import (
        WritebackError,
        apply_account_budget_writeback,
        apply_keyword_writeback,
        apply_negative_writeback,
        apply_pause_writeback,
    )
    from app.models import Keyword

    if atype not in ADOPT_TYPES:
        raise ValueError(f"不支持的动作类型：{atype}")

    # set_budget：账户日预算（安全总闸），不涉及关键词，单独处理
    if atype == "set_budget":
        if budget is None:
            raise ValueError("设日预算需要 budget 金额")
        try:
            rec = await apply_account_budget_writeback(
                session, tenant_id, budget,
                operator_user_id=operator_user_id, operator_name=operator_name,
            )
        except WritebackError as e:
            raise ValueError(str(e))
        detail = (
            f"账户日预算 {rec.old_value or '—'} → {rec.new_value}"
            + ("（演练未真改）" if rec.dry_run else "")
        )
        return {
            "results": [{"keyword": "账户日预算", "status": rec.status, "detail": detail}],
            "dry_run": rec.dry_run,
        }

    names = [k.strip() for k in (keywords or []) if k and k.strip()][:MAX_ADOPT_KEYWORDS]
    if not names:
        raise ValueError("没有可执行的关键词")

    results: list[dict] = []
    for name in names:
        kws = (await session.scalars(
            select(Keyword).where(Keyword.tenant_id == tenant_id, Keyword.keyword == name)
        )).all()

        if atype in ("pause", "adjust_bid"):
            if not kws:
                results.append({"keyword": name, "status": "skipped", "detail": "库里找不到该关键词"})
                continue
            for kw in kws:
                try:
                    if atype == "pause":
                        rec = await apply_pause_writeback(
                            session, tenant_id, kw.keyword_id, True,
                            operator_user_id=operator_user_id, operator_name=operator_name,
                        )
                    else:
                        if kw.price is None:
                            results.append({"keyword": name, "status": "skipped", "detail": "无当前出价，无法调价"})
                            continue
                        target = round(float(kw.price) * (1 + (adjust_pct or 0) / 100), 2)
                        rec = await apply_keyword_writeback(
                            session, tenant_id, kw.keyword_id, target,
                            operator_user_id=operator_user_id, operator_name=operator_name,
                        )
                    results.append({"keyword": name, "status": rec.status, "detail": rec.error_msg or ""})
                except WritebackError as e:
                    results.append({"keyword": name, "status": "failed", "detail": str(e)})
        else:  # negative：加到该词所属单元（去重；找不到单元则跳过提示手动）
            adg_ids = {kw.adgroup_id for kw in kws if kw.adgroup_id is not None}
            if not adg_ids:
                results.append({"keyword": name, "status": "skipped", "detail": "找不到所属单元，去否词页手动加"})
                continue
            for adg in adg_ids:
                try:
                    rec = await apply_negative_writeback(
                        session, tenant_id, name, adg, match_mode=match_mode or "exact",
                        operator_user_id=operator_user_id, operator_name=operator_name,
                    )
                    results.append({"keyword": name, "status": rec.status, "detail": f"单元 #{adg}"})
                except WritebackError as e:
                    results.append({"keyword": name, "status": "failed", "detail": str(e)})

    return {"results": results, "dry_run": any(r["status"] == "dry_run" for r in results)}


async def purge_old_messages(session: AsyncSession, days: int = MESSAGE_RETAIN_DAYS) -> int:
    """清理保留期外的对话（定时任务每日跑）。返回删除条数。记忆表不受影响。"""
    cutoff = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None) - timedelta(days=days)
    n = await session.scalar(
        select(func.count()).select_from(AssistantMessage).where(AssistantMessage.created_at < cutoff)
    )
    await session.execute(delete(AssistantMessage).where(AssistantMessage.created_at < cutoff))
    await session.commit()
    return int(n or 0)
