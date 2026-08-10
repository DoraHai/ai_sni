"""Weekly GEO insights narrative for overview (last 7d vs prior 7d)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.daily_metrics import parse_scope_key
from app.geo.content.topic_heat import build_topic_heat
from app.models import GeoDailyMetric


def _avg_rate(rows: list[GeoDailyMetric], attr: str) -> float | None:
    vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    if not vals:
        return None
    return round(sum(float(v) for v in vals) / len(vals), 4)


def _sum_int(rows: list[GeoDailyMetric], attr: str) -> int:
    return int(sum(int(getattr(r, attr) or 0) for r in rows))


def _delta_pct(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None:
        return None
    if prev == 0:
        return 100.0 if cur > 0 else 0.0
    return round((cur - prev) / abs(prev) * 100.0, 1)


def _bullet_rate(label: str, cur: float | None, prev: float | None) -> str | None:
    if cur is None:
        return None
    d = _delta_pct(cur, prev)
    if d is None:
        return f"{label} {(cur * 100):.1f}%（对比上周无数据）"
    arrow = "↑" if d > 0 else ("↓" if d < 0 else "→")
    return f"{label} {(cur * 100):.1f}%（较上周 {arrow}{abs(d):.0f}%）"


async def build_weekly_insights(
    session: AsyncSession,
    *,
    tenant_id: int,
    scope_key: str = "t",
) -> dict[str, Any]:
    sk = (scope_key or "t").strip() or "t"
    end = date.today()
    cur_from = end - timedelta(days=6)
    prev_to = cur_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=6)

    rows = list(
        await session.scalars(
            select(GeoDailyMetric)
            .where(
                GeoDailyMetric.tenant_id == tenant_id,
                GeoDailyMetric.scope_key == sk,
                GeoDailyMetric.metric_date >= prev_from,
                GeoDailyMetric.metric_date <= end,
            )
            .order_by(GeoDailyMetric.metric_date.asc())
        )
    )
    cur_rows = [r for r in rows if cur_from <= r.metric_date <= end]
    prev_rows = [r for r in rows if prev_from <= r.metric_date <= prev_to]

    cur_mention = _avg_rate(cur_rows, "brand_mention_rate")
    prev_mention = _avg_rate(prev_rows, "brand_mention_rate")
    cur_top1 = _avg_rate(cur_rows, "top1_rate")
    prev_top1 = _avg_rate(prev_rows, "top1_rate")
    cur_cite = _sum_int(cur_rows, "citation_count")
    prev_cite = _sum_int(prev_rows, "citation_count")
    cur_vis = _sum_int(cur_rows, "snapshots_visibility")
    prev_vis = _sum_int(prev_rows, "snapshots_visibility")

    # top competitor from latest day with data
    top_comp = None
    top_comp_rate = None
    for r in reversed(cur_rows):
        if r.top_competitor:
            top_comp = r.top_competitor
            top_comp_rate = r.top_competitor_rate
            break

    heat = await build_topic_heat(session, tenant_id=tenant_id, days=14, group_by="prompt")
    rising = [i for i in (heat.get("items") or []) if i.get("heat") == "rising"][:5]
    falling = [i for i in (heat.get("items") or []) if i.get("heat") == "falling"][:5]

    bullets: list[str] = []
    b = _bullet_rate("品牌提及率", cur_mention, prev_mention)
    if b:
        bullets.append(b)
    b = _bullet_rate("首位推荐率", cur_top1, prev_top1)
    if b:
        bullets.append(b)
    cite_d = _delta_pct(float(cur_cite), float(prev_cite) if prev_rows else None)
    if prev_rows:
        arrow = "↑" if (cite_d or 0) > 0 else ("↓" if (cite_d or 0) < 0 else "→")
        bullets.append(
            f"AI 引用次数 {cur_cite}（较上周 {arrow}{abs(cite_d or 0):.0f}% · 前周 {prev_cite}）"
        )
    else:
        bullets.append(f"AI 引用次数 {cur_cite}（本周可见快照 {cur_vis}）")

    if top_comp:
        rate_txt = f"{(top_comp_rate or 0) * 100:.0f}%" if top_comp_rate is not None else "—"
        bullets.append(f"近端领先竞品「{top_comp}」覆盖率约 {rate_txt}")

    if rising:
        labels = "、".join(i["label"][:24] for i in rising[:3])
        bullets.append(f"覆盖上升话题：{labels}")
    if falling:
        labels = "、".join(i["label"][:24] for i in falling[:3])
        bullets.append(f"覆盖回落话题：{labels}")

    if not cur_rows:
        bullets = ["近 7 天尚无日指标：请先跑巡检或在可见度登记快照，再点「重算今日」。"]

    parsed = parse_scope_key(sk)
    return {
        "scope_key": sk,
        "scope_level": parsed.get("level"),
        "period": {
            "current": {"from": cur_from.isoformat(), "to": end.isoformat()},
            "previous": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        },
        "metrics": {
            "brand_mention_rate": cur_mention,
            "brand_mention_rate_prev": prev_mention,
            "brand_mention_delta_pct": _delta_pct(cur_mention, prev_mention),
            "top1_rate": cur_top1,
            "top1_rate_prev": prev_top1,
            "citation_count": cur_cite,
            "citation_count_prev": prev_cite,
            "snapshots_visibility": cur_vis,
            "snapshots_visibility_prev": prev_vis,
            "top_competitor": top_comp,
            "top_competitor_rate": top_comp_rate,
        },
        "rising_topics": [
            {"label": i["label"], "delta_pct": i["delta_pct"], "prompt_id": i.get("prompt_id")}
            for i in rising
        ],
        "falling_topics": [
            {"label": i["label"], "delta_pct": i["delta_pct"], "prompt_id": i.get("prompt_id")}
            for i in falling
        ],
        "bullets": bullets,
        "headline": bullets[0] if bullets else "本周暂无洞察",
    }
