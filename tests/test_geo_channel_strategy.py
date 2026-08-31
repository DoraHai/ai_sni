import unittest

from app.geo.content.channel_strategy import (
    fold_publication_rows,
    merge_geo_profile,
    task_engine_keys,
    task_geo_score,
)
from app.geo.content.schemas import GeoChannelProfile, PublishingChannelCreate


class ChannelStrategyTests(unittest.TestCase):
    def test_geo_profile_is_stored_inside_content_rules(self):
        profile = GeoChannelProfile(
            category="owned",
            source_role="品牌事实底座",
            citation_potential="high",
            geo_strategy="原创首发、Schema",
            adapted_engines=["deepseek", "doubao"],
        )
        rules = merge_geo_profile(None, None, profile.model_dump(), channel_type="website")
        self.assertEqual(rules["geo_profile"]["source_role"], "品牌事实底座")
        self.assertEqual(rules["citation_potential"], "高")
        self.assertEqual(rules["engines"], ["deepseek", "doubao"])

    def test_create_schema_accepts_geo_profile(self):
        req = PublishingChannelCreate(
            tenant_id=1,
            name="官网",
            channel_type="website",
            geo_profile={
                "category": "owned",
                "source_role": "品牌事实底座",
                "citation_potential": "high",
                "geo_strategy": "原创首发",
                "adapted_engines": ["kimi"],
            },
        )
        self.assertEqual(req.geo_profile.category, "owned")

    def test_fold_publication_rows_aggregates_without_n_plus_one(self):
        out = fold_publication_rows([(1, "wechat", 2), (1, "zhihu", 1), (2, "website", 1)])
        self.assertEqual(out[1]["channels"], ["wechat", "zhihu"])
        self.assertEqual(out[1]["count"], 3)
        self.assertEqual(out[2]["count"], 1)

    def test_task_list_summary_fields(self):
        self.assertEqual(task_geo_score({"geo_score": 82}), 82)
        self.assertEqual(task_engine_keys({"engines": ["deepseek", "doubao"]}, {}), ["deepseek", "doubao"])


if __name__ == "__main__":
    unittest.main()
