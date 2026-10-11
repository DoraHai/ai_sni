import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api import customer_modules as api
from app.security.auth import AuthContext


def actor(permission="edit", tenant=1):
    return AuthContext(7,"operator","test",tenant,{"seo.assets":permission})


def execute(session, ctx=None, domain="example.com"):
    with patch.object(api,"ensure_module_access",new=AsyncMock()):
        return asyncio.run(api.delete_seo_site(10,1,domain,ctx or actor(),session))


def fixture():
    session=AsyncMock()
    row=SimpleNamespace(id=10,tenant_id=1,canonical_domain="example.com")
    session.scalar.side_effect=[row,True]
    return session,row


def test_site_delete_accepts_populated_site_and_commits_once():
    session,row=fixture()
    assert execute(session)=={"deleted":True,"site_id":10}
    session.delete.assert_awaited_once_with(row)
    session.commit.assert_awaited_once()
    assert "FOR UPDATE" in str(session.scalar.call_args_list[0].args[0])


@pytest.mark.parametrize("ctx",[actor("view"),actor(tenant=2)])
def test_site_delete_permission_and_tenant_isolation(ctx):
    session,_=fixture()
    with pytest.raises(HTTPException) as error:execute(session,ctx)
    assert error.value.status_code==403
    session.delete.assert_not_awaited()


@pytest.mark.parametrize("case,code",[("missing",404),("confirmation",409),("migration",503),("integrity",409)])
def test_delete_fails_without_mutation_or_rolls_back(case,code):
    session,row=fixture()
    if case=="missing":session.scalar.side_effect=[None]
    if case=="migration":session.scalar.side_effect=[row,False]
    if case=="integrity":session.commit.side_effect=IntegrityError("delete",{},Exception("fk"))
    with pytest.raises(HTTPException) as error:
        execute(session,domain="different.com" if case=="confirmation" else "example.com")
    assert error.value.status_code==code
    if case=="integrity":session.rollback.assert_awaited_once()
    else:session.delete.assert_not_awaited()


def test_archiving_is_removed_only_for_seo_sites():
    with pytest.raises(ValidationError):api.SeoSiteUpdate(status="archived")
    assert api.SeoSiteUpdate(status="paused").status=="paused"
    assert api.GeoProjectUpdate(status="archived").status=="archived"
