import unittest
from unittest.mock import AsyncMock, patch

from app.geo.audit import PageDocument
from app.geo.brand_profile import (
    _competitor_candidates,
    discover_brand_profile,
    extract_brand_candidate,
    website_key,
)


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
        self.assertEqual(result["competitors"], [])

    def test_ai_competitor_candidates_require_confirmation(self):
        competitors = _competitor_candidates(
            [
                {
                    "name": "竞品甲",
                    "website": "https://competitor.example.com",
                    "competitor_type": "direct",
                    "overlap_products": ["工业刀具"],
                    "target_market": "中国制造业",
                },
                {
                    "name": "竞品乙",
                    "website": "可能是这个网址",
                    "competitor_type": "unknown",
                },
            ]
        )

        self.assertEqual(len(competitors), 2)
        self.assertFalse(competitors[0]["confirmed"])
        self.assertEqual(competitors[0]["source"], "AI 市场候选")
        self.assertEqual(competitors[1]["website"], "")
        self.assertEqual(competitors[1]["competitor_type"], "direct")

    def test_discovery_reports_when_ai_market_inference_is_unavailable(self):
        document = PageDocument(
            requested_url="https://www.example.com",
            final_url="https://www.example.com",
            content_type="text/html",
            html="<html><head><title>示例制造</title></head><body><h1>工业刀具</h1></body></html>",
        )
        settings = {
            "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
            "BAIDU_APP_ID": "test",
            "BAIDU_SECRET_KEY": "test",
            "BAIDU_DEFAULT_USERNAME": "test",
            "BAIDU_DEFAULT_UCID": "0",
            "BAIDU_SELF_ACCESS_TOKEN": "test",
            "BAIDU_SELF_TOKEN_EXPIRES_AT": "2099-01-01T00:00:00Z",
            "CRYPTO_MASTER_KEY_B64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "ADMIN_API_KEY": "test-admin-key",
        }
        with patch.dict("os.environ", settings, clear=False):
            with (
                patch("app.geo.brand_profile.safe_fetch", new=AsyncMock(return_value=document)),
                patch("app.ai.deepseek.is_enabled", return_value=False),
            ):
                result = __import__("asyncio").run(discover_brand_profile(document.final_url))

        self.assertFalse(result["ai_used"])
        self.assertEqual(result["competitor_discovery"]["status"], "unavailable")
        self.assertEqual(result["competitor_discovery"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
