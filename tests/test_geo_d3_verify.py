"""D3 action-ticket verify checkers (GeoLook verify adapt)."""

import unittest

from app.geo.verify import (
    CODE_TO_CHECK,
    apply_verdict_to_status,
    evaluate_check,
    materialize_ticket_specs,
    resolve_acceptance,
)
from app.security.auth import _required


class CheckerTests(unittest.TestCase):
    def test_finding_passed(self):
        audit = {
            "findings": [
                {"code": "schema", "passed": True, "evidence": "Organization"},
                {"code": "llms", "passed": False, "evidence": "missing"},
            ]
        }
        ok, note, _ = evaluate_check("pages.has_jsonld", audit=audit)
        self.assertTrue(ok)
        ok2, _, _ = evaluate_check("site.has_llms_txt", audit=audit)
        self.assertFalse(ok2)
        ok3, note3, _ = evaluate_check("finding.passed:title", audit=audit)
        self.assertIsNone(ok3)
        self.assertIn("无检查项", note3)

    def test_pages_block(self):
        audit = {"snapshot": {"blocks": {"definition": True, "numbers": False}}}
        ok, _, prog = evaluate_check("pages.block:definition", audit=audit)
        self.assertTrue(ok)
        ok2, _, prog2 = evaluate_check("pages.block:numbers", audit=audit)
        self.assertFalse(ok2)
        self.assertEqual(prog2["cur"], 1)

    def test_media_published(self):
        media = [
            {"id": 1, "channel_key": "zhihu", "status": "planned", "published_url": ""},
            {
                "id": 2,
                "channel_key": "official",
                "status": "published",
                "published_url": "https://ex.com",
            },
        ]
        ok, _, _ = evaluate_check("media.any_published", media_placements=media)
        self.assertTrue(ok)
        ok2, _, _ = evaluate_check(
            "media.published:zhihu", media_placements=media
        )
        self.assertFalse(ok2)
        ok3, _, _ = evaluate_check(
            "media.published:official", media_placements=media
        )
        self.assertTrue(ok3)
        ok4, _, _ = evaluate_check(
            "media.placement_published:2", media_placements=media
        )
        self.assertTrue(ok4)

    def test_unknown_is_manual(self):
        ok, note, _ = evaluate_check("metrics.mention_rate_gte:cn:0.3")
        self.assertIsNone(ok)
        self.assertIn("未知检查器", note)


class MaterializeTests(unittest.TestCase):
    def test_from_advice_maps_llms(self):
        advice = [
            {
                "code": "llms",
                "priority": "low",
                "title": "提供 llms.txt",
                "action": "发布 llms.txt",
                "acceptance": "重新诊断后通过",
            }
        ]
        findings = [
            {
                "code": "llms",
                "passed": False,
                "title": "提供 llms.txt 导览",
                "automatable": True,
                "recommendation": "生成 llms.txt",
            }
        ]
        specs = materialize_ticket_specs(advice=advice, findings=findings)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["acceptance_type"], "auto")
        self.assertEqual(specs[0]["acceptance_check"], "site.has_llms_txt")

    def test_from_failed_findings_when_no_advice(self):
        findings = [
            {
                "code": "schema",
                "passed": False,
                "severity": "high",
                "title": "JSON-LD",
                "recommendation": "补 Schema",
                "automatable": True,
            },
            {"code": "https", "passed": True, "title": "HTTPS"},
        ]
        specs = materialize_ticket_specs(advice=None, findings=findings)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["acceptance_check"], CODE_TO_CHECK["schema"])

    def test_resolve_manual_without_map(self):
        acc_type, check, _ = resolve_acceptance(
            code="custom_thing", finding={"automatable": False}
        )
        self.assertEqual(acc_type, "manual")
        self.assertIsNone(check)


class VerdictStatusTests(unittest.TestCase):
    def test_pass_and_regression(self):
        self.assertEqual(apply_verdict_to_status(current_status="todo", ok=True), ("done", "pass"))
        self.assertEqual(
            apply_verdict_to_status(current_status="done", ok=False),
            ("reopened", "fail"),
        )
        self.assertEqual(
            apply_verdict_to_status(current_status="todo", ok=False),
            ("todo", "fail"),
        )
        self.assertEqual(
            apply_verdict_to_status(current_status="doing", ok=None),
            ("doing", "manual"),
        )


class AuthPathTests(unittest.TestCase):
    def test_tickets_under_diagnosis(self):
        self.assertEqual(
            _required("/api/v1/geo/action-tickets", "GET"),
            ({"geo.diagnosis"}, False),
        )
        self.assertEqual(
            _required("/api/v1/geo/audits/3/tickets", "POST"),
            ({"geo.diagnosis"}, False),
        )
        self.assertEqual(
            _required("/api/v1/geo/audits/3/verify", "POST"),
            ({"geo.diagnosis"}, False),
        )


if __name__ == "__main__":
    unittest.main()
