import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api import manage
from app.baidu.services.campaign import CampaignService
from app.baidu.writeback import (
    WritebackError,
    _normalize_region_price_factor,
    _normalize_region_target,
)


class BaiduRegionCodeTests(unittest.IsolatedAsyncioTestCase):
    def test_region_resource_has_known_parent_relationships(self):
        manage._REGION_CACHE = None
        regions = manage._load_regions()
        by_id = {row["id"]: row for row in regions}

        self.assertEqual(len(regions), 400)
        self.assertEqual(by_id[4000], {"id": 4000, "name": "广东", "level": "province", "parent_id": None})
        self.assertEqual(by_id[4084]["parent_id"], 4000)
        self.assertEqual(by_id[9999999]["level"], "special")

    async def test_campaign_region_update_uses_only_region_fields(self):
        client = SimpleNamespace(call=AsyncMock(return_value={"data": []}))

        await CampaignService(client).update_campaign_region(
            1001,
            [4000, 4084],
            region_price_factor=[{"regionId": 4084, "priceFactor": 1.0}],
            geo_location_status=1,
        )

        client.call.assert_awaited_once_with(
            "CampaignService",
            "updateCampaign",
            {
                "campaignTypes": [
                    {
                        "campaignId": 1001,
                        "regionTarget": [4000, 4084],
                        "regionPriceFactor": [{"regionId": 4084, "priceFactor": 1.0}],
                        "geoLocationStatus": 1,
                    }
                ]
            },
            is_write=True,
        )

    def test_region_writeback_input_validation(self):
        self.assertEqual(_normalize_region_target([4000, 4084, 4084]), [4000, 4084])
        self.assertEqual(
            _normalize_region_price_factor(
                [{"regionId": 4084, "priceFactor": "1.0"}], [4000, 4084]
            ),
            [{"regionId": 4084, "priceFactor": 1.0}],
        )
        with self.assertRaisesRegex(WritebackError, "投放地域不能为空"):
            _normalize_region_target([])
        with self.assertRaisesRegex(WritebackError, "必须在投放地域列表中"):
            _normalize_region_price_factor(
                [{"regionId": 4093, "priceFactor": 1.0}], [4000, 4084]
            )
        with self.assertRaisesRegex(WritebackError, "0.1 到 1.0"):
            _normalize_region_price_factor(
                [{"regionId": 4084, "priceFactor": 1.5}], [4000, 4084]
            )

    async def test_campaign_region_api_maps_snake_case_contract(self):
        req = manage.CampaignRegionReq.model_validate(
            {
                "tenant_id": 1,
                "campaign_id": 1942121658,
                "region_target": [4000, 1000],
                "region_price_factor": [{"region_id": 4000, "price_factor": 0.9}],
                "geo_location_status": 1,
            }
        )
        ctx = SimpleNamespace(user_id=7, username="operator", ensure_tenant=Mock())
        rec = SimpleNamespace(status="dry_run", dry_run=True, error_msg=None)

        with patch(
            "app.api.manage.apply_campaign_region_writeback",
            new=AsyncMock(return_value=rec),
        ) as writeback:
            result = await manage.set_campaign_region(req, ctx, object())

        ctx.ensure_tenant.assert_called_once_with(1)
        self.assertEqual(result, {
            "status": "dry_run",
            "dry_run": True,
            "campaign_id": 1942121658,
            "region_count": 2,
            "error_msg": None,
        })
        self.assertEqual(
            writeback.await_args.kwargs["operator_name"], "operator"
        )
        self.assertEqual(
            writeback.await_args.args[4], [{"regionId": 4000, "priceFactor": 0.9}]
        )
        self.assertEqual(writeback.await_args.args[5], 1)

    async def test_campaign_list_includes_current_region_settings(self):
        campaign = SimpleNamespace(
            campaign_id=1001,
            campaign_name="测试计划",
            budget=100.0,
            pause=False,
            status=21,
            region_target=[4000, 4084],
            region_price_factor=[{"regionId": 4084, "priceFactor": 0.9}],
            geo_location_status=1,
            synced_at=None,
        )
        session = SimpleNamespace(
            scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [campaign]))
        )

        result = await manage.list_campaigns_budget(tenant_id=1, session=session)

        self.assertEqual(result["campaigns"][0]["region_target"], [4000, 4084])
        self.assertEqual(
            result["campaigns"][0]["region_price_factor"],
            [{"regionId": 4084, "priceFactor": 0.9}],
        )
        self.assertEqual(result["campaigns"][0]["geo_location_status"], 1)


if __name__ == "__main__":
    unittest.main()
