import unittest
from unittest.mock import AsyncMock, patch

from app.geo.audit import GeoAuditError, PageDocument
from app.geo.site_audit import (
    aggregate_site_results,
    deduplicate_results,
    discover_site_urls,
    page_weight,
)


def _result(url: str, score: int, passed: bool) -> dict:
    return {
        "rule_version": "1.1.0",
        "url": url,
        "final_url": url,
        "score": score,
        "title": f"页面 {url}",
        "description": "",
        "checks": [
            {
                "code": "title",
                "title": "页面标题清晰完整",
                "category": "页面语义",
                "severity": "high",
                "passed": passed,
                "evidence": "标题证据",
                "recommendation": "补充标题",
                "weight": 8,
                "deduction": 0 if passed else 8,
                "automatable": True,
            }
        ],
        "snapshot": {
            "passed": 1 if passed else 0,
            "total": 1,
            "content_units": 100,
            "external_links": [],
            "schema_types": [],
        },
    }


class GeoSiteAuditTests(unittest.IsolatedAsyncioTestCase):
    def test_page_weight_prioritizes_home_and_core_pages(self):
        self.assertEqual(page_weight("https://example.com/"), (3, "首页"))
        self.assertEqual(page_weight("https://example.com/zh/home.html"), (3, "首页"))
        self.assertEqual(page_weight("https://example.com/products/pump"), (2, "核心页"))
        self.assertEqual(page_weight("https://example.com/news/a"), (1, "普通页"))

    async def test_discovery_uses_same_host_sitemap_pages(self):
        homepage = PageDocument(
            requested_url="https://example.com",
            final_url="https://example.com/",
            html='<html><a href="/fallback">Fallback</a></html>',
            content_type="text/html",
        )
        robots = PageDocument(
            requested_url="https://example.com/robots.txt",
            final_url="https://example.com/robots.txt",
            html="Sitemap: https://example.com/sitemap.xml",
            content_type="text/plain",
        )
        sitemap = PageDocument(
            requested_url="https://example.com/sitemap.xml",
            final_url="https://example.com/sitemap.xml",
            html=(
                '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<url><loc>https://example.com/news/a</loc></url>"
                "<url><loc>https://example.com/products/pump</loc></url>"
                "<url><loc>https://other.example/page</loc></url>"
                "</urlset>"
            ),
            content_type="application/xml",
        )

        async def fake_fetch(url, **_kwargs):
            if url.endswith("robots.txt"):
                return robots
            if url.endswith("sitemap.xml"):
                return sitemap
            return homepage

        with patch("app.geo.site_audit.safe_fetch", new=AsyncMock(side_effect=fake_fetch)):
            urls, source = await discover_site_urls("https://example.com", limit=10)
        self.assertEqual(source, "sitemap")
        self.assertEqual(urls[0], "https://example.com/")
        self.assertIn("https://example.com/products/pump", urls)
        self.assertNotIn("https://other.example/page", urls)

    async def test_localized_home_does_not_add_origin_homepage(self):
        localized_home = PageDocument(
            requested_url="https://example.com/sg/zh/home.html",
            final_url="https://example.com/sg/zh/home.html",
            html='<html><a href="/sg/zh/products/pump">Pump</a></html>',
            content_type="text/html",
        )

        async def fake_fetch(url, **_kwargs):
            if url.endswith("robots.txt") or url.endswith("sitemap.xml"):
                raise GeoAuditError("not found")
            return localized_home

        with patch("app.geo.site_audit.safe_fetch", new=AsyncMock(side_effect=fake_fetch)):
            urls, source = await discover_site_urls(
                "https://example.com/sg/zh/home.html", limit=10
            )
        self.assertEqual(source, "homepage_links")
        self.assertEqual(urls[0], "https://example.com/sg/zh/home.html")
        self.assertNotIn("https://example.com/", urls)

    def test_aggregate_uses_core_page_weights_and_keeps_page_evidence(self):
        result = aggregate_site_results(
            [
                _result("https://example.com/", 100, True),
                _result("https://example.com/products/pump", 92, False),
            ],
            discovery_source="sitemap",
            requested_count=2,
        )
        self.assertEqual(result["score"], 97)
        self.assertEqual(result["checks"][0]["deduction"], 3.2)
        self.assertEqual(len(result["checks"][0]["page_evidence"]), 2)
        self.assertIn(
            "未满足“页面标题清晰完整”规则",
            result["checks"][0]["page_evidence"][1]["reason"],
        )
        self.assertEqual(result["snapshot"]["site_audit"]["total_weight"], 5)
        self.assertEqual(result["snapshot"]["audit_scope"], "site")

    def test_aggregate_supports_extractable_block_rules(self):
        homepage = _result("https://example.com/", 94, False)
        homepage["checks"][0].update(
            {
                "code": "block_definition",
                "title": "可抽取块 · 定义",
                "category": "AI 可引用性",
                "weight": 6,
                "deduction": 6,
            }
        )
        result = aggregate_site_results(
            [homepage], discovery_source="homepage_links", requested_count=1
        )
        self.assertEqual(result["checks"][0]["weight"], 6)
        self.assertEqual(result["checks"][0]["deduction"], 6)
        self.assertEqual(result["score"], 94)

    def test_aggregate_keeps_unknown_future_rules_compatible(self):
        homepage = _result("https://example.com/", 96, False)
        homepage["checks"][0].update(
            {
                "code": "future_rule",
                "title": "未来规则",
                "weight": 4,
                "deduction": 4,
            }
        )
        result = aggregate_site_results(
            [homepage], discovery_source="homepage_links", requested_count=1
        )
        self.assertEqual(result["checks"][0]["weight"], 4)
        self.assertEqual(result["score"], 96)

    def test_results_are_deduplicated_after_redirects(self):
        first = _result("https://example.com/zh/home.html", 80, True)
        duplicate = _result("https://example.com/zh/home.html", 80, True)
        product = _result("https://example.com/products/pump", 70, False)
        self.assertEqual(len(deduplicate_results([first, duplicate, product])), 2)


if __name__ == "__main__":
    unittest.main()
