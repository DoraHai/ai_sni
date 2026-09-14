import os
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from fastapi import HTTPException
from starlette.requests import Request

from app.geo.project_routes import (
    GeoProjectCreate,
    GeoProjectUpdate,
    create_geo_project,
    list_geo_projects,
    geo_projects_router,
    update_geo_project,
)
from app.module_scope import ensure_module_access
from app.security.auth import AuthContext, _required, require_scoped_auth


def _context(tenant_id: int, level: str = "edit") -> AuthContext:
    return AuthContext(7, "geo-user", "GEO 用户", tenant_id, {"geo.assets": level})


def _request(method: str, path: str, query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query.encode(),
            "headers": [],
        }
    )


class GeoProjectRouteTests(unittest.IsolatedAsyncioTestCase):
    def test_router_exposes_get_post_and_patch_once(self):
        methods = {
            (route.path, method)
            for route in geo_projects_router.routes
            for method in (route.methods or set())
        }
        self.assertIn(("/api/v1/geo/projects", "GET"), methods)
        self.assertIn(("/api/v1/geo/projects", "POST"), methods)
        self.assertIn(("/api/v1/geo/projects/{project_id}", "PATCH"), methods)
        self.assertEqual(
            len([route for route in geo_projects_router.routes if route.path == "/api/v1/geo/projects"]),
            2,
        )

    def test_permission_registry_requires_geo_asset_edit_for_writes(self):
        self.assertEqual(_required("/api/v1/geo/projects", "GET"), ({"geo.assets"}, False))
        self.assertEqual(_required("/api/v1/geo/projects", "POST"), ({"geo.assets"}, True))
        self.assertEqual(_required("/api/v1/geo/projects/3", "PATCH"), ({"geo.assets"}, True))

    async def test_viewer_can_read_but_cannot_write(self):
        viewer = _context(17, "view")
        allowed = await require_scoped_auth(
            _request("GET", "/api/v1/geo/projects", "tenant_id=17"),
            viewer,
        )
        self.assertIs(allowed, viewer)
        with self.assertRaises(HTTPException) as caught:
            await require_scoped_auth(
                _request("POST", "/api/v1/geo/projects"),
                viewer,
            )
        self.assertEqual(caught.exception.status_code, 403)

    async def test_shared_module_gate_rejects_cross_tenant_and_expired_geo(self):
        active = SimpleNamespace(status="active", expires_at=None)
        session = SimpleNamespace(scalar=AsyncMock(return_value=active))
        with self.assertRaises(HTTPException) as cross_tenant:
            await ensure_module_access(session, _context(17), 18, "geo")
        self.assertEqual(cross_tenant.exception.status_code, 403)

        expired = SimpleNamespace(
            status="trial",
            expires_at=date.today() - timedelta(days=1),
        )
        session.scalar = AsyncMock(return_value=expired)
        with self.assertRaises(HTTPException) as inactive:
            await ensure_module_access(session, _context(17), 17, "geo")
        self.assertEqual(inactive.exception.status_code, 403)

    async def test_list_applies_module_gate_and_tenant_filter(self):
        statements = []
        result = SimpleNamespace(all=lambda: [])

        async def scalars(statement):
            statements.append(statement)
            return result

        session = SimpleNamespace(scalars=scalars)
        gate = AsyncMock(return_value=SimpleNamespace(id=11))
        with patch("app.geo.project_routes.ensure_module_access", gate):
            response = await list_geo_projects(17, _context(17, "view"), session)

        self.assertEqual(response, {"projects": []})
        gate.assert_awaited_once_with(session, unittest.mock.ANY, 17, "geo")
        compiled = statements[0].compile()
        self.assertIn("geo_projects.tenant_id", str(statements[0]))
        self.assertIn(17, compiled.params.values())

    async def test_create_stops_before_mutation_when_module_is_unavailable(self):
        session = SimpleNamespace(
            add=Mock(),
            commit=AsyncMock(),
            rollback=AsyncMock(),
            refresh=AsyncMock(),
        )
        denial = HTTPException(403, "当前客户的 GEO 模块未启用或已过期")
        with patch("app.geo.project_routes.ensure_module_access", AsyncMock(side_effect=denial)):
            with self.assertRaises(HTTPException) as caught:
                await create_geo_project(
                    GeoProjectCreate(tenant_id=17, name="项目", domain="example.com"),
                    _context(17),
                    session,
                )

        self.assertEqual(caught.exception.status_code, 403)
        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    async def test_update_cannot_cross_tenant_boundary(self):
        foreign = SimpleNamespace(id=9, tenant_id=18)
        session = SimpleNamespace(
            get=AsyncMock(return_value=foreign),
            commit=AsyncMock(),
            rollback=AsyncMock(),
            refresh=AsyncMock(),
        )
        gate = AsyncMock(return_value=SimpleNamespace(id=12))
        with patch("app.geo.project_routes.ensure_module_access", gate):
            with self.assertRaises(HTTPException) as caught:
                await update_geo_project(
                    9,
                    17,
                    GeoProjectUpdate(name="不能修改"),
                    _context(17),
                    session,
                )

        self.assertEqual(caught.exception.status_code, 404)
        gate.assert_awaited_once_with(session, unittest.mock.ANY, 17, "geo")
        session.commit.assert_not_awaited()


class GeoProjectAppRegistrationTests(unittest.TestCase):
    def test_main_and_geo_service_mount_the_same_project_paths(self):
        from app.geo_main import app as geo_app
        from app.main import app as main_app

        expected = {
            ("/api/v1/geo/projects", "GET"),
            ("/api/v1/geo/projects", "POST"),
            ("/api/v1/geo/projects/{project_id}", "PATCH"),
        }

        def project_methods(app):
            return {
                (route.path, method)
                for route in app.routes
                if route.path.startswith("/api/v1/geo/projects")
                for method in (route.methods or set())
            }

        self.assertEqual(project_methods(main_app), expected)
        self.assertEqual(project_methods(geo_app), expected)


if __name__ == "__main__":
    unittest.main()
