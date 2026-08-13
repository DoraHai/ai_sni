import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.geo.chinaz import (
    _baidu_index_cache,
    _metric_cache,
    fetch_baidu_index_count,
    fetch_baidu_mobile_keywords,
    fetch_baidu_pc_keywords,
    fetch_chinaz_seo_metrics,
    fetch_comprehensive_weight,
    fetch_whois,
)


class ChinazBaiduIndexTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _baidu_index_cache.clear()
        _metric_cache.clear()

    async def test_unconfigured_key_is_non_blocking(self):
        result = await fetch_baidu_index_count("https://www.example.com/page", api_key="")
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["site_count"])
        self.assertEqual(result["domain"], "www.example.com")
        self.assertTrue(result["is_estimate"])

    async def test_successful_response_is_normalized_and_cached(self):
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            self.assertEqual(request.url.params["domain"], "www.example.com")
            return httpx.Response(
                200,
                json={"StateCode": 1, "Reason": "成功", "Result": {"SiteCount": 1234}},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await fetch_baidu_index_count(
                "https://www.example.com/page",
                api_key="secret-key",
                base_url="https://apidatav2.chinaz.com",
                timeout=1,
                client=client,
            )
            second = await fetch_baidu_index_count(
                "https://www.example.com/other",
                api_key="secret-key",
                base_url="https://apidatav2.chinaz.com",
                timeout=1,
                client=client,
            )

        self.assertEqual(first["status"], "available")
        self.assertEqual(first["site_count"], 1234)
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(calls, 1)

    async def test_provider_error_does_not_raise(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"StateCode": 10022, "Reason": "剩余次数不足"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_baidu_index_count(
                "example.com",
                api_key="secret-key",
                base_url="https://apidatav2.chinaz.com",
                timeout=1,
                client=client,
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "剩余次数不足")
        self.assertIsNone(result["site_count"])

    async def test_pc_keyword_response_is_normalized(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/1001/baidupckeyword")
            self.assertEqual(request.url.params["APIKey"], "pc-key")
            self.assertEqual(request.url.params["ChinazVer"], "1.0")
            self.assertEqual(request.url.params["page"], "1")
            return httpx.Response(
                200,
                json={
                    "StateCode": 1,
                    "Reason": "成功",
                    "Result": {
                        "Total": 218,
                        "Pages": 3,
                        "Uv": "500~798",
                        "List": [
                            {
                                "Keyword": "硬质合金刀具",
                                "RankStr": "1-4",
                                "Index": 32,
                                "Title": "产品中心",
                                "Url": "https://example.com/tools",
                                "Calalog": "tools",
                            }
                        ],
                    },
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_baidu_pc_keywords(
                "https://www.example.com",
                api_key="pc-key",
                base_url="https://openapi.chinaz.net/v1/1001",
                timeout=1,
                client=client,
            )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["total"], 218)
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["keywords"][0]["keyword"], "硬质合金刀具")

    async def test_mobile_keyword_response_is_normalized(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/1001/keyword_baidumobile")
            return httpx.Response(
                200,
                json={
                    "StateCode": "1",
                    "Reason": "成功",
                    "Result": {"Total": 49, "Pages": 1, "Uv": "25~40", "List": []},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_baidu_mobile_keywords(
                "example.com",
                api_key="mobile-key",
                base_url="https://openapi.chinaz.net/v1/1001",
                timeout=1,
                client=client,
            )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["total"], 49)

    async def test_comprehensive_weight_response_is_normalized(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/1001/weight_all")
            return httpx.Response(
                200,
                json={
                    "StateCode": 1,
                    "Reason": "成功",
                    "Result": {
                        "BaidupcBr": 1,
                        "BaidupcKwcount": 218,
                        "BaidupcUvcount": "500~798IP",
                        "BaiduMobileBr": 3,
                        "BaiduMobileKwcount": 49,
                        "BaiduMobileUvcount": "120~190IP",
                    },
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_comprehensive_weight(
                "example.com",
                api_key="weight-key",
                base_url="https://openapi.chinaz.net/v1/1001",
                timeout=1,
                client=client,
            )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["baidu_pc"]["weight"], 1)
        self.assertEqual(result["baidu_mobile"]["weight"], 3)
        self.assertEqual(result["baidu_pc"]["uv"], "500~798")

    async def test_whois_response_is_normalized_without_contact_details(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/1001/whois")
            self.assertEqual(request.url.params["APIKey"], "whois-key")
            return httpx.Response(
                200,
                json={
                    "StateCode": 1,
                    "Reason": "成功",
                    "Host": "example.com",
                    "ContactPerson": "Private Person",
                    "Email": "private@example.com",
                    "Phone": "+1.5555555555",
                    "Registrar": "Example Registrar",
                    "CreationDate": "1995-08-14T04:00:00Z",
                    "ExpirationDate": "2030-08-13T04:00:00Z",
                    "WhoisServer": "whois.example.test",
                    "DnsServer": "NS1.EXAMPLE.COM,NS2.EXAMPLE.COM",
                    "DomainStatus": "clientTransferProhibited",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_whois(
                "https://example.com/path",
                api_key="whois-key",
                base_url="https://openapi.chinaz.net/v1/1001",
                timeout=1,
                client=client,
            )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["registrar"], "Example Registrar")
        self.assertGreaterEqual(result["domain_age_years"], 30)
        self.assertEqual(result["dns_servers"], ["NS1.EXAMPLE.COM", "NS2.EXAMPLE.COM"])
        self.assertNotIn("email", result)
        self.assertNotIn("phone", result)
        self.assertNotIn("contact_person", result)

    async def test_unconfigured_whois_key_is_non_blocking(self):
        result = await fetch_whois("https://example.com", api_key="")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "站长之家 Whois 查询接口尚未配置")

    async def test_global_switch_pauses_all_provider_requests(self):
        with (
            patch(
                "app.geo.chinaz.get_settings",
                return_value=SimpleNamespace(chinaz_api_enabled=False),
            ),
            patch("app.geo.chinaz._request_json", new=AsyncMock()) as request_json,
        ):
            metrics = await fetch_chinaz_seo_metrics("https://example.com")

        request_json.assert_not_awaited()
        self.assertEqual(len(metrics), 5)
        self.assertTrue(
            all(item["reason"] == "站长之家数据查询已暂停" for item in metrics.values())
        )


if __name__ == "__main__":
    unittest.main()
