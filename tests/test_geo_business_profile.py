"""Business profile is the content context, not tenant brand."""

from __future__ import annotations

import unittest

from app.geo.content.brief_suggest import suggest_brief_heuristic
from app.geo.content.business_profile import (
    brand_names_for_profile,
    display_brand,
    normalize_profile,
    profile_brief_hints,
)


class BusinessProfileTests(unittest.TestCase):
    def test_normalize_lists_and_strings(self):
        p = normalize_profile(
            {
                "product_name": "智齿客服",
                "website": "https://example.com",
                "honors": "2025 行业创新奖",
                "qualifications": "ISO 27001",
                "capabilities": "多渠道接入, 工单",
                "banned_claims": ["第一名", "保证收录"],
                "cta": "预约演示",
                "unknown": "drop-me",
            }
        )
        self.assertEqual(p["product_name"], "智齿客服")
        self.assertEqual(p["website"], "https://example.com")
        self.assertEqual(p["honors"], ["2025 行业创新奖"])
        self.assertEqual(p["qualifications"], ["ISO 27001"])
        self.assertEqual(p["capabilities"], ["多渠道接入", "工单"])
        self.assertEqual(p["banned_claims"], ["第一名", "保证收录"])
        self.assertNotIn("unknown", p)

    def test_display_brand_prefers_product(self):
        self.assertEqual(
            display_brand({"product_name": "智齿客服"}, fallback="泉衡科技"),
            "智齿客服",
        )
        self.assertEqual(display_brand({}, fallback="泉衡科技"), "泉衡科技")

    def test_brief_hints_do_not_use_other_brand(self):
        hints = profile_brief_hints(
            {
                "industry": "智能客服",
                "audience": "客服负责人",
                "competitors": "七鱼, Udesk",
                "banned_claims": "第一名",
                "capabilities": "工单",
                "recommend_reasons": "私有化部署",
                "cta": "预约演示",
            }
        )
        brief = suggest_brief_heuristic(
            question="客服系统怎么选型",
            brand=display_brand({"product_name": "智齿客服"}, fallback="泉衡科技"),
            profile_hints=hints,
        )
        self.assertEqual(brief["industry"], "智能客服")
        self.assertEqual(brief["audience"], "客服负责人")
        self.assertEqual(brief["cta"], "预约演示")
        self.assertIn("第一名", brief["banned_claims"])
        self.assertIn("智齿客服", brief["must_cover"])
        self.assertNotIn("泉衡科技", brief["must_cover"])
        self.assertIn("七鱼", brief["competitors"])

    def test_probe_names_do_not_mix_tenant_brand(self):
        names = brand_names_for_profile({"product_name": "智齿客服"}, fallback="泉衡科技")
        self.assertEqual(names, ["智齿客服"])
        self.assertNotIn("泉衡科技", names)


if __name__ == "__main__":
    unittest.main()
