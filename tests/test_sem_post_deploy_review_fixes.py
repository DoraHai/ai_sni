import inspect
import os
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.operations import _change, _over_limit_clause, list_operation_records
from app.baidu import BaiduAPIError
from app.baidu.sync import (
    _legacy_operation_record_dedup_key,
    _operation_record_dedup_key,
    sync_operation_records_for_account,
)
from app.main import sync_operation_records
from app.models import OperationRecord
from app.security.auth import _required


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def test_manual_operation_sync_processes_every_active_account_and_reports_partial():
    async def scenario():
        accounts = [SimpleNamespace(id=11), SimpleNamespace(id=12)]
        session = SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(id=3)),
            scalars=AsyncMock(return_value=_Rows(accounts)),
        )
        sync = AsyncMock(side_effect=[4, BaiduAPIError(89403, "token expired")])

        with patch("app.main.sync_operation_records_for_account", new=sync):
            result = await sync_operation_records(
                tenant_id=3,
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 3),
                session=session,
            )

        assert sync.await_count == 2
        assert [call.args[1].id for call in sync.await_args_list] == [11, 12]
        assert result["status"] == "partial"
        assert result["records_fetched"] == 4
        assert result["accounts_total"] == 2
        assert result["accounts_succeeded"] == 1
        assert result["account_failures"][0]["baidu_account_id"] == 12

    asyncio.run(scenario())


def test_manual_operation_sync_reports_error_when_every_account_fails():
    async def scenario():
        accounts = [SimpleNamespace(id=11), SimpleNamespace(id=12)]
        session = SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(id=3)),
            scalars=AsyncMock(return_value=_Rows(accounts)),
        )
        sync = AsyncMock(side_effect=[
            BaiduAPIError(89403, "token expired"),
            BaiduAPIError(89403, "token expired"),
        ])

        with patch("app.main.sync_operation_records_for_account", new=sync):
            result = await sync_operation_records(
                tenant_id=3,
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 3),
                session=session,
            )

        assert result["status"] == "error"
        assert result["accounts_succeeded"] == 0
        assert result["accounts_total"] == 2
        assert len(result["account_failures"]) == 2

    asyncio.run(scenario())


def test_operation_record_dedup_is_scoped_to_the_baidu_account():
    fields = ("2026-09-03T10:00:00", "5", "4", "bidPriceWord", "keyword")

    assert _operation_record_dedup_key(11, fields) == _operation_record_dedup_key(11, fields)
    assert _operation_record_dedup_key(11, fields) != _operation_record_dedup_key(12, fields)
    assert _legacy_operation_record_dedup_key(fields) not in {
        _operation_record_dedup_key(11, fields),
        _operation_record_dedup_key(12, fields),
    }


def test_operation_sync_skips_same_account_legacy_rows_without_hiding_other_accounts():
    async def scenario(existing_keys):
        raw = [{
            "optTime": "Sep 03, 2026 10:00:00 AM",
            "optLevel": 5,
            "optType": 4,
            "optContent": "bidPriceWord",
            "optObj": "keyword",
            "oldValue": "13.28",
            "newValue": "13.27",
            "planId": 21,
            "unitId": 22,
        }]
        account = SimpleNamespace(id=11, tenant_id=3, baidu_username="account-a")
        session = SimpleNamespace(
            scalars=AsyncMock(return_value=_Rows(existing_keys)),
            execute=AsyncMock(),
            commit=AsyncMock(),
        )
        toolkit = SimpleNamespace(get_operation_records=AsyncMock(return_value=raw))
        with (
            patch("app.baidu.sync._account_client", return_value=object()),
            patch("app.baidu.sync.ToolkitService", return_value=toolkit),
        ):
            result = await sync_operation_records_for_account(
                session, account, date(2026, 9, 3), date(2026, 9, 3)
            )
        return result, session

    fields = (
        "2026-09-03T10:00:00", "5", "4", "bidPriceWord", "keyword",
        "13.28", "13.27", "21", "22",
    )
    legacy_key = _legacy_operation_record_dedup_key(fields)

    skipped, existing_session = asyncio.run(scenario([legacy_key]))
    inserted, new_account_session = asyncio.run(scenario([]))

    assert skipped == 0
    existing_session.execute.assert_not_awaited()
    existing_session.commit.assert_not_awaited()
    assert inserted == 1
    new_account_session.execute.assert_awaited_once()
    new_account_session.commit.assert_awaited_once()


def test_over_limit_filter_uses_safe_database_numeric_casts_and_database_paging():
    statement = select(OperationRecord).where(_over_limit_clause())
    sql = str(statement.compile(dialect=postgresql.dialect()))
    source = inspect.getsource(list_operation_records)

    assert "CASE WHEN" in sql
    assert " ~ " in sql
    assert "nullif" in sql.lower()
    assert ".offset(" in source
    assert ".limit(" in source
    assert "OperationRecord.id.desc()" in source
    assert "rows_all" not in source


def test_over_limit_display_rounding_does_not_hide_a_raw_limit_breach():
    change = _change("100", "120.04")

    assert change == {"pct": 20.0, "over_limit": True}


def test_writeback_mode_is_available_to_the_keyword_workspace_permission():
    assert _required("/api/v1/writeback/mode", "GET") == (
        {"optimize.keywords", "verify.adjustments"},
        False,
    )
