from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
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

from app.api.customer_modules import (
    SemLiveWritePolicyUpdate,
    _sem_live_write_policy_payload,
    set_sem_execution_policy,
)
from app.api.writeback import get_writeback_mode
from app.sem_live_write_policy import (
    POLICY_HISTORY_LIMIT,
    POLICY_KEY,
    SemLiveWritePolicyLimitError,
    build_policy_update,
    empty_policy,
    resolve_live_write_decision,
)


ROOT = Path(__file__).resolve().parents[1]


def _account_policy(*, enabled=True, scopes=None, daily=5, bid=10.0):
    return {
        "version": 1,
        "enabled": enabled,
        "accounts": {
            "17": {
                "enabled": enabled,
                "scopes": scopes or ["keyword_bid"],
                "daily_live_action_limit": daily,
                "max_bid_change_pct": bid,
            }
        },
        "history": [],
        "updated_at": "2026-09-11T00:00:00+00:00",
        "updated_by": {"user_id": 1, "username": "admin"},
        "change_reason": "initial policy",
    }


def _module(raw=None, *, status="active"):
    return SimpleNamespace(
        tenant_id=3,
        module_code="sem",
        status=status,
        expires_at=None,
        module_settings={} if raw is None else {POLICY_KEY: raw},
    )


def _settings(*, legacy_allowed=True):
    return SimpleNamespace(
        baidu_write_dry_run=False,
        baidu_legacy_split_confirmation_enabled=False,
        baidu_live_write_allowed=lambda tenant, account, scope: (
            legacy_allowed and tenant == 3 and account == 17 and scope == "keyword_bid"
        ),
    )


def _decision_session(module, *counts):
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[module, *counts]))
    return session


def test_saved_policy_is_authoritative_and_revocation_is_immediate():
    allowed_session = _decision_session(_module(_account_policy()), 0, 0)
    allowed = asyncio.run(resolve_live_write_decision(
        allowed_session,
        _settings(), tenant_id=3, account_id=17, write_scope="keyword_bid",
    ))
    revoked = asyncio.run(resolve_live_write_decision(
        _decision_session(_module(_account_policy(enabled=False)), 0, 0),
        _settings(), tenant_id=3, account_id=17, write_scope="keyword_bid",
    ))
    wrong_account = asyncio.run(resolve_live_write_decision(
        _decision_session(_module(_account_policy()), 0, 0),
        _settings(), tenant_id=3, account_id=18, write_scope="keyword_bid",
    ))

    assert allowed.dry_run is False and allowed.source == "policy"
    assert "FOR UPDATE" in str(allowed_session.scalar.await_args_list[0].args[0]).upper()
    assert revoked.dry_run is True and revoked.reason == "grant_missing_or_paused"
    assert wrong_account.dry_run is True


def test_missing_or_invalid_policy_fails_closed_except_bounded_legacy_fallback():
    legacy = asyncio.run(resolve_live_write_decision(
        _decision_session(_module(), 0, 0),
        _settings(), tenant_id=3, account_id=17, write_scope="keyword_bid",
    ))
    invalid = asyncio.run(resolve_live_write_decision(
        _decision_session(_module({"enabled": True})),
        _settings(), tenant_id=3, account_id=17, write_scope="keyword_bid",
    ))
    stopped = asyncio.run(resolve_live_write_decision(
        _decision_session(_module(_account_policy(), status="suspended")),
        _settings(), tenant_id=3, account_id=17, write_scope="keyword_bid",
    ))

    assert legacy.dry_run is False and legacy.source == "legacy_environment"
    assert invalid.dry_run is True and invalid.reason == "invalid_policy"
    assert stopped.dry_run is True and stopped.reason == "sem_module_unavailable"


def test_daily_and_bid_limits_reject_before_live_attempt():
    with pytest.raises(SemLiveWritePolicyLimitError, match="今日真实动作额度不足"):
        asyncio.run(resolve_live_write_decision(
            _decision_session(_module(_account_policy(daily=2)), 1, 1),
            _settings(), tenant_id=3, account_id=17, write_scope="keyword_bid",
        ))
    with pytest.raises(SemLiveWritePolicyLimitError, match="单次上限 8%"):
        asyncio.run(resolve_live_write_decision(
            _decision_session(_module(_account_policy(bid=8)), 0, 0),
            _settings(), tenant_id=3, account_id=17, write_scope="keyword_bid",
            bid_change_pct=8.1,
        ))


