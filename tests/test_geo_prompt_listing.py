"""Regression checks for tenant-scoped GEO prompt candidates."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test")
os.environ.setdefault("BAIDU_SECRET_KEY", "test")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "0")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00Z")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.geo.content import routes
from app.security.auth import AuthContext


class ListGeoPromptsTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_inventory_only_requires_active_tenant_business_and_unit(self):
        session = SimpleNamespace(scalars=AsyncMock(return_value=[]))
        ctx = AuthContext(
            user_id=7,
            username="operator",
            role_name="ops",
            tenant_id=1,
            permissions={"geo.content": "view"},
        )

        result = await routes.list_prompts(
            tenant_id=1,
            status="active",
            active_inventory_only=True,
            tag=None,
            question_group=None,
            is_brand_probe=None,
            need_recheck=None,
            unit_id=None,
            business_id=None,
            ctx=ctx,
            session=session,
        )

        self.assertEqual(result, {"items": []})
        stmt = session.scalars.await_args.args[0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("JOIN geo_optimization_units", sql)
        self.assertIn("JOIN geo_optimization_businesses", sql)
        self.assertIn("geo_prompts.tenant_id = 1", sql)
        self.assertIn("geo_optimization_units.tenant_id = 1", sql)
        self.assertIn("geo_optimization_businesses.tenant_id = 1", sql)
        self.assertIn("geo_optimization_units.status = 'active'", sql)
        self.assertIn("geo_optimization_businesses.status = 'active'", sql)
        self.assertIn("geo_prompts.status = 'active'", sql)


if __name__ == "__main__":
    unittest.main()
