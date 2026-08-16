"""安全网：同一租户同一观察窗，四条路径品牌提及率必须同值。

构造纯内存快照行，断言 compute_metrics_from_rows 与各路径应使用的别名键一致。
集成级四路径路由测试依赖 DB；此处先锁住口径纯函数，再由 compute_metrics 保证调用方对齐。
"""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from app.geo.content.metric_service import (
    compute_metrics_from_rows,
)


def _snap(
    pid: int,
    *,
    mentions: bool,
    probe: bool = False,
    position: str = "unknown",
    urls: list[str] | None = None,
    simulated: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_id=pid,
        mentions_brand=mentions,
        brand_position=position,
        cited_urls=urls or [],
        competitors=[],
        simulated=simulated,
        sample_mode="openai_compat" if not simulated else "mock_persona",
        engine="deepseek",
        note="",
    )


class MetricParityTests(unittest.TestCase):
    def test_four_path_alias_keys_equal(self):
        """概览/期次/交付/业务详情应读取同一 bundle 的同名字段。"""
        snaps = [
            _snap(1, mentions=True, position="first"),
            _snap(1, mentions=False),
            _snap(2, mentions=True),
            _snap(3, mentions=True, probe=True),  # probe — 不进提及率分母
            _snap(4, mentions=False, urls=["https://brand.com/a"]),
            _snap(5, mentions=True, urls=["https://other.com/x"]),
        ]
        probe_map = {1: False, 2: False, 3: True, 4: False, 5: False}
        bundle = compute_metrics_from_rows(
            snaps,
            probe_map=probe_map,
            own_domains=["brand.com"],
            window_start=date(2026, 8, 1),
            window_end=date(2026, 8, 14),
        )
        d = bundle.to_dict()

        # 可见性：4 条非探测（pid 1×2 + 2 + 4 + 5 = 5?）
        # snaps: 1m,1,2m,3probe,4,5m → non-probe = 5, mentions = 1m+2m+5m = 3 → 0.6
        self.assertEqual(bundle.snapshots_visibility, 5)
        self.assertEqual(bundle.brand_mentions, 3)
        self.assertAlmostEqual(bundle.brand_mention_rate or 0, 0.6)

        # 四路径常用键必须指向同一数值
        overview_rate = d["brand_mention_rate"]
        period_rate = d["visibility_mention_rate"]
        deliverable_rate = d["visibility_mention_rate"]
        business_rate = d["brand_mention_rate"]
        self.assertEqual(overview_rate, period_rate)
        self.assertEqual(overview_rate, deliverable_rate)
        self.assertEqual(overview_rate, business_rate)
        self.assertEqual(d["top1_rate"], d["visibility_top1_rate"])
        self.assertEqual(d["probe_recognition_rate"], d["brand_probe_recognition_rate"])

        # 探测：1 条命中
        self.assertEqual(bundle.snapshots_probe, 1)
        self.assertEqual(bundle.brand_probe_hits, 1)
        self.assertAlmostEqual(bundle.probe_recognition_rate or 0, 1.0)

        # 自有域：2 条有引用，1 条自有 → 0.5
        self.assertEqual(bundle.snapshots_with_citations, 2)
        self.assertEqual(bundle.snapshots_own_domain, 1)
        self.assertAlmostEqual(bundle.own_domain_cite_rate or 0, 0.5)

    def test_null_when_no_visibility_sample(self):
        snaps = [_snap(9, mentions=True, probe=True)]
        bundle = compute_metrics_from_rows(
            snaps, probe_map={9: True}, own_domains=["x.com"]
        )
        self.assertIsNone(bundle.brand_mention_rate)
        self.assertEqual(bundle.snapshots_visibility, 0)

    def test_http_https_match_for_own_domain(self):
        from app.geo.content.attribution import normalize_url_for_match, urls_match_publication

        self.assertEqual(
            normalize_url_for_match("http://WWW.Example.com/path/"),
            normalize_url_for_match("https://example.com/path"),
        )
        self.assertTrue(
            urls_match_publication(
                "http://blog.example.com/p/1?utm=x",
                "https://blog.example.com/p/1",
            )
        )


if __name__ == "__main__":
    unittest.main()
