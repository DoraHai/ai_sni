"""R-AI（AI 异常扫描）：突破固定阈值规则的局限，让 AI 主动发现值得关注的异常。

做法（控成本三步）：
  1. 环比聚合：每个关键词 近 7 天 vs 前 7 天 的 消费/点击/展现/排名 变化
  2. 规则预筛：只把「变化显著」的词（占少数）作为候选，避免逐词喂 AI
  3. AI 判断：候选 + 环比数据 → AI 判定真异常 + 优先级 + 类型 + 理由（批量）

产出 AlertDraft（rule_code=R-AI，priority/title/message 由 AI 给），交 engine 统一落库 + 同词归并。
未配 DeepSeek 时返回空（降级，不影响硬规则）。AI 是判断，预筛是护栏（只喂它该看的）。
"""
import json
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import DeepSeekError, chat_json, is_enabled
from app.models import Campaign, KwReportSnapshot, Tenant
from app.rules.base import AlertDraft

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7        # 环比窗口：近 7 天 vs 前 7 天
MAX_CANDIDATES = 30    # 喂 AI 的候选上限（按变化幅度取 top N，控成本）
VALID_PRIORITIES = {"P0", "P1", "P2", "P3", "P4", "P5"}

SYSTEM_PROMPT = """你是资深 SEM 优化师，为工业品（工业泵 / 分离技术）账户盯盘。
我会给你一批关键词近 7 天 vs 前 7 天的环比变化（已用规则预筛出变化较大的词）。
你的任务：判断每个词的变化是不是「值得运营关注的异常」，而不是正常波动。

判断原则：
- 工业品流量小、波动大，轻微变化或低基数（几次展现/点击）的剧烈百分比不算异常
- 真正该报的：消费明显突增（可能烧钱失控）、点击/展现骤降或归零（可能掉量/被否/暂停）、
  排名明显下滑（可能被竞品超）、消费涨但点击没涨（效率恶化）
- 优先级 P0 最紧急（立即处理，如核心词消费暴涨/掉零）→ P5 仅提示；多数异常在 P1~P3
- 谨慎：拿不准当不是异常（is_anomaly=false）

只返回 JSON（不要多余文字）：
{"items": [{"keyword_id": 123, "is_anomaly": true, "priority": "P2", "title": "简短标题(不超15字)", "reason": "一句话说清异常+建议，40字内"}]}
items 覆盖我给的每个词；keyword_id 原样回填；is_anomaly=false 的可省略 priority/title/reason。"""


async def _agg(session: AsyncSession, tenant_id: int, start: date, end: date) -> dict[int, dict]:
    """按关键词聚合窗口内 展现/点击/消费 合计 + 平均排名（跨设备 sum）。"""
    rows = (
        await session.execute(
            select(
                KwReportSnapshot.keyword_id,
                func.max(KwReportSnapshot.keyword),
                func.max(KwReportSnapshot.campaign_id),
                func.coalesce(func.sum(KwReportSnapshot.impression), 0),
                func.coalesce(func.sum(KwReportSnapshot.click), 0),
                func.coalesce(func.sum(KwReportSnapshot.cost), 0),
                func.avg(KwReportSnapshot.avg_rank),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant_id,
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
                KwReportSnapshot.keyword_id.isnot(None),
            )
            .group_by(KwReportSnapshot.keyword_id)
        )
    ).all()
    return {
        r[0]: {
            "keyword": r[1], "campaign_id": r[2],
            "impression": int(r[3]), "click": int(r[4]),
            "cost": float(r[5]), "rank": float(r[6]) if r[6] is not None else None,
        }
        for r in rows
    }


def _pct(cur: float, prev: float) -> float | None:
    if prev == 0:
        return None if cur == 0 else 999.0
    return (cur - prev) / prev * 100


def _significant(cur: dict, prev: dict) -> bool:
    """规则预筛：变化是否够显著，值得交给 AI 判断（粗筛，宁可多放）。"""
    # 消费突增/骤降（基数有意义）
    cp = _pct(cur["cost"], prev["cost"])
    if cp is not None and abs(cp) >= 50 and max(cur["cost"], prev["cost"]) >= 10:
        return True
    # 点击突变
    kp = _pct(cur["click"], prev["click"])
    if kp is not None and abs(kp) >= 50 and max(cur["click"], prev["click"]) >= 10:
        return True
    # 展现归零 / 暴增
    if prev["impression"] >= 20 and cur["impression"] == 0:
        return True
    if cur["impression"] >= 50 and cur["impression"] >= 3 * max(prev["impression"], 1):
        return True
    # 排名明显下滑
    if cur["rank"] is not None and prev["rank"] is not None and (cur["rank"] - prev["rank"]) >= 1.5:
        return True
    return False


