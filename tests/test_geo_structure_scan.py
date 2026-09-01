from __future__ import annotations

import unittest
from urllib.parse import urlparse

from app.geo.structure_scan import (
    build_page_row,
    page_kind,
    page_type_cn,
    pick_scan_urls,
    summarize_structure,
)


class StructureScanTests(unittest.TestCase):
    def test_classifies_service_and_product(self):
        self.assertEqual(page_kind("https://ex.com/services/impl"), "service")
        self.assertEqual(page_type_cn("https://ex.com/product/crm"), "产品")
        self.assertEqual(page_type_cn("https://ex.com/faq"), "FAQ")

    def test_product_page_without_schema_is_missing(self):
        row = build_page_row(
            url="https://ex.com/product/crm",
            title="CRM",
            types=["Organization"],
            h1s=["CRM"],
            has_author=False,
            has_date=False,
            questions=[],
            same_as=[],
            about_product=False,
            items=[],
            brand="泉衡",
            summary="",
        )
        self.assertEqual(row["type"], "产品")
        self.assertEqual(row["status"], "缺失")
        self.assertEqual(row["jsonld"]["@type"], "Product")
        self.assertEqual(row["jsonld"]["brand"]["name"], "泉衡")

    def test_summarize_does_not_invent_coverage_counts(self):
        product = build_page_row(
            url="https://ex.com/product/a",
            title="泵",
            types=[],
            h1s=["泵"],
            has_author=False,
            has_date=False,
            questions=[],
            same_as=[],
            about_product=False,
            items=[],
            brand="泉衡泵业",
            summary="",
        )
        home = build_page_row(
            url="https://ex.com/",
            title="首页",
            types=["Organization", "WebSite"],
            h1s=["泉衡泵业"],
            has_author=False,
            has_date=False,
            questions=[],
            same_as=["https://www.zhihu.com/org/x"],
            about_product=False,
            items=[
                {"@type": "Organization", "name": "泉衡泵业", "url": "https://ex.com/"},
                {"@type": "WebSite", "name": "泉衡泵业官网", "url": "https://ex.com/"},
            ],
            brand="泉衡泵业",
            summary="",
        )
        out = summarize_structure(
            [home, product],
            brand="泉衡泵业",
            website="https://ex.com",
            sitemap_url="https://ex.com/sitemap.xml",
            discovered=2,
        )
        self.assertEqual(out["kind"], "website_structure")
        self.assertEqual(out["page_count"], 2)
        self.assertEqual(out["structured_count"], 1)
        product_card = next(c for c in out["coverage"] if c["key"] == "product")
        self.assertEqual(product_card["value"], "0 / 1 页面")
        self.assertTrue(any("Product" in i["title"] for i in out["issues"]))
        org_card = next(c for c in out["coverage"] if c["key"] == "org")
        self.assertEqual(org_card["value"], "已覆盖")
        faq_card = next(c for c in out["coverage"] if c["key"] == "faq")
        self.assertEqual(faq_card["value"], "未发现 FAQ 页")
        self.assertLess(out["score"], 100)
        self.assertGreaterEqual(out["score"], 0)

    def test_pick_skips_apiv2_and_keeps_real_pages(self):
        urls = [f"https://www.udesk.cn/apiv2/x{i}/" for i in range(40)]
        urls += [
            "https://www.udesk.cn/product/crm",
            "https://www.udesk.cn/faq",
            "https://www.udesk.cn/about",
        ]
        picked = pick_scan_urls("https://www.udesk.cn/", urls, limit=8)
        self.assertTrue(all("apiv2" not in u for u in picked))
        self.assertTrue(any(urlparse(u).path in {"", "/"} for u in picked))
        self.assertTrue(any("/product/" in u for u in picked))
        self.assertTrue(any("/faq" in u for u in picked))

    def test_pick_normalizes_home_url_before_deduplication(self):
        picked = pick_scan_urls(
            "https://example.com",
            ["https://example.com/", "https://example.com/products/pump"],
        )

        home_urls = [url for url in picked if urlparse(url).path in {"", "/"}]
        self.assertEqual(len(home_urls), 1)
        self.assertIn("https://example.com/products/pump", picked)

    def test_pick_excludes_sitemap_xml_from_page_sample(self):
        picked = pick_scan_urls(
            "https://example.com/",
            [
                "https://example.com/shop/sitemaps/product.xml",
                "https://example.com/products/pump",
            ],
        )

        self.assertNotIn("https://example.com/shop/sitemaps/product.xml", picked)
        self.assertIn("https://example.com/products/pump", picked)

    def test_summary_marks_all_failed_fetches_as_not_assessable(self):
        failed_home = build_page_row(
            url="https://example.com/",
            title="",
            types=[],
            h1s=[],
            has_author=False,
            has_date=False,
            questions=[],
            same_as=[],
            about_product=False,
            items=[],
            brand="泉衡泵业",
            summary="",
            error="网站连接失败：连接被拒绝",
        )
        out = summarize_structure(
            [failed_home],
            brand="泉衡泵业",
            website="https://example.com",
            sitemap_url=None,
            discovered=1,
        )

        self.assertEqual(out["assessment_status"], "insufficient_sample")
        self.assertEqual(out["successful_page_count"], 0)
        self.assertEqual(out["failed_page_count"], 1)
        self.assertIsNone(out["score"])
        self.assertTrue(any(issue["code"] == "scan_no_successful_pages" for issue in out["issues"]))

    def test_summary_with_too_many_failed_pages_is_not_assessable(self):
        success = build_page_row(
            url="https://example.com/",
            title="首页",
            types=["Organization"],
            h1s=[], has_author=False, has_date=False, questions=[], same_as=[],
            about_product=False, items=[{"@type": "Organization", "name": "示例", "url": "https://example.com/"}],
            brand="示例", summary="",
        )
        failed = [
            build_page_row(
                url=f"https://example.com/p{i}", title="", types=[], h1s=[],
                has_author=False, has_date=False, questions=[], same_as=[], about_product=False,
                items=[], brand="示例", summary="", error="网站连接失败",
            )
            for i in range(3)
        ]
        out = summarize_structure(
            [success, *failed], brand="示例", website="https://example.com", sitemap_url=None, discovered=4,
        )

        self.assertEqual(out["assessment_status"], "insufficient_sample")
        self.assertIsNone(out["score"])

    def test_product_schema_without_required_fields_is_not_counted_as_complete(self):
        row = build_page_row(
            url="https://example.com/products/pump", title="泵", types=["Product"], h1s=[],
            has_author=False, has_date=False, questions=[], same_as=[], about_product=False,
            items=[{"@type": "Product", "name": "耐腐蚀泵"}], brand="示例", summary="",
        )

        self.assertEqual(row["status"], "可增强")
        self.assertEqual(row["valid_schema_types"], [])

    def test_faq_schema_with_question_and_answer_is_counted_as_complete(self):
        row = build_page_row(
            url="https://example.com/faq", title="常见问题", types=["FAQPage"], h1s=[],
            has_author=False, has_date=False, questions=[], same_as=[], about_product=False,
            items=[{
                "@type": "FAQPage",
                "mainEntity": [{
                    "@type": "Question",
                    "name": "如何选型？",
                    "acceptedAnswer": {"@type": "Answer", "text": "请按介质与流量选型。"},
                }],
            }],
            brand="示例", summary="",
        )

        self.assertEqual(row["status"], "正常")
        self.assertEqual(row["valid_schema_types"], ["FAQPage"])

    def test_summary_does_not_count_organization_schema_more_than_once(self):
        pages = [
            build_page_row(
                url=url,
                title="泉衡泵业",
                types=["Organization"],
                h1s=[],
                has_author=False,
                has_date=False,
                questions=[],
                same_as=[],
                about_product=False,
                items=[{"@type": "Organization", "name": "泉衡泵业", "url": url}],
                brand="泉衡泵业",
                summary="",
            )
            for url in (
                "https://example.com/",
                "https://example.com/features/one",
                "https://example.com/features/two",
            )
        ]
        out = summarize_structure(
            pages,
            brand="泉衡泵业",
            website="https://example.com",
            sitemap_url=None,
            discovered=3,
        )

        self.assertEqual(out["score_dims"][0]["value"], 100)
        self.assertLessEqual(out["score"], 100)

    def test_brand_page_jsonld_uses_brand_name(self):
        row = build_page_row(
            url="https://ex.com/",
            title="营销口号首页",
            types=[],
            h1s=["营销口号首页"],
            has_author=False,
            has_date=False,
            questions=[],
            same_as=[],
            about_product=False,
            items=[],
            brand="Udesk",
            summary="",
        )
        self.assertEqual(row["jsonld"]["@type"], "Organization")
        self.assertEqual(row["jsonld"]["name"], "Udesk")
        name_field = next(f for f in row["fields"] if f["key"] == "name")
        self.assertEqual(name_field["value"], "Udesk")


class StructureScanBrandPickTests(unittest.TestCase):
    def test_prefers_business_with_matching_website(self):
        from types import SimpleNamespace

        from app.geo.routes import pick_business_for_website

        empty = SimpleNamespace(name="口号业务", profile={})
        match = SimpleNamespace(
            name="Udesk",
            profile={"product_name": "Udesk", "website": "https://www.udesk.cn/"},
        )
        later = SimpleNamespace(name="空业务", profile={})
        hit = pick_business_for_website([empty, match, later], "https://www.udesk.cn")
        self.assertIs(hit, match)


if __name__ == "__main__":
    unittest.main()
