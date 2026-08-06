"""Multi-media push target listing helpers."""

from __future__ import annotations

import unittest

from app.geo.content.multi_push import AUTO_PUSH_TYPES, account_push_kind, variant_key_for_channel


class MultiPushHelpersTests(unittest.TestCase):
    def test_auto_types_cover_media(self):
        for t in ("website", "docs", "wechat", "zhihu", "baijiahao", "toutiao"):
            self.assertIn(t, AUTO_PUSH_TYPES)

    def test_account_push_kind(self):
        self.assertEqual(account_push_kind("webhook", "website"), "webhook")
        self.assertEqual(account_push_kind("social_api", "wechat"), "social")
        self.assertIsNone(account_push_kind("manual", "wechat"))
        self.assertIsNone(account_push_kind("webhook", "wechat"))

    def test_variant_key(self):
        self.assertEqual(variant_key_for_channel("docs"), "website")
        self.assertEqual(variant_key_for_channel("wechat"), "wechat")


if __name__ == "__main__":
    unittest.main()
