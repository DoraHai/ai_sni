"""Visibility window metrics + expand vs-last-run badges."""

from datetime import datetime
from types import SimpleNamespace
import unittest

from app.geo.content.expand import annotate_vs_last_run, candidate_term_key
from app.geo.content.snapshots import (
    compute_window_metrics,
    in_captured_window,
    parse_window_bound,
    rate_delta,
)


class VisibilityPeriodDiffTests(unittest.TestCase):
    def test_parse_and_window(self):
        start = parse_window_bound("2026-08-01T00:00:00Z", label="from")
        end = parse_window_bound("2026-08-07T23:59:59", label="to")
        self.assertTrue(
            in_captured_window(datetime(2026, 8, 3, 12, 0, 0), start=start, end=end)
        )
        self.assertFalse(
            in_captured_window(datetime(2026, 7, 31, 23, 0, 0), start=start, end=end)
        )

    def test_compute_window_excludes_probe_from_mention_rate(self):
        rows = [
            SimpleNamespace(
                prompt_id=1,
                mentions_brand=True,
                cited_urls=["https://example.com/a"],
            ),
            SimpleNamespace(
                prompt_id=2,
                mentions_brand=True,
                cited_urls=[],
            ),
            SimpleNamespace(
                prompt_id=3,
                mentions_brand=False,
                cited_urls=["https://other.com/x"],
            ),
        ]
        metrics = compute_window_metrics(
            rows,
            prompt_probe={1: False, 2: True, 3: False},
            own_domains=["example.com"],
        )
        # visibility rows: id1 mention, id3 miss → 0.5
        self.assertEqual(metrics["snapshots_visibility"], 2)
        self.assertEqual(metrics["visibility_mention_rate"], 0.5)
        self.assertEqual(metrics["snapshots_with_citations"], 2)
        self.assertEqual(metrics["own_domain_cite_rate"], 0.5)

    def test_no_own_domains_yields_null_cite_rate(self):
        rows = [
            SimpleNamespace(
                prompt_id=1, mentions_brand=False, cited_urls=["https://a.com"]
            )
        ]
        metrics = compute_window_metrics(
            rows, prompt_probe={1: False}, own_domains=[]
        )
        self.assertIsNone(metrics["own_domain_cite_rate"])
        self.assertIsNone(rate_delta(0.2, None))
        self.assertEqual(rate_delta(0.2, 0.5), 0.3)


class ExpandRunDiffTests(unittest.TestCase):
    def test_annotate_vs_last_run(self):
        items = [
            {"term": "A", "question": "qa", "in_bank": False},
            {"term": "B", "question": "qb", "in_bank": True},
        ]
        first = annotate_vs_last_run(items, None)
        self.assertIsNone(first["new_vs_last_count"])
        self.assertIsNone(first["items"][0]["vs_last_run"])

        second = annotate_vs_last_run(items, {"a"})
        self.assertEqual(second["new_vs_last_count"], 1)
        self.assertEqual(second["items"][0]["vs_last_run"], "still")
        self.assertEqual(second["items"][1]["vs_last_run"], "new")
        self.assertEqual(candidate_term_key({"term": " X "}), "x")


if __name__ == "__main__":
    unittest.main()
