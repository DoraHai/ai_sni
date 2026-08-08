"""GEO Wave A 流水线步骤单测。"""

import unittest

from app.geo.content.pipeline import derive_pipeline_step, sync_pipeline_fields


class _Task:
    status = "draft"
    pipeline_step = "opportunity"
    blocked_reason = None


class GeoPipelineTests(unittest.TestCase):
    def test_opportunity_when_empty(self):
        self.assertEqual(derive_pipeline_step("draft", 0, False, 0), "opportunity")

    def test_evidence_when_facts_bound(self):
        self.assertEqual(derive_pipeline_step("facts_bound", 3, False, 0), "evidence")

    def test_draft_when_has_article(self):
        self.assertEqual(derive_pipeline_step("editing", 3, True, 0), "draft")

    def test_adapt_when_variants(self):
        self.assertEqual(derive_pipeline_step("ready", 3, True, 2), "adapt")

    def test_publish_when_published(self):
        self.assertEqual(derive_pipeline_step("published", 3, True, 2), "publish")

    def test_sync_sets_fields(self):
        task = _Task()
        task.status = "needs_fix"
        sync_pipeline_fields(task, fact_count=3, has_article=True, variant_count=0, blocked_reason="faq_min")
        self.assertEqual(task.pipeline_step, "draft")
        self.assertEqual(task.blocked_reason, "faq_min")


if __name__ == "__main__":
    unittest.main()
