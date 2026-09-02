"""Regression contracts for the 2026-08-25 strict SEM audit fixes."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.baidu.writeback import WritebackError, _active_account


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows

    async def scalars(self, _statement):
        return _ScalarRows(self.rows)


def test_anonymous_baidu_account_info_route_is_removed():
    source = _read("app/main.py")
    assert '"/api/baidu/account/info"' not in source


def test_writebacks_never_guess_an_active_account_for_an_asset():
    source = _read("app/baidu/writeback.py")
    assert "_active_account(session, tenant_id)" not in source
    assert source.count("_asset_account_id(") >= 11


def test_multiple_active_accounts_require_explicit_selection():
    rows = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    with pytest.raises(WritebackError, match="必须明确选择"):
        asyncio.run(_active_account(_Session(rows), 3))


def test_background_sem_work_is_entitlement_scoped():
    scheduler = _read("app/scheduler.py")
    sync = _read("app/baidu/sync.py")
    rules = _read("app/rules/engine.py") + _read("app/rules/site_health.py")
    suggestions = _read("app/suggestions/engine.py")
    assert "await list_active_sem_accounts(session)" in scheduler
    assert scheduler.count("await _scheduled_account_refs(session)") >= 3
    assert "list_active_sem_accounts" in sync
    assert rules.count("list_active_module_tenants") >= 2
    assert "list_active_module_tenants" in suggestions


def test_smart_builder_cannot_real_write_without_its_own_approval_flow():
    source = _read("app/api/onboarding_builder.py")
    dry_run_guard = source.index("if any(", source.index('router.post("/apply")'))
    first_service = source.index("CampaignService(client)", dry_run_guard)
    assert dry_run_guard < first_service
    assert "智能搭建真实执行暂未启用" in source[dry_run_guard:first_service]
    assert "dry_run = True" in source[dry_run_guard:first_service]
    preheat = source[source.index("async def _preheat_expansion_candidates"):source.index("def _creative_items")]
    assert '"message": str(e)' not in preheat
    assert '"message": e.message' not in preheat


def test_frontend_release_records_exact_git_commit():
    script = _read("frontend/scripts/deploy-sem.sh")
    assert "Refusing to deploy from a dirty Git worktree" in script
    assert "DEPLOYED_GIT_COMMIT" in script
    assert "${release_stamp}-${git_short}" in script
