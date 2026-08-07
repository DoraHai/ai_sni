"""GEO 按天汇总：租户 / 业务 / 单元切片。

scope_key 约定：
  t           租户级（全量快照）
  b{id}       优化业务切片（意图词 unit 属于该业务）
  u{id}       优化单元切片（意图词挂在该 unit）

AI 引用口径：
  citation_count          快照 cited_urls 出现总次数
  distinct_cited_domains  独立被引域名数
  仅统计系统内回答快照，非全网抓取。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.snapshots import extract_cited_domain, normalize_cited_urls
from app.models import (
    GeoAnswerSnapshot,
    GeoDailyMetric,
    GeoOptimizationUnit,
    GeoPrompt,
)


def scope_tenant() -> str:
    return "t"


def scope_business(business_id: int) -> str:
    return f"b{int(business_id)}"


def scope_unit(unit_id: int) -> str:
    return f"u{int(unit_id)}"


def parse_scope_key(scope_key: str) -> dict[str, Any]:
    sk = (scope_key or "t").strip()
    if sk == "t":
        return {"level": "tenant", "business_id": None, "unit_id": None}
    if sk.startswith("b") and sk[1:].isdigit():
        return {"level": "business", "business_id": int(sk[1:]), "unit_id": None}
    if sk.startswith("u") and sk[1:].isdigit():
        return {"level": "unit", "business_id": None, "unit_id": int(sk[1:])}
    return {"level": "unknown", "business_id": None, "unit_id": None}


@dataclass
class MetricBucket:
    business_id: int | None = None
    unit_id: int | None = None
    snapshots_visibility: int = 0
    snapshots_probe: int = 0
    brand_mentions: int = 0
    brand_probe_hits: int = 0
    top1_count: int = 0
    citation_count: int = 0
    domains: set[str] | None = None

    def __post_init__(self) -> None:
        if self.domains is None:
            self.domains = set()

    def add_snapshot(self, snap: GeoAnswerSnapshot, *, is_probe: bool) -> None:
        if is_probe:
            self.snapshots_probe += 1
            if snap.mentions_brand:
                self.brand_probe_hits += 1
        else:
            self.snapshots_visibility += 1
            if snap.mentions_brand:
                self.brand_mentions += 1
            if (snap.brand_position or "") == "first":
                self.top1_count += 1
        urls = normalize_cited_urls(getattr(snap, "cited_urls", None) or [])
        self.citation_count += len(urls)
        for u in urls:
            d = extract_cited_domain(u)
            if d:
                self.domains.add(d)

    def to_metrics_dict(self) -> dict[str, Any]:
        vis_n = self.snapshots_visibility
        probe_n = self.snapshots_probe
        return {
            "snapshots_visibility": vis_n,
            "snapshots_probe": probe_n,
            "brand_mentions": self.brand_mentions,
            "brand_probe_hits": self.brand_probe_hits,
            "top1_count": self.top1_count,
            "distinct_cited_domains": len(self.domains or set()),
            "citation_count": self.citation_count,
            "brand_mention_rate": (self.brand_mentions / vis_n) if vis_n else None,
            "brand_probe_recognition_rate": (
                (self.brand_probe_hits / probe_n) if probe_n else None
            ),
            "top1_rate": (self.top1_count / vis_n) if vis_n else None,
        }


def aggregate_buckets(
    snaps: Iterable[GeoAnswerSnapshot],
    *,
    probe_map: dict[int, bool],
    unit_of_prompt: dict[int, int | None],
    business_of_unit: dict[int, int],
) -> dict[str, MetricBucket]:
    """按 scope_key 聚合。仅创建有快照落入的切片（+ 始终有租户 t）。"""
    buckets: dict[str, MetricBucket] = {
        scope_tenant(): MetricBucket(),
    }
    for snap in snaps:
        pid = snap.prompt_id
        is_probe = bool(probe_map.get(pid, False))
        unit_id = unit_of_prompt.get(pid)
        biz_id = business_of_unit.get(unit_id) if unit_id else None

        buckets[scope_tenant()].add_snapshot(snap, is_probe=is_probe)

        if unit_id:
            uk = scope_unit(unit_id)
            if uk not in buckets:
                buckets[uk] = MetricBucket(business_id=biz_id, unit_id=unit_id)
            buckets[uk].add_snapshot(snap, is_probe=is_probe)

        if biz_id:
            bk = scope_business(biz_id)
            if bk not in buckets:
                buckets[bk] = MetricBucket(business_id=biz_id, unit_id=None)
            buckets[bk].add_snapshot(snap, is_probe=is_probe)

    return buckets


async def load_day_snapshots(
    session: AsyncSession, tenant_id: int, day: date
) -> list[GeoAnswerSnapshot]:
    start_dt = datetime.combine(day, time.min)
    end_dt = datetime.combine(day, time.max)
    rows = await session.scalars(
        select(GeoAnswerSnapshot).where(
            GeoAnswerSnapshot.tenant_id == tenant_id,
            GeoAnswerSnapshot.captured_at >= start_dt,
            GeoAnswerSnapshot.captured_at <= end_dt,
        )
    )
    return list(rows)


async def load_prompt_unit_maps(
    session: AsyncSession, tenant_id: int, prompt_ids: set[int]
) -> tuple[dict[int, bool], dict[int, int | None], dict[int, int]]:
    """probe_map, unit_of_prompt, business_of_unit."""
    probe_map: dict[int, bool] = {}
    unit_of_prompt: dict[int, int | None] = {}
    if not prompt_ids:
        return probe_map, unit_of_prompt, {}

    prompts = list(
        await session.scalars(
            select(GeoPrompt).where(
                GeoPrompt.tenant_id == tenant_id,
                GeoPrompt.id.in_(list(prompt_ids)),
            )
        )
    )
    unit_ids: set[int] = set()
    for p in prompts:
        probe_map[p.id] = bool(p.is_brand_probe)
        uid = getattr(p, "unit_id", None)
        unit_of_prompt[p.id] = uid
        if uid:
            unit_ids.add(uid)

    business_of_unit: dict[int, int] = {}
    if unit_ids:
        for u in await session.scalars(
            select(GeoOptimizationUnit).where(
                GeoOptimizationUnit.tenant_id == tenant_id,
                GeoOptimizationUnit.id.in_(list(unit_ids)),
            )
        ):
            business_of_unit[u.id] = u.business_id
    return probe_map, unit_of_prompt, business_of_unit


async def upsert_metric_row(
    session: AsyncSession,
    *,
    tenant_id: int,
    day: date,
    scope_key: str,
    bucket: MetricBucket,
) -> GeoDailyMetric:
    row = await session.scalar(
        select(GeoDailyMetric).where(
            GeoDailyMetric.tenant_id == tenant_id,
            GeoDailyMetric.metric_date == day,
            GeoDailyMetric.scope_key == scope_key,
        )
    )
    if not row:
        row = GeoDailyMetric(
            tenant_id=tenant_id,
            metric_date=day,
            scope_key=scope_key,
        )
        session.add(row)
    row.business_id = bucket.business_id
    row.unit_id = bucket.unit_id
    row.engine = None
    for k, v in bucket.to_metrics_dict().items():
        setattr(row, k, v)
    return row


async def rebuild_day(
    session: AsyncSession,
    tenant_id: int,
    day: date,
    *,
    include_empty_slices: bool = False,
) -> dict[str, Any]:
    """重算单日：租户 + 有快照的业务/单元切片。

    include_empty_slices=True 时，还会为零快照的活跃业务/单元写入 0 行。
    """
    snaps = await load_day_snapshots(session, tenant_id, day)
    prompt_ids = {s.prompt_id for s in snaps if s.prompt_id}
    probe_map, unit_of_prompt, business_of_unit = await load_prompt_unit_maps(
        session, tenant_id, prompt_ids
    )
    buckets = aggregate_buckets(
        snaps,
        probe_map=probe_map,
        unit_of_prompt=unit_of_prompt,
        business_of_unit=business_of_unit,
    )

    if include_empty_slices:
        units = list(
            await session.scalars(
                select(GeoOptimizationUnit).where(
                    GeoOptimizationUnit.tenant_id == tenant_id,
                    GeoOptimizationUnit.status == "active",
                )
            )
        )
        for u in units:
            uk = scope_unit(u.id)
            if uk not in buckets:
                buckets[uk] = MetricBucket(business_id=u.business_id, unit_id=u.id)
            bk = scope_business(u.business_id)
            if bk not in buckets:
                buckets[bk] = MetricBucket(business_id=u.business_id, unit_id=None)

    scopes_written: list[str] = []
    for sk, bucket in buckets.items():
        await upsert_metric_row(
            session, tenant_id=tenant_id, day=day, scope_key=sk, bucket=bucket
        )
        scopes_written.append(sk)

    await session.commit()

    by_level = defaultdict(int)
    for sk in scopes_written:
        by_level[parse_scope_key(sk)["level"]] += 1

    tenant_metrics = buckets[scope_tenant()].to_metrics_dict()
    return {
        "metric_date": day.isoformat(),
        "snapshot_total": len(snaps),
        "scopes_written": sorted(scopes_written),
        "scope_counts": dict(by_level),
        "tenant": {"scope_key": scope_tenant(), **tenant_metrics},
        "business_scopes": [
            {
                "scope_key": sk,
                "business_id": buckets[sk].business_id,
                **buckets[sk].to_metrics_dict(),
            }
            for sk in sorted(scopes_written)
            if parse_scope_key(sk)["level"] == "business"
        ],
        "unit_scopes": [
            {
                "scope_key": sk,
                "business_id": buckets[sk].business_id,
                "unit_id": buckets[sk].unit_id,
                **buckets[sk].to_metrics_dict(),
            }
            for sk in sorted(scopes_written)
            if parse_scope_key(sk)["level"] == "unit"
        ],
    }


async def rebuild_range(
    session: AsyncSession,
    tenant_id: int,
    date_from: date,
    date_to: date,
    *,
    include_empty_slices: bool = False,
) -> dict[str, Any]:
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    # 防护：最多 62 天
    if (date_to - date_from).days > 61:
        date_from = date_to - timedelta(days=61)

    days: list[dict[str, Any]] = []
    cur = date_from
    while cur <= date_to:
        # rebuild_day 内部 commit；逐日提交便于长区间
        day_result = await rebuild_day(
            session, tenant_id, cur, include_empty_slices=include_empty_slices
        )
        days.append(
            {
                "metric_date": day_result["metric_date"],
                "snapshot_total": day_result["snapshot_total"],
                "scopes": len(day_result["scopes_written"]),
                "scope_counts": day_result["scope_counts"],
            }
        )
        cur += timedelta(days=1)

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "days": days,
        "day_count": len(days),
    }


def metric_row_payload(row: GeoDailyMetric) -> dict[str, Any]:
    sk = row.scope_key or "t"
    parsed = parse_scope_key(sk)
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "metric_date": row.metric_date.isoformat() if row.metric_date else None,
        "scope_key": sk,
        "scope_level": parsed["level"],
        "business_id": row.business_id if row.business_id is not None else parsed["business_id"],
        "unit_id": row.unit_id if row.unit_id is not None else parsed["unit_id"],
        "engine": row.engine,
        "snapshots_visibility": row.snapshots_visibility,
        "snapshots_probe": row.snapshots_probe,
        "brand_mentions": row.brand_mentions,
        "brand_probe_hits": row.brand_probe_hits,
        "top1_count": row.top1_count,
        "distinct_cited_domains": row.distinct_cited_domains,
        "citation_count": row.citation_count,
        "brand_mention_rate": row.brand_mention_rate,
        "brand_probe_recognition_rate": row.brand_probe_recognition_rate,
        "top1_rate": row.top1_rate,
    }


CITATION_STAT_NOTE = (
    "AI 引用次数来自回答快照 cited_urls 聚合："
    "citation_count 为 URL 出现总次数，distinct_cited_domains 为独立域名数；非全网抓取。"
    "业务/单元切片仅统计挂在该业务/单元下意图词的快照。"
)

METRIC_LABELS = {
    "brand_mention_rate": "品牌提及率",
    "brand_probe_recognition_rate": "品牌点名认知率",
    "citation_count": "AI 引用次数",
    "distinct_cited_domains": "AI 引用·独立域名数",
}
