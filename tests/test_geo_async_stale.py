"""Async job stale reconciliation helpers."""

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.geo.content.async_jobs import (
    KIND_GENERATE,
    _age_seconds,
    job_payload,
)


class AsyncStaleHelpersTests(unittest.TestCase):
    def test_age_seconds(self):
        past = datetime.utcnow() - timedelta(seconds=90)
        age = _age_seconds(past)
        self.assertIsNotNone(age)
        self.assertGreaterEqual(age, 89)
        self.assertIsNone(_age_seconds(None))

    def test_job_payload_shape(self):
        row = SimpleNamespace(
            id=1,
            tenant_id=1,
            kind=KIND_GENERATE,
            status="pending",
            ref_type="content_task",
            ref_id=9,
            request_meta={},
            result_meta=None,
            error=None,
            created_by=1,
            created_at=datetime.utcnow(),
            started_at=None,
            finished_at=None,
        )
        p = job_payload(row)
        self.assertEqual(p["kind"], KIND_GENERATE)
        self.assertEqual(p["status"], "pending")


class UnclassifiedScopeTests(unittest.TestCase):
    def test_parse_unc(self):
        from app.geo.content.daily_metrics import parse_scope_key, scope_unclassified

        self.assertEqual(scope_unclassified(), "unc")
        p = parse_scope_key("unc")
        self.assertEqual(p["level"], "unclassified")
        p2 = parse_scope_key("unc@deepseek")
        self.assertEqual(p2["level"], "unclassified")
        self.assertEqual(p2["engine"], "deepseek")

    def test_aggregate_puts_orphan_in_unc(self):
        from app.geo.content.daily_metrics import aggregate_buckets, scope_unclassified

        snap = SimpleNamespace(
            prompt_id=7,
            engine="deepseek",
            mentions_brand=True,
            brand_position="first",
            is_brand_probe=False,
            cited_urls=[],
            competitors=[],
        )
        # monkey: add_snapshot needs more attrs - use real-like
        snap.simulated = False

        buckets = aggregate_buckets(
            [snap],
            probe_map={7: False},
            unit_of_prompt={7: None},
            business_of_unit={},
        )
        self.assertIn(scope_unclassified(), buckets)
        self.assertIn("t", buckets)
        self.assertIn("p7", buckets)


if __name__ == "__main__":
    unittest.main()
