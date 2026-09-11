"""Database-backed, fail-closed SEM live-write policy.

The process environment remains the global kill switch.  A saved tenant policy
is the customer-level source of truth; legacy environment grants are consulted
only until an administrator saves the first policy for that tenant.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SEM_CUSTOMER_LIVE_WRITE_SCOPES
from app.models import BidWriteback, TenantModule, WritebackAction
from app.module_scope import module_is_available


POLICY_KEY = "sem_live_write_policy"
POLICY_HISTORY_LIMIT = 20
DEFAULT_DAILY_LIVE_ACTION_LIMIT = 100
MAX_DAILY_LIVE_ACTION_LIMIT = 1000
HARD_MAX_BID_CHANGE_PCT = 20.0
REAL_ATTEMPT_STATUSES = frozenset({"pending", "success", "failed", "reconcile"})


class SemLiveWritePolicyLimitError(ValueError):
    pass


@dataclass(frozen=True)
class SemLiveWriteDecision:
    dry_run: bool
    source: str
    reason: str
    max_bid_change_pct: float = HARD_MAX_BID_CHANGE_PCT
    daily_limit: int = DEFAULT_DAILY_LIVE_ACTION_LIMIT


def empty_policy() -> dict[str, Any]:
    return {
        "version": 0,
        "enabled": False,
        "accounts": {},
        "updated_at": None,
        "updated_by": None,
        "change_reason": None,
        "history": [],
    }


def parse_policy(raw: Any) -> dict[str, Any]:
    """Validate stored JSON without accepting partial or widened grants."""
    if not isinstance(raw, dict):
        raise ValueError("SEM live-write policy must be an object")
    version = raw.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("SEM live-write policy version is invalid")
    enabled = raw.get("enabled")
    accounts = raw.get("accounts")
    if not isinstance(enabled, bool) or not isinstance(accounts, dict):
        raise ValueError("SEM live-write policy shape is invalid")
    normalized: dict[str, dict[str, Any]] = {}
    for account_key, item in accounts.items():
        if not str(account_key).isascii() or not str(account_key).isdecimal() or int(account_key) <= 0:
            raise ValueError("SEM live-write account ID is invalid")
        if not isinstance(item, dict):
            raise ValueError("SEM live-write account policy is invalid")
        scopes = item.get("scopes")
        account_enabled = item.get("enabled")
        daily_limit = item.get("daily_live_action_limit")
        bid_limit = item.get("max_bid_change_pct")
        if not isinstance(account_enabled, bool):
            raise ValueError("SEM live-write account enabled flag is invalid")
        if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
            raise ValueError("SEM live-write scopes are invalid")
        scope_set = set(scopes)
        if scope_set - SEM_CUSTOMER_LIVE_WRITE_SCOPES:
            raise ValueError("SEM live-write policy contains unsupported scopes")
        if isinstance(daily_limit, bool) or not isinstance(daily_limit, int) or not 1 <= daily_limit <= MAX_DAILY_LIVE_ACTION_LIMIT:
            raise ValueError("SEM live-write daily limit is invalid")
        if isinstance(bid_limit, bool) or not isinstance(bid_limit, (int, float)) or not 0 < float(bid_limit) <= HARD_MAX_BID_CHANGE_PCT:
            raise ValueError("SEM live-write bid limit is invalid")
        normalized[str(int(account_key))] = {
            "enabled": account_enabled,
            "scopes": sorted(scope_set),
            "daily_live_action_limit": daily_limit,
            "max_bid_change_pct": float(bid_limit),
        }
    raw_history = raw.get("history") or []
    if not isinstance(raw_history, list) or any(not isinstance(item, dict) for item in raw_history):
        raise ValueError("SEM live-write policy history is invalid")
    normalized_history = []
    for item in raw_history[-POLICY_HISTORY_LIMIT:]:
        actor = item.get("updated_by")
        normalized_history.append({
            key: item.get(key)
            for key in (
                "version", "enabled", "global_enabled", "account_id", "scopes",
                "daily_live_action_limit", "max_bid_change_pct", "change_reason",
                "updated_at",
            )
        } | {
            "updated_by": (
                {"user_id": actor.get("user_id"), "username": actor.get("username")}
                if isinstance(actor, dict)
                else None
            )
        })
    updated_by = raw.get("updated_by")
    safe_updated_by = (
        {"user_id": updated_by.get("user_id"), "username": updated_by.get("username")}
        if isinstance(updated_by, dict)
        else None
    )
    result = dict(raw)
    result["accounts"] = normalized
    result["history"] = normalized_history
    result["updated_by"] = safe_updated_by
    return result


def build_policy_update(
    current_raw: Any,
    *,
    account_id: int,
    enabled: bool,
    scopes: set[str],
    daily_limit: int,
    max_bid_change_pct: float,
    change_reason: str,
    actor_user_id: int | None,
    actor_username: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = empty_policy() if current_raw is None else parse_policy(current_raw)
    now = now or datetime.now(timezone.utc)
    accounts = dict(current.get("accounts") or {})
    accounts[str(account_id)] = {
        "enabled": enabled,
        "scopes": sorted(scopes),
        "daily_live_action_limit": daily_limit,
        "max_bid_change_pct": float(max_bid_change_pct),
    }
    history = list(current.get("history") or [])
    history.append({
        "version": int(current.get("version") or 0) + 1,
        "enabled": enabled,
        "global_enabled": any(item.get("enabled") is True for item in accounts.values()),
        "account_id": account_id,
        "scopes": sorted(scopes),
        "daily_live_action_limit": daily_limit,
        "max_bid_change_pct": float(max_bid_change_pct),
        "change_reason": change_reason,
        "updated_at": now.isoformat(),
        "updated_by": {"user_id": actor_user_id, "username": actor_username},
    })
    return {
        "version": int(current.get("version") or 0) + 1,
        "enabled": any(item.get("enabled") is True for item in accounts.values()),
        "accounts": accounts,
        "change_reason": change_reason,
        "updated_at": now.isoformat(),
        "updated_by": {"user_id": actor_user_id, "username": actor_username},
        "history": history[-POLICY_HISTORY_LIMIT:],
    }


def shanghai_day_utc_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(ZoneInfo("Asia/Shanghai"))
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, start_utc + timedelta(days=1)


async def count_live_attempts_today(
    session: AsyncSession, tenant_id: int, account_id: int
) -> int:
    start, end = shanghai_day_utc_bounds()
    total = 0
    for model in (BidWriteback, WritebackAction):
        total += int(await session.scalar(
            select(func.count()).select_from(model).where(
                model.tenant_id == tenant_id,
                model.baidu_account_id == account_id,
                model.dry_run.is_(False),
                model.status.in_(REAL_ATTEMPT_STATUSES),
                model.created_at >= start,
                model.created_at < end,
            )
        ) or 0)
    return total


def evaluate_live_write_grant(
    settings: object,
    module: TenantModule | None,
    *,
    tenant_id: int,
    account_id: int,
    write_scope: str,
) -> SemLiveWriteDecision:
    """Evaluate one grant without locking, counting or reserving quota."""
    if write_scope not in SEM_CUSTOMER_LIVE_WRITE_SCOPES:
        return SemLiveWriteDecision(True, "policy", "unsupported_scope")
    if module is None or not module_is_available(module):
        return SemLiveWriteDecision(True, "policy", "sem_module_unavailable")

    settings_blob = module.module_settings if isinstance(module.module_settings, dict) else {}
    policy = None
    account_policy = None
    legacy_allowed = False
    if POLICY_KEY in settings_blob:
        try:
            policy = parse_policy(settings_blob[POLICY_KEY])
        except (TypeError, ValueError):
            return SemLiveWriteDecision(True, "policy", "invalid_policy")
        account_policy = policy["accounts"].get(str(account_id))
    else:
        try:
            legacy_allowed = bool(
                settings.baidu_live_write_allowed(tenant_id, account_id, write_scope)
            )
        except (AttributeError, TypeError, ValueError):
            legacy_allowed = False
    bid_limit = (
        account_policy["max_bid_change_pct"]
        if account_policy is not None else HARD_MAX_BID_CHANGE_PCT
    )
    daily_limit = (
        account_policy["daily_live_action_limit"]
        if account_policy is not None else DEFAULT_DAILY_LIVE_ACTION_LIMIT
    )
    if bool(getattr(settings, "baidu_write_dry_run", True)):
        return SemLiveWriteDecision(
            True,
            "policy" if policy is not None else "legacy_environment",
            "global_dry_run",
            bid_limit,
            daily_limit,
        )
    if bool(getattr(settings, "baidu_legacy_split_confirmation_enabled", True)):
        return SemLiveWriteDecision(
            True,
            "policy" if policy is not None else "legacy_environment",
            "legacy_confirmation_gate",
            bid_limit,
            daily_limit,
        )
    if POLICY_KEY not in settings_blob:
        if not legacy_allowed:
            return SemLiveWriteDecision(True, "legacy_environment", "legacy_grant_missing")
        return SemLiveWriteDecision(
            False,
            "legacy_environment",
            "legacy_grant",
            HARD_MAX_BID_CHANGE_PCT,
            DEFAULT_DAILY_LIVE_ACTION_LIMIT,
        )

    assert policy is not None
    if account_policy is None:
        return SemLiveWriteDecision(True, "policy", "grant_missing_or_paused")
    if (
        not policy["enabled"]
        or account_policy.get("enabled") is not True
        or write_scope not in account_policy["scopes"]
    ):
        return SemLiveWriteDecision(
            True,
            "policy",
            "grant_missing_or_paused",
            account_policy["max_bid_change_pct"],
            account_policy["daily_live_action_limit"],
        )
    return SemLiveWriteDecision(
        False,
        "policy",
        "configured_grant",
        account_policy["max_bid_change_pct"],
        account_policy["daily_live_action_limit"],
    )


async def resolve_live_write_decision(
    session: AsyncSession,
    settings: object,
    *,
    tenant_id: int,
    account_id: int,
    write_scope: str,
    requested_attempts: int = 1,
    bid_change_pct: float | None = None,
) -> SemLiveWriteDecision:
    # The environment kill switches are sufficient to prove rehearsal mode;
    # avoid taking a database lock when no live request can be emitted.
    if bool(getattr(settings, "baidu_write_dry_run", True)):
        return SemLiveWriteDecision(True, "environment", "global_dry_run")
    if bool(getattr(settings, "baidu_legacy_split_confirmation_enabled", True)):
        return SemLiveWriteDecision(True, "environment", "legacy_confirmation_gate")
    # All real attempts and policy updates serialize on this existing row.  The
    # caller keeps the transaction open until its pending intent is persisted,
    # so count + reservation cannot race past the configured daily limit.
    module = await session.scalar(select(TenantModule).where(
        TenantModule.tenant_id == tenant_id,
        TenantModule.module_code == "sem",
    ).with_for_update())
    decision = evaluate_live_write_grant(
        settings,
        module,
        tenant_id=tenant_id,
        account_id=account_id,
        write_scope=write_scope,
    )
    if decision.dry_run:
        return decision

    if bid_change_pct is not None and abs(float(bid_change_pct)) > decision.max_bid_change_pct + 1e-6:
        raise SemLiveWritePolicyLimitError(
            f"调价幅度超过管理员设置的单次上限 {decision.max_bid_change_pct:g}%"
        )
    used = await count_live_attempts_today(session, tenant_id, account_id)
    if requested_attempts < 0 or used + requested_attempts > decision.daily_limit:
        raise SemLiveWritePolicyLimitError(
            f"今日真实动作额度不足（已用 {used} / 上限 {decision.daily_limit}）"
        )
    return decision
