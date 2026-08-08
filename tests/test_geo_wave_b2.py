"""GEO Wave B2 helpers and auth path mapping."""

import unittest

from app.geo.content.engines import DEFAULT_TRACKING_ENGINES, default_engine_rows
from app.security.auth import _required


class WaveB2HelpersTests(unittest.TestCase):
    def test_default_engines(self):
        rows = default_engine_rows(7)
        self.assertEqual(len(rows), len(DEFAULT_TRACKING_ENGINES))
        self.assertEqual(rows[0]["tenant_id"], 7)
        self.assertEqual(rows[0]["engine_key"], "chatgpt")
        self.assertTrue(all(r["enabled"] for r in rows))

    def test_answer_snapshots_require_geo_content(self):
        self.assertEqual(
            _required("/api/v1/geo/answer-snapshots", "GET"),
            ({"geo.content"}, False),
        )
        self.assertEqual(
            _required("/api/v1/geo/answer-snapshots", "POST"),
            ({"geo.content"}, True),
        )
        self.assertEqual(
            _required("/api/v1/geo/answer-snapshots/12", "PATCH"),
            ({"geo.content"}, True),
        )

    def test_tracking_engines_and_media_require_geo_content(self):
        self.assertEqual(
            _required("/api/v1/geo/tracking-engines", "PUT"),
            ({"geo.content"}, True),
        )
        self.assertEqual(
            _required("/api/v1/geo/media-placements", "POST"),
            ({"geo.content"}, True),
        )
        self.assertEqual(
            _required("/api/v1/geo/media-placements/3", "PATCH"),
            ({"geo.content"}, True),
        )

    def test_audits_still_diagnosis(self):
        self.assertEqual(
            _required("/api/v1/geo/audits", "POST"),
            ({"geo.diagnosis"}, False),
        )


if __name__ == "__main__":
    unittest.main()
