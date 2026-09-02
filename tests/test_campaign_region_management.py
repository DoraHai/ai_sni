import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/gsniper_test"
)
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "0123456789abcdef")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "123456")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00+00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.manage import CampaignRegionReq, set_campaign_region
from app.baidu.regions import ALL_REGIONS_ID, load_regions, region_ids
from app.baidu.services.campaign import CampaignService
from app.baidu.writeback import (
    WritebackError,
    _normalize_region_price_factor,
    _normalize_region_target,
    apply_campaign_region_writeback,
)
from app.security.auth import AuthContext


def test_region_snapshot_is_valid_and_contains_all_regions():
    rows = load_regions()

    assert len(rows) == 400
    assert ALL_REGIONS_ID in region_ids()
    assert len(region_ids()) == len(rows)


def test_normalize_region_target_deduplicates_known_ids():
    assert _normalize_region_target([1000, 4000, 1000]) == [1000, 4000]


@pytest.mark.parametrize("regions", [[], [True], [0], [123456789]])
def test_normalize_region_target_rejects_invalid_or_unknown_ids(regions):
    with pytest.raises(WritebackError):
        _normalize_region_target(regions)


def test_normalize_region_target_rejects_all_regions_mixed_with_city():
    with pytest.raises(WritebackError, match="全部区域"):
        _normalize_region_target([ALL_REGIONS_ID, 1000])


def test_normalize_region_factor_requires_selected_region():
    with pytest.raises(WritebackError, match="投放地域列表"):
        _normalize_region_price_factor(
            [{"regionId": 4000, "priceFactor": 0.8}],
            [1000],
        )


@pytest.mark.parametrize("factor", [0, 0.09, 1.01, True, "bad"])
def test_normalize_region_factor_rejects_invalid_factor(factor):
    with pytest.raises(WritebackError):
        _normalize_region_price_factor(
            [{"regionId": 1000, "priceFactor": factor}],
            [1000],
        )


def test_campaign_service_writes_only_region_fields():
    client = AsyncMock()
    client.call.return_value = {"data": []}

    asyncio.run(
        CampaignService(client).update_campaign_region(
            12,
            [1000, 4000],
            region_price_factor=[{"regionId": 1000, "priceFactor": 0.8}],
            geo_location_status=1,
        )
    )

    client.call.assert_awaited_once_with(
        "CampaignService",
        "updateCampaign",
        {
            "campaignTypes": [
                {
                    "campaignId": 12,
                    "regionTarget": [1000, 4000],
                    "regionPriceFactor": [{"regionId": 1000, "priceFactor": 0.8}],
                    "geoLocationStatus": 1,
                }
            ]
        },
        is_write=True,
        write_scope="campaign_region",
    )


def test_region_writeback_uses_campaign_baidu_account_and_clears_factors():
    session = AsyncMock()
    session.add = Mock()
    campaign = SimpleNamespace(
        baidu_account_id=88,
        campaign_id=12,
        campaign_name="品牌计划",
        region_target=[4000],
        region_price_factor=[{"regionId": 4000, "priceFactor": 0.7}],
        geo_location_status=0,
    )
    session.scalar.return_value = campaign
    account = SimpleNamespace(id=88)
    active_account = AsyncMock(return_value=account)
    update_region = AsyncMock(return_value={"data": []})

    async def run():
        with (
            patch("app.baidu.writeback._active_account", active_account),
            patch("app.baidu.writeback._account_client", return_value=object()),
            patch(
                "app.baidu.writeback.get_settings",
                return_value=SimpleNamespace(
                    baidu_write_dry_run=False,
                    baidu_write_is_dry_run=lambda tenant_id, account_id, scope: False,
                ),
            ),
            patch("app.baidu.writeback.CampaignService.update_campaign_region", update_region),
        ):
            return await apply_campaign_region_writeback(
                session,
                7,
                12,
                [1000],
                [],
                1,
                operator_user_id=3,
                operator_name="tester",
            )

    record = asyncio.run(run())

    active_account.assert_awaited_once_with(session, 7, 88)
    update_region.assert_awaited_once_with(
        12,
        [1000],
        region_price_factor=[],
        geo_location_status=1,
    )
    assert record.baidu_account_id == 88
    assert record.status == "success"
    assert campaign.region_target == [1000]
    assert campaign.region_price_factor == []
    assert campaign.geo_location_status == 1


def test_region_writeback_rejects_campaign_without_account():
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(
        baidu_account_id=None,
        campaign_id=12,
        campaign_name="未归属计划",
        region_target=[],
        region_price_factor=[],
        geo_location_status=None,
    )

    async def run():
        await apply_campaign_region_writeback(
            session,
            7,
            12,
            [1000],
            [],
            0,
            operator_user_id=3,
            operator_name="tester",
        )

    with pytest.raises(WritebackError, match="缺少所属百度账户"):
        asyncio.run(run())


def test_region_api_returns_verified_baidu_account_context():
    request = CampaignRegionReq(
        tenant_id=7,
        campaign_id=12,
        region_target=[1000],
        region_price_factor=[],
        geo_location_status=1,
    )
    context = AuthContext(
        user_id=3,
        username="tester",
        role_name="operator",
        tenant_id=7,
    )
    record = SimpleNamespace(
        status="dry_run",
        dry_run=True,
        baidu_account_id=88,
        error_msg=None,
    )
    apply_region = AsyncMock(return_value=record)

    async def run():
        with patch("app.api.manage.apply_campaign_region_writeback", apply_region):
            return await set_campaign_region(request, context, AsyncMock())

    result = asyncio.run(run())

    assert result["baidu_account_id"] == 88
    assert result["campaign_id"] == 12
    assert result["region_count"] == 1
    apply_region.assert_awaited_once()
