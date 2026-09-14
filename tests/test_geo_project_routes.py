import os
import asyncio
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
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

from app.geo_main import app
from app.module_scope import ensure_module_access, module_is_available
from app.security.auth import AuthContext, _required, require_scoped_auth


class ScalarSession:
    def __init__(self, value):
        self.value = value

    async def scalar(self, _statement):
        return self.value


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


def test_independent_geo_app_registers_project_contract():
    methods_by_path = {}
    for route in app.routes:
        if getattr(route, "methods", None):
            methods_by_path.setdefault(route.path, set()).update(route.methods)
    assert "GET" in methods_by_path["/api/v1/geo/projects"]
    assert "POST" in methods_by_path["/api/v1/geo/projects"]
    assert "PATCH" in methods_by_path["/api/v1/geo/projects/{project_id}"]


def test_project_permission_requires_geo_assets_at_matching_access_level():
    assert _required("/api/v1/geo/projects", "GET") == ({"geo.assets"}, False)
    assert _required("/api/v1/geo/projects/4", "PATCH") == ({"geo.assets"}, True)

    viewer = AuthContext(1, "viewer", "viewer", 17, {"geo.assets": "view"})
    asyncio.run(require_scoped_auth(_request("GET", "/api/v1/geo/projects", "tenant_id=17"), viewer))
    with pytest.raises(HTTPException) as denied:
        asyncio.run(
            require_scoped_auth(
                _request("POST", "/api/v1/geo/projects"),
                viewer,
            )
        )
    assert denied.value.status_code == 403


def test_project_module_gate_rejects_cross_tenant_and_inactive_geo():
    active = SimpleNamespace(status="active", expires_at=None)
    bound = AuthContext(1, "customer", "customer", 17, {"geo.assets": "edit"})
    with pytest.raises(HTTPException) as cross_tenant:
        asyncio.run(ensure_module_access(ScalarSession(active), bound, 18, "geo"))
    assert cross_tenant.value.status_code == 403

    expired = SimpleNamespace(status="trial", expires_at=date.today() - timedelta(days=1))
    with pytest.raises(HTTPException) as inactive:
        asyncio.run(ensure_module_access(ScalarSession(expired), bound, 17, "geo"))
    assert inactive.value.status_code == 403
    assert module_is_available(SimpleNamespace(status="trial", expires_at=date.today()))


def test_project_navigation_and_route_are_visible_in_geo_source():
    root = Path(__file__).resolve().parents[1]
    nav = (root / "frontend/src/utils/geoPrototypeNavigation.js").read_text(encoding="utf-8")
    router = (root / "frontend/geo-frontend/src/router.js").read_text(encoding="utf-8")
    view = (root / "frontend/src/views/geo/GeoProjectsView.vue").read_text(encoding="utf-8")
    assert "label: '项目管理', path: '/geo/projects', key: 'geo.assets'" in nav
    assert "path: 'projects'" in router
    assert "perm: 'geo.assets'" in router
    assert "fetchGeoProjects" in view
