"""Sitemap site-wide diagnosis helpers (no network)."""

from __future__ import annotations

import unittest

from app.geo.sitemap_audit import (
    classify_path,
    collect_robots_sitemaps,
    skip_reason,
    _parse_sitemap_locs,
)


class SitemapAuditTests(unittest.TestCase):
    def test_classify_path(self):
        self.assertEqual(classify_path("https://ex.com/"), "home")
        self.assertEqual(classify_path("https://ex.com/products/a"), "product")
        self.assertEqual(classify_path("https://ex.com/faq"), "faq")
        self.assertEqual(classify_path("https://ex.com/case/acme"), "case")
        self.assertEqual(classify_path("https://ex.com/blog/hello"), "blog")
        self.assertEqual(classify_path("https://ex.com/random"), "other")

    def test_skip_api_paths(self):
        self.assertIsNotNone(skip_reason("https://www.udesk.cn/api/v1/users"))
        self.assertIsNotNone(skip_reason("https://www.udesk.cn/openapi.json"))
        self.assertIsNotNone(skip_reason("https://www.udesk.cn/apiv2/intro/"))
        self.assertIsNotNone(skip_reason("https://www.udesk.cn/apiv2/tickets"))
        self.assertIsNotNone(skip_reason("https://www.udesk.cn/thirdparty/cc_force_api/"))
        self.assertIsNone(skip_reason("https://www.udesk.cn/product"))

    def test_robots_sitemaps_keep_listed_order(self):
        text = """User-agent: *
Sitemap: https://www.udesk.cn/sitemap.xml
Sitemap: https://www.udesk.cn/landing/sitemap.xml
Sitemap: https://www.udesk.cn/doc/sitemap.xml
"""
        self.assertEqual(
            collect_robots_sitemaps(text),
            [
                "https://www.udesk.cn/sitemap.xml",
                "https://www.udesk.cn/landing/sitemap.xml",
                "https://www.udesk.cn/doc/sitemap.xml",
            ],
        )

    def test_parse_locs(self):
        xml = """<?xml version="1.0"?>
        <urlset>
          <url><loc>https://ex.com/a</loc></url>
          <url><loc>https://ex.com/faq</loc></url>
          <url><loc>not-a-url</loc></url>
        </urlset>"""
        locs = _parse_sitemap_locs(xml)
        self.assertEqual(locs, ["https://ex.com/a", "https://ex.com/faq"])


if __name__ == "__main__":
    unittest.main()
