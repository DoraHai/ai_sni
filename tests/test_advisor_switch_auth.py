"""Old #657 derived credentials cannot bypass multi-tenant grants."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.security.advisor_switch import validate_switch_claims


def test_switch_credentials_disabled_without_reading_legacy_tables():
    session = AsyncMock()
    for payload in ({'via':'advisor_switch'}, {'via':'other'}, {'via':None}):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(validate_switch_claims(session, payload, SimpleNamespace()))
        assert denied.value.status_code == 401
    session.get.assert_not_awaited()


def test_ordinary_password_session_has_no_legacy_table_dependency():
    session = AsyncMock()
    asyncio.run(validate_switch_claims(session, {'sub':'1'}, SimpleNamespace()))
    session.get.assert_not_awaited()
