"""Regression checks for creating GEO content tasks."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
from app.geo.content.schemas import TaskCreate
from app.security.auth import AuthContext


class CreateContentTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_without_facts_succeeds(self):
        session = SimpleNamespace(
            add=MagicMock(),
            flush=AsyncMock(),
            commit=AsyncMock(),
            refresh=AsyncMock(),
            rollback=AsyncMock(),
        )
        prompt = SimpleNamespace(
            id=20,
            tenant_id=1,
            unit_id=None,
            question="苏尔寿ZA参数详解，实际用起来怎么样?",
            last_task_id=None,
        )
        ctx = AuthContext(
            user_id=7,
            username="operator",
            role_name="ops",
            tenant_id=1,
            permissions={"geo.content": "edit"},
        )
        request = TaskCreate(tenant_id=1, prompt_id=20, fact_ids=[])

        async def assign_task_id() -> None:
            session.add.call_args.args[0].id = 101

        session.flush.side_effect = assign_task_id
        expected = {"id": 101, "prompt_id": 20, "fact_ids": []}

        with (
            patch.object(
                routes,
                "_ensure_tenant_exists",
                new=AsyncMock(return_value=SimpleNamespace(id=1)),
            ),
            patch.object(routes, "_get_prompt", new=AsyncMock(return_value=prompt)),
            patch.object(
                routes, "_resolve_task_business_id", new=AsyncMock(return_value=None)
            ),
            patch.object(
                routes, "_resolve_active_period_id", new=AsyncMock(return_value=None)
            ),
            patch.object(routes, "_sync_task_pipeline", new=AsyncMock()) as sync,
            patch.object(
                routes, "_task_payload", new=AsyncMock(return_value=expected)
            ),
        ):
            result = await routes.create_task(request, ctx, session)

        self.assertEqual(result, expected)
        self.assertEqual(prompt.last_task_id, 101)
        sync.assert_awaited_once()
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
