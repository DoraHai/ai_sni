"""Database-backed limits for user-triggered SEO rank collection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import tempfile
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.module_workspace import SeoSite
from app.process_lock import acquire_file_lock, release_file_lock


_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_STATE_KEY = "manual_rank_collection_limit"
_LEGACY_STATE_PATH = Path(tempfile.gettempdir()) / "seo_manual_rank_limits.json"
MANUAL_RANK_RESERVATION_TTL_SECONDS = 10 * 60
SEO_RANK_COLLECTION_LOCK_PATH = Path(tempfile.gettempdir()) / "seo_rank_collection.lock"


@dataclass
class ManualRankLimitError(Exception):
    code: str
    message: str
    retry_after: int

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class ManualRankReservation:
    token: str
    requested: int
    status: dict


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _aware_utc(value: datetime | str | None) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _local_day(now: datetime) -> date:
    return now.astimezone(_SHANGHAI_TZ).date()


def _state(site: SeoSite | None) -> dict:
    if site is None or not isinstance(site.site_settings, dict):
        return {}
    value = site.site_settings.get(_STATE_KEY)
    return dict(value) if isinstance(value, dict) else {}


def _store_state(site: SeoSite, state: dict) -> None:
    settings = dict(site.site_settings or {})
    settings[_STATE_KEY] = state
    site.site_settings = settings


def _legacy_state(
    tenant_id: int,
    site_id: int,
    *,
    state_path: Path,
) -> dict:
    if not state_path.exists():
        return {}
    lock_handle = acquire_file_lock(state_path.with_suffix(f"{state_path.suffix}.lock"))
    if lock_handle is None:
        raise ManualRankLimitError(
            "collection_busy",
            "另一排名采集请求正在处理，请稍后重试",
            5,
        )
    try:
        try:
            value = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManualRankLimitError(
                "limit_state_unavailable",
                "排名采集限流状态不可用，请联系管理员",
                60,
            ) from exc
        if not isinstance(value, dict):
            raise ManualRankLimitError(
                "limit_state_unavailable",
                "排名采集限流状态不可用，请联系管理员",
                60,
            )
        entry = value.get(f"{tenant_id}:{site_id}")
        if not isinstance(entry, dict):
            return {}
        return {
            key: entry[key]
            for key in ("daily_date", "daily_requests", "last_attempt_at")
            if key in entry
        }
    finally:
        release_file_lock(lock_handle)


def _state_with_legacy(
    site: SeoSite,
    tenant_id: int,
    site_id: int,
    *,
    legacy_state_path: Path,
) -> tuple[dict, bool]:
    state = _state(site)
    if state:
        return state, False
    legacy = _legacy_state(tenant_id, site_id, state_path=legacy_state_path)
    return legacy, bool(legacy)


def _active_reservation_retry_after(state: dict, now: datetime) -> int:
    expires_at = _aware_utc(state.get("reservation_expires_at"))
    if not state.get("reservation_token") or expires_at is None or expires_at <= now:
        return 0
    return max(1, int((expires_at - now).total_seconds() + 0.999))


def _payload(
    state: dict,
    *,
    now: datetime,
    cooldown_seconds: int,
    max_requests_per_day: int,
) -> dict:
    current_day = _local_day(now).isoformat()
    used = int(state.get("daily_requests") or 0) if state.get("daily_date") == current_day else 0
    last_attempt = _aware_utc(state.get("last_attempt_at"))
    next_allowed = last_attempt + timedelta(seconds=cooldown_seconds) if last_attempt else now
    cooldown_retry = max(0, int((next_allowed - now).total_seconds() + 0.999))
    reservation_retry = _active_reservation_retry_after(state, now)
    retry_after = max(cooldown_retry, reservation_retry)
    return {
        "allowed": retry_after == 0 and used < max_requests_per_day,
        "retry_after_seconds": retry_after,
        "next_allowed_at": (now + timedelta(seconds=retry_after)).isoformat(),
        "daily_requests_used": used,
        "daily_requests_limit": max_requests_per_day,
        "collection_in_progress": reservation_retry > 0,
    }


async def _site(
    session: AsyncSession,
    tenant_id: int,
    site_id: int,
    *,
    for_update: bool,
) -> SeoSite:
    statement = select(SeoSite).where(SeoSite.id == site_id, SeoSite.tenant_id == tenant_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    site = await session.scalar(statement)
    if site is None:
        raise ManualRankLimitError(
            "limit_state_unavailable",
            "排名采集限流状态不可用，请联系管理员",
            60,
        )
    return site


async def manual_rank_status(
    session: AsyncSession,
    tenant_id: int,
    site_id: int,
    *,
    cooldown_seconds: int,
    max_requests_per_day: int,
    now: datetime | None = None,
    legacy_state_path: Path | None = None,
) -> dict:
    current = now or _utc_now()
    site = await _site(session, tenant_id, site_id, for_update=False)
    state = _state(site)
    if not state:
        legacy = _legacy_state(
            tenant_id,
            site_id,
            state_path=legacy_state_path or _LEGACY_STATE_PATH,
        )
        if legacy:
            site = await _site(session, tenant_id, site_id, for_update=True)
            state = _state(site)
            if not state:
                state = legacy
                _store_state(site, state)
                await session.commit()
    return _payload(
        state,
        now=current,
        cooldown_seconds=max(1, cooldown_seconds),
        max_requests_per_day=max(1, max_requests_per_day),
    )


async def reserve_manual_rank_collection(
    session: AsyncSession,
    tenant_id: int,
    site_id: int,
    request_count: int,
    *,
    cooldown_seconds: int,
    max_requests_per_day: int,
    now: datetime | None = None,
    legacy_state_path: Path | None = None,
) -> ManualRankReservation:
    current = now or _utc_now()
    current_day = _local_day(current).isoformat()
    cooldown = max(1, cooldown_seconds)
    daily_limit = max(1, max_requests_per_day)
    requested = max(1, int(request_count))
    site = await _site(session, tenant_id, site_id, for_update=True)
    state, imported = _state_with_legacy(
        site,
        tenant_id,
        site_id,
        legacy_state_path=legacy_state_path or _LEGACY_STATE_PATH,
    )
    active_retry = _active_reservation_retry_after(state, current)
    if active_retry:
        await session.rollback()
        raise ManualRankLimitError(
            "collection_busy",
            "另一排名采集请求正在处理，请稍后重试",
            active_retry,
        )
    state.pop("reservation_token", None)
    state.pop("reserved_requests", None)
    state.pop("reservation_expires_at", None)
    if state.get("daily_date") != current_day:
        state["daily_date"] = current_day
        state["daily_requests"] = 0
    status = _payload(
        state,
        now=current,
        cooldown_seconds=cooldown,
        max_requests_per_day=daily_limit,
    )
    if status["retry_after_seconds"]:
        if imported:
            _store_state(site, state)
            await session.commit()
        else:
            await session.rollback()
        raise ManualRankLimitError(
            "collection_cooldown",
            f"排名刚刚更新过，请在 {status['retry_after_seconds']} 秒后再试",
            status["retry_after_seconds"],
        )
    if status["daily_requests_used"] + requested > daily_limit:
        local_now = current.astimezone(_SHANGHAI_TZ)
        tomorrow = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        retry_after = max(1, int((tomorrow - local_now).total_seconds()))
        if imported:
            _store_state(site, state)
            await session.commit()
        else:
            await session.rollback()
        raise ManualRankLimitError(
            "daily_request_limit",
            "今日人工排名采集额度已用完，请明日再试",
            retry_after,
        )
    token = str(uuid4())
    state.update(
        last_attempt_at=_naive_utc(current).isoformat(),
        reservation_token=token,
        reserved_requests=requested,
        reservation_expires_at=_naive_utc(
            current + timedelta(seconds=MANUAL_RANK_RESERVATION_TTL_SECONDS)
        ).isoformat(),
    )
    _store_state(site, state)
    await session.commit()
    return ManualRankReservation(
        token=token,
        requested=requested,
        status=_payload(
            state,
            now=current,
            cooldown_seconds=cooldown,
            max_requests_per_day=daily_limit,
        ),
    )


async def settle_manual_rank_collection(
    session: AsyncSession,
    tenant_id: int,
    site_id: int,
    reservation: ManualRankReservation,
    successful_requests: int,
    *,
    cooldown_seconds: int,
    max_requests_per_day: int,
    now: datetime | None = None,
) -> dict:
    current = now or _utc_now()
    site = await _site(session, tenant_id, site_id, for_update=True)
    state = _state(site)
    if state.get("reservation_token") != reservation.token:
        await session.rollback()
        raise ManualRankLimitError(
            "limit_reservation_lost",
            "排名采集配额结算失败，请联系管理员",
            60,
        )
    charged = min(reservation.requested, max(0, int(successful_requests)))
    state["daily_requests"] = int(state.get("daily_requests") or 0) + charged
    state.pop("reservation_token", None)
    state.pop("reserved_requests", None)
    state.pop("reservation_expires_at", None)
    _store_state(site, state)
    await session.commit()
    return _payload(
        state,
        now=current,
        cooldown_seconds=max(1, cooldown_seconds),
        max_requests_per_day=max(1, max_requests_per_day),
    )
