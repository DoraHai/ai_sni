"""GEO 按天汇总：租户 / 业务 / 单元 / 意图词切片，并支持按引擎二次切片。

scope_key 约定：
  t           租户级（全量快照）
  b{id}       优化业务切片（意图词 unit 属于该业务）
  u{id}       优化单元切片（意图词挂在该 unit）
  p{id}       优化意图词切片
  unc         未分类（意图词未挂 unit，显式桶，避免业务切片静默丢数）
  {base}@{engine}  上述任一维度 × 引擎（如 t@deepseek、u3@doubao、unc@deepseek）

AI 引用口径：
  citation_count          快照 cited_urls 出现总次数
  distinct_cited_domains  独立被引域名数
  仅统计系统内回答快照，非全网抓取。
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.snapshots import (
    extract_cited_domain,
    normalize_cited_urls,
    normalize_competitors,
)
from app.models import (
    GeoAnswerSnapshot,
    GeoDailyMetric,
    GeoOptimizationUnit,
    GeoPrompt,
)

logger = logging.getLogger(__name__)

_ENGINE_SAFE = re.compile(r"[^a-z0-9_\-]+")


def scope_tenant() -> str:
    return "t"


def scope_business(business_id: int) -> str:
    return f"b{int(business_id)}"


def scope_unit(unit_id: int) -> str:
    return f"u{int(unit_id)}"


def scope_prompt(prompt_id: int) -> str:
    return f"p{int(prompt_id)}"


def scope_unclassified() -> str:
    """未挂优化单元的意图词显式归入此桶（业务汇报可见）。"""
    return "unc"


def normalize_engine_key(engine: str | None) -> str:
    raw = (engine or "other").strip().lower() or "other"
    cleaned = _ENGINE_SAFE.sub("", raw)[:32]
    return cleaned or "other"


def scope_with_engine(base: str, engine: str | None) -> str:
    return f"{base}@{normalize_engine_key(engine)}"


def parse_scope_key(scope_key: str) -> dict[str, Any]:
    sk = (scope_key or "t").strip()
    engine: str | None = None
    if "@" in sk:
        base, eng = sk.rsplit("@", 1)
        sk = base.strip() or "t"
        engine = eng.strip() or None
    if sk == "t":
        return {
            "level": "tenant",
            "business_id": None,
            "unit_id": None,
            "prompt_id": None,
            "engine": engine,
        }
    if sk.startswith("b") and sk[1:].isdigit():
        return {
            "level": "business",
            "business_id": int(sk[1:]),
            "unit_id": None,
            "prompt_id": None,
            "engine": engine,
        }
    if sk.startswith("u") and sk[1:].isdigit():
        return {
            "level": "unit",
            "business_id": None,
            "unit_id": int(sk[1:]),
            "prompt_id": None,
            "engine": engine,
        }
    if sk.startswith("p") and sk[1:].isdigit():
        return {
            "level": "prompt",
            "business_id": None,
            "unit_id": None,
            "prompt_id": int(sk[1:]),
            "engine": engine,
        }
    if sk == "unc":
        return {
            "level": "unclassified",
            "business_id": None,
            "unit_id": None,
            "prompt_id": None,
            "engine": engine,
        }
    return {
        "level": "unknown",
        "business_id": None,
        "unit_id": None,
        "prompt_id": None,
        "engine": engine,
    }


@dataclass
class MetricBucket:
    samples: list = field(default_factory=list, repr=False)
    business_id: int | None = None
    unit_id: int | None = None
    snapshots_visibility: int = 0
    snapshots_probe: int = 0
    brand_mentions: int = 0
    brand_probe_hits: int = 0
    top1_count: int = 0
    citation_count: int = 0
    domains: set[str] | None = None
    competitor_counts: dict[str, int] | None = None
    any_competitor_mentions: int = 0

    def __post_init__(self) -> None:
        if self.domains is None:
            self.domains = set()
        if self.competitor_counts is None:
            self.competitor_counts = {}

    def add_snapshot(self, snap: GeoAnswerSnapshot, *, is_probe: bool) -> None:
        from app.geo.content.sample_provenance import sample_provenance

        if sample_provenance(snap)["sample_kind"] == "simulated":
            return
        self.samples.append(snap)
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
            from app.geo.content.competitor_scope import competitor_names
            comps = competitor_names(getattr(snap, "competitors", None))
            if comps:
                self.any_competitor_mentions += 1
                for name in comps:
                    self.competitor_counts[name] = self.competitor_counts.get(name, 0) + 1
        urls = normalize_cited_urls(getattr(snap, "cited_urls", None) or [])
        self.citation_count += len(urls)
        for u in urls:
            d = extract_cited_domain(u)
            if d:
                self.domains.add(d)

    def to_metrics_dict(self) -> dict[str, Any]:
        from app.geo.content.metric_service import composition_of

        composition = composition_of(self.samples)
        comparable = len(composition.sampling_methods) <= 1 and not composition.needs_review
        vis_n = self.snapshots_visibility
        probe_n = self.snapshots_probe
        # Persist all competitors; ranking limits belong only in presentation.
        ranked = sorted(
            (self.competitor_counts or {}).items(),
            key=lambda x: (-x[1], x[0]),
        )
        competitor_mentions: dict[str, Any] = {}
        for name, n in ranked:
            competitor_mentions[name] = {
                "mentions": int(n),
                "rate": round(n / vis_n, 4) if vis_n and comparable else None,
            }
        top_name = ranked[0][0] if ranked else None
        top_n = ranked[0][1] if ranked else 0
        return {
            "snapshots_visibility": vis_n,
            "snapshots_probe": probe_n,
            "brand_mentions": self.brand_mentions,
            "brand_probe_hits": self.brand_probe_hits,
            "top1_count": self.top1_count,
            "distinct_cited_domains": len(self.domains or set()),
            "citation_count": self.citation_count,
            "brand_mention_rate": (self.brand_mentions / vis_n) if vis_n and comparable else None,
            "brand_probe_recognition_rate": (
                (self.brand_probe_hits / probe_n) if probe_n and comparable else None
            ),
            "top1_rate": (self.top1_count / vis_n) if vis_n and comparable else None,
            "competitor_mentions": competitor_mentions or None,
            "top_competitor": top_name,
            "top_competitor_rate": (top_n / vis_n) if vis_n and top_name and comparable else None,
            "any_competitor_mentions": self.any_competitor_mentions,
        }


def aggregate_buckets(
    snaps: Iterable[GeoAnswerSnapshot],
    *,
    probe_map: dict[int, bool],
    unit_of_prompt: dict[int, int | None],
    business_of_unit: dict[int, int],
) -> dict[str, MetricBucket]:
    """按 scope_key 聚合。仅创建有快照落入的切片（+ 始终有租户 t）。

    同时写入全引擎汇总键，以及 `{base}@{engine}` 引擎切片。
    """
    buckets: dict[str, MetricBucket] = {
        scope_tenant(): MetricBucket(),
    }

    def _ensure(sk: str, *, business_id=None, unit_id=None) -> MetricBucket:
        if sk not in buckets:
            buckets[sk] = MetricBucket(business_id=business_id, unit_id=unit_id)
        return buckets[sk]

    for snap in snaps:
        from app.geo.content.sample_provenance import sample_provenance
        if sample_provenance(snap)["sample_kind"] == "simulated":
            continue
        pid = snap.prompt_id
        is_probe = bool(probe_map.get(pid, False))
        unit_id = unit_of_prompt.get(pid)
        biz_id = business_of_unit.get(unit_id) if unit_id else None
        engine = normalize_engine_key(getattr(snap, "engine", None))

        bases: list[tuple[str, int | None, int | None]] = [
            (scope_tenant(), None, None),
        ]
        if pid:
            bases.append((scope_prompt(int(pid)), biz_id, unit_id))
        if unit_id:
            bases.append((scope_unit(unit_id), biz_id, unit_id))
        if biz_id:
            bases.append((scope_business(biz_id), biz_id, None))
        elif pid and not unit_id:
            # 未归属业务/单元：显式「未分类」桶，避免只进 t/p 导致业务维度静默丢数
            bases.append((scope_unclassified(), None, None))

        for base, b_id, u_id in bases:
            _ensure(base, business_id=b_id, unit_id=u_id).add_snapshot(
                snap, is_probe=is_probe
            )
            ek = scope_with_engine(base, engine)
            _ensure(ek, business_id=b_id, unit_id=u_id).add_snapshot(
                snap, is_probe=is_probe
            )

    return buckets


def snapshot_daily_rows(snaps, *, tenant_id, start, end, probe_map, unit_of_prompt, business_of_unit, include_engines=False):
    """Read-only daily rows for a report, built from its exact snapshot population."""
    from types import SimpleNamespace
    from app.geo.content.metric_service import composition_of
    from app.geo.content.time_windows import shanghai_day_of_utc_naive

    by_day = defaultdict(list)
    for snap in snaps:
        day = shanghai_day_of_utc_naive(snap.captured_at)
        if day is not None and start <= day <= end:
            by_day[day].append(snap)
    templates = aggregate_buckets([row for rows in by_day.values() for row in rows],
        probe_map=probe_map, unit_of_prompt=unit_of_prompt, business_of_unit=business_of_unit)
    output = []
    day = start
    while day <= end:
        buckets = aggregate_buckets(by_day.get(day, []), probe_map=probe_map,
            unit_of_prompt=unit_of_prompt, business_of_unit=business_of_unit)
        for key, template in templates.items():
            buckets.setdefault(key, MetricBucket(business_id=template.business_id, unit_id=template.unit_id))
        for key, bucket in buckets.items():
            if "@" in key and not include_engines:
                continue  # Report slices are across all engines.
            output.append(SimpleNamespace(id=None, tenant_id=tenant_id, metric_date=day,
                scope_key=key, business_id=bucket.business_id, unit_id=bucket.unit_id,
                engine=None, sample_composition=composition_of(bucket.samples).to_dict(),
                **bucket.to_metrics_dict()))
        day += timedelta(days=1)
    return output


async def load_day_snapshots(
    session: AsyncSession, tenant_id: int, day: date
) -> list[GeoAnswerSnapshot]:
    """按租户时区 Asia/Shanghai 的日历日加载快照（captured_at 存 naive UTC）。"""
    from app.geo.content.time_windows import shanghai_day_bounds_utc_naive

    start_dt, end_dt = shanghai_day_bounds_utc_naive(day)
    rows = await session.scalars(
        select(GeoAnswerSnapshot).where(
            GeoAnswerSnapshot.tenant_id == tenant_id,
            GeoAnswerSnapshot.captured_at >= start_dt,
            GeoAnswerSnapshot.captured_at < end_dt,
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
    parsed = parse_scope_key(scope_key)
    row.business_id = bucket.business_id
    row.unit_id = bucket.unit_id
    row.engine = parsed.get("engine")
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

    # A removed/reclassified/simulated-only slice must not retain yesterday's cached counts.
    existing_rows = list(await session.scalars(select(GeoDailyMetric).where(
        GeoDailyMetric.tenant_id == tenant_id, GeoDailyMetric.metric_date == day,
    )))
    for row in existing_rows:
        if row.scope_key not in buckets:
            buckets[row.scope_key] = MetricBucket(business_id=row.business_id, unit_id=row.unit_id)

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
        "unclassified_scopes": [
            {
                "scope_key": sk,
                "label": "未分类",
                **buckets[sk].to_metrics_dict(),
            }
            for sk in sorted(scopes_written)
            if parse_scope_key(sk)["level"] == "unclassified"
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


def _metric_day_from_captured(captured_at: datetime | date | None) -> date:
    """Map snapshot captured_at (naive UTC) to Asia/Shanghai calendar day."""
    from app.geo.content.time_windows import shanghai_day_of_utc_naive, shanghai_today

    if captured_at is None:
        return shanghai_today()
    if isinstance(captured_at, datetime):
        return shanghai_day_of_utc_naive(captured_at) or shanghai_today()
    return captured_at


async def safe_rebuild_day(
    tenant_id: int,
    day: date | None = None,
    *,
    include_empty_slices: bool = False,
) -> dict[str, Any] | None:
    """独立 session 重算，失败只记日志（供巡检/落库后钩子）。"""
    from app.database import async_session_factory
    from app.geo.content.time_windows import shanghai_today

    target = day or shanghai_today()
    try:
        async with async_session_factory() as session:
            result = await rebuild_day(
                session,
                tenant_id,
                target,
                include_empty_slices=include_empty_slices,
            )
            logger.info(
                "daily metrics rebuilt tenant=%s day=%s snaps=%s scopes=%s",
                tenant_id,
                target.isoformat(),
                result.get("snapshot_total"),
                len(result.get("scopes_written") or []),
            )
            return result
    except Exception:  # noqa: BLE001
        logger.exception(
            "daily metrics rebuild failed tenant=%s day=%s", tenant_id, target
        )
        return None


async def safe_rebuild_for_captured_at(
    tenant_id: int, captured_at: datetime | date | None
) -> dict[str, Any] | None:
    return await safe_rebuild_day(tenant_id, _metric_day_from_captured(captured_at))


async def list_tenant_ids_with_recent_snapshots(
    session: AsyncSession, *, days: int = 2
) -> list[int]:
    """Tenants that had any answer snapshot in the last N calendar days."""
    from sqlalchemy import distinct

    start = datetime.combine(date.today() - timedelta(days=max(0, days - 1)), time.min)
    rows = await session.scalars(
        select(distinct(GeoAnswerSnapshot.tenant_id)).where(
            GeoAnswerSnapshot.captured_at >= start
        )
    )
    return [int(x) for x in rows if x is not None]


async def nightly_rebuild_recent_tenants(*, lookback_days: int = 2) -> dict[str, Any]:
    """Rebuild today + yesterday for tenants with recent snapshots (scheduler)."""
    from app.database import async_session_factory

    today = date.today()
    days = [today - timedelta(days=i) for i in range(lookback_days)]
    summary: dict[str, Any] = {"tenants": 0, "rebuilt": 0, "errors": 0, "days": [d.isoformat() for d in days]}
    async with async_session_factory() as session:
        tenant_ids = await list_tenant_ids_with_recent_snapshots(
            session, days=max(lookback_days, 2)
        )
    summary["tenants"] = len(tenant_ids)
    for tid in tenant_ids:
        for d in days:
            r = await safe_rebuild_day(tid, d)
            if r is None:
                summary["errors"] += 1
            else:
                summary["rebuilt"] += 1
    logger.info("nightly daily-metrics rebuild done %s", summary)
    return summary


def metric_row_payload(row: GeoDailyMetric) -> dict[str, Any]:
    sk = row.scope_key or "t"
    parsed = parse_scope_key(sk)
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "metric_date": row.metric_date.isoformat() if row.metric_date else None,
        "scope_key": sk,
        "sample_composition": getattr(row, "sample_composition", None),
        "scope_level": parsed["level"],
        "business_id": row.business_id if row.business_id is not None else parsed["business_id"],
        "unit_id": row.unit_id if row.unit_id is not None else parsed["unit_id"],
        "prompt_id": parsed.get("prompt_id"),
        "engine": row.engine if row.engine is not None else parsed.get("engine"),
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
        "competitor_mentions": getattr(row, "competitor_mentions", None),
        "top_competitor": getattr(row, "top_competitor", None),
        "top_competitor_rate": getattr(row, "top_competitor_rate", None),
        "any_competitor_mentions": int(getattr(row, "any_competitor_mentions", 0) or 0),
    }


CITATION_STAT_NOTE = (
    "AI 引用次数来自回答快照 cited_urls 聚合："
    "citation_count 为 URL 出现总次数，distinct_cited_domains 为独立域名数；非全网抓取。"
    "业务/单元/意图词切片仅统计对应意图词的快照；带 @引擎 的 scope_key 为按模型切片。"
)

METRIC_LABELS = {
    "brand_mention_rate": "品牌提及率",
    "brand_probe_recognition_rate": "品牌点名认知率",
    "citation_count": "AI 引用次数",
    "distinct_cited_domains": "AI 引用·独立域名数",
}
