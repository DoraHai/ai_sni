import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.seo_rank_limits import (
    ManualRankLimitError,
    manual_rank_status,
    reserve_manual_rank_collection,
    settle_manual_rank_collection,
)


def _row() -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=1,
        id=2,
        site_settings={},
    )


def _limit_state(row: SimpleNamespace) -> dict:
    return row.site_settings["manual_rank_collection_limit"]


def _session(row: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        execute=AsyncMock(),
        scalar=AsyncMock(return_value=row),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )


def test_manual_collection_reservation_enforces_cooldown_and_busy_state() -> None:
    row = _row()
    session = _session(row)
    now = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
    reservation = asyncio.run(
        reserve_manual_rank_collection(
            session,
            1,
            2,
            3,
            cooldown_seconds=3600,
            max_requests_per_day=100,
            now=now,
        )
    )
    assert reservation.requested == 3
    assert reservation.status["collection_in_progress"] is True
    assert reservation.status["daily_requests_used"] == 0
    assert _limit_state(row)["reserved_requests"] == 3
    session.commit.assert_awaited_once()

    with pytest.raises(ManualRankLimitError) as exc:
        asyncio.run(
            reserve_manual_rank_collection(
                session,
                1,
                2,
                3,
                cooldown_seconds=3600,
                max_requests_per_day=100,
                now=now + timedelta(minutes=1),
            )
        )
    assert exc.value.code == "collection_busy"


def test_manual_collection_charges_only_successful_requests() -> None:
    row = _row()
    session = _session(row)
    now = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
    reservation = asyncio.run(
        reserve_manual_rank_collection(
            session,
            1,
            2,
            3,
            cooldown_seconds=60,
            max_requests_per_day=5,
            now=now,
        )
    )
    status = asyncio.run(
        settle_manual_rank_collection(
            session,
            1,
            2,
            reservation,
            2,
            cooldown_seconds=60,
            max_requests_per_day=5,
            now=now + timedelta(seconds=10),
        )
    )
    assert _limit_state(row)["daily_requests"] == 2
    assert "reservation_token" not in _limit_state(row)
    assert "reserved_requests" not in _limit_state(row)
    assert status["daily_requests_used"] == 2


def test_manual_collection_system_failure_does_not_charge_daily_quota() -> None:
    row = _row()
    session = _session(row)
    now = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
    reservation = asyncio.run(
        reserve_manual_rank_collection(
            session,
            1,
            2,
            4,
            cooldown_seconds=60,
            max_requests_per_day=5,
            now=now,
        )
    )
    status = asyncio.run(
        settle_manual_rank_collection(
            session,
            1,
            2,
            reservation,
            0,
            cooldown_seconds=60,
            max_requests_per_day=5,
            now=now + timedelta(seconds=10),
        )
    )
    assert _limit_state(row)["daily_requests"] == 0
    assert status["daily_requests_used"] == 0
    assert status["retry_after_seconds"] == 50


def test_manual_collection_status_reopens_after_cooldown() -> None:
    row = _row()
    row.site_settings = {
        "manual_rank_collection_limit": {
            "daily_date": "2026-08-24",
            "daily_requests": 2,
            "last_attempt_at": "2026-08-24T06:00:00",
        }
    }
    session = _session(row)
    status = asyncio.run(
        manual_rank_status(
            session,
            1,
            2,
            cooldown_seconds=60,
            max_requests_per_day=5,
            now=datetime(2026, 8, 24, 6, 1, 1, tzinfo=timezone.utc),
        )
    )
    assert status["allowed"] is True
    assert status["daily_requests_used"] == 2


def test_manual_collection_enforces_daily_success_budget() -> None:
    row = _row()
    row.site_settings = {
        "manual_rank_collection_limit": {
            "daily_date": "2026-08-24",
            "daily_requests": 4,
        }
    }
    session = _session(row)
    now = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
    with pytest.raises(ManualRankLimitError) as exc:
        asyncio.run(
            reserve_manual_rank_collection(
                session,
                1,
                2,
                2,
                cooldown_seconds=1,
                max_requests_per_day=5,
                now=now,
            )
        )
    assert exc.value.code == "daily_request_limit"
    session.rollback.assert_awaited_once()
