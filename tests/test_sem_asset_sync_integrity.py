import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.baidu.sync import sync_search_terms_for_account
from app.api.customer_modules import repair_sem_account_assets
from app.sem_asset_sync import (
    begin_sync_run,
    normalize_dimensions,
    safe_sync_error,
    update_dimension,
)


class SemAssetSyncStateTests(unittest.TestCase):
    def test_stale_run_cannot_overwrite_newer_state(self):
        old_state, old_run = begin_sync_run(None, ("campaigns",))
        new_state, new_run = begin_sync_run(old_state, ("campaigns",))
        stale_result = update_dimension(new_state, old_run, "campaigns", "failed", error="old")

        self.assertEqual(stale_result["run_id"], new_run)
        self.assertEqual(stale_result["dimensions"]["campaigns"]["status"], "pending")

    def test_dimension_validation_and_order(self):
        self.assertEqual(normalize_dimensions(["keywords", "campaigns"]), ("campaigns", "keywords"))
        with self.assertRaisesRegex(ValueError, "unknown"):
            normalize_dimensions(["unknown"])

    def test_sync_error_redacts_secrets(self):
        message = safe_sync_error(RuntimeError("access_token=abc123 password: hunter2"))
        self.assertNotIn("abc123", message)
        self.assertNotIn("hunter2", message)
        self.assertIn("[REDACTED]", message)


class SearchTermIntegrityTests(unittest.IsolatedAsyncioTestCase):
    def _account(self):
        return SimpleNamespace(id=22, tenant_id=7, baidu_username="account-a")

    def _rows(self, count):
        return [{"queryWord": f"term-{i}"} for i in range(count)]

    async def test_large_unexpected_drop_preserves_existing_snapshot(self):
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=100),
            execute=AsyncMock(),
            add_all=MagicMock(),
            commit=AsyncMock(),
        )
        with (
            patch("app.baidu.sync._fetch_search_term_rows", new=AsyncMock(return_value=self._rows(10))),
            patch("app.baidu.sync._merge_search_term_rows", return_value=self._rows(10)),
        ):
            with self.assertRaisesRegex(RuntimeError, "完整性校验失败"):
                await sync_search_terms_for_account(
                    session, self._account(), date(2026, 8, 1), date(2026, 8, 1)
                )

        session.execute.assert_not_awaited()
        session.add_all.assert_not_called()

    async def test_successful_replace_is_scoped_to_baidu_account(self):
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=10),
            execute=AsyncMock(),
            add_all=MagicMock(),
            commit=AsyncMock(),
        )
        with (
            patch("app.baidu.sync._fetch_search_term_rows", new=AsyncMock(return_value=self._rows(5))),
            patch("app.baidu.sync._merge_search_term_rows", return_value=self._rows(5)),
        ):
            result = await sync_search_terms_for_account(
                session, self._account(), date(2026, 8, 1), date(2026, 8, 1)
            )

        self.assertEqual(result, 5)
        delete_sql = str(session.execute.await_args.args[0])
        self.assertIn("search_term_reports.baidu_account_id", delete_sql)
        session.add_all.assert_called_once()
        session.commit.assert_awaited_once()


class SemAssetRepairApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_dimension_is_forwarded_to_read_only_sync(self):
        account = SimpleNamespace(id=22, tenant_id=7, status="active")
        tenant = SimpleNamespace(id=7)
        session = SimpleNamespace(get=AsyncMock(side_effect=[account, tenant]))
        ctx = SimpleNamespace(can_edit=lambda permission: permission == "onboarding")
        sync = AsyncMock(return_value={"status": "ok", "keywords_synced": 12})

        with (
            patch("app.api.customer_modules.ensure_module_access", new=AsyncMock()),
            patch("app.scheduler.refresh_keyword_workbench_snapshot", new=sync),
        ):
            result = await repair_sem_account_assets(
                account_id=22,
                tenant_id=7,
                dimension="keywords",
                ctx=ctx,
                session=session,
            )

        self.assertEqual(result["mode"], "read_only_repair")
        self.assertEqual(sync.await_args.kwargs["dimensions"], ["keywords"])


if __name__ == "__main__":
    unittest.main()
