from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.seo_rank_limits import (
    ManualRankLimitError,
    manual_rank_status,
    reserve_manual_rank_collection,
)


def test_manual_collection_reservation_enforces_cooldown(tmp_path: Path) -> None:
    state_path = tmp_path / "limits.json"
    now = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
    reserved = reserve_manual_rank_collection(
        1,
        2,
        3,
        cooldown_seconds=3600,
        max_requests_per_day=100,
        state_path=state_path,
        now=now,
    )
    assert reserved["allowed"] is False
    assert reserved["retry_after_seconds"] == 3600
    assert reserved["daily_requests_used"] == 3

    with pytest.raises(ManualRankLimitError) as exc:
        reserve_manual_rank_collection(
            1,
            2,
            3,
            cooldown_seconds=3600,
            max_requests_per_day=100,
            state_path=state_path,
            now=now + timedelta(minutes=10),
        )
    assert exc.value.code == "collection_cooldown"
    assert exc.value.retry_after == 3000


def test_manual_collection_status_reopens_after_cooldown(tmp_path: Path) -> None:
    state_path = tmp_path / "limits.json"
    now = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
    reserve_manual_rank_collection(
        7,
        9,
        2,
        cooldown_seconds=60,
        max_requests_per_day=5,
        state_path=state_path,
        now=now,
    )
    status = manual_rank_status(
        7,
        9,
        cooldown_seconds=60,
        max_requests_per_day=5,
        state_path=state_path,
        now=now + timedelta(seconds=61),
    )
    assert status["allowed"] is True
    assert status["daily_requests_used"] == 2


def test_manual_collection_enforces_daily_provider_request_budget(tmp_path: Path) -> None:
    state_path = tmp_path / "limits.json"
    now = datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)
    reserve_manual_rank_collection(
        1,
        1,
        4,
        cooldown_seconds=1,
        max_requests_per_day=5,
        state_path=state_path,
        now=now,
    )
    with pytest.raises(ManualRankLimitError) as exc:
        reserve_manual_rank_collection(
            1,
            1,
            2,
            cooldown_seconds=1,
            max_requests_per_day=5,
            state_path=state_path,
            now=now + timedelta(seconds=2),
        )
    assert exc.value.code == "daily_request_limit"
