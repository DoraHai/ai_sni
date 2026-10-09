import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api import seo
from app.models.seo import SeoKeywordAsset, SeoRankSnapshot, SeoSerpResult, SeoSitePage, SeoContentAsset
from app.security.auth import AuthContext, _required


def context(permission="edit", tenant=1):
    return AuthContext(7, "operator", "test", tenant, {"seo.keywords": permission})


def fixture():
    session = AsyncMock()
    row = SeoKeywordAsset(id=11, tenant_id=1, site_id=8, keyword="测试词")
    session.scalar.return_value = row
    assets = [SimpleNamespace(keyword_ids=[11, 22, 11]), SimpleNamespace(keyword_ids=[11])]
    session.scalars.return_value = MagicMock(all=lambda: assets)
    return session, row, assets


def test_delete_cleans_all_json_references_and_commits_once():
    session, row, assets = fixture()
    with patch.object(seo, "_require_resource_operational_site", new=AsyncMock()) as gate:
        result = asyncio.run(seo.delete_seo_keyword(11, 1, session, context()))
    assert result == {"deleted": True, "keyword_id": 11}
    assert [a.keyword_ids for a in assets] == [[22], []]
    session.delete.assert_awaited_once_with(row)
    session.flush.assert_awaited_once()
    session.commit.assert_awaited_once()
    gate.assert_awaited_once_with(session, 1, 8)
    # Both the keyword lookup and JSON cleanup are tenant-scoped and row-locked.
    for statement in [session.scalar.call_args.args[0], session.scalars.call_args.args[0]]:
        assert "tenant_id" in str(statement)
        assert "FOR UPDATE" in str(statement)


@pytest.mark.parametrize("ctx", [context("view"), context(tenant=2)])
def test_delete_denies_viewers_and_other_tenants_before_database_access(ctx):
    session, _, _ = fixture()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(seo.delete_seo_keyword(11, 1, session, ctx))
    assert exc.value.status_code == 403
    session.scalar.assert_not_awaited()
    session.delete.assert_not_awaited()


def test_missing_or_other_tenant_keyword_returns_404():
    session, _, _ = fixture()
    session.scalar.return_value = None
    with pytest.raises(HTTPException) as exc:
        asyncio.run(seo.delete_seo_keyword(11, 1, session, context()))
    assert exc.value.status_code == 404
    session.delete.assert_not_awaited()


def test_non_operational_site_prevents_delete():
    session, _, _ = fixture()
    with patch.object(seo, "_require_resource_operational_site", new=AsyncMock(side_effect=HTTPException(403, "paused"))):
        with pytest.raises(HTTPException):
            asyncio.run(seo.delete_seo_keyword(11, 1, session, context()))
    session.scalars.assert_not_awaited()
    session.delete.assert_not_awaited()


def test_integrity_failure_rolls_back_instead_of_reporting_success():
    session, _, _ = fixture()
    session.commit.side_effect = IntegrityError("delete", {}, Exception("fk"))
    with patch.object(seo, "_require_resource_operational_site", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(seo.delete_seo_keyword(11, 1, session, context()))
    assert exc.value.status_code == 409
    session.rollback.assert_awaited_once()


def test_route_permission_and_reference_retention_contract():
    assert _required("/api/v1/seo/keywords/11", "DELETE") == ({"seo.keywords"}, True)
    assert any(route.path == "/api/v1/seo/keywords/{keyword_id}" and "DELETE" in route.methods for route in seo.router.routes)
    for model, column, action in [(SeoRankSnapshot, "keyword_id", "CASCADE"), (SeoSerpResult, "keyword_id", "CASCADE"),
                                   (SeoSitePage, "target_keyword_id", "SET NULL"), (SeoContentAsset, "keyword_id", "SET NULL")]:
        fk, = model.__table__.c[column].foreign_keys
        assert fk.ondelete == action
