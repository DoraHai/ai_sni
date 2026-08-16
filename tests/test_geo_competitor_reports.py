"""Competitor report asset helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from datetime import datetime

from app.geo.content.competitor_reports import markdown_to_simple_html, report_payload
from app.security.auth import _required


class CompetitorReportHelperTests(unittest.TestCase):
    def test_payload_and_html(self):
        row = SimpleNamespace(
            id=3,
            tenant_id=1,
            business_id=9,
            period_id=None,
            competitor="七鱼",
            title="竞品溯源报告 · 七鱼",
            status="draft",
            insight="知乎为主阵地",
            action="补对比页",
            note="",
            markdown="# 七鱼\n结论",
            source_urls=["https://zhuanlan.zhihu.com/p/1"],
            platform_keys=["zhihu"],
            evidence={"source_count": 1},
            version_no=2,
            created_by=1,
            confirmed_by=None,
            confirmed_at=None,
            created_at=datetime(2026, 8, 16, 8, 0, 0),
            updated_at=datetime(2026, 8, 16, 9, 0, 0),
        )
        payload = report_payload(row)
        self.assertEqual(payload["status"], "draft")
        self.assertEqual(payload["competitor"], "七鱼")
        self.assertEqual(payload["version_no"], 2)
        html = markdown_to_simple_html(row.markdown, row.title)
        self.assertIn("七鱼", html)
        self.assertIn("<article>", html)

    def test_routes_require_geo_content(self):
        self.assertEqual(
            _required("/api/v1/geo/competitor-reports", "GET"),
            ({"geo.content"}, False),
        )
        self.assertEqual(
            _required("/api/v1/geo/competitor-reports", "POST"),
            ({"geo.content"}, True),
        )
        self.assertEqual(
            _required("/api/v1/geo/onboarding/sitemap-audit", "POST"),
            ({"geo.content"}, True),
        )


if __name__ == "__main__":
    unittest.main()
