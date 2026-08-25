import os
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64",
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.baidu.oauth import (
    BaiduOAuthError,
    OAuthAccount,
    calculate_callback_signature,
    persist_authorization,
    verify_callback_signature,
)
from app.models import BaiduAccount, BaiduOAuthGrant, Tenant
from app.api.oauth_baidu import AuthorizationRequest, _initial_sync, authorize
from app.security.auth import AuthContext, _required


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _OAuthSession:
    def __init__(self):
        self.added = []
        self._scalar_calls = 0
        self.execute = AsyncMock()
        self.commit = AsyncMock(side_effect=self._assign_ids)

    def add(self, row):
        self.added.append(row)

    async def scalar(self, _statement):
        self._scalar_calls += 1
        return None  # 新客户、新 grant

    async def scalars(self, _statement):
        return _ScalarRows([])  # 尚无同 UCID 的 OAuth 账户

    async def flush(self):
        self._assign_ids()

    def _assign_ids(self):
        for index, row in enumerate(self.added, 100):
            if getattr(row, "id", None) is None:
                row.id = index


class _ConflictingOAuthSession(_OAuthSession):
    def __init__(self):
        super().__init__()
        self.account_tenant = Tenant(id=101, name="account-a", baidu_ucid=2080601)
        self.conflicting_account = BaiduAccount(
            id=88,
            tenant_id=999,
            baidu_username="account-a",
            baidu_ucid=2080601,
            access_token_encrypted="encrypted",
            expires_at=datetime(2099, 1, 1),
            auth_mode="oauth",
            status="active",
        )

    async def scalar(self, _statement):
        self._scalar_calls += 1
        if self._scalar_calls == 1:
            return self.account_tenant
        return None

    async def scalars(self, _statement):
        return _ScalarRows([self.conflicting_account])


class _SameTenantSelfAuthSession(_OAuthSession):
    def __init__(self):
        super().__init__()
        self.account_tenant = Tenant(id=101, name="account-a", baidu_ucid=2080601)
        self.self_account = BaiduAccount(
            id=88,
            tenant_id=101,
            baidu_username="account-a",
            baidu_ucid=2080601,
            access_token_encrypted="encrypted",
            expires_at=datetime(2099, 1, 1),
            auth_mode="self",
            status="active",
        )

    async def scalar(self, _statement):
        self._scalar_calls += 1
        if self._scalar_calls == 1:
            return self.account_tenant
        return None

    async def scalars(self, _statement):
        return _ScalarRows([self.self_account])


class _TargetTenantOAuthSession(_OAuthSession):
    def __init__(self):
        super().__init__()
        self.target_tenant = Tenant(id=7, name="待重新绑定客户", baidu_ucid=None)

    async def scalar(self, _statement):
        self._scalar_calls += 1
        if self._scalar_calls == 1:
            return self.target_tenant
        return None


class BaiduOAuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.params = {
            "appId": "app",
            "authCode": "code",
            "state": "state",
            "timestamp": "123",
            "userId": "456",
        }

    def test_callback_signature_matches_official_algorithm_shape(self):
        signature = calculate_callback_signature(
            self.params, "1234567890abcdefEXTRA"
        )
        self.assertEqual(
            signature,
            "BA29260C7DB75734D05CA571556DC4904707205A811E1EB405AC68020149B368"
            "FA25582C979A9A34352EF99AB77BEB25A5DAF1B1AA6542D3ADCAECCDCF0A10F2"
            "3807C2C934256C5D0857F07783FA7E86373521E2FBDB93374FDA92BF85BB64E49F"
            "F0B89AC949FFABE1EFE36134CCF1FD",
        )

    def test_callback_signature_rejects_tampering(self):
        signature = calculate_callback_signature(
            self.params, os.environ["BAIDU_SECRET_KEY"]
        )
        self.assertTrue(verify_callback_signature(self.params, signature))
        tampered = dict(self.params, userId="999")
        self.assertFalse(verify_callback_signature(tampered, signature))

    def test_oauth_authorize_accepts_onboarding_or_customer_admin_at_route_gate(self):
        self.assertEqual(
            _required("/api/v1/oauth/baidu/authorize", "POST"),
            ({"onboarding", "settings.customers"}, True),
        )
        self.assertEqual(
            _required("/api/v1/oauth/baidu/status", "GET"),
            ({"onboarding", "settings.customers"}, False),
        )

    async def test_rebind_rejects_customer_without_active_sem_module(self):
        ctx = AuthContext(
            user_id=9,
            username="admin",
            role_name="管理员",
            tenant_id=None,
            permissions={"settings.customers": "edit"},
        )
        session = SimpleNamespace(get=AsyncMock(return_value=Tenant(id=7, name="SEO客户")))
        with patch(
            "app.api.oauth_baidu.get_tenant_module",
            AsyncMock(side_effect=HTTPException(403, "当前客户的 SEM 模块未启用或已过期")),
        ):
            with self.assertRaises(HTTPException) as cm:
                await authorize(
                    AuthorizationRequest(tenant_id=7, bind_to_tenant=True),
                    ctx=ctx,
                    session=session,
                )
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("SEM 模块未启用", cm.exception.detail)

    def test_customer_admin_rebind_button_is_sem_entitlement_gated(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "frontend/src/views/settings/CustomerModulesView.vue"
        ).read_text(encoding="utf-8")
        self.assertIn('v-if="moduleRow(row, \'sem\')?.available"', source)
        router = (
            Path(__file__).resolve().parents[1] / "frontend/src/router/index.js"
        ).read_text(encoding="utf-8")
        self.assertIn("perm: ['onboarding', 'settings.customers']", router)

    def test_callback_rechecks_sem_entitlement_before_token_exchange(self):
        source = (
            Path(__file__).resolve().parents[1] / "app/api/oauth_baidu.py"
        ).read_text(encoding="utf-8")
        consume_at = source.index("state_row = await consume_oauth_state")
        entitlement_at = source.index(
            'await get_tenant_module(session, state_row.tenant_id, "sem")'
        )
        exchange_at = source.index("token_data = await exchange_auth_code")
        self.assertLess(consume_at, entitlement_at)
        self.assertLess(entitlement_at, exchange_at)

    async def test_initial_sync_backfills_thirty_days_of_keyword_history(self):
        account = SimpleNamespace(id=22, tenant_id=7, status="active")
        tenant = SimpleNamespace(id=7)
        session = SimpleNamespace(
            get=AsyncMock(side_effect=[account, tenant]),
            rollback=AsyncMock(),
        )

        class SessionContext:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *_args):
                return False

        refresh = AsyncMock(return_value={"status": "ok"})
        with (
            patch("app.api.oauth_baidu.async_session_factory", return_value=SessionContext()),
            patch("app.api.oauth_baidu.refresh_keyword_workbench_snapshot", new=refresh),
            patch("app.api.oauth_baidu.datetime") as now,
        ):
            now.now.return_value = datetime(2026, 8, 25, 12, 0)
            await _initial_sync([22])

        refresh.assert_awaited_once_with(
            session,
            tenant,
            account,
            date(2026, 8, 25),
            report_start_date=date(2026, 7, 27),
        )

    async def test_authorized_account_creates_its_own_tenant(self):
        session = _OAuthSession()
        _, linked, tenants = await persist_authorization(
            session,
            oauth_user_id=2080601,
            token_data={
                "accessToken": "access-token",
                "refreshToken": "refresh-token",
                "openId": "open-id",
            },
            master={
                "master_ucid": 2080601,
                "master_name": "chinainspection",
                "account_type": 1,
            },
            accounts=[
                OAuthAccount(
                    ucid=2080601,
                    username="chinainspection",
                    role="standalone",
                )
            ],
        )

        self.assertEqual(len(tenants), 1)
        self.assertEqual(tenants[0].name, "chinainspection")
        self.assertEqual(tenants[0].baidu_ucid, 2080601)
        self.assertNotEqual(tenants[0].id, 7)
        self.assertEqual(linked[0].tenant_id, tenants[0].id)
        self.assertEqual(linked[0].sync_status, "pending")
        self.assertTrue(any(isinstance(row, Tenant) for row in session.added))
        self.assertTrue(any(isinstance(row, BaiduOAuthGrant) for row in session.added))
        self.assertTrue(any(isinstance(row, BaiduAccount) for row in session.added))
        module_insert = session.execute.await_args_list[0].args[0]
        compiled = str(module_insert.compile()).lower()
        params = module_insert.compile().params
        self.assertIn("on conflict", compiled)
        self.assertIn("tenant_modules", compiled)
        self.assertIn("sem", params.values())
        self.assertIn(tenants[0].id, params.values())

    async def test_explicit_rebind_uses_the_oauth_state_target_tenant(self):
        session = _TargetTenantOAuthSession()

        _, linked, tenants = await persist_authorization(
            session,
            oauth_user_id=2080601,
            token_data={
                "accessToken": "access-token",
                "refreshToken": "refresh-token",
                "openId": "open-id",
            },
            master={
                "master_ucid": 2080601,
                "master_name": "target-account",
                "account_type": 1,
            },
            accounts=[OAuthAccount(ucid=2080601, username="target-account", role="standalone")],
            target_tenant_id=7,
        )

        self.assertEqual(tenants, [session.target_tenant])
        self.assertEqual(session.target_tenant.baidu_ucid, 2080601)
        self.assertEqual(linked[0].tenant_id, 7)
        self.assertFalse(any(isinstance(row, Tenant) for row in session.added))

    async def test_explicit_rebind_rejects_ambiguous_multi_account_authorization(self):
        session = _TargetTenantOAuthSession()

        with self.assertRaises(BaiduOAuthError) as cm:
            await persist_authorization(
                session,
                oauth_user_id=2080601,
                token_data={
                    "accessToken": "access-token",
                    "refreshToken": "refresh-token",
                    "openId": "open-id",
                },
                master={
                    "master_ucid": 2080601,
                    "master_name": "agency-master",
                    "account_type": 2,
                },
                accounts=[
                    OAuthAccount(ucid=2080601, username="account-a", role="subaccount"),
                    OAuthAccount(ucid=2080602, username="account-b", role="subaccount"),
                ],
                target_tenant_id=7,
            )

        self.assertEqual(cm.exception.code, "rebind_requires_single_account")
        self.assertEqual(session._scalar_calls, 0)

    async def test_authorization_stops_on_cross_customer_account_binding(self):
        session = _ConflictingOAuthSession()
        with self.assertRaises(BaiduOAuthError) as cm:
            await persist_authorization(
                session,
                oauth_user_id=2080601,
                token_data={
                    "accessToken": "access-token",
                    "refreshToken": "refresh-token",
                    "openId": "open-id",
                },
                master={
                    "master_ucid": 2080601,
                    "master_name": "account-a",
                    "account_type": 1,
                },
                accounts=[OAuthAccount(ucid=2080601, username="account-a", role="standalone")],
            )

        self.assertEqual(cm.exception.code, "account_tenant_conflict")

    async def test_authorization_also_stops_on_cross_customer_self_auth_binding(self):
        session = _ConflictingOAuthSession()
        session.conflicting_account.auth_mode = "self"
        with self.assertRaises(BaiduOAuthError) as cm:
            await persist_authorization(
                session,
                oauth_user_id=2080601,
                token_data={
                    "accessToken": "access-token",
                    "refreshToken": "refresh-token",
                    "openId": "open-id",
                },
                master={
                    "master_ucid": 2080601,
                    "master_name": "account-a",
                    "account_type": 1,
                },
                accounts=[OAuthAccount(ucid=2080601, username="account-a", role="standalone")],
            )

        self.assertEqual(cm.exception.code, "account_tenant_conflict")

    async def test_same_customer_self_auth_row_is_upgraded_in_place(self):
        session = _SameTenantSelfAuthSession()
        _, linked, _ = await persist_authorization(
            session,
            oauth_user_id=2080601,
            token_data={
                "accessToken": "access-token",
                "refreshToken": "refresh-token",
                "openId": "open-id",
            },
            master={
                "master_ucid": 2080601,
                "master_name": "account-a",
                "account_type": 1,
            },
            accounts=[OAuthAccount(ucid=2080601, username="account-a", role="standalone")],
        )

        self.assertIs(linked[0], session.self_account)
        self.assertEqual(linked[0].id, 88)
        self.assertEqual(linked[0].auth_mode, "oauth")
        self.assertEqual(linked[0].status, "active")


if __name__ == "__main__":
    unittest.main()
