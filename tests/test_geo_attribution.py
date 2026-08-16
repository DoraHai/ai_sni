"""发布 URL ↔ 监测归因 helpers."""

import unittest

from app.geo.content.attribution import (
    PubRef,
    impact_windows,
    match_publication_ids,
    merge_domain_lists,
    normalize_url_for_match,
    rate_or_none,
    urls_match_publication,
)


class AttributionTests(unittest.TestCase):
    def test_normalize_url(self):
        self.assertEqual(
            normalize_url_for_match("HTTPS://WWW.Example.com/path/?q=1#frag"),
            "https://example.com/path",
        )
        self.assertEqual(
            normalize_url_for_match("example.com/a/"),
            "https://example.com/a",
        )
        self.assertIsNone(normalize_url_for_match(""))
        self.assertIsNone(normalize_url_for_match("not a url"))

    def test_urls_match(self):
        self.assertTrue(
            urls_match_publication(
                "https://blog.example.com/p/123?utm=1",
                "https://blog.example.com/p/123",
            )
        )
        self.assertTrue(
            urls_match_publication(
                "https://blog.example.com/p/123/comments",
                "https://blog.example.com/p/123",
            )
        )
        self.assertFalse(
            urls_match_publication(
                "https://other.com/p/123",
                "https://blog.example.com/p/123",
            )
        )

    def test_match_publication_ids(self):
        pubs = [
            PubRef(
                id=10,
                published_url="https://www.brand.com/articles/geo-guide",
                channel="website",
                variant_id=1,
                task_id=100,
                published_at=None,
            ),
            PubRef(
                id=11,
                published_url="https://zhuanlan.zhihu.com/p/999",
                channel="zhihu",
                variant_id=2,
                task_id=100,
                published_at=None,
            ),
        ]
        hits = match_publication_ids(
            [
                "https://brand.com/articles/geo-guide?from=ai",
                "https://example.com/other",
            ],
            pubs,
        )
        self.assertEqual(hits, [10])
        hits2 = match_publication_ids(
            ["https://zhuanlan.zhihu.com/p/999"],
            pubs,
        )
        self.assertEqual(hits2, [11])
        self.assertEqual(match_publication_ids([], pubs), [])
        self.assertEqual(match_publication_ids(["https://x.com"], []), [])

    def test_merge_domains(self):
        self.assertEqual(
            merge_domain_lists(["a.com"], ["b.com", "a.com"], ["c.com"]),
            ["a.com", "b.com", "c.com"],
        )

    def test_impact_windows_and_rate(self):
        from datetime import datetime

        b, a, e = impact_windows(datetime(2026, 8, 1, 12, 0, 0), window_days=14)
        self.assertEqual(b.day, 18)
        self.assertEqual(a.day, 1)
        self.assertEqual(e.day, 15)
        self.assertIsNone(impact_windows(None)[0])
        self.assertEqual(rate_or_none(1, 4), 0.25)
        self.assertIsNone(rate_or_none(0, 0))


if __name__ == "__main__":
    unittest.main()
