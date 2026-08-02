"""Eligibility rules for facts used in publishable GEO content."""

import unittest
from datetime import date, timedelta

from app.geo.content.evidence import eligible_facts, evidence_issues


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


if __name__ == "__main__":
    unittest.main()
