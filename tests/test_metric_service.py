"""Unified metric service + Shanghai day bounds."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.geo.content.metric_service import (
    composition_of,
    compute_brand_mention_from_rows,
)
from app.geo.content.time_windows import (
    shanghai_day_bounds_utc_naive,
    shanghai_day_of_utc_naive,
)


class TimeWindowsTests(unittest.TestCase):
    def test_shanghai_day_of_utc_evening(self):
        # 2026-08-11 20:30 Shanghai = 12:30 UTC same calendar day
        utc = datetime(2026, 8, 11, 12, 30, 0)
        self.assertEqual(shanghai_day_of_utc_naive(utc), date(2026, 8, 11))
        # 2026-08-11 23:30 Shanghai = 15:30 UTC still same day
        utc2 = datetime(2026, 8, 11, 15, 30, 0)
        self.assertEqual(shanghai_day_of_utc_naive(utc2), date(2026, 8, 11))

    def test_day_bounds_cover_shanghai_evening(self):
        start, end = shanghai_day_bounds_utc_naive(date(2026, 8, 11))
        # 20:00 Shanghai = 12:00 UTC
        evening = datetime(2026, 8, 11, 12, 0, 0)
        self.assertGreaterEqual(evening, start)
        self.assertLess(evening, end)


class MetricComputeTests(unittest.TestCase):
    def _snap(self, **kw):
        base = dict(
            prompt_id=1,
            mentions_brand=False,
            brand_position="unknown",
            sample_mode="openai_compat",
            simulated=False,
            note=None,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_exclude_probes(self):
        snaps = [
            self._snap(prompt_id=1, mentions_brand=True),
            self._snap(prompt_id=2, mentions_brand=True),  # probe
            self._snap(prompt_id=1, mentions_brand=False),
        ]
        probe_map = {1: False, 2: True}
        r = compute_brand_mention_from_rows(snaps, probe_map=probe_map)
        self.assertEqual(r.visibility_n, 2)
        self.assertEqual(r.mentions, 1)
        self.assertAlmostEqual(r.rate or 0, 0.5)
        self.assertEqual(r.probe_n, 1)
        self.assertEqual(r.probe_hits, 1)

    def test_composition_simulated(self):
        snaps = [
            self._snap(sample_mode="openai_compat", simulated=False),
            self._snap(sample_mode="mock_persona", simulated=True),
            self._snap(sample_mode="manual", simulated=False),
        ]
        c = composition_of(snaps)
        self.assertEqual(c.real, 1)
        self.assertEqual(c.simulated, 1)
        self.assertEqual(c.manual, 1)
        self.assertTrue(c.to_dict()["has_simulated"])


if __name__ == "__main__":
    unittest.main()
