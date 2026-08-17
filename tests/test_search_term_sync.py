import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.baidu.sync import (
    _merge_search_term_rows,
    _search_term_windows,
    sync_search_terms_for_account,
)


def test_search_term_windows_split_91_days_into_31_day_ranges():
    windows = _search_term_windows(date(2026, 5, 17), date(2026, 8, 15))

    assert windows == [
        (date(2026, 5, 17), date(2026, 6, 16)),
        (date(2026, 6, 17), date(2026, 7, 17)),
        (date(2026, 7, 18), date(2026, 8, 15)),
    ]


def test_search_term_windows_reject_inverted_dates():
    with pytest.raises(ValueError, match="开始日期"):
        _search_term_windows(date(2026, 8, 15), date(2026, 8, 14))


def test_merge_search_term_rows_aggregates_same_dimension_across_windows():
    rows = _merge_search_term_rows(
        [
            {
                "queryWord": "SEM 工具",
                "campaignId": "10",
                "adGroupId": "20",
                "campaignName": "旧计划名",
                "impression": "100",
                "click": "10",
                "cost": "20.0",
                "ocpcConversionsDetail2": "2",
            },
            {
                "queryWord": "SEM 工具",
                "campaignId": "10",
                "adGroupId": "20",
                "campaignName": "新计划名",
                "impression": "50",
                "click": "5",
                "cost": "15.0",
                "ocpcConversionsDetail2": "1",
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["campaignName"] == "新计划名"
    assert rows[0]["impression"] == 150
    assert rows[0]["click"] == 15
    assert rows[0]["cost"] == 35.0
    assert rows[0]["ocpcConversionsDetail2"] == 3
    assert rows[0]["cpc"] == pytest.approx(35 / 15)
    assert rows[0]["ctr"] == pytest.approx(10.0)
    assert rows[0]["ocpcConversionsDetail2CVR"] == pytest.approx(20.0)


def test_sync_search_terms_keeps_old_snapshot_when_all_windows_are_empty():
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), add_all=lambda rows: None)
    account = SimpleNamespace(tenant_id=1, baidu_username="masked")

    with patch("app.baidu.sync._fetch_search_term_rows", new=AsyncMock(return_value=[])) as fetch:
        result = asyncio.run(
            sync_search_terms_for_account(session, account, date(2026, 5, 17), date(2026, 8, 15))
        )

    assert result == 0
    assert fetch.await_count == 3
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_sync_search_terms_replaces_snapshot_once_after_non_empty_fetch():
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), add_all=lambda rows: None)
    account = SimpleNamespace(tenant_id=1, baidu_username="masked", id=1)
    row = {
        "queryWord": "SEM 工具",
        "queryStatusName": "未添加",
        "campaignId": "10",
        "adGroupId": "20",
        "impression": "10",
        "click": "1",
        "cost": "2.0",
        "ocpcConversionsDetail2": "0",
    }

    with patch("app.baidu.sync._fetch_search_term_rows", new=AsyncMock(return_value=[row])) as fetch:
        result = asyncio.run(
            sync_search_terms_for_account(session, account, date(2026, 5, 17), date(2026, 8, 15))
        )

    assert result == 1
    assert fetch.await_count == 3
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
