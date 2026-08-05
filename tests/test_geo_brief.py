"""Structured content brief for GEO generation."""

import unittest

from app.geo.content.brief import (
    brief_blockers,
    brief_ready,
    missing_required_fields,
    normalize_brief,
)
from app.geo.content.generate_article import generate_master_article
from app.geo.content.variants import GeoContentError
from app.security.auth import _required


def _eligible_facts():
    return [
        {"id": 1, "title": "部署", "statement": "支持私有化", "source_name": "白皮书", "trust_level": "verified", "status": "active"},
        {"id": 2, "title": "API", "statement": "开放接口", "source_name": "文档", "trust_level": "verified", "status": "active"},
        {"id": 3, "title": "行业", "statement": "服务制造", "source_name": "案例", "trust_level": "verified", "status": "active"},
    ]


class BriefNormalizeTests(unittest.TestCase):
    def test_normalize_and_ready(self):
        raw = {
            "industry": " 工业泵 ",
            "audience": "采购负责人",
            "intent": "compare",
            "content_type": "answer_guide",
            "cta": "预约演示",
            "banned_claims": "第一名, 保证收录",
        }
        brief = normalize_brief(raw)
        self.assertEqual(brief["industry"], "工业泵")
        self.assertEqual(brief["banned_claims"], ["第一名", "保证收录"])
        self.assertTrue(brief_ready(brief))
        self.assertEqual(missing_required_fields({}), ["industry", "audience", "intent", "content_type", "cta"])

    def test_blockers_message(self):
        ok, message, action = brief_blockers({"industry": "SaaS"})
        self.assertFalse(ok)
        self.assertIn("受众", message)
        self.assertIn("填写", action)


class GenerateBriefGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_requires_brief(self):
        with self.assertRaises(GeoContentError) as ctx:
            await generate_master_article(
                tenant_name="Demo",
                question="数据分析平台哪个好用",
                facts=_eligible_facts(),
                brief={},
            )
        self.assertIn("Brief", str(ctx.exception))

    async def test_generate_succeeds_with_brief(self):
        brief = {
            "industry": "B2B SaaS",
            "audience": "运营负责人",
            "intent": "recommend",
            "content_type": "answer_guide",
            "cta": "预约演示",
            "banned_claims": ["保证收录"],
        }
        payload = await generate_master_article(
            tenant_name="Demo",
            question="数据分析平台哪个好用",
            facts=_eligible_facts(),
            brief=brief,
        )
        self.assertEqual(payload["_brief"]["cta"], "预约演示")
        self.assertIn("Brief", payload.get("disclaimer") or "")


class AuthPathTests(unittest.TestCase):
    def test_brief_catalog_geo_content(self):
        self.assertEqual(
            _required("/api/v1/geo/content-brief-catalog", "GET"),
            ({"geo.content"}, False),
        )

    def test_v1_still_schema_version_1_without_strategy(self):
        brief = normalize_brief(
            {
                "industry": "SaaS",
                "audience": "运营",
                "intent": "recommend",
                "content_type": "answer_guide",
                "cta": "演示",
            }
        )
        self.assertEqual(brief["schema_version"], 1)
        self.assertEqual(brief.get("source_bar"), "any")


if __name__ == "__main__":
    unittest.main()
