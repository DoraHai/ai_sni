"""Social direct-publish connector unit tests."""

from __future__ import annotations

import unittest

from app.geo.content.connectors.social import (
    SOCIAL_PLATFORMS,
    SocialError,
    build_social_payload,
    normalize_social_credentials,
)


class SocialConnectorTests(unittest.TestCase):
    def test_platforms(self):
        self.assertIn("wechat", SOCIAL_PLATFORMS)
        self.assertIn("zhihu", SOCIAL_PLATFORMS)

    def test_normalize_ok(self):
        c = normalize_social_credentials(
            {
                "platform": "wechat",
                "api_url": "https://api.example.com/publish",
                "access_token": "tok-12345678",
            }
        )
        self.assertEqual(c["platform"], "wechat")
        self.assertEqual(c["method"], "POST")

    def test_normalize_requires_https(self):
        with self.assertRaises(SocialError):
            normalize_social_credentials(
                {
                    "platform": "wechat",
                    "api_url": "http://insecure.example.com",
                    "access_token": "tok",
                }
            )

    def test_build_wechat_payload(self):
        p = build_social_payload(
            platform="wechat",
            mode="draft",
            tenant_id=1,
            task_id=2,
            channel="wechat",
            title="标题",
            body_markdown="正文",
        )
        self.assertEqual(p["platform"], "wechat")
        self.assertIn("articles", p)
        self.assertEqual(p["articles"][0]["title"], "标题")


if __name__ == "__main__":
    unittest.main()
