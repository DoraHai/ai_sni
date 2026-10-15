"""Offline switch JWT revocation checks shared with GEO."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import DBAPIError

from app.models.advisor_account import AdvisorAccountLink
from app.models.role import Role
from app.models.user import User
from app.security.auth import JWT_ALG, _jwt_secret, require_auth


def test_switch_claims_rechecked_on_every_request():
    group = uuid4()
    users = {i: User(id=i, username=f"advisor{i}", role_id=1, tenant_id=i * 10,
                     is_active=True, password_hash="unused") for i in (1, 2, 3)}
    roles = {1: Role(id=1, name="顾问", is_system=False,
                     permissions={"seo.site": "edit", "seo.content": "edit"}),
             2: Role(id=2, name="管理员", is_system=True,
                     permissions={"seo.site": "edit", "seo.content": "edit",
                                  "settings.accounts": "edit"})}
    links = {i: SimpleNamespace(group_id=group, tenant_id=i * 10) for i in users}
    session = AsyncMock()

    async def get(model, ident, **_kwargs):
        if model is User:
            return users.get(ident)
        if model is Role:
            return roles.get(ident)
        if model is AdvisorAccountLink:
            return links.get(ident)
        return None

    session.get.side_effect = get
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {"sub": "3", "via": "advisor_switch", "src": 2, "root_src": 1,
              "grp": str(group), "auth_exp": now + 3600, "exp": now + 1800}

    def authenticate(payload=claims):
        token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALG)
        bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        return asyncio.run(require_auth(bearer, None, None, session))

    assert authenticate().user_id == 3
    users[1].is_active = False
    with pytest.raises(HTTPException) as denied:
        authenticate()
    assert denied.value.status_code == 401
    users[1].is_active = True
    users[2].is_active = False
    with pytest.raises(HTTPException) as denied:
        authenticate()
    assert denied.value.status_code == 401
    users[2].is_active = True
    links[1].group_id = uuid4()
    with pytest.raises(HTTPException) as denied:
        authenticate()
    assert denied.value.status_code == 401
    links[1].group_id = group
    links[3].tenant_id = 999
    with pytest.raises(HTTPException) as denied:
        authenticate()
    assert denied.value.status_code == 401
    links[3].tenant_id = 30
    links.pop(2)
    with pytest.raises(HTTPException) as denied:
        authenticate()
    assert denied.value.status_code == 401
    links[2] = SimpleNamespace(group_id=group, tenant_id=20)
    users[3].role_id = 2
    with pytest.raises(HTTPException) as denied:
        authenticate()
    assert denied.value.status_code == 401
    users[3].role_id = 1
    with pytest.raises(HTTPException) as denied:
        authenticate({**claims, "exp": now + 3601})
    assert denied.value.status_code == 401

    async def missing(model, ident, **kwargs):
        if model is AdvisorAccountLink:
            raise DBAPIError("SELECT", {}, SimpleNamespace(sqlstate="42P01"))
        return await get(model, ident, **kwargs)

    session.get.side_effect = missing
    with pytest.raises(HTTPException) as denied:
        authenticate()
    assert denied.value.status_code == 401
    # Password sessions do not depend on the pending association table.
    assert authenticate({"sub": "3", "exp": now + 1800}).user_id == 3
