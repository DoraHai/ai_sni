"""Release-gate oriented unit checks for the five-item loop."""

from __future__ import annotations

import unittest

from app.http_errors import is_db_unavailable
from app.geo.content.business_profile import display_brand, profile_brief_hints
from app.geo.content.metric_service import SampleComposition, sample_verdict
from app.permissions import OPERATOR_PERMS
from app.security.auth import AuthContext, _required
from fastapi import HTTPException


class QualityGateTests(unittest.TestCase):
    def test_isolation_bound_user(self):
        ctx = AuthContext(
            user_id=2,
            username="reader",
            role_name="client",
            tenant_id=3,
            permissions={"geo.content": "view"},
            is_superadmin=False,
        )
        ctx.ensure_tenant(3)
        with self.assertRaises(HTTPException) as cm:
            ctx.ensure_tenant(1)
        self.assertEqual(cm.exception.status_code, 403)
        self.assertFalse(ctx.can_edit("geo.content"))

    def test_operator_can_edit_geo(self):
        ctx = AuthContext(
            user_id=1,
            username="op",
            role_name="ops",
            tenant_id=3,
            permissions=dict(OPERATOR_PERMS),
            is_superadmin=False,
        )
        self.assertTrue(ctx.can_edit("geo.content"))

    def test_business_profile_isolates_brand(self):
        brand = display_brand({"product_name": "智齿客服"}, fallback="泉衡科技")
        hints = profile_brief_hints({"banned_claims": ["第一名"], "cta": "预约"})
        self.assertEqual(brand, "智齿客服")
        self.assertEqual(hints["cta"], "预约")

    def test_sample_verdict_blocks_zero_percent(self):
        empty = sample_verdict(SampleComposition(total=4, real=0, simulated=4))
        self.assertFalse(empty["suitable_for_client"])
        self.assertEqual(empty["verdict"], "未形成有效结论")

    def test_db_down_is_detected(self):
        self.assertTrue(is_db_unavailable(ConnectionRefusedError(1225, "远程计算机拒绝网络连接")))
        self.assertFalse(is_db_unavailable(ValueError("bad input")))

    def test_core_loop_routes_mapped(self):
        pairs = [
            ("/api/v1/geo/onboarding/preview", "POST"),
            ("/api/v1/geo/onboarding/sitemap-audit", "POST"),
            ("/api/v1/geo/content-tasks", "POST"),
            ("/api/v1/geo/competitor-reports", "POST"),
            ("/api/v1/geo/competitor-reports/1/restore", "POST"),
            ("/api/v1/geo/onboarding/sitemap-audit/create-tasks", "POST"),
            ("/api/v1/geo/deliverables/pack", "GET"),
        ]
        for path, method in pairs:
            need, _ = _required(path, method)
            self.assertIn("geo.content", need)


if __name__ == "__main__":
    unittest.main()
