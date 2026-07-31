"""GEO Wave B answer snapshot helpers."""

import unittest

from app.geo.content.snapshots import clear_brand_missing_tag, normalize_cited_urls


class SnapshotHelpersTests(unittest.TestCase):
    def test_clear_brand_missing(self):
        self.assertEqual(
            clear_brand_missing_tag(["high_demand", "brand_missing", "demo"]),
            ["high_demand", "demo"],
        )
        self.assertEqual(clear_brand_missing_tag(["high_demand"]), ["high_demand"])
        self.assertEqual(clear_brand_missing_tag(None), [])
        self.assertEqual(clear_brand_missing_tag([]), [])

    def test_normalize_cited_urls(self):
        urls = normalize_cited_urls(
            [" https://a.com ", "https://a.com", "", "https://b.com"]
        )
        self.assertEqual(urls, ["https://a.com", "https://b.com"])
        self.assertEqual(normalize_cited_urls(None), [])


if __name__ == "__main__":
    unittest.main()
