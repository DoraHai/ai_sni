import os
import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
from app.geo.project_routes import GeoServicePlanUpdate, update_project_plan, project_advisor_candidates
from app.geo.project_workflows import save_plan, advisor_available, advisor_assignable, refresh_project
from app.geo.onsite_routes import can_operate, advisor_tasks
from app.models.user import User
from app.models.role import Role


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


def test_service_plan_blocks_self_assignment_and_preserves_other_edits():
    project = SimpleNamespace(tenant_id=17, project_settings={"geo_service_plan": {
        "revision": 1, "enabled": False, "status": "paused", "prompt_ids": [],
        "interval_days": 7, "advisor_user_id": None,
    }})
    session = AsyncMock()
    session.get.return_value = project
    session.scalar.return_value = 17
    values = {"enabled": False, "status": "paused", "prompt_ids": [],
              "interval_days": 10, "advisor_user_id": 7}
    with (patch("app.geo.project_workflows.project_scope", new=AsyncMock(return_value=(project, []))),
          patch("app.geo.project_workflows.prompt_ids_for_businesses", new=AsyncMock(return_value=[])),
          patch("app.geo.project_workflows.advisor_assignable", new=AsyncMock(return_value=True)) as available,
          patch("app.geo.project_workflows.logger.info") as audit_log):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(save_plan(session, 17, 3, values, 1, 7))
        assert denied.value.status_code == 403
        assert project.project_settings["geo_service_plan"]["advisor_user_id"] is None
        allowed = asyncio.run(save_plan(session, 17, 3, {**values, "advisor_user_id": None}, 1, 7))
        assert allowed["interval_days"] == 10
        assert allowed["advisor_user_id"] is None
        project.project_settings["geo_service_plan"]["revision"] = 1
        assigned = asyncio.run(save_plan(session, 17, 3, values, 1, 99, allow_advisor_change=True))
        assert assigned["advisor_user_id"] == 7
        available.assert_awaited_with(session, 17, 7, lock=True)
        audit_log.assert_called_once()
        project.project_settings["geo_service_plan"]["revision"] = 1
        project.project_settings["geo_service_plan"]["advisor_user_id"] = None
        available.return_value = False
        with pytest.raises(HTTPException) as invalid:
            asyncio.run(save_plan(session, 17, 3, values, 1, 99, allow_advisor_change=True))
        assert invalid.value.status_code == 409


def test_service_plan_route_only_grants_global_account_admin_assignment():
    req = GeoServicePlanUpdate(expected_revision=1, advisor_user_id=7)
    session = AsyncMock()
    with (patch("app.geo.project_routes.ensure_module_access", new=AsyncMock()),
          patch("app.geo.project_workflows.save_plan", new=AsyncMock(return_value={})) as writer):
        editor = AuthContext(7, "advisor", "advisor", 17,
                             {"geo.assets": "edit", "geo.content": "edit"})
        with pytest.raises(HTTPException) as denied:
            asyncio.run(update_project_plan(3, 17, req, editor, session))
        assert denied.value.status_code == 403
        writer.assert_not_awaited()
        admin = AuthContext(99, "admin", "admin", None,
                            {"geo.assets": "edit", "geo.content": "edit", "settings.accounts": "edit"})
        asyncio.run(update_project_plan(3, 17, req, admin, session))
        assert writer.call_args.kwargs["allow_advisor_change"] is True
        tenant_admin = AuthContext(98, "admin", "admin", 17,
            {"geo.assets": "edit", "geo.content": "edit", "settings.accounts": "edit"})
        with pytest.raises(HTTPException):
            asyncio.run(update_project_plan(3, 17, req, tenant_admin, session))
        with pytest.raises(HTTPException) as api_key:
            asyncio.run(update_project_plan(3, 17, req,
                AuthContext(None, "key", "key", None, {}, True), session))
        assert api_key.value.status_code == 403


def test_non_admin_cannot_clear_existing_advisor():
    project = SimpleNamespace(tenant_id=17, project_settings={"geo_service_plan": {
        "revision": 2, "enabled": False, "status": "paused", "prompt_ids": [],
        "interval_days": 7, "advisor_user_id": 7,
    }})
    session = AsyncMock()
    session.get.return_value = project
    session.scalar.return_value = 17
    values = {"enabled": False, "status": "paused", "prompt_ids": [],
              "interval_days": 7, "advisor_user_id": None}
    with pytest.raises(HTTPException) as denied:
        asyncio.run(save_plan(session, 17, 3, values, 2, 7))
    assert denied.value.status_code == 403
    assert project.project_settings["geo_service_plan"]["advisor_user_id"] == 7


