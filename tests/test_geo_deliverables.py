"""GEO deliverables pack helpers and auth mapping."""

from __future__ import annotations

import unittest

from app.geo.content.deliverables import (
    build_deliverables_pack,
    render_deliverables_markdown,
)
from app.security.auth import _required


class DeliverablesPackTests(unittest.TestCase):
    def test_build_and_render_markdown(self):
        pack = build_deliverables_pack(
            tenant_id=1,
            tenant_name="Acme",
            period={"from": "2026-07-01T00:00:00", "to": "2026-07-31T23:59:59", "days": 31},
            summary={
                "prompts": 5,
                "tasks": 3,
                "published": 1,
                "visibility_mention_rate": 0.5,
                "snapshots_visibility": 4,
                "visibility_engines_covered": 2,
                "distinct_cited_domains": 1,
                "prompts_need_recheck": 0,
            },
            citations_top=[
                {
                    "domain": "example.com",
                    "cite_count": 3,
                    "engines": ["deepseek"],
                    "is_own_domain": True,
                    "blueprint_channel_name": "官网",
                }
            ],
            tasks=[{"id": 9, "status": "published", "title": "指南"}],
            snapshots_sample=[
                {
                    "captured_at": "2026-07-10T12:00:00",
                    "engine": "deepseek",
                    "mentions_brand": True,
                    "prompt_question": "哪个好？",
                }
            ],
        )
        self.assertEqual(pack["generated_kind"], "geo_deliverables_pack_v1")
        md = render_deliverables_markdown(pack)
        self.assertIn("Acme", md)
        self.assertIn("example.com", md)
        self.assertIn("指南", md)
        self.assertIn("50.0%", md)

    def test_deliverables_require_geo_content(self):
        self.assertEqual(
            _required("/api/v1/geo/deliverables/pack", "GET"),
            ({"geo.content"}, False),
        )
        self.assertEqual(
            _required("/api/v1/geo/competitor-insights", "GET"),
            ({"geo.content"}, False),
        )
        self.assertEqual(
            _required("/api/v1/geo/evaluation-insights", "GET"),
            ({"geo.content"}, False),
        )


if __name__ == "__main__":
    unittest.main()
