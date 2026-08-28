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
from app.scheduler import fetch_today_keyword_report


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
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
            11: SimpleNamespace(id=11, tenant_id=101, baidu_username="first"),
            12: SimpleNamespace(id=12, tenant_id=102, baidu_username="second"),
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
            patch("app.scheduler.refresh_keyword_workbench_snapshot", new=sync),
        ):
            await fetch_today_keyword_report()

        self.assertEqual(sync_calls, [(101, 11), (102, 12)])
        self.assertEqual(session_factory.call_count, 3)

    async def test_one_account_reload_failure_does_not_abort_next_account(self):
        listed = [_Account(11, 101, "broken"), _Account(12, 102, "healthy")]
        healthy = SimpleNamespace(id=12, tenant_id=102, baidu_username="healthy")
        tenant = SimpleNamespace(id=102)

        async def get(model, row_id):
            if row_id in {11, 101}:
                raise RuntimeError("account reload failed")
            return tenant if model is Tenant else healthy

        session = SimpleNamespace(
            get=AsyncMock(side_effect=get),
            rollback=AsyncMock(),
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
            patch("app.scheduler.refresh_keyword_workbench_snapshot", new=sync),
        ):
            await fetch_today_keyword_report()

        sync.assert_awaited_once()
        self.assertEqual(sync.await_args.args[2].id, 12)
        session.rollback.assert_awaited_once()
        self.assertEqual(session_factory.call_count, 3)


if __name__ == "__main__":
    unittest.main()
