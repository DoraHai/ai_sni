import os
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

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

from app.api.auth import _MODULE_PERMISSION_KEYS, list_my_modules, list_tenants
from app.permissions import MENUS
from app.security.auth import AuthContext, _required


SEO_KEYS = tuple(menu["key"] for menu in MENUS if menu["key"].startswith("seo."))
SEO_ROUTE_EXAMPLES = {
    "seo.assets": "/api/v1/seo/sites",
    "seo.dashboard": "/api/v1/seo/overview",
    "seo.alerts": "/api/v1/seo/alerts",
    "seo.keywords": "/api/v1/seo/keywords",
    "seo.content": "/api/v1/seo/content-assets",
    "seo.site": "/api/v1/seo/site-pages",
    "seo.links": "/api/v1/seo/internal-links",
    "seo.competitors": "/api/v1/seo/competitors",
}


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


def _context(permission=None, level="view", tenant_id=7):
    return AuthContext(
        user_id=5,
        username="customer",
        role_name="customer",
        tenant_id=tenant_id,
        permissions={permission: level} if permission else {},
    )


def _module(status="active", expires_at=None):
    return SimpleNamespace(
        tenant_id=7,
        module_code="seo",
        status=status,
        expires_at=expires_at,
    )


def _seo_result(result):
    return next(item for item in result["modules"] if item["module_code"] == "seo")


class TestModulePermissionRegistry(IsolatedAsyncioTestCase):
    def test_seo_module_permissions_cover_every_registered_seo_leaf(self):
        self.assertEqual(set(_MODULE_PERMISSION_KEYS["seo"]), set(SEO_KEYS))
        self.assertEqual(
            len(_MODULE_PERMISSION_KEYS["seo"]),
            len(set(_MODULE_PERMISSION_KEYS["seo"])),
        )
        self.assertEqual(set(SEO_ROUTE_EXAMPLES), set(SEO_KEYS))
        for permission, path in SEO_ROUTE_EXAMPLES.items():
            with self.subTest(permission=permission, path=path):
                required, edit = _required(path, "GET")
                self.assertIn(permission, required)
                self.assertFalse(edit)

    async def test_each_seo_leaf_view_and_edit_grants_active_module_and_tenant_scope(self):
        for permission in SEO_KEYS:
            for level in ("view", "edit"):
                with self.subTest(permission=permission, level=level):
                    ctx = _context(permission, level)
                    module_result = await list_my_modules(
                        ctx=ctx,
                        session=SimpleNamespace(
                            scalars=AsyncMock(return_value=_Rows([_module()]))
                        ),
                    )
                    self.assertEqual(
                        _seo_result(module_result),
                        {
                            "module_code": "seo",
                            "status": "active",
                            "available": True,
                            "expires_at": None,
                            "tenant_count": 1,
                        },
                    )

                    tenant = SimpleNamespace(id=7, name="SEO customer")
                    tenant_result = await list_tenants(
                        module="seo",
                        ctx=ctx,
                        session=SimpleNamespace(
                            scalars=AsyncMock(return_value=_Rows([tenant]))
                        ),
                    )
                    self.assertEqual(
                        tenant_result,
                        {
                            "module": "seo",
                            "tenants": [{"id": 7, "name": "SEO customer"}],
                        },
                    )

    async def test_unopened_disabled_and_expired_seo_modules_are_unavailable(self):
        cases = (
            ([], "not_opened"),
            ([_module(status="disabled")], "disabled"),
            ([_module(expires_at=date.today() - timedelta(days=1))], "active"),
        )
        for rows, expected_status in cases:
            with self.subTest(expected_status=expected_status):
                result = await list_my_modules(
                    ctx=_context("seo.alerts"),
                    session=SimpleNamespace(
                        scalars=AsyncMock(return_value=_Rows(rows))
                    ),
                )
                seo = _seo_result(result)
                self.assertEqual(seo["status"], expected_status)
                self.assertFalse(seo["available"])
                self.assertEqual(seo["tenant_count"], 0)

    async def test_trial_through_today_is_available_and_inactive_scope_is_empty(self):
        result = await list_my_modules(
            ctx=_context("seo.links", level="edit"),
            session=SimpleNamespace(
                scalars=AsyncMock(
                    return_value=_Rows([_module(status="trial", expires_at=date.today())])
                )
            ),
        )
        self.assertTrue(_seo_result(result)["available"])

        tenant_result = await list_tenants(
            module="seo",
            ctx=_context("seo.links"),
            session=SimpleNamespace(scalars=AsyncMock(return_value=_Rows([]))),
        )
        self.assertEqual(tenant_result["tenants"], [])

    async def test_no_seo_permission_denies_module_and_module_tenant_list(self):
        ctx = _context()
        result = await list_my_modules(
            ctx=ctx,
            session=SimpleNamespace(
                scalars=AsyncMock(return_value=_Rows([_module()]))
            ),
        )
        self.assertFalse(_seo_result(result)["available"])

        with self.assertRaises(HTTPException) as raised:
            await list_tenants(module="seo", ctx=ctx, session=SimpleNamespace())
        self.assertEqual(raised.exception.status_code, 403)

    async def test_bound_identity_cannot_receive_another_tenant_from_module_scope(self):
        ctx = _context("seo.competitors", tenant_id=7)
        own = SimpleNamespace(id=7, name="own")
        foreign = SimpleNamespace(id=8, name="foreign")
        result = await list_tenants(
            module="seo",
            ctx=ctx,
            session=SimpleNamespace(
                scalars=AsyncMock(return_value=_Rows([own, foreign]))
            ),
        )
        self.assertEqual(result["tenants"], [{"id": 7, "name": "own"}])
