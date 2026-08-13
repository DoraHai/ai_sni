"""GEO onboarding pure helpers (no network)."""

import unittest

from app.geo.content.monitoring_stance import (
    compose_stance_banner,
    normalize_stance,
    stance_payload,
)
from app.geo.content.onboarding import (
    _business_candidates,
    _fact_drafts,
    _host_brand,
    build_readiness_items,
)


class OnboardingHelpersTests(unittest.TestCase):
    def test_host_brand(self):
        self.assertEqual(_host_brand("https://www.acme.com/products"), "acme")
        self.assertEqual(_host_brand("https://blog.foo.com.cn/a"), "foo")

    def test_business_candidates(self):
        c = _business_candidates("智能泵 | 苏尔寿", ["离心泵", "分离"], "")
        names = [x["name"] for x in c]
        self.assertTrue(any("智能泵" in n or "苏尔寿" in n for n in names))
        self.assertTrue(any(x.get("selected") for x in c))

    def test_fact_drafts(self):
        d = _fact_drafts(
            title="Acme 官网",
            text="我们是工业泵领导品牌。离心泵适用于化工场景。登录注册下载。",
            url="https://acme.com",
            words=["离心泵", "化工"],
            brand="acme",
        )
        self.assertGreaterEqual(len(d), 1)
        self.assertEqual(d[0]["trust_level"], "needs_review")

    def test_readiness_empty_not_ready(self):
        r = build_readiness_items(
            has_brand_terms=False,
            business_count=0,
            prompt_count=0,
            fact_count=0,
            verified_fact_count=0,
            engine_count=0,
            real_engine_count=0,
            ai_key_configured=False,
            patrol_enabled=False,
            channel_count=0,
        )
        self.assertFalse(r["ready"])
        self.assertIn("businesses", r["blocking"])
        self.assertIn("prompts", r["blocking"])
        self.assertEqual(r["ready_count"], 0)

    def test_readiness_full_ready(self):
        r = build_readiness_items(
            has_brand_terms=True,
            business_count=1,
            prompt_count=5,
            fact_count=4,
            verified_fact_count=3,
            engine_count=2,
            real_engine_count=1,
            ai_key_configured=True,
            patrol_enabled=True,
            channel_count=1,
            stance="hybrid",
        )
        self.assertTrue(r["ready"])
        self.assertEqual(r["ready_count"], r["total"])

    def test_readiness_simulation_skips_engine_keys(self):
        r = build_readiness_items(
            has_brand_terms=True,
            business_count=1,
            prompt_count=1,
            fact_count=3,
            verified_fact_count=3,
            engine_count=1,
            real_engine_count=0,
            ai_key_configured=True,
            patrol_enabled=True,
            channel_count=1,
            stance="simulation",
        )
        keys = {i["key"]: i["ok"] for i in r["items"]}
        self.assertTrue(keys["engine_keys"])


class StanceTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_stance(None), "hybrid")
        self.assertEqual(normalize_stance("real_only"), "real_only")
        self.assertEqual(normalize_stance("bogus"), "hybrid")

    def test_banner(self):
        b = compose_stance_banner(
            "hybrid",
            simulated_share=0.8,
            real_ready_engines=0,
            enabled_engines=3,
        )
        self.assertEqual(b["key"], "hybrid")
        self.assertTrue(b["messages"])
        self.assertIn("模拟", " ".join(b["messages"]))

    def test_stance_payload(self):
        p = stance_payload("simulation")
        self.assertFalse(p["deliverable_ok"])


if __name__ == "__main__":
    unittest.main()
