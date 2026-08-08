"""GEO data cleanup API surface (archive/delete helpers)."""

from __future__ import annotations

import unittest

from app.geo.content.schemas import TaskUpdate


class TaskUpdateStatusTests(unittest.TestCase):
    def test_status_archived_allowed(self):
        u = TaskUpdate(status="archived")
        self.assertEqual(u.status, "archived")

    def test_status_optional(self):
        u = TaskUpdate(title="x")
        self.assertIsNone(u.status)


if __name__ == "__main__":
    unittest.main()
