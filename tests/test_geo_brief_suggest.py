"""P0 brief suggest + strategy fields; P1 fact retrieve heuristics."""

from __future__ import annotations

import unittest

from app.geo.content.brief import (
    catalog_payload,
    merge_brief,
    normalize_brief,
    strategy_richness,
    brief_strategy_block,
)
from app.geo.content.brief_suggest import suggest_brief_heuristic, suggest_brief_for_task
from app.geo.content.fact_retrieve import retrieve_facts, tokenize
from app.security.auth import _required


class BriefV2Tests(unittest.TestCase):
    def test_normalize_strategy_fields(self):
        b = normalize_brief(
            {
                "industry": "制造",
                "audience": "采购",
                "intent": "recommend",
                "content_type": "answer_guide",
                "cta": "预约",
                "ai_question": "国产机器人有哪些？",
                "info_gaps": ["行业定位", "comparison", "bogus_gap"],
                "competitors": ["A", "B"],
                "must_cover": ["我司"],
                "source_bar": "verified_only",
            }
        )
        self.assertEqual(b["schema_version"], 2)
        self.assertIn("comparison", b["info_gaps"])
        self.assertIn("industry_positioning", b["info_gaps"])
        self.assertNotIn("bogus_gap", b["info_gaps"])
        self.assertGreater(strategy_richness(b), 0.4)
        block = brief_strategy_block(b)
        self.assertIn("国产机器人", block)
        self.assertIn("对比对象", block)

    def test_catalog_has_v2(self):
        cat = catalog_payload()
        self.assertEqual(cat["schema_version"], 2)
        self.assertTrue(cat["info_gaps"])
        self.assertIn("ai_question", cat["strategy_fields"])

    def test_merge_preserves_filled(self):
        existing = normalize_brief(
            {
                "industry": "已填行业",
                "audience": "受众",
                "intent": "recommend",
                "content_type": "answer_guide",
                "cta": "CTA",
            }
        )
        sug = suggest_brief_heuristic(question="CDMO 企业有哪些", brand="Acme")
        merged = merge_brief(existing, sug, overwrite=False)
        self.assertEqual(merged["industry"], "已填行业")
        self.assertTrue(merged.get("ai_question") or merged.get("info_gaps"))


class SuggestHeuristicTests(unittest.IsolatedAsyncioTestCase):
    def test_recommend_question(self):
        b = suggest_brief_heuristic(
            question="中国有哪些优秀 CDMO 企业？", brand="苏尔寿"
        )
        self.assertEqual(b["intent"], "recommend")
        self.assertEqual(b["ai_question"], "中国有哪些优秀 CDMO 企业？")
        self.assertIn("comparison", b["info_gaps"])
        self.assertIn("苏尔寿", b["must_cover"])

    def test_compare_question(self):
        b = suggest_brief_heuristic(question="A 和 B 怎么对比选型", brand="X")
        self.assertEqual(b["intent"], "compare")
        self.assertEqual(b["content_type"], "comparison")

    async def test_suggest_for_task_merge(self):
        existing = {
            "industry": "固定行业",
            "audience": "固定受众",
            "intent": "recommend",
            "content_type": "answer_guide",
            "cta": "固定CTA",
        }
        out = await suggest_brief_for_task(
            question="数据分析平台哪个好用",
            brand="Demo",
            existing_brief=existing,
            overwrite=False,
            llm=None,
        )
        self.assertEqual(out["industry"], "固定行业")
        self.assertTrue(out.get("ai_question"))


class FactRetrieveTests(unittest.TestCase):
    def test_tokenize(self):
        toks = tokenize("国产 工业机器人 厂商 有哪些")
        self.assertTrue(any("机器人" in t or t == "机器人" for t in toks) or "工业" in toks)

    def test_tokenize_chinese_question_emits_grams_not_whole_sentence(self):
        q = "制造业企业如何选择支持私有化部署的数据分析平台？"
        toks = tokenize(q)
        self.assertTrue(len(toks) >= 3)
        self.assertTrue(any(len(t) <= 3 for t in toks))
        # whole sentence must not be the only token
        self.assertFalse(len(toks) == 1 and len(toks[0]) > 10)
        self.assertTrue(
            any(t in ("数据", "分析", "平台", "私有", "部署", "制造") for t in toks)
            or any("数据" in t for t in toks)
        )

    def test_retrieve_ranks_relevant(self):
        facts = [
            {
                "id": 1,
                "title": "机器人本体",
                "statement": "国产工业机器人负载 10kg",
                "source_name": "白皮书",
                "trust_level": "verified",
                "status": "active",
                "fact_type": "product",
            },
            {
                "id": 2,
                "title": "办公软件",
                "statement": "支持文档协作",
                "source_name": "官网",
                "trust_level": "verified",
                "status": "active",
                "fact_type": "product",
            },
            {
                "id": 3,
                "title": "其他",
                "statement": "无关内容",
                "source_name": "",
                "trust_level": "draft",
                "status": "active",
                "fact_type": "other",
            },
        ]
        result = retrieve_facts(
            facts,
            question="国产工业机器人厂商有哪些？",
            brief={
                "industry": "制造",
                "audience": "采购",
                "intent": "recommend",
                "content_type": "answer_guide",
                "cta": "x",
                "must_cover": ["机器人"],
            },
            limit=5,
            verified_only=False,
        )
        ids = [i["fact_id"] for i in result["items"]]
        self.assertIn(1, ids)
        self.assertEqual(ids[0], 1)
        self.assertTrue(result["query_meta"]["tokens"])

    def test_verified_only(self):
        facts = [
            {
                "id": 1,
                "title": "机器人",
                "statement": "国产机器人",
                "source_name": "a",
                "trust_level": "draft",
                "status": "active",
                "fact_type": "product",
            },
            {
                "id": 2,
                "title": "机器人已核验",
                "statement": "国产工业机器人",
                "source_name": "b",
                "trust_level": "verified",
                "status": "active",
                "fact_type": "product",
            },
        ]
        result = retrieve_facts(
            facts, question="国产机器人", brief=None, limit=5, verified_only=True
        )
        ids = [i["fact_id"] for i in result["items"]]
        self.assertEqual(ids, [2])


class AuthPathTests(unittest.TestCase):
    def test_suggest_brief_requires_edit(self):
        self.assertEqual(
            _required("/api/v1/geo/content-tasks/1/suggest-brief", "POST"),
            ({"geo.content"}, True),
        )

    def test_retrieve_facts_requires_edit(self):
        self.assertEqual(
            _required("/api/v1/geo/content-tasks/1/retrieve-facts", "POST"),
            ({"geo.content"}, True),
        )


if __name__ == "__main__":
    unittest.main()
