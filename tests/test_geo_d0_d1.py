"""D0 prompt taxonomy + visibility split; D1 CN blueprint helpers."""

import unittest

from app.geo.content.cn_blueprint import (
    CHANNELS_CN,
    blueprint_payload,
    default_media_placement_rows,
    recommend_channels_for_group,
)
from app.geo.content.prompt_taxonomy import (
    brand_in_question,
    resolve_is_brand_probe,
)
from app.geo.content.snapshots import split_visibility_metrics, visibility_mention_rate


class PromptTaxonomyTests(unittest.TestCase):
    def test_brand_in_question(self):
        self.assertTrue(brand_in_question("GrowthSniper 怎么样", ["GrowthSniper", "获客"]))
        self.assertFalse(brand_in_question("数据分析平台哪个好用", ["GrowthSniper"]))

    def test_resolve_probe_from_group(self):
        self.assertTrue(
            resolve_is_brand_probe(
                question="随便",
                brand_names=[],
                question_group="品牌验证",
            )
        )
        self.assertFalse(
            resolve_is_brand_probe(
                question="数据分析平台哪个好用",
                brand_names=["GrowthSniper"],
                question_group="推荐",
            )
        )


class VisibilitySplitTests(unittest.TestCase):
    def test_probe_excluded_from_visibility_rate(self):
        rows = [
            {"mentions_brand": True, "is_brand_probe": True},
            {"mentions_brand": True, "is_brand_probe": True},
            {"mentions_brand": False, "is_brand_probe": False},
            {"mentions_brand": True, "is_brand_probe": False},
        ]
        split = split_visibility_metrics(rows)
        self.assertEqual(split["snapshots_visibility"], 2)
        self.assertEqual(split["snapshots_visibility_mention"], 1)
        self.assertEqual(split["visibility_mention_rate"], 0.5)
        self.assertEqual(split["probe_recognition_rate"], 1.0)

    def test_unmeasured_is_none_not_zero(self):
        self.assertIsNone(visibility_mention_rate(total_snapshots=0, mention_snapshots=0))
        only_probe = split_visibility_metrics(
            [{"mentions_brand": True, "is_brand_probe": True}]
        )
        self.assertIsNone(only_probe["visibility_mention_rate"])
        self.assertEqual(only_probe["probe_recognition_rate"], 1.0)


class CnBlueprintTests(unittest.TestCase):
    def test_seed_rows_cover_p0_p1(self):
        rows = default_media_placement_rows(1)
        self.assertGreaterEqual(len(rows), 8)
        keys = {r["channel_key"] for r in rows}
        self.assertIn("official", keys)
        self.assertIn("ranking", keys)
        official = next(r for r in rows if r["channel_key"] == "official")
        self.assertEqual(official["priority_band"], "P0")
        self.assertIn("1.37%", official["authority_note"])

    def test_recommend_for_recommend_group(self):
        items = recommend_channels_for_group("推荐")
        keys = [i["channel_key"] for i in items]
        self.assertIn("official", keys)
        self.assertIn("ranking", keys)
        self.assertIn("zhihu", keys)
        self.assertNotIn("quark", keys)  # quark has empty fits

    def test_blueprint_payload(self):
        data = blueprint_payload(group="比较")
        self.assertEqual(data["group"], "比较")
        self.assertTrue(data["group_plan"])
        self.assertEqual(len(data["all_channels"]), len(CHANNELS_CN))


if __name__ == "__main__":
    unittest.main()
