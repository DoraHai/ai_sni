import unittest

from app.geo.audit import PageDocument
from app.geo.brand_profile import extract_brand_candidate, website_key


class GeoBrandProfileTests(unittest.TestCase):
    def test_website_key_normalizes_www_and_paths(self):
        self.assertEqual(
            website_key("https://www.kennametal.com/sg/zh/home.html"),
            "kennametal.com",
        )

    def test_schema_and_page_headings_create_reviewable_candidate(self):
        document = PageDocument(
            requested_url="https://www.example.com",
            final_url="https://www.example.com/zh/home.html",
            content_type="text/html",
            html="""
            <html><head>
              <title>示例制造 | 精密加工解决方案</title>
              <meta name="description" content="为制造企业提供精密加工与刀具服务">
              <script type="application/ld+json">
                {"@type":"Organization","name":"示例制造","industry":"工业制造"}
              </script>
            </head><body><h1>精密加工解决方案</h1><h2>金属切削刀具</h2></body></html>
            """,
        )
        result = extract_brand_candidate(document)
        self.assertEqual(result["name"], "示例制造")
        self.assertEqual(result["industry"], "工业制造")
        self.assertEqual(result["core_products"][0], "精密加工解决方案")
        self.assertEqual(result["evidence"]["name"], "Schema.org")


if __name__ == "__main__":
    unittest.main()
