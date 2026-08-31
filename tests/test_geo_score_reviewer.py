"""P2 GEO Score + P3 AI Reviewer helpers."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from app.geo.content.ai_reviewer import (
    reviewer_blocks_publish,
    run_ai_review,
    _normalize_issues,
)
from app.geo.content import geo_score as geo_score_module
from app.geo.content.geo_score import compute_geo_score, score_blocks_ready
from app.geo.content.rules import RuleInput
from app.security.auth import _required


def _rule(
    *,
    title="选型指南",
    body=None,
    outline=None,
    facts=None,
    question="数据分析平台哪个好用",
):
    if body is None:
        body = (
            "## 定义\n数据分析平台用于企业自助分析。\n\n"
            "## 对比\n可对照 Tableau 与 PowerBI。\n\n"
            "## FAQ\n- Q: 是否私有化？\n  A: 支持私有化（来源：白皮书）。\n"
            "- Q: 有案例吗？\n  A: 有制造行业案例（来源：案例集）。\n\n"
            "## 结论\n综合事实，适合需要私有化的买家。\n更新时间：2026-08-05\n"
        )
    if outline is None:
        outline = {
            "direct_answer": "针对数据分析平台选型，可优先看私有化与开放 API 能力。",
            "sections": [
                {"type": "definition", "heading": "定义", "body": "数据分析平台用于企业自助分析。"},
                {
                    "type": "comparison",
                    "heading": "对比",
                    "body": "可对照 Tableau 与 PowerBI。",
                },
                {
                    "type": "faq",
                    "heading": "FAQ",
                    "items": [
                        {"q": "是否私有化？", "a": "支持私有化（来源：白皮书）"},
                        {"q": "有案例吗？", "a": "有制造行业案例（来源：案例集）"},
                    ],
                },
                {"type": "conclusion", "heading": "结论", "body": "适合需要私有化的买家。"},
            ],
            "updated_at": "2026-08-05",
        }
    if facts is None:
        facts = [
            {
                "id": 1,
                "title": "私有化",
                "statement": "支持私有化部署",
                "source_name": "白皮书",
                "source_url": "https://example.com/wp",
                "trust_level": "verified",
            },
            {
                "id": 2,
                "title": "API",
                "statement": "开放接口",
                "source_name": "文档",
                "trust_level": "verified",
            },
            {
                "id": 3,
                "title": "案例",
                "statement": "制造行业案例",
                "source_name": "案例集",
                "trust_level": "verified",
            },
        ]
    return RuleInput(
        question=question,
        title=title,
        body_markdown=body,
        outline=outline,
        facts=facts,
        target_channels=["website"],
        variants=["website"],
    )


class GeoScoreTests(unittest.TestCase):
    def test_strong_draft_scores_high(self):
        ri = _rule()
        brief = {
            "industry": "SaaS",
            "audience": "运营",
            "intent": "recommend",
            "content_type": "answer_guide",
            "cta": "预约",
            "competitors": ["Tableau", "PowerBI"],
            "info_gaps": ["comparison", "customer_case"],
            "must_cover": ["私有化"],
        }
        out = compute_geo_score(ri, brief=brief, lint_ok=True)
        self.assertGreaterEqual(out["geo_score"], 55)
        self.assertIn("structure", out["geo_subscores"])
        self.assertIsInstance(out["geo_actions"], list)

    def test_ungrounded_lint_caps_score(self):
        out = compute_geo_score(_rule(), brief={}, lint_ok=False)
        self.assertLessEqual(out["geo_score"], 59)
        self.assertTrue(any(a["code"] == "geo_evidence_ungrounded" for a in out["geo_actions"]))

    def test_weak_draft_scores_lower(self):
        ri = _rule(
            title="稿",
            body="随便写一点。",
            outline={"direct_answer": "", "sections": []},
            facts=[],
        )
        weak = compute_geo_score(ri, brief={}, lint_ok=False)
        strong = compute_geo_score(_rule(), brief={
            "industry": "SaaS",
            "audience": "a",
            "intent": "recommend",
            "content_type": "answer_guide",
            "cta": "c",
            "competitors": ["Tableau"],
        }, lint_ok=True)
        self.assertLess(weak["geo_score"], strong["geo_score"])
        self.assertTrue(weak["geo_actions"])

    def test_score_gate(self):
        ok, _ = score_blocks_ready({"geo_score": 70}, threshold=60, gate_enabled=True)
        self.assertTrue(ok)
        bad, msg = score_blocks_ready({"geo_score": 40}, threshold=60, gate_enabled=True)
        self.assertFalse(bad)
        self.assertIn("40", msg)
        ok2, _ = score_blocks_ready({"geo_score": 10}, threshold=60, gate_enabled=False)
        self.assertTrue(ok2)

    def test_channel_draft_gate_always_requires_a_passing_score(self):
        self.assertTrue(hasattr(geo_score_module, "channel_draft_score_gate"))
        gate = geo_score_module.channel_draft_score_gate

        ok, msg = gate({}, threshold=60)
        self.assertFalse(ok)
        self.assertIn("先完成 GEO 评分", msg)

        ok, msg = gate({"geo_score": 59}, threshold=60)
        self.assertFalse(ok)
        self.assertIn("当前 59 分", msg)

        ok, msg = gate({"geo_score": 60}, threshold=60)
        self.assertTrue(ok)
        self.assertEqual(msg, "")


class AiReviewerTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_issues(self):
        issues = _normalize_issues(
            [
                {
                    "category": "exaggeration",
                    "severity": "block",
                    "quote": "第一名",
                    "message": "夸大排名",
                    "fix_hint": "删除绝对表述",
                },
                {"category": "tone", "severity": "warn", "message": "语气偏硬"},
                {"message": ""},
            ]
        )
        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0]["severity"], "block")

    def test_reviewer_gate(self):
        ok, _ = reviewer_blocks_publish(
            {"issues": [{"severity": "block", "message": "矛盾"}]},
            gate_enabled=False,
        )
        self.assertTrue(ok)
        bad, msg = reviewer_blocks_publish(
            {"issues": [{"severity": "block", "message": "与事实矛盾"}]},
            gate_enabled=True,
        )
        self.assertFalse(bad)
        self.assertIn("矛盾", msg)

    async def test_run_ai_review_mock(self):
        chat = AsyncMock(
            return_value={
                "summary": "有一处夸大",
                "issues": [
                    {
                        "category": "exaggeration",
                        "severity": "warn",
                        "quote": "最好",
                        "message": "用词过满",
                        "fix_hint": "改为可核验表述",
                    }
                ],
            }
        )
        out = await run_ai_review(
            brand="Demo",
            question="哪个好",
            brief={"industry": "SaaS", "audience": "a", "intent": "recommend", "content_type": "answer_guide", "cta": "c"},
            rule_input=_rule(),
            llm={"api_key": "k", "base_url": "https://x", "model": "m", "provider": "dashscope"},
            chat_json=chat,
        )
        self.assertEqual(out["warn_count"], 1)
        self.assertEqual(out["block_count"], 0)
        self.assertTrue(out["issues"])


class AuthPathTests(unittest.TestCase):
    def test_ai_review_path(self):
        self.assertEqual(
            _required("/api/v1/geo/content-tasks/1/ai-review", "POST"),
            ({"geo.content"}, True),
        )


if __name__ == "__main__":
    unittest.main()
