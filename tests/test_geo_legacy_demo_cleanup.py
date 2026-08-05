"""Regression coverage for legacy local demo records with corrupted text."""

import unittest

from app.geo.content.legacy_demo_cleanup import (
    clean_legacy_demo_fact,
    clean_legacy_demo_fact_statement,
    clean_legacy_demo_task,
)


class LegacyDemoCleanupTests(unittest.TestCase):
    def test_replaces_only_the_known_corrupted_task_placeholder(self):
        self.assertEqual(
            clean_legacy_demo_task("[???] ????????", 4),
            "历史演示内容任务 4",
        )
        self.assertEqual(clean_legacy_demo_task("正常内容任务", 4), "正常内容任务")

    def test_replaces_only_the_known_corrupted_demo_fact_placeholder(self):
        self.assertEqual(
            clean_legacy_demo_fact("????2", "demo-source-2"),
            "历史演示事实 2",
        )
        self.assertEqual(clean_legacy_demo_fact("????2", "客户来源"), "????2")

    def test_replaces_only_the_known_corrupted_demo_fact_statement(self):
        self.assertEqual(
            clean_legacy_demo_fact_statement("?????????? 3", "seed-3"),
            "历史演示数据，供本地界面测试使用。",
        )
        self.assertEqual(
            clean_legacy_demo_fact_statement("正常事实陈述", "seed-3"),
            "正常事实陈述",
        )


if __name__ == "__main__":
    unittest.main()
