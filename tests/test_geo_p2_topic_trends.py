"""P2: topic heat + AI trends catalog helpers."""

from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from app.geo.content.ai_trends import list_trend_catalog
from app.geo.content.engines import DEFAULT_TRACKING_ENGINES
from app.geo.content.probe import engine_persona
from app.geo.content.topic_heat import (
    _day_key,
    classify_heat,
    compute_topic_heat_rows,
    coverage_cell_key,
    delta_pct_for_halves,
    is_patrol_snapshot,
    topic_bucket_key,
)


class TopicHeatHelpers(unittest.TestCase):
    def test_day_key(self):
        self.assertEqual(_day_key(datetime(2026, 8, 1, 12, 0, 0)), "2026-08-01")
        self.assertIsNone(_day_key(None))

    def test_patrol_note(self):
        self.assertTrue(is_patrol_snapshot("auto-patrol #12 · mock_persona · 模拟"))
        self.assertTrue(is_patrol_snapshot("note auto-patrol #3 done"))
        self.assertFalse(is_patrol_snapshot("deepseek 探测草稿（待确认）"))
        self.assertFalse(is_patrol_snapshot(None))

    def test_coverage_cell_dedupe_key(self):
        a = coverage_cell_key(topic_key="p1", engine="DeepSeek", day="2026-08-01")
        b = coverage_cell_key(topic_key="p1", engine="deepseek", day="2026-08-01")
        c = coverage_cell_key(topic_key="p1", engine="kimi", day="2026-08-01")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_classify_heat(self):
        self.assertEqual(classify_heat(recent=4, earlier=2, delta_pct=100.0), "rising")
        self.assertEqual(classify_heat(recent=1, earlier=0, delta_pct=100.0), "stable")
        self.assertEqual(classify_heat(recent=1, earlier=4, delta_pct=-75.0), "falling")
        self.assertEqual(delta_pct_for_halves(3, 0), 100.0)
        self.assertEqual(delta_pct_for_halves(0, 0), 0.0)
        self.assertEqual(delta_pct_for_halves(3, 2), 50.0)

    def test_topic_bucket_key(self):
        prompt = SimpleNamespace(question="谁家 CRM 好用", question_group="CRM")
        k, label = topic_bucket_key(group_by="prompt", prompt_id=9, prompt=prompt)
        self.assertEqual(k, "p9")
        self.assertEqual(label, "谁家 CRM 好用")
        gk, gl = topic_bucket_key(group_by="group", prompt_id=9, prompt=prompt)
        self.assertEqual(gk, "CRM")
        self.assertEqual(gl, "CRM")

    def test_dedupe_and_split_activity(self):
        # 4-day window; same prompt×engine×day counted once for heat
        start = datetime(2026, 8, 1).date()
        prompts = {
            1: SimpleNamespace(question="CRM 怎么选", question_group="CRM"),
        }
        snaps = [
            SimpleNamespace(
                prompt_id=1,
                engine="deepseek",
                captured_at=datetime(2026, 8, 1, 10),
                mentions_brand=True,
                note="auto-patrol #1 · mock",
            ),
            SimpleNamespace(
                prompt_id=1,
                engine="deepseek",
                captured_at=datetime(2026, 8, 1, 18),
                mentions_brand=False,
                note="auto-patrol #1 · mock",
            ),
            SimpleNamespace(
                prompt_id=1,
                engine="kimi",
                captured_at=datetime(2026, 8, 1, 12),
                mentions_brand=True,
                note="人工粘贴",
            ),
            SimpleNamespace(
                prompt_id=1,
                engine="deepseek",
                captured_at=datetime(2026, 8, 4, 9),
                mentions_brand=True,
                note="人工",
            ),
        ]
        out = compute_topic_heat_rows(
            snaps, prompts, days=4, group_by="prompt", start=start
        )
        self.assertEqual(out["summary"]["snapshot_total"], 4)
        self.assertEqual(out["summary"]["patrol_snapshot_total"], 2)
        self.assertEqual(out["summary"]["manual_snapshot_total"], 2)
        # cells: (p1,deepseek,08-01), (p1,kimi,08-01), (p1,deepseek,08-04)
        self.assertEqual(out["summary"]["coverage_total"], 3)
        item = out["items"][0]
        self.assertEqual(item["coverage_count"], 3)
        self.assertEqual(item["snapshot_count"], 4)
        self.assertEqual(item["patrol_snapshot_count"], 2)
        self.assertEqual(item["manual_snapshot_count"], 2)
        self.assertEqual(item["brand_mentions"], 3)  # all 3 cells had a brand hit
        # day_totals[0]=2 engines on day1, day_totals[3]=1 on day4
        self.assertEqual(out["day_totals"][0], 2)
        self.assertEqual(out["day_totals"][3], 1)
        self.assertEqual(out["day_totals_raw"][0], 3)
        self.assertEqual(out["day_totals_raw"][3], 1)


class AiTrendsHelpers(unittest.TestCase):
    def test_catalog_regions(self):
        cn = list_trend_catalog(region="cn", limit=20)
        self.assertTrue(cn)
        self.assertTrue(all(t["region"] in ("cn", "both") for t in cn))
        glob = list_trend_catalog(region="global", limit=20)
        self.assertTrue(all(t["region"] in ("global", "both") for t in glob))


class KimiEngineDefaults(unittest.TestCase):
    def test_kimi_in_defaults(self):
        keys = {k for k, _, _ in DEFAULT_TRACKING_ENGINES}
        self.assertIn("kimi", keys)
        self.assertIn("Kimi", engine_persona("kimi"))


if __name__ == "__main__":
    unittest.main()
