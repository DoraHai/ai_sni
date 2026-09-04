"""Regression coverage for the 2026-09-02 SEM backend review findings."""

from __future__ import annotations

import asyncio
import inspect
import os
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.keywords import _bid_coefficients
from app.baidu.oauth import BaiduOAuthError, persist_authorization
from app.baidu.writeback import apply_account_budget_writeback
from app.rules.engine import _upsert_entity_alerts, _upsert_keyword_alerts
from app.scheduler import start_scheduler


def _campaign(*, schedule: list[dict], region: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        campaign_id=1,
        campaign_name="campaign",
        schedule_price_factors=schedule,
        region_price_factor=region,
        price_ratio=None,
    )


def test_region_only_bid_factor_uses_neutral_schedule_factor():
    result = _bid_coefficients(
        10.0,
        _campaign(schedule=[], region=[{"priceFactor": 1.5}]),
        None,
    )

    assert result["effective"] == {
        "current_min": 15.0,
        "current_max": 15.0,
        "max_multiplier": 1.5,
    }


def test_schedule_only_bid_factor_uses_neutral_region_factor():
    now = datetime(2026, 9, 2, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    current_time_id = now.isoweekday() * 100 + now.hour
    with patch("app.api.keywords.datetime") as clock:
        clock.now.return_value = now
        result = _bid_coefficients(
            10.0,
            _campaign(
                schedule=[{"timeId": current_time_id, "priceFactor": 1.2}],
                region=[],
            ),
            None,
        )

    assert result["effective"] == {
        "current_min": 12.0,
        "current_max": 12.0,
        "max_multiplier": 1.2,
    }


def test_configured_schedule_keeps_non_serving_slot_empty():
    now = datetime(2026, 9, 2, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    current_time_id = now.isoweekday() * 100 + now.hour
    other_time_id = 101 if current_time_id != 101 else 102
    with patch("app.api.keywords.datetime") as clock:
        clock.now.return_value = now
        result = _bid_coefficients(
            10.0,
            _campaign(
                schedule=[{"timeId": other_time_id, "priceFactor": 1.2}],
                region=[{"priceFactor": 1.5}],
            ),
            None,
        )

    assert result["effective"] is None


def test_account_budget_reconciliation_guard_is_account_scoped():
    source = inspect.getsource(apply_account_budget_writeback)
    guard = source[
        source.index("_ensure_no_unresolved_funds_writeback") :
        source.index("_claim_funds_approval")
    ]

    assert "WritebackAction.baidu_account_id == acc.id" in guard


def test_site_health_probe_is_registered_once_daily():
    with (
        patch("app.scheduler._acquire_scheduler_lock", return_value=True),
        patch("app.scheduler.scheduler.add_job") as add_job,
        patch("app.scheduler.scheduler.start"),
    ):
        start_scheduler()

    probe_call = next(
        call for call in add_job.call_args_list
        if call.kwargs.get("id") == "probe_site_health_alerts"
    )
    trigger = str(probe_call.args[1])
    assert "hour='4'" in trigger
    assert "minute='20'" in trigger


@pytest.mark.parametrize("upsert", [_upsert_keyword_alerts, _upsert_entity_alerts])
def test_alert_upsert_refreshes_priority_and_reopens_status(upsert):
    record = {
        "tenant_id": 1,
        "rule_code": "test_rule",
        "priority": "P1",
        "title": "title",
        "message": "message",
        "report_date": date(2026, 9, 2),
        "keyword_id": 1 if upsert is _upsert_keyword_alerts else None,
        "keyword": "keyword" if upsert is _upsert_keyword_alerts else None,
        "campaign_id": None,
        "campaign_name": None,
        "entity_ref": None if upsert is _upsert_keyword_alerts else "url:test",
        "metrics": {},
        "status": "open",
    }
    session = SimpleNamespace(execute=AsyncMock())

    asyncio.run(upsert(session, [record]))

    statement = session.execute.await_args.args[0]
    updated_fields = {
        field for field, _value in statement._post_values_clause.update_values_to_set
    }
    assert "priority" in updated_fields
    assert "status" in updated_fields


def test_oauth_empty_account_result_has_explicit_error():
    with pytest.raises(BaiduOAuthError, match="未返回可授权的推广账户") as exc:
        asyncio.run(
            persist_authorization(
                AsyncMock(),
                oauth_user_id=1,
                token_data={
                    "accessToken": "access-token",
                    "refreshToken": "refresh-token",
                    "openId": "open-id",
                },
                master={
                    "master_ucid": 1,
                    "master_name": "master",
                    "account_type": 1,
                },
                accounts=[],
            )
        )

    assert exc.value.code == "no_accounts"
