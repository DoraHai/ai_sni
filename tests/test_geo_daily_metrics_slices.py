"""业务 / 单元按天切片汇总单元测试（无 DB）。"""

from __future__ import annotations

from types import SimpleNamespace

from app.geo.content.daily_metrics import (
    MetricBucket,
    aggregate_buckets,
    parse_scope_key,
    scope_business,
    scope_tenant,
    scope_unit,
)


def _snap(prompt_id: int, *, mentions=False, position="unknown", urls=None):
    return SimpleNamespace(
        prompt_id=prompt_id,
        mentions_brand=mentions,
        brand_position=position,
        cited_urls=urls or [],
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
    }
    assert parse_scope_key("u4")["unit_id"] == 4


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
