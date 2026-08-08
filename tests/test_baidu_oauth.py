import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
    OAuthAccount,
    calculate_callback_signature,
    persist_authorization,
    verify_callback_signature,
)
from app.models import BaiduAccount, BaiduOAuthGrant, Tenant
from app.security.auth import _required


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

    def test_oauth_write_routes_require_onboarding_edit(self):
        self.assertEqual(
            _required("/api/v1/oauth/baidu/authorize", "POST"),
            ({"onboarding"}, True),
        )
        self.assertEqual(
            _required("/api/v1/oauth/baidu/status", "GET"),
            ({"onboarding"}, False),
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


if __name__ == "__main__":
    unittest.main()
