import os
import unittest
from datetime import date
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

from app.baidu.sync import (
    _chunked_upsert,
    _safe_upsert_chunk_size,
    sync_keyword_dimension_reports_for_account,
    sync_keyword_report_range_for_account,
)
from app.models import KwReportSnapshot
from app.scheduler import refresh_keyword_workbench_snapshot
from app.security.auth import _required


class KeywordRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_keyword_history_range_preserves_each_row_date(self):
        svc = SimpleNamespace(
            get_keyword_report=AsyncMock(
                return_value=[
                    {"date": "2026-07-01", "wInfoId": 11, "device": 0},
                    {"date": "2026-07-02", "wInfoId": 12, "device": 1},
                ]
            )
        )
        session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        account = SimpleNamespace(
            id=5,
            tenant_id=9,
            baidu_username="history-account",
            access_token_encrypted="encrypted",
        )

        with (
            patch("app.baidu.sync.BaiduAPIClient"),
            patch("app.baidu.sync.decrypt", return_value="token"),
            patch("app.baidu.sync.ReportService", return_value=svc),
        ):
            result = await sync_keyword_report_range_for_account(
                session, account, date(2026, 7, 1), date(2026, 7, 2)
            )

        self.assertEqual(result, 2)
        values = session.execute.await_args.args[0].compile().params
        self.assertIn(date(2026, 7, 1), values.values())
        self.assertIn(date(2026, 7, 2), values.values())
        svc.get_keyword_report.assert_awaited_once_with(
            start_date="2026-07-01", end_date="2026-07-02"
        )

    async def test_keyword_history_range_uses_chunked_upsert(self):
        svc = SimpleNamespace(
            get_keyword_report=AsyncMock(
                return_value=[
                    {"date": "2026-07-01", "wInfoId": i, "device": 0}
                    for i in range(1200)
                ]
            )
        )
        chunked = AsyncMock()
        account = SimpleNamespace(
            id=5,
            tenant_id=9,
            baidu_username="large-history-account",
            access_token_encrypted="encrypted",
        )

        with (
            patch("app.baidu.sync.BaiduAPIClient"),
            patch("app.baidu.sync.decrypt", return_value="token"),
            patch("app.baidu.sync.ReportService", return_value=svc),
            patch("app.baidu.sync._chunked_upsert", new=chunked),
        ):
            result = await sync_keyword_report_range_for_account(
                object(), account, date(2026, 7, 1), date(2026, 7, 1)
            )

        self.assertEqual(result, 1200)
        chunked.assert_awaited_once()
        self.assertEqual(len(chunked.await_args.args[2]), 1200)
        self.assertEqual(
            chunked.await_args.args[3], "uq_kw_report_tenant_date_kw_device"
        )
        self.assertIn("fetched_at", chunked.await_args.kwargs["update_keys"])
        self.assertNotIn("keyword", chunked.await_args.kwargs["update_keys"])

    async def test_chunked_upsert_respects_bind_parameter_budget(self):
        records = [
            {
                "tenant_id": 9,
                "report_date": date(2026, 7, 1),
                "keyword_id": i,
                "device": 0,
                "click": i,
            }
            for i in range(5)
        ]
        session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())

        with patch("app.baidu.sync.UPSERT_BIND_PARAM_BUDGET", 16):
            self.assertEqual(_safe_upsert_chunk_size(KwReportSnapshot, records), 2)
            await _chunked_upsert(
                session,
                KwReportSnapshot,
                records,
                "uq_kw_report_tenant_date_kw_device",
                {"tenant_id", "report_date", "keyword_id", "device"},
            )

        self.assertEqual(session.execute.await_count, 3)
        self.assertTrue(
            all(
                len(call.args[0].compile().params) <= 16
                for call in session.execute.await_args_list
            )
        )
        session.commit.assert_awaited_once()

    async def test_keyword_history_range_fails_closed_when_dates_are_missing(self):
        svc = SimpleNamespace(
            get_keyword_report=AsyncMock(
                return_value=[{"wInfoId": 11, "device": 0}]
            )
        )
        session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        account = SimpleNamespace(
            id=5,
            tenant_id=9,
            baidu_username="history-account",
            access_token_encrypted="encrypted",
        )

        with (
            patch("app.baidu.sync.BaiduAPIClient"),
            patch("app.baidu.sync.decrypt", return_value="token"),
            patch("app.baidu.sync.ReportService", return_value=svc),
        ):
            with self.assertRaisesRegex(ValueError, "缺少有效日期"):
                await sync_keyword_report_range_for_account(
                    session, account, date(2026, 7, 1), date(2026, 7, 2)
                )

        session.execute.assert_not_awaited()

    async def test_keyword_history_range_is_split_into_safe_seven_day_windows(self):
        svc = SimpleNamespace(get_keyword_report=AsyncMock(return_value=[]))
        account = SimpleNamespace(
            id=5,
            tenant_id=9,
            baidu_username="history-account",
            access_token_encrypted="encrypted",
        )

        with (
            patch("app.baidu.sync.BaiduAPIClient"),
            patch("app.baidu.sync.decrypt", return_value="token"),
            patch("app.baidu.sync.ReportService", return_value=svc),
        ):
            result = await sync_keyword_report_range_for_account(
                object(), account, date(2026, 7, 1), date(2026, 7, 30)
            )

        self.assertEqual(result, 0)
        self.assertEqual(
            [call.kwargs for call in svc.get_keyword_report.await_args_list],
            [
                {"start_date": "2026-07-01", "end_date": "2026-07-07"},
                {"start_date": "2026-07-08", "end_date": "2026-07-14"},
                {"start_date": "2026-07-15", "end_date": "2026-07-21"},
                {"start_date": "2026-07-22", "end_date": "2026-07-28"},
                {"start_date": "2026-07-29", "end_date": "2026-07-30"},
            ],
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
                "app.scheduler.sync_keyword_report_range_for_account",
                new=AsyncMock(return_value=120),
            ) as report_sync,
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
                "app.scheduler.sync_search_terms_for_account",
                new=AsyncMock(return_value=328),
            ) as search_term_sync,
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
        self.assertEqual(result["search_terms_synced"], 328)
        self.assertEqual(
            search_term_sync.await_args.args[2:],
            (date(2026, 6, 28), date(2026, 7, 28)),
        )
        self.assertEqual(result["date"], "2026-07-28")
        self.assertEqual(result["report_start_date"], "2026-07-28")
        report_sync.assert_awaited_once_with(
            session, account, date(2026, 7, 28), date(2026, 7, 28)
        )
        release_lock.assert_called_once_with(lock_handle)

    async def test_refresh_returns_busy_without_calling_baidu(self):
        report_sync = AsyncMock()
        with (
            patch("app.scheduler._acquire_tenant_sync_lock", return_value=None),
            patch("app.scheduler.sync_keyword_report_range_for_account", new=report_sync),
        ):
            result = await refresh_keyword_workbench_snapshot(
                object(),
                SimpleNamespace(id=7),
                SimpleNamespace(tenant_id=7),
                date(2026, 7, 28),
            )

        self.assertEqual(result, {"status": "busy", "tenant_id": 7})
        report_sync.assert_not_awaited()

    async def test_refresh_isolates_failed_dimension_and_continues(self):
        tenant = SimpleNamespace(id=7)
        account = SimpleNamespace(id=12, tenant_id=7, asset_sync_state=None)
        session = SimpleNamespace(
            commit=AsyncMock(),
            rollback=AsyncMock(),
            get=AsyncMock(return_value=account),
        )
        with (
            patch("app.scheduler._acquire_tenant_sync_lock", return_value=object()),
            patch("app.scheduler._release_tenant_sync_lock"),
            patch(
                "app.scheduler.sync_keyword_report_range_for_account",
                new=AsyncMock(side_effect=RuntimeError("region batch failed")),
            ),
            patch(
                "app.scheduler.sync_campaigns_for_account",
                new=AsyncMock(return_value=12),
            ) as campaign_sync,
        ):
            result = await refresh_keyword_workbench_snapshot(
                session,
                tenant,
                account,
                date(2026, 7, 31),
                dimensions=["reports", "campaigns"],
            )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(account.sync_status, "partial")
        self.assertIn("region batch failed", account.last_sync_error)
        self.assertEqual(account.asset_sync_state["dimensions"]["reports"]["status"], "failed")
        self.assertEqual(account.asset_sync_state["dimensions"]["campaigns"]["status"], "success")
        campaign_sync.assert_awaited_once()
        session.rollback.assert_awaited_once()
    def test_manual_refresh_requires_keyword_edit_permission(self):
        self.assertEqual(
            _required("/api/v1/admin/refresh-keyword-workbench", "POST"),
            ({"optimize.keywords"}, True),
        )


if __name__ == "__main__":
    unittest.main()