def _change_magnitude(cur: dict, prev: dict) -> float:
    """变化幅度（排序用，取消费/点击/展现环比绝对值的最大者）。"""
    vals = [
        abs(_pct(cur["cost"], prev["cost"]) or 0),
        abs(_pct(cur["click"], prev["click"]) or 0),
        abs(_pct(cur["impression"], prev["impression"]) or 0),
    ]
    return max(vals)


class AIAnomalyRule:
    """AI 异常扫描（实现 Rule 接口，挂进 engine.ALL_RULES，复用落库 + 归并 + 调度）。"""

    code = "R-AI"
    priority = "P2"  # 仅满足 Rule 协议；实际每条用 AI 给的优先级

    async def evaluate(
        self, session: AsyncSession, tenant: Tenant, target_date: date
    ) -> list[AlertDraft]:
        if not is_enabled():
            return []

        cur_start = target_date - timedelta(days=WINDOW_DAYS - 1)
        prev_end = cur_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=WINDOW_DAYS - 1)

        cur = await _agg(session, tenant.id, cur_start, target_date)
        prev = await _agg(session, tenant.id, prev_start, prev_end)
        if not cur and not prev:
            return []

        # 预筛显著变化候选
        cands = []
        for kid, c in cur.items():
            p = prev.get(kid, {"impression": 0, "click": 0, "cost": 0.0, "rank": None})
            if _significant(c, p):
                cands.append((kid, c, p, _change_magnitude(c, p)))
        # 前期有量、本期完全无数据（掉零）的词也算候选
        for kid, p in prev.items():
            if kid not in cur and p["impression"] >= 20:
                cands.append((kid, {"impression": 0, "click": 0, "cost": 0.0, "rank": None, "keyword": p["keyword"], "campaign_id": p["campaign_id"]}, p, 999.0))

        if not cands:
            return []
        cands.sort(key=lambda x: x[3], reverse=True)
        cands = cands[:MAX_CANDIDATES]

        camp_names = await _campaign_names(session, tenant.id)
        try:
            verdicts = await self._judge(cands)
        except DeepSeekError as e:
            logger.warning("AI 异常扫描调用失败（降级跳过）tenant=%s：%s", tenant.id, e)
            return []

        drafts: list[AlertDraft] = []
        for kid, c, p, _ in cands:
            v = verdicts.get(kid)
            if not v or not v.get("is_anomaly"):
                continue
            pr = v.get("priority") if v.get("priority") in VALID_PRIORITIES else "P3"
            drafts.append(
                AlertDraft(
                    rule_code=self.code, priority=pr,
                    title=str(v.get("title") or "AI 发现异常")[:40],
                    message=str(v.get("reason") or "")[:300],
                    report_date=target_date,
                    keyword_id=kid, keyword=c.get("keyword") or p.get("keyword"),
                    campaign_id=c.get("campaign_id") or p.get("campaign_id"),
                    campaign_name=camp_names.get(c.get("campaign_id") or p.get("campaign_id")),
                    metrics={
                        "近7天": {"展现": c["impression"], "点击": c["click"], "消费": round(c["cost"], 2), "排名": c["rank"]},
                        "前7天": {"展现": p["impression"], "点击": p["click"], "消费": round(p["cost"], 2), "排名": p["rank"]},
                    },
                )
            )
        return drafts

    async def _judge(self, cands: list[tuple]) -> dict[int, dict]:
        lines = ["待研判关键词（近7天 → 前7天环比）："]
        for kid, c, p, _ in cands:
            lines.append(
                f"- id={kid}「{c.get('keyword') or p.get('keyword')}」"
                f"展现 {p['impression']}→{c['impression']}，点击 {p['click']}→{c['click']}，"
                f"消费 ¥{p['cost']:.0f}→¥{c['cost']:.0f}，"
                f"排名 {p['rank'] if p['rank'] is not None else '—'}→{c['rank'] if c['rank'] is not None else '—'}"
            )
        out = await chat_json(SYSTEM_PROMPT, "\n".join(lines))
        items = out.get("items")
        if not isinstance(items, list):
            raise DeepSeekError(f"返回结构异常（缺 items）：{json.dumps(out)[:200]}")
        result: dict[int, dict] = {}
        for it in items:
            if isinstance(it, dict) and it.get("keyword_id") is not None:
                try:
                    result[int(it["keyword_id"])] = it
                except (TypeError, ValueError):
                    continue
        return result


async def _campaign_names(session: AsyncSession, tenant_id: int) -> dict[int, str]:
    rows = (
        await session.execute(
            select(Campaign.campaign_id, Campaign.campaign_name).where(Campaign.tenant_id == tenant_id)
        )
    ).all()
    return {r[0]: r[1] for r in rows}
