"""Old #657 derived JWTs must fail in GEO without consulting old link tables."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from app.models.user import User
from app.security.auth import JWT_ALG, _jwt_secret, require_auth


def test_legacy_switch_always_closed():
    session = AsyncMock()
    session.get.return_value = User(id=1, username="advisor", role_id=1, tenant_id=10,
                                   is_active=True, password_hash="unused")
    now = int(datetime.now(timezone.utc).timestamp())
    for via in ("advisor_switch", "unknown"):
        payload = {"sub": "1", "exp": now+600, "via": via}
        bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALG))
        with pytest.raises(HTTPException) as denied:
            asyncio.run(require_auth(bearer, None, None, session))
        assert denied.value.status_code == 401
