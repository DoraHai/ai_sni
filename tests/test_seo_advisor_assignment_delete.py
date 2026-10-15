"""Deletion of a site advisor assignment stays within its tenant and site."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:1/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.seo import delete_advisor_assignment, router
from app.security.auth import AuthContext


def _ctx(*, tenant_id=None, permissions=None, user_id=7):
    return AuthContext(
        user_id=user_id,
        username="test-admin",
        role_name="管理员",
        tenant_id=tenant_id,
        permissions=permissions if permissions is not None else {
            "seo.content": "edit", "settings.accounts": "edit",
        },
    )


def _delete(session, ctx, *, tenant_id=1, site_id=9):
    return asyncio.run(delete_advisor_assignment(
        assignment_id=42, tenant_id=tenant_id, site_id=site_id,
        session=session, ctx=ctx,
    ))


def test_delete_assignment_in_validated_scope():
    assert any(
        route.path.endswith("/workbench/advisor-assignments/{assignment_id}")
        and "DELETE" in route.methods
        for route in router.routes
    )
    row = SimpleNamespace(id=42, tenant_id=1, site_id=9)
    session = AsyncMock()
    session.get.return_value = row
    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._seo_site", new=AsyncMock(return_value=object())) as site,
    ):
        assert _delete(session, _ctx()) == {"status": "ok"}
    site.assert_awaited_once_with(session, 1, 9)
    session.get.assert_awaited_once()
    assert session.get.call_args.kwargs["with_for_update"] is True
    session.delete.assert_awaited_once_with(row)
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("ctx", [
    _ctx(permissions={"seo.content": "edit", "settings.accounts": "view"}),
    _ctx(permissions={"seo.content": "view", "settings.accounts": "edit"}),
    _ctx(user_id=None),
    _ctx(tenant_id=2),
])
def test_delete_assignment_forbidden_without_full_scope_and_permission(ctx):
    session = AsyncMock()
    with patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)):
        with pytest.raises(HTTPException) as exc:
            _delete(session, ctx)
    assert exc.value.status_code == 403
    session.get.assert_not_awaited()
    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("row", [
    None,
    SimpleNamespace(id=42, tenant_id=2, site_id=9),
    SimpleNamespace(id=42, tenant_id=1, site_id=10),
])
def test_delete_assignment_missing_or_outside_scope_returns_404(row):
    session = AsyncMock()
    session.get.return_value = row
    with (
        patch("app.api.seo._content_confirmation_schema_ready", new=AsyncMock(return_value=True)),
        patch("app.api.seo._seo_site", new=AsyncMock(return_value=object())),
    ):
        with pytest.raises(HTTPException) as exc:
            _delete(session, _ctx())
    assert exc.value.status_code == 404
    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()
