"""Single-current-draft behavior for the GEO editor."""

import unittest
from types import SimpleNamespace

from app.geo.content import routes


class GeoCurrentDraftTests(unittest.TestCase):
    def test_history_and_restore_routes_are_not_exposed(self):
        paths = {route.path for route in routes.router.routes}

        self.assertNotIn("/content-tasks/{task_id}/article-versions", paths)
        self.assertNotIn(
            "/content-tasks/{task_id}/article-versions/{version_id}/restore",
            paths,
        )

    def test_article_update_overwrites_the_same_current_row(self):
        overwrite = getattr(routes, "_overwrite_current_article", None)
        self.assertIsNotNone(overwrite, "current-draft overwrite helper is missing")
        article = SimpleNamespace(
            id=12,
            task_id=7,
            version_no=31,
            kind="master",
            title="Old title",
            body_markdown="Old body",
            body_html="<p>Old body</p>",
            outline={"sections": ["old"]},
            generation_meta={"source": "manual_edit"},
            author_name="Editor",
            created_by=2,
        )

        result = overwrite(
            article,
            title="Current title",
            body_markdown="Current body",
            outline={"sections": ["current"]},
            generation_meta={"source": "ai_rewrite"},
            created_by=9,
        )

        self.assertIs(result, article)
        self.assertEqual(article.id, 12)
        self.assertEqual(article.version_no, 1)
        self.assertEqual(article.title, "Current title")
        self.assertEqual(article.body_markdown, "Current body")
        self.assertEqual(article.outline, {"sections": ["current"]})
        self.assertEqual(article.generation_meta, {"source": "ai_rewrite"})
        self.assertEqual(article.created_by, 9)

    def test_upstream_edit_invalidates_score_review_and_channel_state(self):
        invalidate = getattr(routes, "_invalidate_current_draft", None)
        self.assertIsNotNone(invalidate, "current-draft invalidation helper is missing")
        task = SimpleNamespace(
            status="ready",
            rule_result={"geo_score": 88, "ai_review": {"issues": ["old"]}},
            ready_at="2026-08-30T09:00:00",
            review_status="approved",
            review_note="old review",
            review_submitted_by=3,
            reviewed_by=4,
            reviewed_at="2026-08-30T10:00:00",
        )

        invalidate(task)

        self.assertEqual(task.status, "editing")
        self.assertIsNone(task.rule_result)
        self.assertIsNone(task.ready_at)
        self.assertEqual(task.review_status, "none")
        self.assertIsNone(task.review_note)
        self.assertIsNone(task.review_submitted_by)
        self.assertIsNone(task.reviewed_by)
        self.assertIsNone(task.reviewed_at)

    def test_channel_gate_score_is_bound_to_current_article_content(self):
        fingerprint = getattr(routes, "_article_fingerprint", None)
        score_matches = getattr(routes, "_score_matches_current_article", None)
        self.assertIsNotNone(fingerprint, "article fingerprint helper is missing")
        self.assertIsNotNone(score_matches, "score binding helper is missing")
        article = SimpleNamespace(title="Current title", body_markdown="Current body")
        rule_result = {
            "geo_score": 82,
            "article_fingerprint": fingerprint(article),
        }

        self.assertTrue(score_matches(rule_result, article))
        article.body_markdown = "Edited after scoring"
        self.assertFalse(score_matches(rule_result, article))

    def test_old_channel_job_diagnostics_do_not_attach_to_the_current_draft(self):
        job_matches = getattr(routes, "_variant_job_matches_current_article", None)
        self.assertIsNotNone(job_matches, "variant job binding helper is missing")
        article = SimpleNamespace(title="Current title", body_markdown="Current body")
        job = SimpleNamespace(
            request_meta={"article_fingerprint": routes._article_fingerprint(article)}
        )

        self.assertTrue(job_matches(job, article))
        article.body_markdown = "New current body"
        self.assertFalse(job_matches(job, article))
        self.assertFalse(job_matches(SimpleNamespace(request_meta={}), article))


if __name__ == "__main__":
    unittest.main()
