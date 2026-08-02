import unittest
from unittest.mock import AsyncMock

from app.geo.ai_sampling import (
    build_neutral_questions,
    clean_questions,
    detect_brand_mentions,
    run_deepseek_sample,
)


class GeoAISamplingTests(unittest.IsolatedAsyncioTestCase):
    def test_neutral_questions_remove_brand_terms(self):
        questions = build_neutral_questions(
            industry="工业制造",
            core_products=["示例品牌工业泵"],
            audience_segments=["设备负责人"],
            brand_terms=["示例品牌"],
        )
        self.assertEqual(len(questions), 3)
        self.assertTrue(all("示例品牌" not in question for question in questions))

    def test_custom_questions_reject_brand_injection(self):
        with self.assertRaises(ValueError):
            clean_questions(["示例品牌工业泵怎么样？"], ["示例品牌"])

    def test_deterministic_mention_detection(self):
        response = "可以比较 Alpha Pumps、示例 品牌和其他供应商。"
        self.assertEqual(
            detect_brand_mentions(response, ["示例品牌", "Example Brand"]),
            ["示例品牌"],
        )

    async def test_sample_uses_raw_responses_and_programmatic_rate(self):
        chat = AsyncMock(
            side_effect=[
                "推荐示例品牌与 Alpha Pumps。参考 https://example.org/a",
                "可以比较 Alpha Pumps 与 Beta Pumps。",
                "示例 品牌在该领域也值得关注。",
            ]
        )
        sample = await run_deepseek_sample(
            questions=["问题一？", "问题二？", "问题三？"],
            brand_terms=["示例品牌"],
            model="deepseek-chat",
            chat=chat,
        )
        self.assertEqual(sample["mention_count"], 2)
        self.assertEqual(sample["mention_rate"], 0.6667)
        self.assertEqual(sample["results"][0]["source_urls"], ["https://example.org/a"])
        self.assertIn("Alpha Pumps", sample["results"][1]["response"])
        self.assertEqual(chat.await_count, 3)


if __name__ == "__main__":
    unittest.main()
