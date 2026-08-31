"""GEO deterministic article optimization tests."""

import unittest
from unittest.mock import AsyncMock

from app.geo.content.routes import _ai_rewrite_optimize, _deterministic_rule_optimize, router
from app.geo.content.rules import RuleInput
from app.geo.content.schemas import ArticleOptimizeRequest


def _rule_input(body_markdown: str) -> RuleInput:
    return RuleInput(
        question="How should a team choose a platform?",
        title="Platform selection",
        body_markdown=body_markdown,
        outline={},
        facts=[
            {"id": 1, "statement": "Supports private deployment", "source_name": "Guide", "trust_level": "verified", "status": "active"},
            {"id": 2, "statement": "Includes audit logs", "source_name": "Guide", "trust_level": "verified", "status": "active"},
            {"id": 3, "statement": "Has role-based access", "source_name": "Guide", "trust_level": "verified", "status": "active"},
        ],
        target_channels=["website"],
        variants=[],
    )


class GeoArticleOptimizeTests(unittest.TestCase):
    def test_schema_requires_section_name_for_section_scope(self):
        request = ArticleOptimizeRequest(tenant_id=1, scope="section", section="Introduction")
        self.assertEqual(request.scope, "section")
        with self.assertRaises(ValueError):
            ArticleOptimizeRequest(tenant_id=1, scope="section")

    def test_all_scope_applies_real_rule_patches(self):
        original = "Direct answer: start with verified requirements.\n"
        result = _deterministic_rule_optimize(_rule_input(original), scope="all")

        self.assertNotEqual(result["body_markdown"], original)
        self.assertIn("faq_min", result["applied_codes"])
        self.assertIn("## FAQ", result["body_markdown"])

    def test_section_scope_changes_only_selected_markdown_section(self):
        original = "## Introduction\n\nDirect answer: start with verified requirements.\n\n## Keep\n\nThis text stays.\n"
        result = _deterministic_rule_optimize(
            _rule_input(original), scope="section", section="Introduction"
        )

        self.assertIn("## Keep\n\nThis text stays.", result["body_markdown"])
        self.assertNotEqual(result["body_markdown"], original)

    def test_optimize_route_is_registered(self):
        methods_by_path = {route.path: route.methods for route in router.routes}
        self.assertIn("POST", methods_by_path["/content-tasks/{task_id}/optimize"])

    def test_ai_rewrite_uses_model_body_without_inventing_facts(self):
        original = "## Introduction\n\nDirect answer: start with verified requirements.\n"
        rewritten = "## Introduction\n\nDirect answer: Supports private deployment for audited teams.\n"

        async def _run():
            chat = AsyncMock(return_value={"body_markdown": rewritten})
            return await _ai_rewrite_optimize(
                _rule_input(original),
                scope="all",
                section=None,
                brand="Acme",
                question="How should a team choose a platform?",
                llm={"model": "test"},
                chat_json=chat,
            )

        import asyncio

        result = asyncio.run(_run())
        self.assertEqual(result["source"], "ai_rewrite_optimize")
        self.assertIn("private deployment", result["body_markdown"])
        self.assertIn("ai_rewrite", result["applied_codes"])


if __name__ == "__main__":
    unittest.main()
