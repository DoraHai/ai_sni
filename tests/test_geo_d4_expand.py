"""D4 expand candidates (GeoLook suggest → question bank)."""

import unittest
from unittest.mock import AsyncMock, patch

from app.geo.content.expand import (
    build_roots,
    classify_term,
    expand_candidates,
    is_relevant,
    to_question,
)
from app.security.auth import _required


class ClassifyTests(unittest.TestCase):
    def test_group_cues(self):
        self.assertEqual(classify_term("数据分析平台哪个好", "category"), "比较")
        self.assertEqual(classify_term("某某 替代", "brand"), "替代")
        self.assertEqual(classify_term("价格多少", "category"), "价格")
        self.assertEqual(classify_term("GrowthSniper怎么样", "brand"), "品牌验证")
        self.assertEqual(classify_term("工具推荐", "category"), "推荐")
        # 品类 + 怎么样 → 推荐（非品牌验证）
        self.assertEqual(classify_term("平台怎么样", "category"), "推荐")

    def test_relevant_filters_nav(self):
        self.assertFalse(is_relevant("某某官网下载", "某某"))
        self.assertTrue(is_relevant("数据分析平台推荐", "数据分析"))

    def test_to_question_template(self):
        q = to_question("数据分析平台", group="推荐", market="cn")
        self.assertIn("推荐", q)
        self.assertTrue(q.endswith("？") or "吗" in q)


class RootsTests(unittest.TestCase):
    def test_seed_from_brand_and_industry(self):
        roots = build_roots(
            brand_names=["GrowthSniper", "获客精灵"],
            industry="数据分析平台",
            competitors=["竞品甲"],
            market="cn",
        )
        kinds = {r["kind"] for r in roots}
        self.assertIn("brand", kinds)
        self.assertIn("category", kinds)
        self.assertIn("competitor", kinds)

    def test_explicit_roots_win(self):
        roots = build_roots(
            brand_names=["Ignored"],
            explicit_roots=[{"root": "工业泵", "kind": "category", "market": "cn"}],
        )
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["root"], "工业泵")


class ExpandFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_expand_with_stub_suggest(self):
        async def fake_suggest(query: str, market: str):
            if "推荐" in query:
                return ["数据分析平台推荐", "数据分析平台哪个好", "官网下载"]
            return ["数据分析平台", "数据分析软件"]

        roots = [{"root": "数据分析", "kind": "category", "market": "cn"}]
        out = await expand_candidates(
            roots=roots,
            existing_questions={"数据分析平台，有值得推荐的吗？"},
            suggest=fake_suggest,
            throttle_s=0,
            max_terms=40,
        )
        self.assertGreaterEqual(out["calls"], 1)
        self.assertGreater(out["total"], 0)
        terms = [i["term"] for i in out["items"]]
        self.assertNotIn("官网下载", terms)
        # template for 推荐 may mark in_bank
        self.assertTrue(any(i["question_group"] in {"推荐", "比较", "场景"} for i in out["items"]))


class AuthPathTests(unittest.TestCase):
    def test_expand_requires_geo_content(self):
        self.assertEqual(
            _required("/api/v1/geo/prompts/expand-candidates", "POST"),
            ({"geo.content"}, True),
        )
        self.assertEqual(
            _required("/api/v1/geo/prompts/promote-candidates", "POST"),
            ({"geo.content"}, True),
        )


if __name__ == "__main__":
    unittest.main()
