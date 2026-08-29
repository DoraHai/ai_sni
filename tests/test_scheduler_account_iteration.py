import asyncio
import os
import unittest
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

from app.models import BaiduAccount, Tenant
from app.scheduler import (
    fetch_today_keyword_report,
    fetch_yesterday_keyword_report,
    sync_search_terms_daily,
)


class _SessionContext:
    def __init__(self, session, exit_error=None):
        self.session = session
        self.exit_error = exit_error

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        if self.exit_error is not None:
            raise self.exit_error
        return False


class _Account:
    def __init__(self, account_id: int, tenant_id: int, username: str):
        self.id = account_id
        self._tenant_id = tenant_id
        self._username = username
        self.expired = False

    @property
    def tenant_id(self):
        if self.expired:
            raise RuntimeError("expired tenant_id was accessed")
        return self._tenant_id

    @property
    def baidu_username(self):
        if self.expired:
            raise RuntimeError("expired username was accessed")
        return self._username


class SchedulerAccountIterationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rollback_expiration_does_not_abort_remaining_accounts(self):
        listed = [_Account(11, 101, "first"), _Account(12, 102, "second")]
        fresh = {
            11: SimpleNamespace(
                id=11, tenant_id=101, baidu_username="first", status="active"
            ),
            12: SimpleNamespace(
                id=12, tenant_id=102, baidu_username="second", status="active"
            ),
        }
        tenants = {101: SimpleNamespace(id=101), 102: SimpleNamespace(id=102)}

        async def get(model, row_id):
            return tenants.get(row_id) if model is Tenant else fresh.get(row_id)

        session = SimpleNamespace(get=AsyncMock(side_effect=get))
        sync_calls = []

        async def sync(_session, tenant, account, _today):
            sync_calls.append((tenant.id, account.id))
            if account.id == 11:
                for original in listed:
                    original.expired = True
            return {"status": "ok"}

        with (
            patch("app.scheduler._report_sync_lock", new=asyncio.Lock()),
            patch(
                "app.scheduler.async_session_factory",
                return_value=_SessionContext(session),
            ) as session_factory,
            patch(
                "app.scheduler.refresh_expiring_oauth_grants",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.scheduler.list_active_sem_accounts",
                new=AsyncMock(return_value=listed),
            ),
            patch(
                "app.scheduler.filter_identity_safe_active_accounts",
                side_effect=lambda rows: rows,
            ),
            patch("app.scheduler.get_tenant_module", new=AsyncMock()),
            patch("app.scheduler.ensure_sem_identity_access", new=AsyncMock()),
            patch("app.scheduler.refresh_keyword_workbench_snapshot", new=sync),
        ):
            await fetch_today_keyword_report()

        self.assertEqual(sync_calls, [(101, 11), (102, 12)])
        self.assertEqual(session_factory.call_count, 3)
    async def test_search_term_failure_does_not_abort_next_account(self):
        refs = [(11, 101, "broken"), (12, 102, "healthy")]
        accounts = [
            SimpleNamespace(id=11, tenant_id=101, baidu_username="broken"),
            SimpleNamespace(id=12, tenant_id=102, baidu_username="healthy"),
        ]
        sessions = [SimpleNamespace() for _ in range(3)]
        session_factory = unittest.mock.Mock(
            side_effect=[
                _SessionContext(sessions[0]),
                _SessionContext(sessions[1], RuntimeError("rollback failed")),
                _SessionContext(sessions[2]),
            ]
        )
        reload_account = AsyncMock(
            side_effect=[
                (accounts[0], SimpleNamespace(id=101), None),
                (accounts[1], SimpleNamespace(id=102), None),
            ]
        )
        sync = AsyncMock(side_effect=[RuntimeError("provider failed"), 7])

        with (
            patch("app.scheduler._report_sync_lock", new=asyncio.Lock()),
            patch("app.scheduler.async_session_factory", new=session_factory),
            patch(
                "app.scheduler.refresh_expiring_oauth_grants",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.scheduler._scheduled_account_refs",
                new=AsyncMock(return_value=refs),
            ),
            patch("app.scheduler._reload_scheduled_account", new=reload_account),
            patch("app.scheduler.sync_search_terms_for_account", new=sync),
        ):
            await sync_search_terms_daily()

        self.assertEqual(sync.await_count, 2)
        self.assertEqual(sync.await_args_list[1].args[1].id, 12)
        self.assertEqual(session_factory.call_count, 3)

    async def test_yesterday_report_failure_does_not_abort_later_account_or_phases(self):
        refs = [(11, 101, "broken"), (12, 102, "healthy")]
        accounts = {
            11: SimpleNamespace(id=11, tenant_id=101, baidu_username="broken"),
            12: SimpleNamespace(id=12, tenant_id=102, baidu_username="healthy"),
        }

        async def reload_account(_session, account_id, tenant_id):
            return accounts[account_id], SimpleNamespace(id=tenant_id), None

        session_factory = unittest.mock.Mock(
            side_effect=lambda: _SessionContext(SimpleNamespace())
        )
        report_sync = AsyncMock(side_effect=[RuntimeError("db failed"), 5])
        dimension_sync = AsyncMock(return_value={"region": 0, "hourly": 0})
        operation_sync = AsyncMock(return_value=0)

        with (
            patch("app.scheduler._report_sync_lock", new=asyncio.Lock()),
            patch("app.scheduler.async_session_factory", new=session_factory),
            patch(
                "app.scheduler.refresh_expiring_oauth_grants",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.scheduler._scheduled_account_refs",
                new=AsyncMock(return_value=refs),
            ),
            patch("app.scheduler._reload_scheduled_account", new=reload_account),
            patch("app.scheduler.sync_keyword_report_for_account", new=report_sync),
            patch(
                "app.scheduler.sync_keyword_dimension_reports_for_account",
                new=dimension_sync,
            ),
            patch("app.scheduler.sync_region_snapshot", new=AsyncMock(return_value=0)),
            patch("app.scheduler.sync_campaigns_for_account", new=AsyncMock(return_value=0)),
            patch("app.scheduler.sync_adgroups_for_account", new=AsyncMock(return_value=0)),
            patch("app.scheduler.sync_keywords_for_account", new=AsyncMock(return_value=0)),
            patch("app.scheduler.sync_price_strategies_for_account", new=AsyncMock(return_value=0)),
            patch("app.scheduler.sync_ocpc_packages_for_account", new=AsyncMock(return_value=0)),
            patch("app.scheduler.sync_operation_records_for_account", new=operation_sync),
            patch("app.scheduler.sleep", new=AsyncMock()),
            patch(
                "app.scheduler.list_active_module_tenants",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.scheduler.run_rules_for_all_tenants",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.scheduler.run_suggestions_for_all_tenants",
                new=AsyncMock(return_value={}),
            ),
        ):
            await fetch_yesterday_keyword_report()

        self.assertEqual(report_sync.await_count, 2)
        self.assertEqual(report_sync.await_args_list[1].args[1].id, 12)
        dimension_sync.assert_awaited_once()
        self.assertEqual(operation_sync.await_count, 2)

    async def test_one_account_reload_failure_does_not_abort_next_account(self):
        listed = [_Account(11, 101, "broken"), _Account(12, 102, "healthy")]
        healthy = SimpleNamespace(
            id=12, tenant_id=102, baidu_username="healthy", status="active"
        )
        tenant = SimpleNamespace(id=102)

        async def get(model, row_id):
            if row_id in {11, 101}:
                raise RuntimeError("account reload failed")
            return tenant if model is Tenant else healthy

        session = SimpleNamespace(
            get=AsyncMock(side_effect=get),
        )
        sync = AsyncMock(return_value={"status": "ok"})

        with (
            patch("app.scheduler._report_sync_lock", new=asyncio.Lock()),
            patch(
                "app.scheduler.async_session_factory",
                return_value=_SessionContext(session),
            ) as session_factory,
            patch(
                "app.scheduler.refresh_expiring_oauth_grants",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.scheduler.list_active_sem_accounts",
                new=AsyncMock(return_value=listed),
            ),
            patch(
                "app.scheduler.filter_identity_safe_active_accounts",
                side_effect=lambda rows: rows,
            ),
            patch("app.scheduler.get_tenant_module", new=AsyncMock()),
            patch("app.scheduler.ensure_sem_identity_access", new=AsyncMock()),
            patch("app.scheduler.refresh_keyword_workbench_snapshot", new=sync),
        ):
            await fetch_today_keyword_report()

        sync.assert_awaited_once()
        self.assertEqual(sync.await_args.args[2].id, 12)
        self.assertEqual(session_factory.call_count, 3)

    async def test_account_changed_after_listing_is_not_synced(self):
        listed = [_Account(11, 101, "changed"), _Account(12, 102, "healthy")]
        reloaded = {
            11: SimpleNamespace(
                id=11,
                tenant_id=999,
                baidu_username="changed",
                status="active",
            ),
            12: SimpleNamespace(
                id=12,
                tenant_id=102,
                baidu_username="healthy",
                status="active",
            ),
        }
        tenants = {102: SimpleNamespace(id=102)}

        async def get(model, row_id):
            return tenants.get(row_id) if model is Tenant else reloaded.get(row_id)

        session = SimpleNamespace(get=AsyncMock(side_effect=get))
        sync = AsyncMock(return_value={"status": "ok"})
        module_check = AsyncMock()
        identity_check = AsyncMock()

        with (
            patch("app.scheduler._report_sync_lock", new=asyncio.Lock()),
            patch(
                "app.scheduler.async_session_factory",
                return_value=_SessionContext(session),
            ),
            patch(
                "app.scheduler.refresh_expiring_oauth_grants",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.scheduler.list_active_sem_accounts",
                new=AsyncMock(return_value=listed),
            ),
            patch(
                "app.scheduler.filter_identity_safe_active_accounts",
                side_effect=lambda rows: rows,
            ),
            patch("app.scheduler.get_tenant_module", new=module_check),
            patch("app.scheduler.ensure_sem_identity_access", new=identity_check),
            patch("app.scheduler.refresh_keyword_workbench_snapshot", new=sync),
        ):
            await fetch_today_keyword_report()

        sync.assert_awaited_once()
        self.assertEqual(sync.await_args.args[2].id, 12)
        module_check.assert_awaited_once_with(session, 102, "sem")
        identity_check.assert_awaited_once_with(session, 102)

    async def test_new_identity_conflict_is_skipped_without_aborting_next_account(self):
        listed = [_Account(11, 101, "conflicted"), _Account(12, 102, "healthy")]
        accounts = {
            11: SimpleNamespace(
                id=11, tenant_id=101, baidu_username="conflicted", status="active"
            ),
            12: SimpleNamespace(
                id=12, tenant_id=102, baidu_username="healthy", status="active"
            ),
        }
        tenants = {101: SimpleNamespace(id=101), 102: SimpleNamespace(id=102)}

        async def get(model, row_id):
            return tenants.get(row_id) if model is Tenant else accounts.get(row_id)

        session = SimpleNamespace(get=AsyncMock(side_effect=get))
        sync = AsyncMock(return_value={"status": "ok"})
        identity_check = AsyncMock(
            side_effect=[RuntimeError("identity conflict"), None]
        )

        with (
            patch("app.scheduler._report_sync_lock", new=asyncio.Lock()),
            patch(
                "app.scheduler.async_session_factory",
                return_value=_SessionContext(session),
            ),
            patch(
                "app.scheduler.refresh_expiring_oauth_grants",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.scheduler.list_active_sem_accounts",
                new=AsyncMock(return_value=listed),
            ),
            patch(
                "app.scheduler.filter_identity_safe_active_accounts",
                side_effect=lambda rows: rows,
            ),
            patch("app.scheduler.get_tenant_module", new=AsyncMock()),
            patch("app.scheduler.ensure_sem_identity_access", new=identity_check),
            patch("app.scheduler.refresh_keyword_workbench_snapshot", new=sync),
        ):
            await fetch_today_keyword_report()

        sync.assert_awaited_once()
        self.assertEqual(sync.await_args.args[2].id, 12)
        self.assertEqual(identity_check.await_count, 2)

    async def test_session_cleanup_failure_does_not_abort_next_account(self):
        listed = [_Account(11, 101, "broken"), _Account(12, 102, "healthy")]
        sessions = [
            SimpleNamespace(),
            SimpleNamespace(
                get=AsyncMock(side_effect=RuntimeError("account reload failed"))
            ),
            SimpleNamespace(
                get=AsyncMock(
                    side_effect=[
                        SimpleNamespace(
                            id=12,
                            tenant_id=102,
                            baidu_username="healthy",
                            status="active",
                        ),
                        SimpleNamespace(id=102),
                    ]
                )
            ),
        ]
        contexts = [
            _SessionContext(sessions[0]),
            _SessionContext(sessions[1], RuntimeError("rollback failed")),
            _SessionContext(sessions[2]),
        ]
        session_factory = unittest.mock.Mock(side_effect=contexts)
        sync = AsyncMock(return_value={"status": "ok"})

        with (
            patch("app.scheduler._report_sync_lock", new=asyncio.Lock()),
            patch("app.scheduler.async_session_factory", new=session_factory),
            patch(
                "app.scheduler.refresh_expiring_oauth_grants",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.scheduler.list_active_sem_accounts",
                new=AsyncMock(return_value=listed),
            ),
            patch(
                "app.scheduler.filter_identity_safe_active_accounts",
                side_effect=lambda rows: rows,
            ),
            patch("app.scheduler.get_tenant_module", new=AsyncMock()),
            patch("app.scheduler.ensure_sem_identity_access", new=AsyncMock()),
            patch("app.scheduler.refresh_keyword_workbench_snapshot", new=sync),
        ):
            await fetch_today_keyword_report()

        sync.assert_awaited_once()
        self.assertEqual(sync.await_args.args[2].id, 12)
        self.assertEqual(session_factory.call_count, 3)


if __name__ == "__main__":
    unittest.main()
