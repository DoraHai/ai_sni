"""Citation quality heuristic helpers."""

from __future__ import annotations

import unittest

from app.geo.content.citation_quality import (
    classify_url_vs_own,
    suggest_accuracy_from_checks,
)


class CitationQualityTests(unittest.TestCase):
    def test_classify_own_domain(self):
        self.assertEqual(
            classify_url_vs_own("https://www.example.com/a", ["example.com"]),
            "own",
        )
        self.assertEqual(
            classify_url_vs_own("https://news.example.com/a", ["example.com"]),
            "own",
        )
        self.assertEqual(
            classify_url_vs_own("https://zhihu.com/q/1", ["example.com"]),
            "external",
        )

    def test_suggest_accuracy(self):
        self.assertEqual(
            suggest_accuracy_from_checks(cited_urls=[], own_domains=["a.com"]),
            "unknown",
        )
        self.assertEqual(
            suggest_accuracy_from_checks(
                cited_urls=["https://a.com/x"],
                own_domains=["a.com"],
            ),
            "accurate",
        )
        self.assertEqual(
            suggest_accuracy_from_checks(
                cited_urls=["https://a.com/x", "https://b.com/y"],
                own_domains=["a.com"],
            ),
            "partial",
        )
        self.assertEqual(
            suggest_accuracy_from_checks(
                cited_urls=["https://a.com/x"],
                own_domains=["a.com"],
                url_results=[
                    {
                        "checked": True,
                        "reachable": False,
                        "status": 404,
                        "domain_kind": "own",
                    }
                ],
            ),
            "inaccurate",
        )


if __name__ == "__main__":
    unittest.main()
