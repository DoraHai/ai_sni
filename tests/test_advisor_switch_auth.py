"""SEO rollback rejects switch sessions while preserving ordinary JWT login."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.models.role import Role
from app.models.user import User
from app.security.auth import JWT_ALG, require_auth


@pytest.mark.parametrize("via", ["advisor_switch", "other", None])
def test_switch_marker_is_rejected_before_account_lookup(via):
    session = AsyncMock()
    claims = {
        "sub": "3",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        "via": via,
    }
    token = jwt.encode(claims, "test-only-secret", algorithm=JWT_ALG)
    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with patch("app.security.auth._jwt_secret", return_value="test-only-secret"):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(require_auth(bearer, None, None, session))

    assert denied.value.status_code == 401
    session.get.assert_not_awaited()


def test_ordinary_jwt_still_builds_account_context():
    user = User(id=3, username="ordinary", role_id=2, tenant_id=7,
                is_active=True, password_hash="unused")
    role = Role(id=2, name="operator", permissions={"seo.content": "view"})
    session = AsyncMock()

    async def get(model, ident):
        if model is User and ident == 3:
            return user
        if model is Role and ident == 2:
            return role
        return None

    session.get.side_effect = get
    token = jwt.encode({"sub": "3", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)},
                       "test-only-secret", algorithm=JWT_ALG)
    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with patch("app.security.auth._jwt_secret", return_value="test-only-secret"):
        ctx = asyncio.run(require_auth(bearer, None, None, session))

    assert (ctx.user_id, ctx.tenant_id, ctx.permissions) == (3, 7, {"seo.content": "view"})
    assert session.get.await_count == 2
