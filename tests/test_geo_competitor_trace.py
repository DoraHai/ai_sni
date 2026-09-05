"""Competitor source reverse-trace + manual report markdown."""

from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from app.geo.content.competitor_placements import (
    attach_geo_reverse,
    resolve_placement_profile,
)
from app.geo.content.competitor_trace import (
    build_competitor_compare,
    build_competitor_report_markdown,
    build_competitor_trace,
    snapshot_mentions_competitor,
)


class CompetitorTraceTests(unittest.TestCase):
    def test_mention_match_casefold(self):
        self.assertTrue(snapshot_mentions_competitor(["Tableau", "Power BI"], "tableau"))
        self.assertFalse(snapshot_mentions_competitor(["Tableau"], "Looker"))

    def test_trace_maps_zhihu_and_unknown(self):
        rows = [
            SimpleNamespace(
                id=1,
                competitors=["Tableau"],
                cited_urls=[
                    "https://zhuanlan.zhihu.com/p/123",
                    "https://obscure-example.test/a",
                ],
                engine="chatgpt",
                prompt_id=9,
                captured_at=datetime(2026, 8, 1, 12, 0, 0),
            ),
            SimpleNamespace(
                id=2,
                competitors=["OtherCo"],
                cited_urls=["https://zhuanlan.zhihu.com/p/999"],
                engine="deepseek",
                prompt_id=10,
                captured_at=datetime(2026, 8, 2, 12, 0, 0),
            ),
        ]
        trace = build_competitor_trace(
            competitor="Tableau",
            rows=rows,
            questions={9: "如何选型 BI？"},
        )
        self.assertEqual(trace["mention_count"], 1)
        self.assertEqual(trace["prompt_count"], 1)
        self.assertEqual(len(trace["sources"]), 2)
        self.assertEqual(trace["unique_url_count"], 2)
        self.assertEqual(len(trace["sources_agg"]), 2)
        keys = {p["channel_key"] for p in trace["platforms"]}
        self.assertIn("zhihu", keys)
        self.assertIn("other", keys)
        zhihu = next(p for p in trace["platforms"] if p["channel_key"] == "zhihu")
        self.assertGreaterEqual(zhihu["cite_count"], 1)
        self.assertTrue(
            any(s["prompt_question"] == "如何选型 BI？" for s in trace["sources"])
        )

    def test_report_contains_competitor_and_selected_url(self):
        rows = [
            SimpleNamespace(
                id=3,
                competitors=["Looker"],
                cited_urls=["https://www.zhihu.com/question/1"],
                engine="doubao",
                prompt_id=1,
                captured_at=datetime(2026, 8, 3, 8, 0, 0),
            ),
            SimpleNamespace(
                id=4,
                competitors=["Looker"],
                cited_urls=["https://www.zhihu.com/question/1"],
                engine="chatgpt",
                prompt_id=2,
                captured_at=datetime(2026, 8, 4, 8, 0, 0),
            ),
        ]
        trace = build_competitor_trace(competitor="Looker", rows=rows, questions={})
        self.assertEqual(trace["unique_url_count"], 1)
        self.assertEqual(trace["sources_agg"][0]["cite_count"], 2)
        report = build_competitor_report_markdown(
            competitor="Looker",
            trace=trace,
            source_urls=["https://www.zhihu.com/question/1"],
            platform_keys=["zhihu"],
            insight="知乎为主阵地。",
            action="补机构号长文。",
            note="重点关注知乎问答。",
            generated_at=datetime(2026, 8, 9, 10, 0, 0),
        )
        md = report["markdown"]
        self.assertIn("Looker", md)
        self.assertIn("https://www.zhihu.com/question/1", md)
        self.assertIn("知乎为主阵地", md)
        self.assertIn("补机构号长文", md)
        self.assertIn("重点关注知乎问答", md)
        self.assertIn("按 URL 去重", md)
        self.assertEqual(report["source_count"], 1)

    def test_compare_brand_vs_competitor(self):
        rows = [
            SimpleNamespace(
                prompt_id=1,
                engine="deepseek",
                mentions_brand=True,
                brand_position="first",
                competitors=["Tableau"],
            ),
            SimpleNamespace(
                prompt_id=1,
                engine="doubao",
                mentions_brand=False,
                brand_position="unknown",
                competitors=["Tableau"],
            ),
            SimpleNamespace(
                prompt_id=2,
                engine="deepseek",
                mentions_brand=True,
                brand_position="mentioned",
                competitors=[],
            ),
        ]
        for row in rows:
            row.sample_mode = 'openai_compat'
            row.note = 'method=unprimed_json_v2 analysis=completed'
        out = build_competitor_compare(
            rows=rows,
            questions={1: "如何选型 BI？", 2: "有哪些工具？"},
        )
        self.assertEqual(out["summary"]["prompt_count"], 2)
        by_id = {i["prompt_id"]: i for i in out["items"]}
        # Sparse observations must not declare either side the winner.
        self.assertEqual(by_id[1]["winner"], "insufficient")
        self.assertEqual(by_id[2]["winner"], "insufficient")
        self.assertEqual(by_id[1]["top_competitor"], "tableau")


class CompetitorPlacementTests(unittest.TestCase):
    def test_resolve_qiyu_aliases(self):
        self.assertEqual(resolve_placement_profile("网易七鱼")["canonical"], "网易七鱼")
        self.assertEqual(resolve_placement_profile("七鱼")["canonical"], "网易七鱼")
        self.assertEqual(resolve_placement_profile("Udesk")["canonical"], "Udesk")
        self.assertIsNone(resolve_placement_profile("不存在的品牌xyz"))

    def test_trace_without_urls_gets_inferred_and_recs(self):
        rows = [
            SimpleNamespace(
                id=11,
                competitors=["网易七鱼"],
                cited_urls=[],
                engine="deepseek",
                prompt_id=47,
                captured_at=datetime(2026, 8, 13, 15, 0, 0),
            ),
            SimpleNamespace(
                id=12,
                competitors=["网易七鱼"],
                cited_urls=[],
                engine="chatgpt",
                prompt_id=48,
                captured_at=datetime(2026, 8, 13, 15, 1, 0),
            ),
        ]
        trace = build_competitor_trace(
            competitor="网易七鱼",
            rows=rows,
            questions={47: "在线客服哪个好", 48: "在线客服对比怎么选"},
        )
        self.assertEqual(trace["unique_url_count"], 0)
        attach_geo_reverse(
            trace,
            competitor="网易七鱼",
            mention_prompt_ids=[47, 47, 48],
            questions={47: "在线客服哪个好", 48: "在线客服对比怎么选"},
            question_groups={47: "推荐", 48: "比较"},
        )
        self.assertTrue(trace["inferred_placements"])
        self.assertFalse(trace["platforms"])
        self.assertFalse(trace.get("sources_agg"))
        self.assertFalse(trace.get("has_real_citations"))
        recs = trace["recommendations"]
        self.assertGreaterEqual(len(recs), 2)
        self.assertTrue(any("对比" in (r["title"] + r["reason"]) for r in recs))
        self.assertTrue(trace["suggested_action"])


if __name__ == "__main__":
    unittest.main()
