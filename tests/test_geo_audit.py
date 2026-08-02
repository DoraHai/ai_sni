import unittest
from unittest.mock import AsyncMock, patch

from app.geo.audit import GeoAuditError, PageDocument, audit_url, normalize_url
from app.geo.generate import generate_json_ld, generate_llms_text


class GeoAuditTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_url(self):
        self.assertEqual(normalize_url("example.com"), "https://example.com")
        with self.assertRaises(GeoAuditError):
            normalize_url("file:///etc/passwd")

    async def test_audit_returns_explainable_findings(self):
        html = """
        <!doctype html><html lang="zh-CN"><head>
          <title>工业泵解决方案与维护服务 - 示例品牌</title>
          <meta name="description" content="为工业客户提供泵设备选型、维护、节能改造和现场支持服务，覆盖完整设备生命周期。">
          <link rel="canonical" href="https://example.com/pumps">
          <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"Organization","name":"示例品牌"}
          </script>
        </head><body>
          <h1>工业泵解决方案</h1>
          <h2>如何选择工业泵？</h2><p>根据介质、流量、扬程和工况选择。</p>
          <h2>维护与节能</h2><p>记录运行参数并定期核验。</p>
          <a href="https://example.org/source-a">资料 A</a>
          <a href="https://example.net/source-b">资料 B</a>
        </body></html>
        """
        document = PageDocument(
            requested_url="https://example.com",
            final_url="https://example.com/pumps",
            html=html,
            content_type="text/html",
        )
        with (
            patch("app.geo.audit.safe_fetch", new=AsyncMock(return_value=document)),
            patch("app.geo.audit._optional_text", new=AsyncMock(return_value=(False, ""))),
        ):
            result = await audit_url("example.com")
        self.assertEqual(result["title"], "工业泵解决方案与维护服务 - 示例品牌")
        self.assertEqual(result["snapshot"]["schema_types"], ["Organization"])
        self.assertEqual(len(result["checks"]), 16)
        self.assertEqual(result["rule_version"], "1.1.0")
        self.assertTrue(all(item["weight"] > 0 for item in result["checks"]))
        self.assertTrue(all(item["deduction"] == 0 for item in result["checks"] if item["passed"]))
        self.assertTrue(any(item["code"] == "llms" and not item["passed"] for item in result["checks"]))
        self.assertEqual(
            result["snapshot"]["external_links"],
            ["https://example.net/source-b", "https://example.org/source-a"],
        )
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_generated_assets_use_audited_facts(self):
        json_ld = generate_json_ld(
            tenant_name="示例品牌",
            url="https://example.com/page",
            title="示例页面",
            description="示例页面描述",
        )
        self.assertEqual(json_ld["@graph"][0]["name"], "示例品牌")
        self.assertEqual(json_ld["@graph"][2]["name"], "示例页面")
        llms = generate_llms_text(
            tenant_name="示例品牌",
            url="https://example.com/page",
            title="示例页面",
            description="示例页面描述",
            snapshot={"headings": [{"level": 2, "text": "产品能力"}]},
        )
        self.assertIn("# 示例品牌", llms)
        self.assertIn("产品能力", llms)


if __name__ == "__main__":
    unittest.main()
