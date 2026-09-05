"""待验证调价（效果验证 · R-10 调价后验证）。

把近 N 天的出价调整（operation_records bidPriceWord）拉成待办，对每条算「调价前 vs 调价后」
效果（排名/消费/点击/CTR），加 AI 研判「这次调价达没达目的」。人工核对后标已验证。

调前/后效果实时算（数据还在变）；审核状态 + AI 研判缓存在 adjustment_reviews。
复用调价建议那套 DeepSeek + 降级。🚫 只读聚合 + 判定，不碰百度写回。
"""
import hashlib
import json
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import DeepSeekError, chat_json, is_enabled
from app.ai.effect_verification import effect_window, window_info, select_review_page, review_note
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
MIN_AFTER_DAYS = 3
AI_CACHE_PREFIX = "sem-effect-v2:"


def _effect_fingerprint(item: dict) -> str:
    context = {key: item.get(key) for key in (
        "dedup_key", "keyword", "keyword_id", "baidu_account_id",
        "old_value", "new_value", "effect",
    )}
    return hashlib.sha256(json.dumps(
        context, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _cached_ai(review, item: dict) -> dict | None:
    """旧缓存没有身份/样本依据，不再展示；保留原记录，不回填数据。"""
    if (not review or not review.ai_verdict
            or item.get("effect", {}).get("sample", {}).get("state") != "ready"):
        return None
    raw = review.ai_reason or ""
    if not raw.startswith(AI_CACHE_PREFIX):
        return None
    try:
        cached = json.loads(raw[len(AI_CACHE_PREFIX):])
    except (ValueError, TypeError):
        return None
    if (not isinstance(cached, dict)
            or cached.get("fingerprint") != _effect_fingerprint(item)
            or not isinstance(cached.get("reason"), str)):
        return None
    return {"verdict": review.ai_verdict, "reason": cached["reason"]}


def _f(v):
    return round(float(v), 2) if v is not None else None


def _parse_num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def sample_status(keyword_id: int | None, before: dict | None, after: dict | None) -> dict:
    if keyword_id is None:
        return {"state": "unmatched", "message": "未匹配到唯一关键词，暂不能计算效果"}
    if before is None:
        return {"state": "missing_before", "message": "缺少调价前快照，暂不能对比"}
    if after is None:
        return {"state": "collecting", "message": "调价后数据尚未同步"}
    if int(after.get("days") or 0) < MIN_AFTER_DAYS:
        return {"state": "collecting", "message": f"调价后仅 {after.get('days', 0)} 天，至少积累 {MIN_AFTER_DAYS} 天"}
    return {"state": "ready", "message": "样本已达到基础验证门槛"}


async def _resolve_keywords(session: AsyncSession, tenant_id: int, records) -> dict[str, Keyword]:
    """按操作记录的账户/计划/单元定位；缺账户或不唯一时失败关闭。"""
    from app.api.operations import _norm_kw

    norm = {_norm_kw(r.opt_obj) for r in records if r.opt_obj}
    if not norm:
        return {}
    candidates = (
        await session.scalars(
            select(Keyword).where(
                Keyword.tenant_id == tenant_id, Keyword.keyword.in_(norm)
            )
        )
    ).all()
    resolved = {}
    for rec in records:
        if rec.tenant_id != tenant_id or rec.baidu_account_id is None:
            continue
        matches = [kw for kw in candidates
                   if kw.keyword == _norm_kw(rec.opt_obj)
                   and kw.baidu_account_id == rec.baidu_account_id
                   and (rec.plan_id is None or kw.campaign_id == rec.plan_id)
                   and (rec.unit_id is None or kw.adgroup_id == rec.unit_id)]
        if len(matches) == 1:
            resolved[rec.dedup_key] = matches[0]
    return resolved


def _report_scope(tenant_id, keyword):
    return [KwReportSnapshot.tenant_id == tenant_id,
            KwReportSnapshot.baidu_account_id == keyword.baidu_account_id,
            KwReportSnapshot.keyword_id == keyword.keyword_id,
            KwReportSnapshot.campaign_id == keyword.campaign_id,
            KwReportSnapshot.adgroup_id == keyword.adgroup_id]


async def _latest_report(session, tenant_id, keyword):
    if keyword is None:
        return None
    return await session.scalar(select(func.max(KwReportSnapshot.report_date)).where(
        *_report_scope(tenant_id, keyword)))


async def _window_metrics(session, tenant_id, keyword, start: date, end: date) -> dict | None:
    """某词某窗口的日均效果。无数据返回 None。"""
    if keyword is None or start > end:
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
                *_report_scope(tenant_id, keyword),
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


async def _keyword_effect(session, tenant_id, rec, keyword):
    latest = await _latest_report(session, tenant_id, keyword)
    next_time = None
    if keyword:
        # 名称标准化在内存完成，以覆盖百度的引号包装；含同一时刻的不同记录。
        later = (await session.scalars(select(OperationRecord).where(
            OperationRecord.tenant_id == tenant_id,
            OperationRecord.baidu_account_id == rec.baidu_account_id,
            OperationRecord.opt_level == 5, OperationRecord.opt_content == "bidPriceWord",
            OperationRecord.opt_time >= rec.opt_time,
            OperationRecord.dedup_key != rec.dedup_key,
        ))).all()
        from app.api.operations import _norm_kw
        possible = [r.opt_time for r in later if _norm_kw(r.opt_obj) == _norm_kw(rec.opt_obj)
                    and (r.plan_id is None or r.plan_id == keyword.campaign_id)
                    and (r.unit_id is None or r.unit_id == keyword.adgroup_id)]
        next_time = min(possible) if possible else None
    next_date = next_time.date() if next_time else None
    start, end = effect_window(rec.opt_time.date(), latest, next_date)
    before = await _window_metrics(session, tenant_id, keyword,
        rec.opt_time.date() - timedelta(days=BEFORE_DAYS), rec.opt_time.date() - timedelta(days=1))
    after = await _window_metrics(session, tenant_id, keyword, start, end) if end and end >= start else None
    info = window_info(start, end, next_date)
    kid = keyword.keyword_id if keyword else None
    return {"before": before, "after": after, "after_through": info["after_through"],
            "window": info, "sample": sample_status(kid, before, after)}


async def list_pending(
    session: AsyncSession, tenant: Tenant, days: int = 7, status: str | None = None,
    offset: int = 0, limit: int = MAX_ITEMS, paged: bool = False,
) -> list[dict]:
    """近 days 天的出价调整 + 调前/后效果 + 审核/AI 状态。status: pending/verified/None=全部。"""
    tid = tenant.id
    since = datetime.utcnow() - timedelta(days=days)
    recs, page = await select_review_page(session, OperationRecord, OperationRecord.dedup_key, [
                OperationRecord.tenant_id == tid,
                OperationRecord.opt_level == 5,
                OperationRecord.opt_content == "bidPriceWord",
                OperationRecord.opt_time >= since,
    ], [OperationRecord.opt_time.desc(), OperationRecord.id.desc()], status, offset, limit)
    if not recs:
        return {**page, "items": []} if paged else []

    keywords = await _resolve_keywords(session, tid, recs)

    reviews = {
        rv.dedup_key: rv
        for rv in (
            await session.scalars(
                select(AdjustmentReview).where(
                    AdjustmentReview.tenant_id == tid,
                    AdjustmentReview.dedup_key.in_([r.dedup_key for r in recs]),
                )
            )
        ).all()
    }

    items = []
    for r in recs:
        rv = reviews.get(r.dedup_key)
        st = rv.status if rv else "pending"
        if status and st != status:
            continue
        keyword = keywords.get(r.dedup_key)
        kid = keyword.keyword_id if keyword else None
        effect = await _keyword_effect(session, tid, r, keyword)
        old_v, new_v = _parse_num(r.old_value), _parse_num(r.new_value)
        change_pct = (
            round((new_v - old_v) / old_v * 100, 1) if old_v not in (None, 0) and new_v is not None else None
        )
        direction = "raise" if change_pct and change_pct > 0 else ("lower" if change_pct and change_pct < 0 else "flat")
        items.append({
            "dedup_key": r.dedup_key,
            "opt_time": r.opt_time.isoformat(),
            "keyword": r.opt_obj,
            "keyword_id": kid,
            "baidu_account_id": r.baidu_account_id,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "change_pct": change_pct,
            "direction": direction,
            "over_limit": bool(change_pct is not None and abs(change_pct) > 20),
            "effect": effect,
            "review": {
                "status": st,
                "verdict": rv.verdict if rv else None,
                "note": review_note(rv.note)[0] if rv else None,
                "evidence": review_note(rv.note)[1] if rv else None,
                "verified_at": rv.verified_at.isoformat() if rv and rv.verified_at else None,
            },
        })
        cached = _cached_ai(rv, items[-1])
        items[-1]["ai"] = {
            "verdict": cached["verdict"] if cached else None,
            "reason": cached["reason"] if cached else None,
            "generated_at": rv.ai_generated_at.isoformat()
            if cached and rv.ai_generated_at else None,
        }
    return {**page, "items": items} if paged else items


async def build_one(session: AsyncSession, tenant: Tenant, dedup_key: str) -> dict | None:
    """重算单条调价的 item（供 AI 研判端点用，不限 7 天窗口）。"""
    rec = await session.scalar(
        select(OperationRecord).where(
            OperationRecord.tenant_id == tenant.id, OperationRecord.dedup_key == dedup_key
        )
    )
    if rec is None:
        return None
    if rec.opt_level != 5 or rec.opt_content != "bidPriceWord":
        return None
    keywords = await _resolve_keywords(session, tenant.id, [rec])
    keyword = keywords.get(rec.dedup_key)
    kid = keyword.keyword_id if keyword else None
    old_v, new_v = _parse_num(rec.old_value), _parse_num(rec.new_value)
    change_pct = (
        round((new_v - old_v) / old_v * 100, 1) if old_v not in (None, 0) and new_v is not None else None
    )
    direction = "raise" if change_pct and change_pct > 0 else ("lower" if change_pct and change_pct < 0 else "flat")
    effect = await _keyword_effect(session, tenant.id, rec, keyword)
    review = await session.scalar(
        select(AdjustmentReview).where(
            AdjustmentReview.tenant_id == tenant.id,
            AdjustmentReview.dedup_key == dedup_key,
        )
    )
    return {
        "dedup_key": dedup_key,
        "keyword": rec.opt_obj,
        "keyword_id": kid,
        "baidu_account_id": rec.baidu_account_id,
        "old_value": rec.old_value,
        "new_value": rec.new_value,
        "change_pct": change_pct,
        "direction": direction,
        "effect": effect,
        "review": {
            "status": review.status if review else "pending",
            "verdict": review.verdict if review else None,
            "note": review_note(review.note)[0] if review else None,
            "evidence": review_note(review.note)[1] if review else None,
            "verified_at": review.verified_at.isoformat() if review and review.verified_at else None,
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
    if item.get("effect", {}).get("sample", {}).get("state") != "ready":
        return {"verdict": "watch", "reason": "身份未唯一匹配或样本不足，暂不能判断效果"}
    if not is_enabled():
        return None
    rv = await session.scalar(
        select(AdjustmentReview).where(
            AdjustmentReview.tenant_id == tenant.id, AdjustmentReview.dedup_key == item["dedup_key"]
        )
    )
    cached = _cached_ai(rv, item)
    if cached and not force:
        return cached
    try:
        out = await chat_json(SYSTEM_PROMPT, _build_prompt(item))
    except DeepSeekError as e:
        logger.warning("调价 AI 研判失败 dedup=%s：%s", item["dedup_key"], e)
        return None
    verdict = out.get("verdict") if out.get("verdict") in ("achieved", "missed", "watch") else "watch"
    reason = str(out.get("reason") or "")[:200]
    # 模型调用期间人工审核或另一个 AI 请求可能已创建记录。
    # 冲突分支仅更新 AI 列，绝不覆盖人工状态、判定、备注或证据。
    ai_values = {
        "ai_verdict": verdict,
        "ai_reason": AI_CACHE_PREFIX + json.dumps({
            "fingerprint": _effect_fingerprint(item), "reason": reason,
        }, ensure_ascii=False),
        "ai_generated_at": datetime.utcnow(),
    }
    stmt = insert(AdjustmentReview).values(
        tenant_id=tenant.id, dedup_key=item["dedup_key"], **ai_values,
    )
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[AdjustmentReview.tenant_id, AdjustmentReview.dedup_key],
        set_=ai_values,
    ))
    await session.commit()
    return {"verdict": verdict, "reason": reason}
