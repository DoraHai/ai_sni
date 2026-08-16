from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.geo.content.competitor_web_search import (
    _clean_url,
    parse_ddg_html,
    search_competitor_web,
)


class CompetitorWebSearchTests(unittest.IsolatedAsyncioTestCase):
    def test_clean_url_unwraps_uddg(self):
        raw = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.udesk.cn%2F&rut=abc"
        self.assertEqual(_clean_url(raw), "https://www.udesk.cn/")

    def test_clean_url_skips_search_hosts(self):
        self.assertIsNone(_clean_url("https://duckduckgo.com/html/?q=udesk"))
        self.assertIsNone(_clean_url("https://www.google.com/search?q=udesk"))

    def test_parse_ddg_result_a(self):
        html = (
            '<a rel="nofollow" class="result__a" '
            'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.udesk.cn%2F">'
            "Udesk 官网</a>"
        )
        items = parse_ddg_html(html, "Udesk 官网")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://www.udesk.cn/")
        self.assertEqual(items[0]["source"], "web_search")
        self.assertFalse(items[0]["confirmed"])

    async def test_fallback_labeled_not_cite(self):
        with patch(
            "app.geo.content.competitor_web_search._ddg_html",
            new=AsyncMock(side_effect=RuntimeError("blocked")),
        ):
            out = await search_competitor_web("Udesk")
        self.assertTrue(out["items"])
        self.assertTrue(all(i["source"] == "web_search_fallback" for i in out["items"]))
        self.assertTrue(all(not i["confirmed"] for i in out["items"]))
        self.assertTrue(any("udesk.cn" in i["url"] for i in out["items"]))
        self.assertIn("cited_urls", out["note"])
        self.assertNotIn("cited_urls", [i.get("source") for i in out["items"]])

    async def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            await search_competitor_web("  ")

    def test_marks_lookalike_and_marketing(self):
        from app.geo.content.competitor_web_search import classify_search_url

        official = {"udesk.cn"}
        fake = classify_search_url("https://www.udesk.com/", official)
        self.assertEqual(fake["trust"], "lookalike")
        self.assertEqual(fake["risk"], "high")
        mkt = classify_search_url("https://www.saasruanjian.com/article/150", official)
        self.assertEqual(mkt["trust"], "marketing")
        official_hit = classify_search_url("https://www.udesk.cn/about", official)
        self.assertEqual(official_hit["trust"], "official")


if __name__ == "__main__":
    unittest.main()
