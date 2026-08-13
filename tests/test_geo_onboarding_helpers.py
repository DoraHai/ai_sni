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
    _title_brand,
    brand_tokens_for_onboarding,
    build_readiness_items,
    finalize_onboarding_prompts,
    match_prompt_business,
    onboarding_expand_roots,
    website_channel_name,
)


class OnboardingHelpersTests(unittest.TestCase):
    def test_host_brand(self):
        self.assertEqual(_host_brand("https://www.acme.com/products"), "acme")
        self.assertEqual(_host_brand("https://blog.foo.com.cn/a"), "foo")

    def test_website_channel_name_avoids_dup(self):
        self.assertEqual(website_channel_name(set()), "官网")
        self.assertEqual(website_channel_name({"官网"}, "zhichi.com"), "官网 · zhichi.com")
        self.assertEqual(
            website_channel_name({"官网", "官网 · zhichi.com"}, "zhichi.com"),
            "官网 · zhichi.com (2)",
        )

    def test_title_brand_prefers_cjk(self):
        self.assertEqual(_title_brand("智齿科技 | 智能客服"), "智齿科技")
        self.assertIsNone(_title_brand("Welcome | Home"))

    def test_onboarding_roots_skip_ascii_host(self):
        roots = onboarding_expand_roots(
            ["智能客服", "工单系统", "在线客服"],
            title="智齿科技 | 智能客服",
            url="https://www.zhichi.com/",
        )
        vals = [r["root"] for r in roots]
        self.assertNotIn("zhichi", vals)
        self.assertIn("智能客服", vals)
        self.assertTrue(any(r["kind"] == "category" for r in roots))

    def test_onboarding_roots_prefer_title_product(self):
        roots = onboarding_expand_roots(
            ["智齿科技", "官网", "智齿", "Agents", "渠道", "客户"],
            title="智齿科技-智齿客服｜AI Agent 驱动的新一代客户联络平台【官网】",
            url="https://www.zhichi.com/",
        )
        vals = [r["root"] for r in roots]
        self.assertIn("智能客服", vals)
        self.assertNotIn("zhichi", vals)
        self.assertNotIn("官网", vals)
        self.assertNotIn("Agents", vals)
        self.assertNotIn("智齿", vals)
        self.assertNotIn("渠道", vals)
        self.assertFalse(any(v.startswith("驱动") for v in vals))
        self.assertFalse(any("智齿" in v and r["kind"] == "category" for r, v in zip(roots, vals)))
        self.assertTrue(any(r["kind"] == "brand" and r["root"] == "智齿科技" for r in roots))

    def test_finalize_prompts_marks_probes_and_keeps_category(self):
        items = finalize_onboarding_prompts(
            [
                {
                    "question": "智齿科技怎么样？用过的说说实际体验。",
                    "question_group": "品牌验证",
                    "term": "智齿科技怎么样",
                    "root": "智齿科技",
                    "kind": "brand",
                },
                {
                    "question": "智能客服，有值得推荐的吗？",
                    "question_group": "推荐",
                    "term": "智能客服推荐",
                    "root": "智能客服",
                    "kind": "category",
                },
            ],
            words=["智能客服", "在线客服"],
            title="智齿科技-智齿客服｜智能客服",
            url="https://www.zhichi.com/",
            max_items=16,
        )
        qs = [i["question"] for i in items]
        self.assertTrue(any(i["is_brand_probe"] and "智齿" in i["question"] for i in items))
        self.assertTrue(any(not i["is_brand_probe"] and "智能客服" in i["question"] for i in items))
        self.assertTrue(any("智能客服" in q for q in qs))
        selected_vis = [i for i in items if i.get("selected") and not i["is_brand_probe"]]
        self.assertGreaterEqual(len(selected_vis), 1)

    def test_brand_tokens_include_short_form(self):
        toks = brand_tokens_for_onboarding("智齿科技 | 智能客服", "https://www.zhichi.com/")
        self.assertIn("智齿科技", toks)
        self.assertIn("智齿", toks)

    def test_business_candidates(self):
        c = _business_candidates("智能泵 | 苏尔寿", ["离心泵", "分离"], "")
        names = [x["name"] for x in c]
        self.assertTrue(any("智能泵" in n or "苏尔寿" in n for n in names))
        self.assertTrue(any(x.get("selected") for x in c))

    def test_business_candidates_skip_ai_fragment(self):
        c = _business_candidates(
            "智齿科技-智齿客服｜AI Agent 驱动的新一代客户联络平台",
            ["智齿"],
            "",
        )
        names = [x["name"] for x in c]
        self.assertNotIn("AI", names)
        self.assertNotIn("Agent", names)
        self.assertIn("智齿科技", names)

    def test_match_prompt_business(self):
        names = ["AI", "智齿科技", "智齿客服"]
        self.assertEqual(match_prompt_business("智齿客服怎么样", names), "智齿客服")
        self.assertEqual(match_prompt_business("随便问问", names), "智齿科技")

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
