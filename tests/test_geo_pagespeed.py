import unittest

import httpx

from app.geo.pagespeed import (
    _pagespeed_cache,
    _parse_lighthouse_report,
    fetch_pagespeed_insights,
)


class PageSpeedInsightsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _pagespeed_cache.clear()

    async def test_unconfigured_key_is_non_blocking(self):
        result = await fetch_pagespeed_insights("https://example.com", api_key="")
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["performance_score"])

    async def test_crux_metrics_are_preferred_and_normalized(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.params["strategy"], "mobile")
            self.assertEqual(request.url.params["category"], "performance")
            return httpx.Response(
                200,
                json={
                    "loadingExperience": {
                        "overall_category": "AVERAGE",
                        "metrics": {
                            "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2300, "category": "FAST"},
                            "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5, "category": "FAST"},
                            "INTERACTION_TO_NEXT_PAINT": {"percentile": 150, "category": "FAST"},
                        },
                    },
                    "lighthouseResult": {
                        "finalUrl": "https://example.com/",
                        "categories": {"performance": {"score": 0.85}},
                        "audits": {
                            "largest-contentful-paint": {"numericValue": 4100},
                            "cumulative-layout-shift": {"numericValue": 0.2},
                        },
                    },
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_pagespeed_insights(
                "https://example.com",
                api_key="secret",
                base_url="https://pagespeed.test/run",
                timeout=1,
                client=client,
            )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["performance_score"], 85)
        self.assertEqual(result["field_data_source"], "url")
        self.assertEqual(result["metrics"]["lcp"]["value"], 2.3)
        self.assertEqual(result["metrics"]["cls"]["value"], 0.05)
        self.assertEqual(result["metrics"]["inp"]["value"], 150)
        self.assertEqual(result["metrics"]["lcp"]["source"], "crux")

    async def test_lighthouse_fallback_does_not_invent_inp(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "lighthouseResult": {
                        "finalUrl": "https://example.com/",
                        "categories": {"performance": {"score": 0.61}},
                        "audits": {
                            "largest-contentful-paint": {"numericValue": 3200},
                            "cumulative-layout-shift": {"numericValue": 0.12},
                        },
                    }
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_pagespeed_insights(
                "example.com",
                api_key="secret",
                base_url="https://pagespeed.test/run",
                timeout=1,
                client=client,
            )

        self.assertEqual(result["metrics"]["lcp"]["source"], "lighthouse")
        self.assertEqual(result["metrics"]["cls"]["status"], "needs_improvement")
        self.assertIsNone(result["metrics"]["inp"])

    def test_local_lighthouse_report_is_normalized_without_inp(self):
        result = _parse_lighthouse_report(
            {
                "finalUrl": "https://example.com/",
                "categories": {"performance": {"score": 0.72}},
                "audits": {
                    "largest-contentful-paint": {"numericValue": 2800},
                    "cumulative-layout-shift": {"numericValue": 0.06},
                },
            },
            "https://example.com",
            "mobile",
        )

        self.assertEqual(result["provider"], "local_lighthouse")
        self.assertEqual(result["performance_score"], 72)
        self.assertEqual(result["metrics"]["lcp"]["value"], 2.8)
        self.assertEqual(result["metrics"]["cls"]["value"], 0.06)
        self.assertIsNone(result["metrics"]["inp"])


if __name__ == "__main__":
    unittest.main()
