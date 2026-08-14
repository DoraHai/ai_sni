"""待验证调价（效果验证 · R-10 调价后验证）。

把近 N 天的出价调整（operation_records bidPriceWord）拉成待办，对每条算「调价前 vs 调价后」
效果（排名/消费/点击/CTR），加 AI 研判「这次调价达没达目的」。人工核对后标已验证。

调前/后效果实时算（数据还在变）；审核状态 + AI 研判缓存在 adjustment_reviews。
复用调价建议那套 DeepSeek + 降级。🚫 只读聚合 + 判定，不碰百度写回。
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import DeepSeekError, chat_json, is_enabled
from app.models import (
    AdjustmentReview,
    Keyword,
    KwReportSnapshot,
    OperationRecord,
    Tenant,
)

logger = logging.getLogger(__name__)

BEFORE_DAYS = 7  # 调价前对比窗口
MAX_ITEMS = 200  # 单次最多处理的调价条数（账户改价频繁，全量算效果会慢；超出截断）


def _f(v):
    return round(float(v), 2) if v is not None else None


def _parse_num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


async def _resolve_kw_ids(session: AsyncSession, tenant_id: int, names: set[str]) -> dict[str, int]:
    """归一化关键词名 → 展现最高的 keyword_id（与调价台账同口径）。"""
    from app.api.operations import _norm_kw

    norm = {_norm_kw(n) for n in names if n}
    if not norm:
        return {}
    best: dict[str, tuple[int, int]] = {}
    for name, kid, imp in (
        await session.execute(
            select(Keyword.keyword, Keyword.keyword_id, Keyword.total_impression).where(
                Keyword.tenant_id == tenant_id, Keyword.keyword.in_(norm)
            )
        )
    ).all():
        imp = int(imp or 0)
        if name not in best or imp > best[name][0]:
            best[name] = (imp, kid)
    return {n: v[1] for n, v in best.items()}


async def _window_metrics(session, tenant_id, keyword_id, start: date, end: date) -> dict | None:
    """某词某窗口的日均效果。无数据返回 None。"""
    if keyword_id is None or start > end:
        return None
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(KwReportSnapshot.cost), 0),
                func.coalesce(func.sum(KwReportSnapshot.click), 0),
                func.coalesce(func.sum(KwReportSnapshot.impression), 0),
                func.avg(KwReportSnapshot.avg_rank),
                func.count(func.distinct(KwReportSnapshot.report_date)),
            ).where(
                KwReportSnapshot.tenant_id == tenant_id,
                KwReportSnapshot.keyword_id == keyword_id,
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
            )
        )
    ).one()
    days = int(row[4] or 0)
    if days == 0:
        return None
    cost, click, imp = float(row[0]), int(row[1]), int(row[2])
    return {
        "days": days,
        "cost_per_day": round(cost / days, 2),
        "click_per_day": round(click / days, 1),
        "impression_per_day": round(imp / days, 1),
        "ctr": round(click / imp, 4) if imp else None,
        "avg_rank": _f(row[3]),
    }


async def list_pending(
    session: AsyncSession, tenant: Tenant, days: int = 7, status: str | None = None
) -> list[dict]:
    """近 days 天的出价调整 + 调前/后效果 + 审核/AI 状态。status: pending/verified/None=全部。"""
    tid = tenant.id
    since = datetime.utcnow() - timedelta(days=days)
    recs = (
        await session.scalars(
            select(OperationRecord)
            .where(
                OperationRecord.tenant_id == tid,
                OperationRecord.opt_level == 5,
                OperationRecord.opt_content == "bidPriceWord",
                OperationRecord.opt_time >= since,
            )
            .order_by(OperationRecord.opt_time.desc())
            .limit(MAX_ITEMS)
        )
    ).all()
    if not recs:
        return []

    kw_ids = await _resolve_kw_ids(session, tid, {r.opt_obj for r in recs})
    from app.api.operations import _norm_kw

    reviews = {
        rv.dedup_key: rv
        for rv in (
            await session.scalars(
                select(AdjustmentReview).where(AdjustmentReview.tenant_id == tid)
            )
        ).all()
    }
    latest = await session.scalar(
        select(func.max(KwReportSnapshot.report_date)).where(KwReportSnapshot.tenant_id == tid)
    )

    items = []
    for r in recs:
        rv = reviews.get(r.dedup_key)
        st = rv.status if rv else "pending"
        if status and st != status:
            continue
        kid = kw_ids.get(_norm_kw(r.opt_obj))
        old_v, new_v = _parse_num(r.old_value), _parse_num(r.new_value)
        change_pct = (
            round((new_v - old_v) / old_v * 100, 1) if old_v not in (None, 0) and new_v is not None else None
        )
        direction = "raise" if change_pct and change_pct > 0 else ("lower" if change_pct and change_pct < 0 else "flat")
        t_date = r.opt_time.date()
        before = await _window_metrics(session, tid, kid, t_date - timedelta(days=BEFORE_DAYS), t_date - timedelta(days=1))
        after = await _window_metrics(session, tid, kid, t_date, latest) if latest else None
        items.append({
            "dedup_key": r.dedup_key,
            "opt_time": r.opt_time.isoformat(),
            "keyword": r.opt_obj,
            "keyword_id": kid,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "change_pct": change_pct,
            "direction": direction,
            "over_limit": bool(change_pct is not None and abs(change_pct) > 20),
            "effect": {"before": before, "after": after, "after_through": latest.isoformat() if latest else None},
            "review": {
                "status": st,
                "verdict": rv.verdict if rv else None,
                "note": rv.note if rv else None,
                "verified_at": rv.verified_at.isoformat() if rv and rv.verified_at else None,
            },
            "ai": {
                "verdict": rv.ai_verdict if rv else None,
                "reason": rv.ai_reason if rv else None,
                "generated_at": rv.ai_generated_at.isoformat() if rv and rv.ai_generated_at else None,
            },
        })
    return items


async def build_one(session: AsyncSession, tenant: Tenant, dedup_key: str) -> dict | None:
    """重算单条调价的 item（供 AI 研判端点用，不限 7 天窗口）。"""
    rec = await session.scalar(
        select(OperationRecord).where(
            OperationRecord.tenant_id == tenant.id, OperationRecord.dedup_key == dedup_key
        )
    )
    if rec is None:
        return None
    from app.api.operations import _norm_kw

    kw_ids = await _resolve_kw_ids(session, tenant.id, {rec.opt_obj})
    kid = kw_ids.get(_norm_kw(rec.opt_obj))
    old_v, new_v = _parse_num(rec.old_value), _parse_num(rec.new_value)
    change_pct = (
        round((new_v - old_v) / old_v * 100, 1) if old_v not in (None, 0) and new_v is not None else None
    )
    direction = "raise" if change_pct and change_pct > 0 else ("lower" if change_pct and change_pct < 0 else "flat")
    latest = await session.scalar(
        select(func.max(KwReportSnapshot.report_date)).where(KwReportSnapshot.tenant_id == tenant.id)
    )
    t_date = rec.opt_time.date()
    return {
        "dedup_key": dedup_key,
        "keyword": rec.opt_obj,
        "old_value": rec.old_value,
        "new_value": rec.new_value,
        "change_pct": change_pct,
        "direction": direction,
        "effect": {
            "before": await _window_metrics(session, tenant.id, kid, t_date - timedelta(days=BEFORE_DAYS), t_date - timedelta(days=1)),
            "after": await _window_metrics(session, tenant.id, kid, t_date, latest) if latest else None,
        },
    }


SYSTEM_PROMPT = """你是资深 SEM 优化师，评估一次关键词出价调整有没有达到目的。
加价目的通常是抢排名/扩量；降价目的通常是控成本/止损。当前无转化数据，按排名/流量/成本效率判断。
对比调价前后的日均数据，给出判定。数据太少（调后天数少）时给「继续观察」。

