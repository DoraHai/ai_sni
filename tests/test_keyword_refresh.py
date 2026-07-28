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

from app.scheduler import refresh_keyword_workbench_snapshot
from app.security.auth import _required


class KeywordRefreshTests(unittest.IsolatedAsyncioTestCase):
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

    def test_manual_refresh_requires_keyword_edit_permission(self):
        self.assertEqual(
            _required("/api/v1/admin/refresh-keyword-workbench", "POST"),
            ({"optimize.keywords"}, True),
        )


if __name__ == "__main__":
    unittest.main()
