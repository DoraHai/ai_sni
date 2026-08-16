"""Topic heat: coverage of intent prompts in snapshots (not market search volume).

Heat = unique (topic × engine × day) coverage cells.
Monitoring activity = raw snapshot volume, split patrol vs manual.
External market trends stay on /ai-trends — not mixed here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GeoAnswerSnapshot, GeoPrompt


def _day_key(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.replace(tzinfo=None)
    return dt.date().isoformat()


def is_patrol_snapshot(note: str | None) -> bool:
    """True when snapshot was auto-persisted by visibility patrol."""
    text = str(note or "").strip().lower()
    return text.startswith("auto-patrol") or "auto-patrol #" in text


def coverage_cell_key(
    *,
    topic_key: str,
    engine: str | None,
    day: str,
) -> tuple[str, str, str]:
    eng = (engine or "other").strip().lower() or "other"
    return (str(topic_key), eng, day)


def classify_heat(*, recent: int, earlier: int, delta_pct: float) -> str:
    """Label coverage trend; needs enough cells to avoid noise."""
    if delta_pct >= 30 and recent >= 2:
        return "rising"
    if delta_pct <= -30 and earlier >= 2:
        return "falling"
    return "stable"


def delta_pct_for_halves(recent: int, earlier: int) -> float:
    if earlier == 0:
        return 100.0 if recent > 0 else 0.0
    return round((recent - earlier) / earlier * 100.0, 1)


def topic_bucket_key(
    *,
    group_by: str,
    prompt_id: int | None,
    prompt: Any | None,
) -> tuple[str, str]:
    """Return (key, label) for aggregation."""
    if group_by == "group":
        qg = getattr(prompt, "question_group", None) if prompt is not None else None
        key = qg if qg else "未分组"
        return str(key), str(key)
    key = f"p{prompt_id}" if prompt_id else "unknown"
    question = getattr(prompt, "question", None) if prompt is not None else None
    label = question or f"意图词 #{prompt_id or '?'}"
    return key, label


def compute_topic_heat_rows(
    snaps: list[Any],
    prompts: dict[int, Any],
    *,
    days: int,
    group_by: str,
    start: date,
) -> dict[str, Any]:
    """Pure aggregation used by API + tests (no DB)."""
    days = max(3, min(int(days or 14), 90))
    gb = group_by if group_by in ("prompt", "group") else "prompt"
    timeline = [(start + timedelta(days=i)).isoformat() for i in range(days)]

    buckets: dict[str, dict[str, Any]] = {}
    global_cells: set[tuple[str, str, str]] = set()
    day_raw: dict[str, int] = defaultdict(int)
    patrol_total = 0
    manual_total = 0

    for snap in snaps:
        day = _day_key(getattr(snap, "captured_at", None))
        if not day:
            continue
        day_raw[day] += 1
        patrol = is_patrol_snapshot(getattr(snap, "note", None))
        if patrol:
            patrol_total += 1
        else:
            manual_total += 1

        pid = getattr(snap, "prompt_id", None)
        p = prompts.get(pid) if pid else None
        topic_key, label = topic_bucket_key(group_by=gb, prompt_id=pid, prompt=p)
        cell = coverage_cell_key(
            topic_key=topic_key,
            engine=getattr(snap, "engine", None),
            day=day,
        )
        global_cells.add(cell)

        b = buckets.setdefault(
            topic_key,
            {
                "key": topic_key,
                "label": label,
                "prompt_id": pid if gb != "group" else None,
                "question_group": getattr(p, "question_group", None) if p else None,
                "cells": set(),
                "cell_brand": set(),
                "series_cells": defaultdict(set),
                "engines": set(),
                "snapshot_count": 0,
                "patrol_snapshot_count": 0,
                "manual_snapshot_count": 0,
                "brand_mention_snapshots": 0,
            },
        )
        b["snapshot_count"] += 1
        if patrol:
            b["patrol_snapshot_count"] += 1
        else:
            b["manual_snapshot_count"] += 1
        if getattr(snap, "mentions_brand", False):
            b["brand_mention_snapshots"] += 1

        eng = cell[1]
        b["engines"].add(eng)
        b["cells"].add(cell)
        b["series_cells"][day].add(eng)
        if getattr(snap, "mentions_brand", False):
            b["cell_brand"].add(cell)

    day_totals = [sum(1 for c in global_cells if c[2] == d) for d in timeline]
    day_totals_raw = [int(day_raw.get(d, 0)) for d in timeline]

    items: list[dict[str, Any]] = []
    half = max(1, days // 2)
    for b in buckets.values():
        series = [len(b["series_cells"].get(d, ())) for d in timeline]
        recent = sum(series[-half:])
        earlier = sum(series[:half])
        delta_pct = delta_pct_for_halves(recent, earlier)
        heat = classify_heat(recent=recent, earlier=earlier, delta_pct=delta_pct)
        items.append(
            {
                "key": b["key"],
                "label": b["label"],
                "prompt_id": b["prompt_id"],
                "question_group": b["question_group"],
                "coverage_count": len(b["cells"]),
                "series": series,
                "recent_count": recent,
                "earlier_count": earlier,
                "delta_pct": delta_pct,
                "heat": heat,
                "brand_mentions": len(b["cell_brand"]),
                "engines": sorted(b["engines"]),
                "snapshot_count": b["snapshot_count"],
                "patrol_snapshot_count": b["patrol_snapshot_count"],
                "manual_snapshot_count": b["manual_snapshot_count"],
                "brand_mention_snapshots": b["brand_mention_snapshots"],
            }
        )

    items.sort(
        key=lambda x: (-x["recent_count"], -x["coverage_count"], -x["snapshot_count"], x["label"])
    )
    return {
        "timeline": timeline,
        "day_totals": day_totals,
        "day_totals_raw": day_totals_raw,
        "items": items,
        "summary": {
            "topic_count": len(items),
            "rising": sum(1 for i in items if i["heat"] == "rising"),
            "falling": sum(1 for i in items if i["heat"] == "falling"),
            "coverage_total": len(global_cells),
            "snapshot_total": len(snaps),
            "patrol_snapshot_total": patrol_total,
            "manual_snapshot_total": manual_total,
        },
    }


async def build_topic_heat(
    session: AsyncSession,
    *,
    tenant_id: int,
    days: int = 14,
    group_by: str = "prompt",
) -> dict[str, Any]:
    """Build topic coverage heat + separate monitoring activity.

    Heat series counts unique (topic × engine × day) cells.
    Monitoring counters use raw snapshots (patrol vs manual).
    """
    days = max(3, min(int(days or 14), 90))
    gb = group_by if group_by in ("prompt", "group") else "prompt"
    end = date.today()
    start = end - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time())

    snaps = list(
        await session.scalars(
            select(GeoAnswerSnapshot).where(
                GeoAnswerSnapshot.tenant_id == tenant_id,
                GeoAnswerSnapshot.captured_at >= start_dt,
            )
        )
    )
    prompt_ids = {s.prompt_id for s in snaps if s.prompt_id}
    prompts: dict[int, GeoPrompt] = {}
    if prompt_ids:
        for p in await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id,
                GeoPrompt.id.in_(list(prompt_ids)),
            )
        ):
            prompts[p.id] = p

    agg = compute_topic_heat_rows(
        snaps, prompts, days=days, group_by=gb, start=start
    )
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "group_by": gb,
        "timeline": agg["timeline"],
        "day_totals": agg["day_totals"],
        "day_totals_raw": agg["day_totals_raw"],
        "items": agg["items"],
        "summary": agg["summary"],
        "metric": {
            "heat": "unique_topic_engine_day",
            "heat_label": "覆盖热度：意图词×引擎×日 去重后的覆盖格数",
            "activity_label": "监测活跃度：原始快照条数（巡检 / 人工分开）",
            "external": "市场/引擎外部动态请看「AI 动态」，不计入本页热度",
        },
    }
