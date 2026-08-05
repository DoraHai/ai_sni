"""Wave C+ snapshot field suggestion normalization."""

import unittest

from app.geo.content.snapshot_suggest import (
    brand_mentioned_in_text,
    normalize_suggest_payload,
)


class SnapshotSuggestTests(unittest.TestCase):
    def test_heuristic_brand_mention(self):
        self.assertTrue(
            brand_mentioned_in_text("Growth Sniper 适合中小团队", ["Growth Sniper"])
        )
        self.assertFalse(brand_mentioned_in_text("只有竞品A", ["Growth Sniper"]))
        self.assertIsNone(brand_mentioned_in_text("任意正文", []))

    def test_normalize_llm_payload(self):
        out = normalize_suggest_payload(
            {
                "suggested_mentions_brand": True,
                "competitors": ["竞品A", "Growth Sniper", "竞品A"],
                "brand_position": "FIRST",
                "sentiment": "positive",
            },
            raw_text="见 https://zhihu.com/q/1 与竞品A。Growth Sniper 也不错。",
            brand_names=["Growth Sniper"],
        )
        self.assertTrue(out["suggested_mentions_brand"])
        self.assertEqual(out["suggested_competitors"], ["竞品A"])
        self.assertEqual(out["suggested_brand_position"], "first")
        self.assertEqual(out["suggested_sentiment"], "positive")
        self.assertEqual(out["suggested_cited_urls"], ["https://zhihu.com/q/1"])
        self.assertEqual(out["source"], "llm")

    def test_normalize_falls_back_to_heuristic_without_llm(self):
        out = normalize_suggest_payload(
            None,
            raw_text="正文提到 Growth Sniper，无链接",
            brand_names=["Growth Sniper"],
        )
        self.assertTrue(out["suggested_mentions_brand"])
        self.assertEqual(out["suggested_competitors"], [])
        self.assertEqual(out["suggested_brand_position"], "mentioned")
        self.assertEqual(out["suggested_sentiment"], "unknown")
        self.assertEqual(out["source"], "heuristic")

    def test_invalid_enums_become_unknown(self):
        out = normalize_suggest_payload(
            {
                "suggested_mentions_brand": False,
                "brand_position": "top3",
                "sentiment": "mixed",
                "competitors": [],
            },
            raw_text="无品牌",
            brand_names=["BrandX"],
        )
        self.assertEqual(out["suggested_brand_position"], "unknown")
        self.assertEqual(out["suggested_sentiment"], "unknown")


if __name__ == "__main__":
    unittest.main()
