"""业务 / 单元按天切片汇总单元测试（无 DB）。"""

from __future__ import annotations

from types import SimpleNamespace

from app.geo.content.daily_metrics import (
    MetricBucket,
    aggregate_buckets,
    parse_scope_key,
    scope_business,
    scope_prompt,
    scope_tenant,
    scope_unit,
    scope_with_engine,
)


def _snap(
    prompt_id: int,
    *,
    mentions=False,
    position="unknown",
    urls=None,
    engine="other",
    competitors=None,
):
    return SimpleNamespace(
        prompt_id=prompt_id,
        mentions_brand=mentions,
        brand_position=position,
        cited_urls=urls or [],
        engine=engine,
        competitors=competitors or [],
    )


def test_scope_key_helpers():
    assert scope_tenant() == "t"
    assert scope_business(12) == "b12"
    assert scope_unit(3) == "u3"
    assert parse_scope_key("t")["level"] == "tenant"
    assert parse_scope_key("b9") == {
        "level": "business",
        "business_id": 9,
        "unit_id": None,
        "prompt_id": None,
        "engine": None,
    }
    assert parse_scope_key("u4")["unit_id"] == 4
    assert parse_scope_key("p8")["level"] == "prompt"
    assert parse_scope_key("t@deepseek")["engine"] == "deepseek"
    assert parse_scope_key("u3@doubao")["unit_id"] == 3
    assert parse_scope_key("u3@doubao")["engine"] == "doubao"


def test_aggregate_tenant_business_unit():
    # p1 → unit 10 → biz 1；p2 → unit 20 → biz 1；p3 无 unit
    snaps = [
        _snap(1, mentions=True, position="first", urls=["https://a.com/x", "https://b.com/y"]),
        _snap(2, mentions=False, urls=["https://a.com/z"]),
        _snap(3, mentions=True, urls=["https://c.com"]),  # 仅租户
        _snap(1, mentions=False),  # 同 unit 再一条
    ]
    probe_map = {1: False, 2: False, 3: False}
    unit_of_prompt = {1: 10, 2: 20, 3: None}
    business_of_unit = {10: 1, 20: 1}

    buckets = aggregate_buckets(
        snaps,
        probe_map=probe_map,
        unit_of_prompt=unit_of_prompt,
        business_of_unit=business_of_unit,
    )

    assert scope_tenant() in buckets
    assert scope_business(1) in buckets
    assert scope_unit(10) in buckets
    assert scope_unit(20) in buckets

    t = buckets[scope_tenant()].to_metrics_dict()
    assert t["snapshots_visibility"] == 4
    assert t["brand_mentions"] == 2
    assert t["top1_count"] == 1
    assert t["citation_count"] == 4  # 2 + 1 + 1
    assert t["distinct_cited_domains"] == 3  # a.com b.com c.com

    b1 = buckets[scope_business(1)].to_metrics_dict()
    # p1×2 + p2×1 = 3（不含 p3）
    assert b1["snapshots_visibility"] == 3
    assert b1["brand_mentions"] == 1
    assert b1["citation_count"] == 3
    assert b1["distinct_cited_domains"] == 2  # a.com b.com

    u10 = buckets[scope_unit(10)].to_metrics_dict()
    assert u10["snapshots_visibility"] == 2
    assert u10["brand_mentions"] == 1
    assert u10["top1_count"] == 1
    assert u10["citation_count"] == 2

    u20 = buckets[scope_unit(20)].to_metrics_dict()
    assert u20["snapshots_visibility"] == 1
    assert u20["brand_mentions"] == 0


def test_probe_excluded_from_mention_rate_denominator():
    snaps = [
        _snap(1, mentions=True),  # visibility
        _snap(2, mentions=True),  # probe
    ]
    buckets = aggregate_buckets(
        snaps,
        probe_map={1: False, 2: True},
        unit_of_prompt={1: 5, 2: 5},
        business_of_unit={5: 9},
    )
    m = buckets[scope_unit(5)].to_metrics_dict()
    assert m["snapshots_visibility"] == 1
    assert m["snapshots_probe"] == 1
    assert m["brand_mentions"] == 1
    assert m["brand_probe_hits"] == 1
    assert m["brand_mention_rate"] == 1.0
    assert m["brand_probe_recognition_rate"] == 1.0


def test_metric_bucket_empty_rates_none():
    b = MetricBucket()
    d = b.to_metrics_dict()
    assert d["brand_mention_rate"] is None
    assert d["brand_probe_recognition_rate"] is None
    assert d["top1_rate"] is None
    assert d["citation_count"] == 0


def test_metric_day_from_captured():
    from datetime import date, datetime

    from app.geo.content.daily_metrics import _metric_day_from_captured
    from app.geo.content.time_windows import shanghai_today

    assert _metric_day_from_captured(datetime(2026, 8, 7, 15, 30)).isoformat() == "2026-08-07"
    assert _metric_day_from_captured(datetime(2026, 8, 7, 20, 30)).isoformat() == "2026-08-08"
    assert _metric_day_from_captured(date(2026, 1, 2)).isoformat() == "2026-01-02"
    assert _metric_day_from_captured(None) == shanghai_today()


