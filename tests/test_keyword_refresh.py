import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.baidu.sync import sync_keyword_dimension_reports_for_account
from app.scheduler import (
    _SHANGHAI_TZ,
    _chunks,
    _local_day_start_utc,
    refresh_keyword_workbench_snapshot,
)
from app.security.auth import _required


class KeywordRefreshTests(unittest.IsolatedAsyncioTestCase):
    def test_seo_rank_scheduler_chunks_all_keywords(self):
        self.assertEqual(_chunks([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(_chunks([1, 2], 0), [[1], [2]])

    def test_seo_rank_scheduler_uses_shanghai_natural_day(self):
        local_now = datetime(2026, 8, 16, 2, 0, tzinfo=_SHANGHAI_TZ)
        self.assertEqual(
            _local_day_start_utc(local_now),
            datetime(2026, 8, 15, 16, 0),
        )

    async def test_dimension_reports_use_chunked_upserts(self):
        svc = SimpleNamespace(
            get_keyword_region_report=AsyncMock(
                return_value=[{"id": i} for i in range(1700)]
            ),
            get_keyword_hourly_report=AsyncMock(
                return_value=[{"id": i} for i in range(400)]
            ),
        )
        chunked = AsyncMock()
        account = SimpleNamespace(
            id=5,
            tenant_id=9,
            baidu_username="large-account",
            access_token_encrypted="encrypted",
        )
        with (
            patch("app.baidu.sync.BaiduAPIClient"),
            patch("app.baidu.sync.decrypt", return_value="token"),
            patch("app.baidu.sync.ReportService", return_value=svc),
            patch(
                "app.baidu.sync._row_to_region_record",
                side_effect=lambda row, *_: {"keyword_id": row["id"]},
            ),
            patch(
                "app.baidu.sync._row_to_hourly_record",
                side_effect=lambda row, *_: {"keyword_id": row["id"]},
            ),
            patch("app.baidu.sync._chunked_upsert", new=chunked),
        ):
            result = await sync_keyword_dimension_reports_for_account(
                object(), account, date(2026, 7, 31)
            )

        self.assertEqual(result, {"region": 1700, "hourly": 400})
        self.assertEqual(chunked.await_count, 2)
        self.assertEqual(
            chunked.await_args_list[0].args[3],
            "uq_kw_region_report_tenant_date_kw_region_device",
        )
        self.assertEqual(
            chunked.await_args_list[1].args[3],
            "uq_kw_hourly_report_tenant_dt_kw_device",
        )

    async def test_refresh_runs_report_structure_and_classification(self):
        session = object()
        tenant = SimpleNamespace(id=7)
        account = SimpleNamespace(tenant_id=7)
        lock_handle = object()

        with (
            patch("app.scheduler._acquire_tenant_sync_lock", return_value=lock_handle),
            patch("app.scheduler._release_tenant_sync_lock") as release_lock,
            patch(
                "app.scheduler.sync_keyword_report_for_account",
                new=AsyncMock(return_value=120),
            ),
            patch(
                "app.scheduler.sync_keyword_dimension_reports_for_account",
                new=AsyncMock(return_value={"region": 20, "hourly": 40}),
            ),
            patch(
                "app.scheduler.sync_campaigns_for_account",
                new=AsyncMock(return_value=12),
            ),
            patch(
                "app.scheduler.sync_adgroups_for_account",
                new=AsyncMock(return_value=84),
            ),
            patch(
                "app.scheduler.sync_keywords_for_account",
                new=AsyncMock(return_value=4757),
            ),
            patch(
                "app.scheduler.sync_price_strategies_for_account",
                new=AsyncMock(return_value=3),
            ),
            patch(
                "app.scheduler.reclassify_keywords",
                new=AsyncMock(return_value={"brand": 173}),
            ),
        ):
            result = await refresh_keyword_workbench_snapshot(
                session, tenant, account, date(2026, 7, 28)
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["keywords_synced"], 4757)
        self.assertEqual(result["date"], "2026-07-28")
        release_lock.assert_called_once_with(lock_handle)

    async def test_refresh_returns_busy_without_calling_baidu(self):
        report_sync = AsyncMock()
        with (
            patch("app.scheduler._acquire_tenant_sync_lock", return_value=None),
            patch("app.scheduler.sync_keyword_report_for_account", new=report_sync),
        ):
            result = await refresh_keyword_workbench_snapshot(
                object(),
                SimpleNamespace(id=7),
                SimpleNamespace(tenant_id=7),
                date(2026, 7, 28),
            )

        self.assertEqual(result, {"status": "busy", "tenant_id": 7})
        report_sync.assert_not_awaited()

    async def test_refresh_records_failed_sync_status(self):
        tenant = SimpleNamespace(id=7)
        account = SimpleNamespace(id=12, tenant_id=7)
        session = SimpleNamespace(
            commit=AsyncMock(),
            rollback=AsyncMock(),
            get=AsyncMock(return_value=account),
        )
        with (
            patch("app.scheduler._acquire_tenant_sync_lock", return_value=object()),
            patch("app.scheduler._release_tenant_sync_lock"),
            patch(
                "app.scheduler.sync_keyword_report_for_account",
                new=AsyncMock(side_effect=RuntimeError("region batch failed")),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "region batch failed"):
                await refresh_keyword_workbench_snapshot(
                    session, tenant, account, date(2026, 7, 31)
                )

        self.assertEqual(account.sync_status, "failed")
        self.assertEqual(account.last_sync_error, "region batch failed")
        session.rollback.assert_awaited_once()

    def test_manual_refresh_requires_keyword_edit_permission(self):
        self.assertEqual(
            _required("/api/v1/admin/refresh-keyword-workbench", "POST"),
            ({"optimize.keywords"}, True),
        )


if __name__ == "__main__":
    unittest.main()
