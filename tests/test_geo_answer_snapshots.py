"""GEO Wave B / B3 answer snapshot helpers."""

from datetime import datetime, timezone
import unittest

from app.geo.content.snapshots import (
    apply_brand_mention_tags,
    clear_brand_missing_tag,
    ensure_brand_missing_tag,
    needs_recheck,
    normalize_brand_position,
    normalize_cited_urls,
    normalize_competitors,
    normalize_sentiment,
    visibility_mention_rate,
)


class SnapshotHelpersTests(unittest.TestCase):
    def test_clear_brand_missing(self):
        self.assertEqual(
            clear_brand_missing_tag(["high_demand", "brand_missing", "demo"]),
            ["high_demand", "demo"],
        )
        self.assertEqual(clear_brand_missing_tag(["high_demand"]), ["high_demand"])
        self.assertEqual(clear_brand_missing_tag(None), [])
        self.assertEqual(clear_brand_missing_tag([]), [])

    def test_ensure_brand_missing(self):
        self.assertEqual(
            ensure_brand_missing_tag(["high_demand"]),
            ["high_demand", "brand_missing"],
        )
        self.assertEqual(
            ensure_brand_missing_tag(["brand_missing"]),
            ["brand_missing"],
        )
        self.assertEqual(ensure_brand_missing_tag(None), ["brand_missing"])

    def test_apply_brand_mention_tags_symmetric(self):
        self.assertEqual(
            apply_brand_mention_tags(["high_demand", "brand_missing"], mentions_brand=True),
            ["high_demand"],
        )
        self.assertEqual(
            apply_brand_mention_tags(["high_demand"], mentions_brand=False),
            ["high_demand", "brand_missing"],
        )
        self.assertEqual(
            apply_brand_mention_tags(["brand_missing"], mentions_brand=False),
            ["brand_missing"],
        )

    def test_needs_recheck(self):
        t0 = datetime(2026, 7, 1, tzinfo=timezone.utc)
        t1 = datetime(2026, 7, 2, tzinfo=timezone.utc)
        self.assertFalse(
            needs_recheck(
                has_published_task=False,
                task_updated_at=t1,
                last_snapshot_at=None,
            )
        )
        self.assertTrue(
            needs_recheck(
                has_published_task=True,
                task_updated_at=t1,
                last_snapshot_at=None,
            )
        )
        self.assertTrue(
            needs_recheck(
                has_published_task=True,
                task_updated_at=t1,
                last_snapshot_at=t0,
            )
        )
        self.assertFalse(
            needs_recheck(
                has_published_task=True,
                task_updated_at=t0,
                last_snapshot_at=t1,
            )
        )

    def test_normalize_cited_urls(self):
        urls = normalize_cited_urls(
            [" https://a.com ", "https://a.com", "", "https://b.com"]
        )
        self.assertEqual(urls, ["https://a.com", "https://b.com"])
        self.assertEqual(normalize_cited_urls(None), [])

    def test_normalize_competitors(self):
        self.assertEqual(
            normalize_competitors([" A ", "A", "", "B"]),
            ["A", "B"],
        )
        self.assertEqual(normalize_competitors(None), [])

    def test_normalize_position_sentiment(self):
        self.assertEqual(normalize_brand_position("first"), "first")
        self.assertEqual(normalize_brand_position("nope"), "unknown")
        self.assertEqual(normalize_sentiment("NEGATIVE"), "negative")
        self.assertEqual(normalize_sentiment(""), "unknown")

    def test_visibility_mention_rate(self):
        self.assertIsNone(
            visibility_mention_rate(total_snapshots=0, mention_snapshots=0)
        )
        self.assertEqual(
            visibility_mention_rate(total_snapshots=4, mention_snapshots=1),
            0.25,
        )


if __name__ == "__main__":
    unittest.main()