def test_policy_update_preserves_other_accounts_and_bounds_history():
    current = empty_policy()
    for index in range(POLICY_HISTORY_LIMIT + 3):
        current = build_policy_update(
            None if index == 0 else current,
            account_id=17,
            enabled=True,
            scopes={"keyword_bid"},
            daily_limit=5,
            max_bid_change_pct=10,
            change_reason=f"change {index}",
            actor_user_id=1,
            actor_username="admin",
            now=datetime(2026, 9, 11, tzinfo=timezone.utc),
        )
    current = build_policy_update(
        current,
        account_id=18,
        enabled=False,
        scopes=set(),
        daily_limit=3,
        max_bid_change_pct=5,
        change_reason="pause second account",
        actor_user_id=1,
        actor_username="admin",
    )
    assert current["enabled"] is True
    assert current["accounts"]["17"]["enabled"] is True
    assert current["accounts"]["18"]["enabled"] is False
    assert len(current["history"]) == POLICY_HISTORY_LIMIT


def test_admin_update_rejects_cross_tenant_account_before_policy_write():
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    ctx = SimpleNamespace(user_id=1, username="admin")
    request = SemLiveWritePolicyUpdate(
        enabled=False,
        scopes=[],
        daily_live_action_limit=5,
        max_bid_change_pct=10,
        expected_version=0,
        change_reason="pause invalid account",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(set_sem_execution_policy(3, 99, request, ctx, session))
    assert exc.value.status_code == 404
    assert session.commit.await_count == 0
    query = str(session.scalar.await_args_list[0].args[0])
    assert "baidu_accounts.tenant_id" in query and "baidu_accounts.id" in query


def test_admin_update_uses_optimistic_version_and_returns_no_credentials():
    account = SimpleNamespace(
        id=17, tenant_id=3, baidu_username="Tiger SEM", baidu_ucid=50661708,
        status="active", access_token_encrypted="must-not-leak",
    )
    module = _module()
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[account, module]),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [account])),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    ctx = SimpleNamespace(user_id=1, username="admin")
    request = SemLiveWritePolicyUpdate(
        enabled=True,
        scopes=["keyword_bid"],
        daily_live_action_limit=5,
        max_bid_change_pct=8,
        expected_version=0,
        change_reason="approved limited rollout",
    )

    result = asyncio.run(set_sem_execution_policy(3, 17, request, ctx, session))

    assert result["version"] == 1
    assert result["accounts"][0]["enabled"] is True
    assert "token" not in repr(result).lower()
    assert module.module_settings[POLICY_KEY]["updated_by"] == {
        "user_id": 1, "username": "admin",
    }

    conflict_session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[account, module]),
        commit=AsyncMock(),
    )
    with pytest.raises(HTTPException, match="其他管理员更新"):
        asyncio.run(set_sem_execution_policy(3, 17, request, ctx, conflict_session))
    conflict_session.commit.assert_not_awaited()


def test_mode_read_uses_saved_policy_and_reads_quota_without_locking(monkeypatch):
    account = SimpleNamespace(id=17, baidu_username="Tiger SEM", baidu_ucid=50661708)
    module = _module(_account_policy(daily=5, bid=8))
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [account])),
        scalar=AsyncMock(side_effect=[1, 0]),
    )
    ctx = SimpleNamespace(ensure_tenant=lambda _tenant_id: None)
    monkeypatch.setattr("app.api.writeback.ensure_module_access", AsyncMock(return_value=module))
    monkeypatch.setattr("app.api.writeback.ensure_sem_identity_access", AsyncMock())
    monkeypatch.setattr("app.api.writeback.get_settings", lambda: _settings(legacy_allowed=False))

    result = asyncio.run(get_writeback_mode(3, ctx, session))

    assert result["accounts"][0]["policy_source"] == "policy"
    assert result["accounts"][0]["daily_live_actions_used"] == 1
    assert result["accounts"][0]["daily_live_action_limit"] == 5
    assert result["accounts"][0]["max_bid_change_pct"] == 8
    assert all("FOR UPDATE" not in str(call.args[0]).upper() for call in session.scalar.await_args_list)


def test_admin_payload_distinguishes_inherited_legacy_grant_from_default_dry_run(monkeypatch):
    account = SimpleNamespace(
        id=17, baidu_username="Tiger SEM", baidu_ucid=50661708, status="active"
    )
    monkeypatch.setattr(
        "app.api.customer_modules.get_settings", lambda: _settings(legacy_allowed=True)
    )
    inherited = _sem_live_write_policy_payload(_module(), [account])["accounts"][0]
    monkeypatch.setattr(
        "app.api.customer_modules.get_settings", lambda: _settings(legacy_allowed=False)
    )
    default_dry = _sem_live_write_policy_payload(_module(), [account])["accounts"][0]

    assert inherited["policy_source"] == "legacy_environment"
    assert inherited["policy_reason"] == "legacy_grant"
    assert inherited["enabled"] is True
    assert default_dry["policy_source"] == "legacy_environment"
    assert default_dry["policy_reason"] == "legacy_grant_missing"
    assert default_dry["enabled"] is False
