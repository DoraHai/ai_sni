import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
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

from app.api import customer_modules as api
from app.security.auth import AuthContext, _required


class ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def context(*, tenant_id=7, permissions=None, superadmin=False):
    return AuthContext(
        user_id=1,
        username="viewer",
        role_name="viewer",
        tenant_id=tenant_id,
        permissions=permissions or {},
        is_superadmin=superadmin,
    )


def site(site_id, status):
    return SimpleNamespace(
        id=site_id,
        tenant_id=7,
        name=f"Site {site_id}",
        domain=f"site-{site_id}.example",
        status=status,
    )


def test_workbench_site_scope_has_explicit_read_permission_mapping():
    assert _required("/api/v1/seo/workbench/sites", "GET") == (
        {"seo.content", "seo.site"},
        False,
    )
    # Existing SEO routes keep the production branch's seo.site mapping; the
    # workbench selector is the narrowly scoped exception under test here.
    assert _required("/api/v1/seo/sites", "GET") == ({"seo.site"}, False)


@pytest.mark.parametrize("permission", ["seo.content", "seo.site"])
def test_content_or_site_viewer_can_list_minimal_tenant_sites(monkeypatch, permission):
    module_guard = AsyncMock()
    monkeypatch.setattr(api, "ensure_module_access", module_guard)
    db = SimpleNamespace(scalars=AsyncMock(return_value=ScalarRows([
        site(1, "active"),
        site(2, "paused"),
        site(3, "archived"),
    ])))

    result = asyncio.run(
        api.list_seo_workbench_sites(
            tenant_id=7,
            ctx=context(permissions={permission: "view"}),
            session=db,
        )
    )

    module_guard.assert_awaited_once_with(db, context(permissions={permission: "view"}), 7, "seo")
    assert result["tenant_id"] == 7
    assert result["selection_policy"] == {
        "selectable_statuses": ["active"],
        "disabled_statuses": ["paused", "archived"],
    }
    assert [row["status"] for row in result["sites"]] == ["active", "paused", "archived"]
    assert all(set(row) == {"id", "name", "domain", "status"} for row in result["sites"])


def test_site_scope_rejects_identity_bound_to_another_tenant():
    db = SimpleNamespace(scalar=AsyncMock(side_effect=AssertionError("database must not be read")))

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            api.list_seo_workbench_sites(
                tenant_id=8,
                ctx=context(tenant_id=7, permissions={"seo.content": "view"}),
                session=db,
            )
        )

    assert error.value.status_code == 403
    db.scalar.assert_not_awaited()


def test_site_scope_rejects_missing_or_inactive_seo_module(monkeypatch):
    module_guard = AsyncMock(side_effect=HTTPException(403, "SEO module unavailable"))
    monkeypatch.setattr(api, "ensure_module_access", module_guard)
    db = SimpleNamespace(scalars=AsyncMock())

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            api.list_seo_workbench_sites(
                tenant_id=7,
                ctx=context(permissions={"seo.site": "view"}),
                session=db,
            )
        )

    assert error.value.status_code == 403
    db.scalars.assert_not_awaited()


def test_site_scope_rejects_identity_without_content_or_site_view(monkeypatch):
    module_guard = AsyncMock()
    monkeypatch.setattr(api, "ensure_module_access", module_guard)
    db = SimpleNamespace(scalars=AsyncMock())

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            api.list_seo_workbench_sites(
                tenant_id=7,
                ctx=context(permissions={"seo.assets": "view"}),
                session=db,
            )
        )

    assert error.value.status_code == 403
    module_guard.assert_not_awaited()
    db.scalars.assert_not_awaited()


def test_site_scope_empty_result_is_an_authorized_empty_list(monkeypatch):
    monkeypatch.setattr(api, "ensure_module_access", AsyncMock())
    db = SimpleNamespace(scalars=AsyncMock(return_value=ScalarRows([])))

    result = asyncio.run(
        api.list_seo_workbench_sites(
            tenant_id=7,
            ctx=context(permissions={"seo.content": "edit"}),
            session=db,
        )
    )

    assert result["sites"] == []
    assert result["selection_policy"]["selectable_statuses"] == ["active"]


def test_superadmin_must_still_supply_and_qualify_tenant_scope(monkeypatch):
    module_guard = AsyncMock()
    monkeypatch.setattr(api, "ensure_module_access", module_guard)
    db = SimpleNamespace(scalars=AsyncMock(return_value=ScalarRows([site(1, "active")])))
    admin = context(tenant_id=None, superadmin=True)

    result = asyncio.run(api.list_seo_workbench_sites(tenant_id=7, ctx=admin, session=db))

    assert result["tenant_id"] == 7
    module_guard.assert_awaited_once_with(db, admin, 7, "seo")