def test_advisor_candidates_are_platform_admin_only():
    session = AsyncMock()
    with patch("app.geo.project_routes.ensure_module_access", new=AsyncMock()):
        for ctx in (
            AuthContext(8, "tenant-admin", "admin", 17, {"settings.accounts": "edit"}),
            AuthContext(None, "key", "key", None, {}, True),
        ):
            with pytest.raises(HTTPException) as denied:
                asyncio.run(project_advisor_candidates(3, 17, ctx, session))
            assert denied.value.status_code == 403

        admin = AuthContext(99, "platform-admin", "admin", None,
                            {"settings.accounts": "edit", "geo.assets": "edit", "geo.content": "edit"})
        session.get.return_value = SimpleNamespace(tenant_id=17)
        session.scalars.return_value = [SimpleNamespace(id=7, display_name="顾问甲", username="a"),
                                        SimpleNamespace(id=8, display_name="顾问乙", username="b")]
        async def available(_session, _tenant, user_id):
            return user_id == 7
        with patch("app.geo.project_workflows.advisor_assignable", new=available):
            result = asyncio.run(project_advisor_candidates(3, 17, admin, session))
        assert result == {"accounts": [{"id": 7, "name": "顾问甲"}]}
        candidate_query = str(session.scalars.await_args.args[0])
        assert "users.tenant_id" in candidate_query
        assert "roles.permissions" in candidate_query


def test_existing_admin_advisor_keeps_runtime_access_but_is_not_assignable():
    user = User(id=99, username="admin", role_id=5, tenant_id=None,
                is_active=True, password_hash="unused")
    role = Role(id=5, name="管理员", is_system=True, permissions={
        "geo.assets": "edit", "geo.content": "edit", "settings.accounts": "edit"})
    session = AsyncMock()
    async def get(model, _ident, **_kwargs):
        return user if model is User else role if model is Role else None
    session.get.side_effect = get
    assert asyncio.run(advisor_available(session, 17, 99)) is True
    assert asyncio.run(advisor_assignable(session, 17, 99)) is False
    project = SimpleNamespace(status="active", tenant_id=17, project_settings={
        "geo_service_plan": {"revision": 1, "advisor_user_id": 99}})
    ctx = AuthContext(99, "admin", "管理员", None, role.permissions)
    assert asyncio.run(can_operate(session, ctx, project)) is True


def test_existing_admin_advisor_remains_in_scheduler_and_task_list():
    project = SimpleNamespace(id=3, tenant_id=17, status="active", project_settings={
        "geo_service_plan": {"revision": 1, "enabled": True, "status": "active",
                             "prompt_ids": [], "interval_days": 7, "advisor_user_id": 99}})
    user = User(id=99, username="admin", role_id=5, tenant_id=None,
                is_active=True, password_hash="unused")
    role = Role(id=5, name="管理员", is_system=True, permissions={
        "geo.assets": "edit", "geo.content": "edit", "settings.accounts": "edit"})
    session = AsyncMock()
    async def get(model, _ident, **_kwargs):
        return project if model.__name__ == "GeoProject" else user if model is User else role if model is Role else None
    session.get.side_effect = get
    session.scalars.side_effect = [[project], []]
    @asynccontextmanager
    async def factory():
        yield session
    with (patch("app.geo.project_workflows.ensure_geo_background_execution_allowed"),
          patch("app.geo.project_workflows.ensure_geo_entitlement", new=AsyncMock()),
          patch("app.geo.project_workflows.project_scope", new=AsyncMock(return_value=(project, []))),
          patch("app.geo.project_workflows.prompt_ids_for_businesses", new=AsyncMock(return_value=[])),
          patch("app.geo.onsite_routes.ensure_geo_entitlement", new=AsyncMock()),
          patch("app.geo.onsite_routes.project_scope", new=AsyncMock(return_value=(project, [])))):
        asyncio.run(refresh_project(3, session_factory=factory))
        assert "geo_workflow_blocker" not in project.project_settings
        session.commit.assert_awaited_once()
        ctx = AuthContext(99, "admin", "管理员", None, role.permissions)
        result = asyncio.run(advisor_tasks(17, None, 20, session, ctx))
        assert result["items"] == []
        assert session.scalars.await_count == 2  # task query reached after accepting the project
