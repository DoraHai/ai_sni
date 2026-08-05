"""GEO publishing-channel registry rules."""

import unittest

from pydantic import ValidationError

from app.geo.content.channels import (
    CHANNEL_TYPE_OPTIONS,
    PUBLISH_MODE_OPTIONS,
    default_channel_rows,
    normalize_channel_type,
    normalize_publish_mode,
)
from app.geo.content.channel_registry import (
    channel_options_from_registry,
    filter_channels_by_registry,
    publication_publish_mode,
    publish_mode_for_channel,
    profile_key_for_registry_type,
)
from app.models import GeoChannelAccount, GeoPublishingChannel
from app.geo.content.schemas import ChannelAccountCreate, PublishingChannelCreate


class GeoChannelRegistryTests(unittest.TestCase):
    def test_b2b_channel_types_include_owned_and_external_sources(self):
        self.assertEqual(
            CHANNEL_TYPE_OPTIONS,
            (
                "website",
                "docs",
                "wechat",
                "zhihu",
                "baijiahao",
                "toutiao",
                "industry_media",
                "community_qa",
                "encyclopedia",
                "visual_content",
            ),
        )

    def test_publish_mode_normalizes_to_manual_when_unknown(self):
        self.assertEqual(PUBLISH_MODE_OPTIONS, ("auto_publish", "draft_then_manual", "manual_only"))
        self.assertEqual(normalize_publish_mode("AUTO_PUBLISH"), "auto_publish")
        self.assertEqual(normalize_publish_mode("unsupported"), "manual_only")

    def test_default_channels_prioritize_owned_b2b_properties(self):
        rows = default_channel_rows(7)
        self.assertEqual([row["channel_type"] for row in rows[:3]], ["website", "docs", "wechat"])
        self.assertEqual(rows[0]["tenant_id"], 7)
        self.assertEqual(rows[0]["publish_mode"], "auto_publish")
        self.assertEqual(rows[1]["publish_mode"], "auto_publish")
        self.assertEqual(rows[2]["publish_mode"], "draft_then_manual")

    def test_channel_type_normalizes_to_other_safe_mode(self):
        self.assertEqual(normalize_channel_type("Zhihu"), "zhihu")
        self.assertEqual(normalize_channel_type("unlisted"), "industry_media")

    def test_channel_and_account_keep_credentials_out_of_channel_records(self):
        self.assertEqual(GeoPublishingChannel.__tablename__, "geo_publishing_channels")
        self.assertEqual(GeoChannelAccount.__tablename__, "geo_channel_accounts")
        self.assertIn("publish_mode", GeoPublishingChannel.__table__.columns)
        self.assertIn("content_rules", GeoPublishingChannel.__table__.columns)
        self.assertNotIn("credentials_encrypted", GeoPublishingChannel.__table__.columns)
        self.assertIn("credentials_encrypted", GeoChannelAccount.__table__.columns)
        self.assertIn("channel_id", GeoChannelAccount.__table__.columns)

    def test_channel_create_rejects_unknown_type_and_mode(self):
        with self.assertRaises(ValidationError):
            PublishingChannelCreate(
                tenant_id=7,
                name="测试渠道",
                channel_type="unknown",
                publish_mode="unsupported",
            )

    def test_account_create_accepts_credentials_without_exposing_them_in_channel(self):
        account = ChannelAccountCreate(
            tenant_id=7,
            channel_id=12,
            display_name="官网 CMS",
            auth_type="api_key",
            credentials={"token": "secret"},
        )
        self.assertEqual(account.auth_type, "api_key")
        self.assertEqual(account.credentials, {"token": "secret"})

    def test_registry_maps_to_adapt_profiles(self):
        self.assertEqual(profile_key_for_registry_type("docs"), "website")
        self.assertEqual(profile_key_for_registry_type("industry_media"), "toutiao")
        rows = [
            {"id": 1, "name": "官网", "channel_type": "website", "publish_mode": "auto_publish", "enabled": True},
            {"id": 2, "name": "知乎", "channel_type": "zhihu", "publish_mode": "draft_then_manual", "enabled": True},
            {"id": 3, "name": "关", "channel_type": "toutiao", "publish_mode": "manual_only", "enabled": False},
        ]
        options = channel_options_from_registry(rows)
        keys = [o["adapt_key"] for o in options]
        self.assertEqual(keys, ["website", "zhihu"])
        # docs maps to website — second website-type row is skipped
        rows_docs = rows + [
            {"id": 4, "name": "文档", "channel_type": "docs", "publish_mode": "auto_publish", "enabled": True},
        ]
        self.assertEqual(
            [o["adapt_key"] for o in channel_options_from_registry(rows_docs)],
            ["website", "zhihu"],
        )
        self.assertEqual(
            filter_channels_by_registry(
                ["website", "zhihu", "toutiao", "baijiahao"],
                enabled_types={"website", "zhihu"},
            ),
            ["website", "zhihu"],
        )
        self.assertEqual(publish_mode_for_channel("website", rows), "auto_publish")
        self.assertEqual(publication_publish_mode("manual_only"), "manual_export")
        self.assertEqual(publication_publish_mode("auto_publish"), "auto_publish")


if __name__ == "__main__":
    unittest.main()
