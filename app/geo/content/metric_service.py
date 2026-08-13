"""GEO 统一指标服务：单一口径，页面只调这里。

指标字典见 docs/GEO_METRIC_DICTIONARY.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.time_windows import (
    default_observation_window,
    shanghai_day_bounds_utc_naive,
    shanghai_today,
)
from app.models import GeoAnswerSnapshot, GeoPrompt

# ---- 指标字典（运行时机器可读）----

METRIC_DICTIONARY: dict[str, dict[str, Any]] = {
    "brand_mention_rate": {
        "label": "品牌提及率",
        "id": "brand_mention_rate",
        "numerator": "可见性样本中 mentions_brand=true 的条数",
        "denominator": "可见性样本条数（默认排除品牌探测题 is_brand_probe）",
        "exclude_brand_probes": True,
        "timezone": "Asia/Shanghai（按 captured_at 转上海日历日筛选）",
        "time_basis": "shanghai_calendar_day",
        "data_source": "geo_answer_snapshots 原始快照",
        "sample_modes_default": "全部（报表须另展示真采样/模拟构成）",
        "null_when_empty": True,
        "note": "无可见性样本时为 null（未测），不得展示为 0%",
    },
    "brand_probe_recognition_rate": {
        "label": "品牌点名认知率",
        "id": "brand_probe_recognition_rate",
        "numerator": "探测题样本中 mentions_brand=true",
        "denominator": "探测题样本条数",
        "exclude_brand_probes": False,
        "only_brand_probes": True,
        "timezone": "Asia/Shanghai",
        "time_basis": "shanghai_calendar_day",
        "data_source": "geo_answer_snapshots 原始快照",
        "null_when_empty": True,
    },
    "top1_rate": {
        "label": "首选位率 / 首位推荐率",
        "id": "top1_rate",
        "numerator": "可见性样本中 brand_position=first",
        "denominator": "可见性样本条数（排除探测题）",
        "exclude_brand_probes": True,
        "timezone": "Asia/Shanghai",
        "time_basis": "shanghai_calendar_day",
        "data_source": "geo_answer_snapshots 原始快照",
        "null_when_empty": True,
    },
    "own_domain_cite_rate": {
        "label": "自有域引用率",
        "id": "own_domain_cite_rate",
        "numerator": "含引用的快照中至少命中一个自有域的条数",
        "denominator": "cited_urls 非空的快照条数",
        "exclude_brand_probes": False,
        "timezone": "Asia/Shanghai",
        "time_basis": "shanghai_calendar_day",
        "data_source": "geo_answer_snapshots.cited_urls + 自有域集合",
        "null_when_empty": True,
        "note": "自有域 = 渠道 base_url ∪ 已发布 URL 域名；无自有域配置时返回 null",
    },
    "visibility_top1_rate": {
        "label": "首位推荐率（别名）",
        "id": "visibility_top1_rate",
        "alias_of": "top1_rate",
        "timezone": "Asia/Shanghai",
        "time_basis": "shanghai_calendar_day",
        "data_source": "geo_answer_snapshots 原始快照",
    },
    "probe_recognition_rate": {
        "label": "点名认知率（别名）",
        "id": "probe_recognition_rate",
        "alias_of": "brand_probe_recognition_rate",
        "timezone": "Asia/Shanghai",
        "time_basis": "shanghai_calendar_day",
        "data_source": "geo_answer_snapshots 原始快照",
    },
}

DEFAULT_OBSERVATION_DAYS = 14


@dataclass
class SampleComposition:
    total: int = 0
    real: int = 0
    simulated: int = 0
    manual: int = 0
    unknown: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "real": self.real,
            "simulated": self.simulated,
            "manual": self.manual,
            "unknown": self.unknown,
            "has_simulated": self.simulated > 0,
            "label": (
                f"真采样 {self.real} · 模拟 {self.simulated} · 人工 {self.manual}"
                + (f" · 未知 {self.unknown}" if self.unknown else "")
            ),
        }


@dataclass
class BrandMentionResult:
    rate: float | None
    mentions: int
    visibility_n: int
    probe_n: int
    probe_hits: int
    probe_rate: float | None
    top1_count: int
    top1_rate: float | None
    composition: SampleComposition = field(default_factory=SampleComposition)
    window_start: date | None = None
    window_end: date | None = None
    exclude_brand_probes: bool = True
    metric_id: str = "brand_mention_rate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "brand_mention_rate": self.rate,
            "brand_mentions": self.mentions,
            "snapshots_visibility": self.visibility_n,
            "snapshots_probe": self.probe_n,
            "brand_probe_hits": self.probe_hits,
            "brand_probe_recognition_rate": self.probe_rate,
            "top1_count": self.top1_count,
            "top1_rate": self.top1_rate,
            "sample_composition": self.composition.to_dict(),
            "window": {
                "start": self.window_start.isoformat() if self.window_start else None,
                "end": self.window_end.isoformat() if self.window_end else None,
                "timezone": "Asia/Shanghai",
            },
            "exclude_brand_probes": self.exclude_brand_probes,
            "definition": METRIC_DICTIONARY.get("brand_mention_rate"),
        }


def _classify_sample(snap: GeoAnswerSnapshot) -> str:
    if getattr(snap, "simulated", False):
        return "simulated"
    mode = (getattr(snap, "sample_mode", None) or "").strip() or "unknown"
    if mode == "openai_compat":
        return "real"
    if mode == "mock_persona":
        return "simulated"
    if mode == "manual":
        return "manual"
    # legacy rows
    note = (getattr(snap, "note", None) or "")
    if "模拟" in note:
        return "simulated"
    if "真采样" in note or "openai_compat" in note:
        return "real"
    if mode in ("", "unknown") and not note:
        return "unknown"
    return "manual" if mode == "manual" else "unknown"


def composition_of(snaps: Sequence[GeoAnswerSnapshot]) -> SampleComposition:
    c = SampleComposition(total=len(snaps))
    for s in snaps:
        kind = _classify_sample(s)
        if kind == "real":
            c.real += 1
        elif kind == "simulated":
            c.simulated += 1
        elif kind == "manual":
            c.manual += 1
        else:
            c.unknown += 1
    return c


def compute_brand_mention_from_rows(
    snaps: Iterable[GeoAnswerSnapshot],
    *,
    probe_map: dict[int, bool],
    exclude_brand_probes: bool = True,
    window_start: date | None = None,
    window_end: date | None = None,
) -> BrandMentionResult:
    rows = list(snaps)
    comp = composition_of(rows)
    vis_n = 0
    mentions = 0
    top1 = 0
    probe_n = 0
    probe_hits = 0
    for s in rows:
        is_probe = bool(probe_map.get(s.prompt_id, False))
        if is_probe:
            probe_n += 1
            if s.mentions_brand:
                probe_hits += 1
            if exclude_brand_probes:
                continue
        vis_n += 1
        if s.mentions_brand:
            mentions += 1
        if (s.brand_position or "") == "first":
            top1 += 1
    rate = (mentions / vis_n) if vis_n else None
    probe_rate = (probe_hits / probe_n) if probe_n else None
    top1_rate = (top1 / vis_n) if vis_n else None
    return BrandMentionResult(
        rate=rate,
        mentions=mentions,
        visibility_n=vis_n,
        probe_n=probe_n,
        probe_hits=probe_hits,
        probe_rate=probe_rate,
        top1_count=top1,
        top1_rate=top1_rate,
        composition=comp,
        window_start=window_start,
        window_end=window_end,
        exclude_brand_probes=exclude_brand_probes,
    )


async def load_snapshots_in_window(
    session: AsyncSession,
    tenant_id: int,
    *,
    start: date,
    end: date,
    prompt_ids: Sequence[int] | None = None,
    engines: Sequence[str] | None = None,
    patrol_run_id: int | None = None,
    exclude_simulated: bool | None = None,
) -> list[GeoAnswerSnapshot]:
    """按上海日历日窗口加载快照（含 start/end）。"""
    start_utc, _ = shanghai_day_bounds_utc_naive(start)
    # end inclusive：取 end 日上海次日 00:00 的 UTC 作为右开界
    _, end_exclusive = shanghai_day_bounds_utc_naive(end)

    stmt = select(GeoAnswerSnapshot).where(
        GeoAnswerSnapshot.tenant_id == tenant_id,
        GeoAnswerSnapshot.captured_at >= start_utc,
        GeoAnswerSnapshot.captured_at < end_exclusive,
    )
    if prompt_ids is not None:
        ids = list(prompt_ids)
        if not ids:
            return []
        stmt = stmt.where(GeoAnswerSnapshot.prompt_id.in_(ids))
    if engines:
        stmt = stmt.where(GeoAnswerSnapshot.engine.in_(list(engines)))
    if patrol_run_id is not None:
        stmt = stmt.where(GeoAnswerSnapshot.patrol_run_id == patrol_run_id)
    if exclude_simulated is True:
        stmt = stmt.where(GeoAnswerSnapshot.simulated.is_(False))
    stmt = stmt.order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
    return list(await session.scalars(stmt))


async def load_probe_map(
    session: AsyncSession, tenant_id: int, prompt_ids: set[int]
) -> dict[int, bool]:
    if not prompt_ids:
        return {}
    rows = await session.scalars(
        select(GeoPrompt).where(
            GeoPrompt.tenant_id == tenant_id,
            GeoPrompt.id.in_(list(prompt_ids)),
        )
    )
    return {p.id: bool(p.is_brand_probe) for p in rows}


async def brand_mention_rate(
    session: AsyncSession,
    tenant_id: int,
    *,
    start: date | None = None,
    end: date | None = None,
    days: int = DEFAULT_OBSERVATION_DAYS,
    exclude_brand_probes: bool = True,
    exclude_simulated: bool | None = None,
    all_time: bool = False,
) -> BrandMentionResult:
    """统一品牌提及率。默认最近 14 个上海日；all_time=True 时不按时间过滤。"""
    if all_time:
        rows = list(
            await session.scalars(
                select(GeoAnswerSnapshot).where(
                    GeoAnswerSnapshot.tenant_id == tenant_id
                )
            )
        )
        if exclude_simulated is True:
            rows = [r for r in rows if not getattr(r, "simulated", False)]
        w_start = w_end = None
    else:
        if start is None or end is None:
            w_start, w_end = default_observation_window(days=days, end=end)
        else:
            w_start, w_end = start, end
        rows = await load_snapshots_in_window(
            session,
            tenant_id,
            start=w_start,
            end=w_end,
            exclude_simulated=exclude_simulated,
        )
    probe_map = await load_probe_map(
        session, tenant_id, {r.prompt_id for r in rows}
    )
    return compute_brand_mention_from_rows(
        rows,
        probe_map=probe_map,
        exclude_brand_probes=exclude_brand_probes,
        window_start=w_start if not all_time else None,
        window_end=w_end if not all_time else None,
    )


async def ensure_daily_metrics_for_window(
    session: AsyncSession,
    tenant_id: int,
    *,
    start: date,
    end: date,
) -> list[str]:
    """窗口内缺聚合行时自动补算（对客户隐藏「重算」）。"""
    from app.geo.content.daily_metrics import rebuild_day
    from app.models import GeoDailyMetric

    from datetime import timedelta

    rebuilt: list[str] = []
    d = start
    while d <= end:
        exists = await session.scalar(
            select(GeoDailyMetric.id).where(
                GeoDailyMetric.tenant_id == tenant_id,
                GeoDailyMetric.metric_date == d,
                GeoDailyMetric.scope_key == "t",
            )
        )
        if exists is None:
            await rebuild_day(session, tenant_id, d)
            rebuilt.append(d.isoformat())
        d += timedelta(days=1)
    return rebuilt


def metric_dictionary_payload() -> dict[str, Any]:
    return {
        "timezone": "Asia/Shanghai",
        "default_observation_days": DEFAULT_OBSERVATION_DAYS,
        "metrics": METRIC_DICTIONARY,
        "observation_note": (
            "默认观察期为最近 14 个上海日历日；"
            "引用域名长尾等全时段指标须在 UI 标注「不受上方时间筛选影响」。"
        ),
    }


@dataclass
class MetricsBundle:
    """统一指标包：所有报表只认这一份数字。"""

    brand_mention_rate: float | None
    brand_mentions: int
    snapshots_visibility: int
    top1_rate: float | None
    top1_count: int
    probe_recognition_rate: float | None
    snapshots_probe: int
    brand_probe_hits: int
    own_domain_cite_rate: float | None
    snapshots_with_citations: int
    snapshots_own_domain: int
    snapshots_total: int
    composition: SampleComposition
    window_start: date | None
    window_end: date | None
    own_domains: list[str] = field(default_factory=list)
    prompt_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "brand_mention_rate": self.brand_mention_rate,
            "visibility_mention_rate": self.brand_mention_rate,  # alias
            "brand_mentions": self.brand_mentions,
            "snapshots_visibility": self.snapshots_visibility,
            "snapshots_visibility_mention": self.brand_mentions,
            "top1_rate": self.top1_rate,
            "visibility_top1_rate": self.top1_rate,
            "top1_count": self.top1_count,
            "snapshots_visibility_first": self.top1_count,
            "probe_recognition_rate": self.probe_recognition_rate,
            "brand_probe_recognition_rate": self.probe_recognition_rate,
            "snapshots_probe": self.snapshots_probe,
            "brand_probe_hits": self.brand_probe_hits,
            "snapshots_probe_mention": self.brand_probe_hits,
            "own_domain_cite_rate": self.own_domain_cite_rate,
            "snapshots_with_citations": self.snapshots_with_citations,
            "snapshots_own_domain": self.snapshots_own_domain,
            "snapshots_total": self.snapshots_total,
            "sample_composition": self.composition.to_dict(),
            "own_domains": list(self.own_domains),
            "prompt_ids": list(self.prompt_ids),
            "window": {
                "start": self.window_start.isoformat() if self.window_start else None,
                "end": self.window_end.isoformat() if self.window_end else None,
                "timezone": "Asia/Shanghai",
                "time_basis": "shanghai_calendar_day",
            },
            "definitions": {
                k: METRIC_DICTIONARY[k]
                for k in (
                    "brand_mention_rate",
                    "top1_rate",
                    "brand_probe_recognition_rate",
                    "own_domain_cite_rate",
                )
            },
        }


def compute_metrics_from_rows(
    snaps: Sequence[GeoAnswerSnapshot],
    *,
    probe_map: dict[int, bool],
    own_domains: Sequence[str] | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
) -> MetricsBundle:
    """纯函数：从快照行算全套可见度指标（上海窗已在加载阶段完成）。"""
    from app.geo.content.snapshots import (
        domain_matches,
        extract_cited_domains,
    )

    mention = compute_brand_mention_from_rows(
        snaps,
        probe_map=probe_map,
        exclude_brand_probes=True,
        window_start=window_start,
        window_end=window_end,
    )
    own = [str(d).strip().lower() for d in (own_domains or []) if d]
    with_cite = 0
    own_hit = 0
    for s in snaps:
        domains = extract_cited_domains(list(getattr(s, "cited_urls", None) or []))
        if not domains:
            continue
        with_cite += 1
        if own and any(domain_matches(d, o) for d in domains for o in own):
            own_hit += 1
    own_rate = (own_hit / with_cite) if with_cite and own else None
    return MetricsBundle(
        brand_mention_rate=mention.rate,
        brand_mentions=mention.mentions,
        snapshots_visibility=mention.visibility_n,
        top1_rate=mention.top1_rate,
        top1_count=mention.top1_count,
        probe_recognition_rate=mention.probe_rate,
        snapshots_probe=mention.probe_n,
        brand_probe_hits=mention.probe_hits,
        own_domain_cite_rate=round(own_rate, 4) if own_rate is not None else None,
        snapshots_with_citations=with_cite,
        snapshots_own_domain=own_hit,
        snapshots_total=len(list(snaps)),
        composition=mention.composition,
        window_start=window_start,
        window_end=window_end,
        own_domains=own,
        prompt_ids=sorted({int(s.prompt_id) for s in snaps if s.prompt_id}),
    )


async def resolve_exclude_simulated(
    session: AsyncSession, tenant_id: int, explicit: bool | None = None
) -> bool | None:
    """W3: real_only → 强制排除模拟；simulation/hybrid 尊重 explicit（默认不排除）。"""
    if explicit is not None:
        return explicit
    try:
        from app.geo.content.ai_settings import ensure_ai_setting
        from app.geo.content.monitoring_stance import normalize_stance

        row = await ensure_ai_setting(session, tenant_id)
        stance = normalize_stance(getattr(row, "monitoring_stance", None))
        if stance == "real_only":
            return True
    except Exception:  # noqa: BLE001
        pass
    return None


async def compute_metrics(
    session: AsyncSession,
    tenant_id: int,
    *,
    start: date | None = None,
    end: date | None = None,
    days: int = DEFAULT_OBSERVATION_DAYS,
    prompt_ids: Sequence[int] | None = None,
    own_domains: Sequence[str] | None = None,
    exclude_simulated: bool | None = None,
    all_time: bool = False,
    apply_stance: bool = True,
) -> MetricsBundle:
    """统一入口：所有报表的品牌提及/首位/点名/自有域引用只走这里。

    时间一律上海日历日边界；all_time 时不做日期过滤（仍返回 composition）。
    apply_stance=True 时 real_only 强制排除 simulated 样本。
    """
    if apply_stance and exclude_simulated is None:
        exclude_simulated = await resolve_exclude_simulated(session, tenant_id)
    if all_time:
        stmt = select(GeoAnswerSnapshot).where(GeoAnswerSnapshot.tenant_id == tenant_id)
        if prompt_ids is not None:
            ids = list(prompt_ids)
            if not ids:
                rows: list[GeoAnswerSnapshot] = []
            else:
                stmt = stmt.where(GeoAnswerSnapshot.prompt_id.in_(ids))
                rows = list(await session.scalars(stmt))
        else:
            rows = list(await session.scalars(stmt))
        if exclude_simulated is True:
            rows = [r for r in rows if not getattr(r, "simulated", False)]
        w_start = w_end = None
    else:
        if start is None or end is None:
            w_start, w_end = default_observation_window(days=days, end=end)
        else:
            w_start, w_end = start, end
        rows = await load_snapshots_in_window(
            session,
            tenant_id,
            start=w_start,
            end=w_end,
            prompt_ids=prompt_ids,
            exclude_simulated=exclude_simulated,
        )
    probe_map = await load_probe_map(session, tenant_id, {r.prompt_id for r in rows})
    domains = list(own_domains) if own_domains is not None else None
    if domains is None:
        # lazy own domains to avoid circular import at module load
        try:
            from app.geo.content.attribution import (
                domains_from_publications,
                load_tenant_publications,
                merge_domain_lists,
            )
            from app.geo.content.snapshots import extract_cited_domain
            from app.models import GeoPublishingChannel

            channel_domains: list[str] = []
            for ch in await session.scalars(
                select(GeoPublishingChannel).where(
                    GeoPublishingChannel.tenant_id == tenant_id,
                    GeoPublishingChannel.channel_type.in_(["website", "docs"]),
                    GeoPublishingChannel.enabled.is_(True),
                )
            ):
                d = extract_cited_domain(ch.base_url)
                if d:
                    channel_domains.append(d)
            pubs = await load_tenant_publications(session, tenant_id)
            domains = merge_domain_lists(
                channel_domains, domains_from_publications(pubs)
            )
        except Exception:  # noqa: BLE001
            domains = []
    return compute_metrics_from_rows(
        rows,
        probe_map=probe_map,
        own_domains=domains or [],
        window_start=w_start if not all_time else None,
        window_end=w_end if not all_time else None,
    )
