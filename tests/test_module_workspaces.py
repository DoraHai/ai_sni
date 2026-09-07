import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.database import get_session
from app.api.customer_modules import (
    _canonical_domain,
    _require_seo_asset_permission,
    _site_payload,
    router as customer_modules_router,
    seo_sites_router,
)
from app.models import GeoProject, SeoSite, TenantModule
from app.module_scope import normalize_module_code
from app.permissions import CLIENT_PERMS, OPERATOR_PERMS
from app.security.auth import AuthContext, _required, require_auth, require_scoped_auth


class ModuleWorkspaceTests(unittest.TestCase):
    def test_models_have_independent_subject_tables(self):
        self.assertEqual(TenantModule.__tablename__, "tenant_modules")
        self.assertEqual(SeoSite.__tablename__, "seo_sites")
        self.assertEqual(GeoProject.__tablename__, "geo_projects")

    def test_default_customer_can_edit_own_module_assets_only(self):
        self.assertEqual(CLIENT_PERMS["sem.assets"], "edit")
        self.assertEqual(CLIENT_PERMS["seo.assets"], "edit")
        self.assertEqual(CLIENT_PERMS["geo.assets"], "edit")
        self.assertNotIn("settings.customers", CLIENT_PERMS)
        self.assertNotIn("settings.customers", OPERATOR_PERMS)

    def test_workbench_site_route_uses_content_or_site_permission(self):
        self.assertEqual(
            _required("/api/v1/seo/workbench/sites", "GET"),
            ({"seo.content", "seo.site"}, False),
        )

    def test_seo_site_routes_enforce_permission_without_global_auth_changes(self):
        viewer = AuthContext(1, "viewer", "viewer", 7, {"seo.assets": "view"})
        editor = AuthContext(2, "editor", "editor", 7, {"seo.assets": "edit"})
        denied = AuthContext(3, "denied", "denied", 7, {})

        _require_seo_asset_permission(viewer)
        _require_seo_asset_permission(editor, edit=True)
        with self.assertRaises(HTTPException):
            _require_seo_asset_permission(viewer, edit=True)
        with self.assertRaises(HTTPException):
            _require_seo_asset_permission(denied)

    def test_seo_site_router_is_isolated_and_preserved_in_shared_backend(self):
        seo_paths = {route.path for route in seo_sites_router.routes}
        shared_paths = {route.path for route in customer_modules_router.routes}

        self.assertEqual(
            seo_paths,
            {
                "/api/v1/seo/sites",
                "/api/v1/seo/sites/{site_id}",
                "/api/v1/seo/workbench/sites",
            },
        )
        delete_routes = [
            route for route in seo_sites_router.routes
            if route.path == "/api/v1/seo/sites/{site_id}" and "DELETE" in route.methods
        ]
        self.assertEqual(len(delete_routes), 1)
        self.assertTrue(seo_paths.issubset(shared_paths))
        self.assertNotIn("/api/v1/sem/assets/accounts", seo_paths)
        self.assertNotIn("/api/v1/admin/customers", seo_paths)

    def test_seo_site_admin_routes_use_local_asset_permission(self):
        for route in seo_sites_router.routes:
            if route.path == "/api/v1/seo/workbench/sites":
                continue
            dependencies = [dependency.dependency for dependency in route.dependencies]
            self.assertIn(require_auth, dependencies)
            self.assertNotIn(require_scoped_auth, dependencies)

    def test_workbench_site_route_uses_scoped_auth(self):
        route = next(
            route
            for route in seo_sites_router.routes
            if route.path == "/api/v1/seo/workbench/sites"
        )
        dependencies = [dependency.dependency for dependency in route.dependencies]
        self.assertIn(require_scoped_auth, dependencies)
        self.assertNotIn(require_auth, dependencies)

    def test_workbench_site_real_url_accepts_read_roles_without_asset_permission(self):
        rows = [SimpleNamespace(id=31, name="Active", domain="example.com", status="active")]
        six_permission_role = {
            "seo.dashboard": "view",
            "seo.alerts": "view",
            "seo.keywords": "view",
            "seo.content": "view",
            "seo.site": "view",
            "seo.links": "view",
        }
        cases = (
            ({"seo.content": "view"}, 200),
            ({"seo.site": "view"}, 200),
            (six_permission_role, 200),
            ({}, 403),
            ({"seo.assets": "view"}, 403),
        )

        for permissions, expected_status in cases:
            with self.subTest(permissions=permissions):
                ctx = AuthContext(9, "reader", "acceptance", 7, permissions)
                session = SimpleNamespace(
                    scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
                )
                app = FastAPI()
                app.include_router(seo_sites_router)

                async def scoped_auth_override():
                    return ctx

                async def session_override():
                    yield session

                app.dependency_overrides[require_scoped_auth] = scoped_auth_override
                app.dependency_overrides[get_session] = session_override
                with patch(
                    "app.api.customer_modules.ensure_module_access",
                    new=AsyncMock(),
                ) as ensure_access:
                    response = TestClient(app).get(
                        "/api/v1/seo/workbench/sites",
                        params={"tenant_id": 7},
                    )

                self.assertEqual(response.status_code, expected_status)
                if expected_status == 200:
                    self.assertEqual(response.json()["selection_policy"]["selectable_statuses"], ["active"])
                    self.assertEqual(response.json()["sites"][0]["id"], 31)
                    ensure_access.assert_awaited_once_with(session, ctx, 7, "seo")
                else:
                    ensure_access.assert_not_awaited()

    def test_bound_customer_cannot_switch_tenant(self):
        ctx = AuthContext(1, "client", "client", 7, {"seo.assets": "edit"})
        ctx.ensure_tenant(7)
        with self.assertRaises(HTTPException):
            ctx.ensure_tenant(8)

    def test_domain_normalization(self):
        self.assertEqual(_canonical_domain("https://www.Example.com/path")[0], "example.com")
        self.assertEqual(normalize_module_code("SEO"), "seo")
        with self.assertRaises(HTTPException):
            normalize_module_code("diagnosis")

    def test_seo_site_created_at_has_an_explicit_database_timezone(self):
        payload = _site_payload(
            SimpleNamespace(
                id=1,
                tenant_id=7,
                name="Example",
                domain="example.com",
                canonical_domain="example.com",
                default_url="https://example.com",
                status="active",
                created_at=datetime(2026, 8, 29, 10, 0),
            )
        )
        self.assertEqual(payload["created_at"], "2026-08-29T10:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
