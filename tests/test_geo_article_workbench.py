import unittest

from app.geo.content.channel_strategy import fold_publication_rows, task_engine_keys, task_geo_score


class ArticleWorkbenchSummaryTests(unittest.TestCase):
    def test_list_summary_shape(self):
        row = {
            "geo_score": task_geo_score({"geo_score": 82}),
            "publication_channels": fold_publication_rows([(9, "wechat", 1)])[9]["channels"],
            "publication_count": fold_publication_rows([(9, "wechat", 1)])[9]["count"],
            "engine_keys": task_engine_keys({"engines": ["deepseek", "doubao"]}, None),
        }
        self.assertEqual(row["geo_score"], 82)
        self.assertEqual(row["publication_channels"], ["wechat"])
        self.assertEqual(row["publication_count"], 1)
        self.assertEqual(row["engine_keys"], ["deepseek", "doubao"])


if __name__ == "__main__":
    unittest.main()
