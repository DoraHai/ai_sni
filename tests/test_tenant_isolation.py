"""Tenant isolation helpers (productization must-do)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.security.auth import AuthContext, require_scoped_auth


class _BudgetRequest(BaseModel):
    tenant_id: int
    budget: float


class TenantIsolationTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_sem_write_body_is_checked_by_identity_guard(self):
        body = b'{"tenant_id":10,"budget":500}'

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/manage/account-budget",
                "query_string": b"",
                "headers": [(b"content-type", b"application/json")],
            },
            receive,
        )
        ctx = self._ctx(None, superadmin=True)
        session = object()
        guard = AsyncMock()
        module_guard = AsyncMock()

        with (
            patch("app.security.auth.ensure_module_access", module_guard),
            patch("app.security.auth.ensure_sem_identity_access", guard),
        ):
            await require_scoped_auth(request, ctx, session)

        module_guard.assert_awaited_once_with(session, ctx, 10, "sem")
        guard.assert_awaited_once_with(session, 10)

    async def test_customer_identity_admin_page_remains_available_for_repair(self):
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/admin/customers",
                "query_string": b"tenant_id=10",
                "headers": [],
            }
        )
        ctx = AuthContext(
            user_id=1,
            username="admin",
            role_name="admin",
            tenant_id=None,
            permissions={"settings.customers": "edit"},
        )
        guard = AsyncMock()

        with patch("app.security.auth.ensure_sem_identity_access", guard):
            await require_scoped_auth(request, ctx, object())

        guard.assert_not_awaited()

    def test_identity_dependency_does_not_consume_validated_request_body(self):
        app = FastAPI()

        @app.post(
            "/api/v1/manage/account-budget",
            dependencies=[Depends(require_scoped_auth)],
        )
        async def budget(req: _BudgetRequest):
            return req.model_dump()

        async def fake_context():
            return self._ctx(None, superadmin=True)

        async def fake_session():
            yield object()

        from app.database import get_session
        from app.security.auth import require_auth

        app.dependency_overrides[require_auth] = fake_context
        app.dependency_overrides[get_session] = fake_session
        guard = AsyncMock()
        module_guard = AsyncMock()
        with (
            patch("app.security.auth.ensure_module_access", module_guard),
            patch("app.security.auth.ensure_sem_identity_access", guard),
        ):
            response = TestClient(app).post(
                "/api/v1/manage/account-budget",
                json={"tenant_id": 10, "budget": 500},
            )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json(), {"tenant_id": 10, "budget": 500.0})
        module_guard.assert_awaited_once()
        guard.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
