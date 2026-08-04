"""Eligibility rules for facts used in publishable GEO content."""

import unittest
from datetime import date, timedelta

from app.geo.content.evidence import (
    eligible_facts,
    evidence_issues,
    generation_evidence_error_message,
    prepare_facts_for_generation,
)
from app.geo.content.generate_article import generate_master_article
from app.geo.content.variants import GeoContentError


class GeoEvidenceTests(unittest.TestCase):
    def test_eligible_facts_require_verified_source_and_freshness(self):
        today = date(2026, 8, 2)
        facts = [
            {"id": 1, "trust_level": "verified", "source_name": "产品文档", "status": "active", "expires_at": today + timedelta(days=1)},
            {"id": 2, "trust_level": "needs_review", "source_name": "案例", "status": "active", "expires_at": today + timedelta(days=1)},
            {"id": 3, "trust_level": "verified", "source_name": "", "status": "active", "expires_at": today + timedelta(days=1)},
            {"id": 4, "trust_level": "verified", "source_name": "旧资料", "status": "active", "expires_at": today - timedelta(days=1)},
        ]
        self.assertEqual([fact["id"] for fact in eligible_facts(facts, today=today)], [1])

    def test_evidence_issues_reports_the_publish_blockers(self):
        today = date(2026, 8, 2)
        issues = evidence_issues(
            [
                {"id": 2, "trust_level": "draft", "source_name": "案例", "status": "active", "expires_at": None},
                {"id": 4, "trust_level": "verified", "source_name": "旧资料", "status": "archived", "expires_at": today},
            ],
            today=today,
        )
        self.assertEqual(issues[2], ["not_verified"])
        self.assertEqual(issues[4], ["not_active", "expired"])

    def test_prepare_facts_for_generation_meta(self):
        today = date(2026, 8, 2)
        facts = [
            {"id": 1, "trust_level": "verified", "source_name": "a", "status": "active"},
            {"id": 2, "trust_level": "needs_review", "source_name": "b", "status": "active"},
            {"id": 3, "trust_level": "verified", "source_name": "c", "status": "active", "expires_at": today - timedelta(days=1)},
        ]
        eligible, meta = prepare_facts_for_generation(facts, today=today, min_eligible=3)
        self.assertEqual([f["id"] for f in eligible], [1])
        self.assertFalse(meta["ok"])
        self.assertEqual(meta["eligible_count"], 1)
        self.assertEqual(len(meta["excluded"]), 2)
        msg = generation_evidence_error_message(meta)
        self.assertIn("可发布证据", msg)
        self.assertIn("#2", msg)


class GenerateEvidenceGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_rejects_when_eligible_below_min(self):
        today = date(2026, 8, 2)
        facts = [
            {"id": 1, "title": "a", "statement": "陈述一", "source_name": "s", "trust_level": "verified", "status": "active"},
            {"id": 2, "title": "b", "statement": "陈述二", "source_name": "s", "trust_level": "needs_review", "status": "active"},
            {"id": 3, "title": "c", "statement": "陈述三", "source_name": "s", "trust_level": "verified", "status": "active", "expires_at": "2026-07-01"},
        ]
        with self.assertRaises(GeoContentError) as ctx:
            await generate_master_article(
                tenant_name="Demo",
                question="数据分析平台哪个好用",
                facts=facts,
                today=today,
            )
        self.assertIn("可发布证据", str(ctx.exception))

    async def test_generate_uses_only_eligible_facts(self):
        today = date(2026, 8, 2)
        facts = [
            {"id": 1, "title": "部署", "statement": "支持私有化", "source_name": "白皮书", "trust_level": "verified", "status": "active"},
            {"id": 2, "title": "API", "statement": "开放接口", "source_name": "文档", "trust_level": "verified", "status": "active"},
            {"id": 3, "title": "行业", "statement": "服务制造", "source_name": "案例", "trust_level": "verified", "status": "active"},
            {"id": 4, "title": "过期", "statement": "旧数字", "source_name": "旧", "trust_level": "verified", "status": "active", "expires_at": "2026-07-01"},
        ]
        payload = await generate_master_article(
            tenant_name="Demo",
            question="数据分析平台哪个好用",
            facts=facts,
            today=today,
        )
        used = set(payload.get("used_fact_ids") or [])
        self.assertTrue(used.issubset({1, 2, 3}))
        self.assertNotIn(4, used)
        evidence = payload.get("_evidence") or {}
        self.assertTrue(evidence.get("ok"))
        self.assertEqual(evidence.get("eligible_count"), 3)
        self.assertEqual(len(evidence.get("excluded") or []), 1)


if __name__ == "__main__":
    unittest.main()
