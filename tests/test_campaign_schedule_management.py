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

from app.baidu.services.campaign import CampaignService
from app.api.manage import list_campaigns_budget
from app.baidu.writeback import (
    WritebackError,
    _normalize_schedule_price_factors,
    apply_campaign_schedule_writeback,
)


def test_normalize_schedule_orders_slots_and_defaults_factor():
    assert _normalize_schedule_price_factors(
        [{"timeId": 209}, {"timeId": 108, "priceFactor": 1.2}]
    ) == [
        {"timeId": 108, "priceFactor": 1.2},
        {"timeId": 209, "priceFactor": 1.0},
    ]


@pytest.mark.parametrize("item", [
    {"timeId": 0},
    {"timeId": 124},
    {"timeId": 800},
    {"timeId": 100, "priceFactor": 0},
])
def test_normalize_schedule_rejects_invalid_slots(item):
    with pytest.raises(WritebackError):
        _normalize_schedule_price_factors([item])


def test_normalize_schedule_rejects_duplicate_slot():
    with pytest.raises(WritebackError, match="重复"):
        _normalize_schedule_price_factors([{"timeId": 109}, {"timeId": 109}])


def test_campaign_service_writes_only_schedule_fields():
    client = AsyncMock()
    client.call.return_value = {"data": []}
    service = CampaignService(client)

    asyncio.run(service.update_campaign_schedule(12, [{"timeId": 109, "priceFactor": 1.0}]))

    client.call.assert_awaited_once_with(
        "CampaignService",
        "updateCampaign",
        {"campaignTypes": [{
            "campaignId": 12,
            "schedulePriceFactors": [{"timeId": 109, "priceFactor": 1.0}],
        }]},
        is_write=True,
        write_scope="campaign_schedule",
    )


def test_campaign_service_holiday_pause_template():
    client = AsyncMock()
    client.call.return_value = {"data": []}

    asyncio.run(CampaignService(client).update_campaign_schedule(12, [], pause=True))

    payload = client.call.await_args.args[2]
    assert payload == {"campaignTypes": [{
        "campaignId": 12,
        "schedulePriceFactors": [],
        "pause": True,
    }]}


def test_schedule_writeback_uses_campaign_baidu_account():
    session = AsyncMock()
    session.add = Mock()
    campaign = SimpleNamespace(
        baidu_account_id=88,
        campaign_id=12,
        campaign_name="品牌计划",
        schedule_price_factors=[],
        pause=False,
    )
    session.scalar.return_value = campaign
    account = SimpleNamespace(id=88)
    active_account = AsyncMock(return_value=account)
    update_schedule = AsyncMock(return_value={"data": []})

    async def run():
        with (
            patch("app.baidu.writeback._active_account", active_account),
            patch("app.baidu.writeback._account_client", return_value=object()),
            patch("app.baidu.writeback.get_settings", return_value=SimpleNamespace(baidu_write_dry_run=True)),
            patch("app.baidu.writeback.CampaignService.update_campaign_schedule", update_schedule),
        ):
            return await apply_campaign_schedule_writeback(
                session,
                7,
                12,
                [{"timeId": 109, "priceFactor": 1}],
                operator_user_id=3,
                operator_name="tester",
            )

    record = asyncio.run(run())

    active_account.assert_awaited_once_with(session, 7, 88)
    assert record.baidu_account_id == 88
    assert record.status == "dry_run"


def test_schedule_writeback_rejects_campaign_without_account():
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(
        baidu_account_id=None,
        campaign_id=12,
        campaign_name="未归属计划",
        schedule_price_factors=[],
        pause=False,
    )

    async def run():
        await apply_campaign_schedule_writeback(
            session,
            7,
            12,
            [{"timeId": 109, "priceFactor": 1}],
            operator_user_id=3,
            operator_name="tester",
        )

    with pytest.raises(WritebackError, match="缺少所属百度账户"):
        asyncio.run(run())


def test_campaign_list_returns_account_context():
    campaign = SimpleNamespace(
        campaign_id=12,
        campaign_name="品牌计划",
        baidu_account_id=88,
        budget=None,
        pause=False,
        status=21,
        region_target=[],
        region_price_factor=[],
        geo_location_status=None,
        schedule_price_factors=[{"timeId": 109, "priceFactor": 1}],
        synced_at=None,
    )
    account = SimpleNamespace(id=88, baidu_username="推广账户 A", status="active")
    campaign_result = Mock()
    campaign_result.all.return_value = [campaign]
    account_result = Mock()
    account_result.all.return_value = [account]
    session = AsyncMock()
    session.scalars.side_effect = [campaign_result, account_result]

    result = asyncio.run(list_campaigns_budget(7, 88, session))

    assert result["campaigns"][0]["baidu_account_id"] == 88
    assert result["campaigns"][0]["baidu_account_name"] == "推广账户 A"
    assert result["accounts"] == [{"id": 88, "name": "推广账户 A", "status": "active"}]
