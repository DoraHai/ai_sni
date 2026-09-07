import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from tests import sem_cockpit_fixtures  # noqa: F401 - supplies isolated test settings
from app.api import search_terms


class ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class Session:
    def __init__(self, rows):
        self.rows = rows

    async def scalars(self, _statement):
        return ScalarRows(self.rows)


class Context:
    def ensure_tenant(self, tenant_id):
        assert tenant_id == 1


def run_sync(session, account_id=None):
    return asyncio.run(search_terms.sync_search_terms(
        tenant_id=1,
        baidu_account_id=account_id,
        days=30,
        ctx=Context(),
        session=session,
    ))


def test_manual_sync_rejects_ambiguous_active_accounts(monkeypatch):
    remote = AsyncMock()
    monkeypatch.setattr(search_terms, "sync_search_terms_for_account", remote)
    accounts = [SimpleNamespace(id=11), SimpleNamespace(id=12)]

    with pytest.raises(HTTPException) as error:
        run_sync(Session(accounts))

    assert error.value.status_code == 409
    remote.assert_not_awaited()


def test_manual_sync_returns_the_explicit_account(monkeypatch):
    remote = AsyncMock(return_value=7)
    monkeypatch.setattr(search_terms, "sync_search_terms_for_account", remote)
    result = run_sync(Session([SimpleNamespace(id=12)]), account_id=12)

    assert result["baidu_account_id"] == 12
    assert result["synced"] == 7
    remote.assert_awaited_once()
