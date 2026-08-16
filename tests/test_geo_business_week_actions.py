"""Business detail 'this week' action picker."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.geo.content.routes import _business_week_actions


class BusinessWeekActionsTests(unittest.TestCase):
    def test_picks_sla_review_and_retest(self):
        old = datetime.utcnow() - timedelta(days=20)
        gap = SimpleNamespace(
            id=11,
            question="哪家工业泵适合化工？",
            updated_at=old,
            created_at=old,
        )
        task = SimpleNamespace(
            id=22,
            title="化工泵选型稿",
            status="editing",
            review_status="pending",
        )
        pubs = [
            {
                "task_id": 33,
                "title": "已发官网文",
                "channel": "website",
            }
        ]
        with patch("app.config.get_settings", return_value=SimpleNamespace(geo_gap_sla_days=7)):
            actions = _business_week_actions(
                gaps=[gap],
                in_prod=[task],
                published=pubs,
                cite_hit_snaps=0,
            )
        kinds = [a["kind"] for a in actions]
        self.assertEqual(kinds, ["gap_sla", "review", "retest"])
        self.assertEqual(actions[0]["prompt_id"], 11)
        self.assertEqual(actions[1]["task_id"], 22)
        self.assertEqual(actions[2]["task_id"], 33)


if __name__ == "__main__":
    unittest.main()
