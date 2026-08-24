"""Tenant isolation helpers (productization must-do)."""

from __future__ import annotations

import os
import unittest

from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.security.auth import AuthContext


class TenantIsolationTests(unittest.TestCase):
    def _ctx(self, tenant_id: int | None, *, superadmin: bool = False) -> AuthContext:
        return AuthContext(
            user_id=1,
            username="op",
            role_name="ops",
            tenant_id=tenant_id,
            permissions={"geo.content": "edit"},
            is_superadmin=superadmin,
        )

    def test_bound_user_blocked(self):
        ctx = self._ctx(10)
        with self.assertRaises(HTTPException) as cm:
            ctx.ensure_tenant(11)
        self.assertEqual(cm.exception.status_code, 403)

    def test_bound_user_ok(self):
        ctx = self._ctx(10)
        ctx.ensure_tenant(10)  # no raise

    def test_unbound_user_any(self):
        ctx = self._ctx(None)
        ctx.ensure_tenant(1)
        ctx.ensure_tenant(999)

    def test_superadmin_any(self):
        ctx = self._ctx(None, superadmin=True)
        ctx.ensure_tenant(42)


if __name__ == "__main__":
    unittest.main()