只返回 JSON：{"verdict": "achieved|missed|watch", "reason": "给运营看的中文理由，30 字以内"}"""


def _fmt_metrics(m: dict | None) -> str:
    if not m:
        return "无数据"
    ctr = f"{round(m['ctr'] * 100, 2)}%" if m["ctr"] is not None else "—"
    return f"日均消费¥{m['cost_per_day']}、日均点击{m['click_per_day']}、点击率{ctr}、均排名{m['avg_rank']}（{m['days']}天）"


def _build_prompt(item: dict) -> str:
    dir_label = {"raise": "加价", "lower": "降价", "flat": "调整"}[item["direction"]]
    return "\n".join([
        f"关键词：{item['keyword']}",
        f"调价：{item['old_value']} → {item['new_value']}（{dir_label} {item['change_pct']}%）",
        f"调价前：{_fmt_metrics(item['effect']['before'])}",
        f"调价后：{_fmt_metrics(item['effect']['after'])}",
    ])


async def generate_verdict(session: AsyncSession, tenant: Tenant, item: dict, force: bool = False) -> dict | None:
    """对一条调价生成 AI 研判，缓存在 adjustment_reviews。未配 key 返回 None。"""
    if not is_enabled():
        return None
    rv = await session.scalar(
        select(AdjustmentReview).where(
            AdjustmentReview.tenant_id == tenant.id, AdjustmentReview.dedup_key == item["dedup_key"]
        )
    )
    if rv and rv.ai_verdict and not force:
        return {"verdict": rv.ai_verdict, "reason": rv.ai_reason}
    try:
        out = await chat_json(SYSTEM_PROMPT, _build_prompt(item))
    except DeepSeekError as e:
        logger.warning("调价 AI 研判失败 dedup=%s：%s", item["dedup_key"], e)
        return None
    verdict = out.get("verdict") if out.get("verdict") in ("achieved", "missed", "watch") else "watch"
    reason = str(out.get("reason") or "")[:200]
    if rv is None:
        rv = AdjustmentReview(tenant_id=tenant.id, dedup_key=item["dedup_key"])
        session.add(rv)
    rv.ai_verdict = verdict
    rv.ai_reason = reason
    rv.ai_generated_at = datetime.utcnow()
    await session.commit()
    return {"verdict": verdict, "reason": reason}
