import unittest
from types import SimpleNamespace

from app.geo.content import current_draft, routes


class GeoPublishSafetyTests(unittest.TestCase):
    def test_draft_delivery_never_marks_article_as_published(self):
        state_for_mode = getattr(routes, "_publication_state_for_mode", None)
        self.assertIsNotNone(state_for_mode, "publication mode state helper is missing")

        self.assertEqual(
            state_for_mode("draft"),
            {"publication_status": "draft", "variant_status": "draft", "task_published": False},
        )
        self.assertEqual(
            state_for_mode("publish"),
            {"publication_status": "published", "variant_status": "published", "task_published": True},
        )

    def test_published_task_cannot_overwrite_its_current_delivery_record(self):
        can_overwrite = getattr(current_draft, "can_overwrite_current_draft", None)
        self.assertIsNotNone(can_overwrite, "published-draft protection helper is missing")

        self.assertFalse(can_overwrite(SimpleNamespace(status="published")))
        self.assertTrue(can_overwrite(SimpleNamespace(status="ready")))


if __name__ == "__main__":
    unittest.main()