def test_aggregate_engine_and_prompt_slices():
    snaps = [
        _snap(1, mentions=True, engine="deepseek"),
        _snap(1, mentions=False, engine="doubao"),
        _snap(2, mentions=True, engine="deepseek"),
    ]
    buckets = aggregate_buckets(
        snaps,
        probe_map={1: False, 2: False},
        unit_of_prompt={1: 10, 2: 10},
        business_of_unit={10: 1},
    )
    assert scope_prompt(1) in buckets
    assert scope_with_engine(scope_tenant(), "deepseek") in buckets
    assert scope_with_engine(scope_unit(10), "doubao") in buckets
    ds = buckets[scope_with_engine(scope_tenant(), "deepseek")].to_metrics_dict()
    assert ds["snapshots_visibility"] == 2
    assert ds["brand_mentions"] == 2
    p1 = buckets[scope_prompt(1)].to_metrics_dict()
    assert p1["snapshots_visibility"] == 2
    assert p1["brand_mentions"] == 1


def test_competitor_mentions_in_bucket():
    snaps = [
        _snap(1, mentions=True, competitors=["竞品A", "竞品B"], engine="deepseek"),
        _snap(1, mentions=False, competitors=["竞品A"], engine="deepseek"),
        _snap(2, mentions=True, competitors=["竞品A"], engine="doubao"),
    ]
    buckets = aggregate_buckets(
        snaps,
        probe_map={1: False, 2: False},
        unit_of_prompt={1: 10, 2: 10},
        business_of_unit={10: 1},
    )
    t = buckets[scope_tenant()].to_metrics_dict()
    assert t["any_competitor_mentions"] == 3
    assert t["top_competitor"] == "竞品A"
    assert t["competitor_mentions"]["竞品A"]["mentions"] == 3
    eng = buckets[scope_with_engine(scope_tenant(), "deepseek")].to_metrics_dict()
    assert eng["competitor_mentions"]["竞品A"]["mentions"] == 2
    assert eng["top_competitor_rate"] == 1.0  # 2/2 visibility


def test_simulated_samples_never_enter_any_daily_slice():
    row = _snap(1, mentions=True)
    row.sample_mode = "mock_persona"
    buckets = aggregate_buckets([row], probe_map={}, unit_of_prompt={1: 2}, business_of_unit={2: 3})
    assert list(buckets) == ['t']
    assert buckets['t'].to_metrics_dict()['snapshots_visibility'] == 0


def test_mixed_methods_hide_daily_rates_but_keep_counts():
    first, second = _snap(1, mentions=True), _snap(1, mentions=False)
    first.sample_mode = second.sample_mode = 'openai_compat'
    first.note = 'method=unprimed_json_v2 · analysis=completed'
    second.note = ''
    bucket = MetricBucket()
    bucket.add_snapshot(first, is_probe=False)
    bucket.add_snapshot(second, is_probe=False)
    result = bucket.to_metrics_dict()
    assert result['snapshots_visibility'] == 2
    assert result['brand_mention_rate'] is None


def test_report_daily_rows_follow_shanghai_days_without_engine_slices():
    from datetime import datetime, date
    from app.geo.content.daily_metrics import snapshot_daily_rows, metric_row_payload
    row = _snap(1, mentions=True, engine='deepseek')
    row.captured_at = datetime(2026, 9, 1, 16, 30)
    rows = snapshot_daily_rows([row], tenant_id=7, start=date(2026, 9, 1), end=date(2026, 9, 2),
        probe_map={}, unit_of_prompt={1: 2}, business_of_unit={2: 3})
    assert not any('@' in r.scope_key for r in rows)
    business = [metric_row_payload(r) for r in rows if r.scope_key == 'b3']
    assert business[0]['snapshots_visibility'] == 0
    assert business[0]['brand_mention_rate'] is None
    assert business[1]['metric_date'] == '2026-09-02'
    assert business[1]['snapshots_visibility'] == 1
    assert business[1]['tenant_id'] == 7


def test_report_population_excludes_simulated_and_outside_window():
    from datetime import datetime, date
    from app.geo.content.daily_metrics import snapshot_daily_rows
    real, simulated, outside = _snap(1), _snap(1), _snap(1)
    real.captured_at = simulated.captured_at = datetime(2026, 9, 1, 1)
    simulated.sample_mode = 'mock_persona'
    outside.captured_at = datetime(2026, 8, 30)
    rows = snapshot_daily_rows([real, simulated, outside], tenant_id=7, start=date(2026, 9, 1), end=date(2026, 9, 1), probe_map={}, unit_of_prompt={}, business_of_unit={})
    assert next(r for r in rows if r.scope_key == 't').snapshots_visibility == 1


def test_rebuild_clears_obsolete_cached_slices():
    import asyncio
    from datetime import date
    from unittest.mock import AsyncMock, patch
    from app.geo.content import daily_metrics as dm
    session = AsyncMock()
    session.scalars.return_value = [SimpleNamespace(scope_key='b3@deepseek', business_id=3, unit_id=None)]
    async def run():
        with patch.object(dm, 'load_day_snapshots', new=AsyncMock(return_value=[])), patch.object(dm, 'load_prompt_unit_maps', new=AsyncMock(return_value=({}, {}, {}))), patch.object(dm, 'upsert_metric_row', new=AsyncMock()) as upsert:
            await dm.rebuild_day(session, 7, date(2026, 9, 1))
            cached = next(call.kwargs['bucket'] for call in upsert.call_args_list if call.kwargs['scope_key'] == 'b3@deepseek')
            assert cached.to_metrics_dict()['snapshots_visibility'] == 0
            assert cached.to_metrics_dict()['brand_mention_rate'] is None
            assert session.scalars.call_args.args[0].compile().params['tenant_id_1'] == 7
    asyncio.run(run())
