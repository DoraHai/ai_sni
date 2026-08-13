"""Tenant isolation helpers (productization must-do)."""

from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.permissions import OPERATOR_PERMS
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

    def test_bound_api_key_is_not_superadmin(self):
        ctx = AuthContext(
            user_id=None,
            username="api-key",
            role_name="租户运维密钥",
            tenant_id=10,
            permissions=dict(OPERATOR_PERMS),
            is_superadmin=False,
        )
        self.assertFalse(ctx.is_superadmin)
        self.assertTrue(ctx.can_edit("geo.content"))
        self.assertFalse(ctx.can_edit("settings.accounts"))
        with self.assertRaises(HTTPException):
            ctx.ensure_tenant(11)


if __name__ == "__main__":
    unittest.main()
