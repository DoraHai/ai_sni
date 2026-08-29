"""Persistent limits for user-triggered SEO rank collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import tempfile
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.seo import SeoManualRankLimit


_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
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


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _local_day(now: datetime) -> date:
    return now.astimezone(_SHANGHAI_TZ).date()


def _active_reservation_retry_after(row: SeoManualRankLimit, now: datetime) -> int:
    expires_at = _aware_utc(row.reservation_expires_at)
    if not row.reservation_token or expires_at is None or expires_at <= now:
        return 0
    return max(1, int((expires_at - now).total_seconds() + 0.999))


def _payload(
    row: SeoManualRankLimit | None,
    *,
    now: datetime,
    cooldown_seconds: int,
    max_requests_per_day: int,
) -> dict:
    current_day = _local_day(now)
    used = int(row.daily_requests or 0) if row and row.daily_date == current_day else 0
    last_attempt = _aware_utc(row.last_attempt_at) if row else None
    next_allowed = last_attempt + timedelta(seconds=cooldown_seconds) if last_attempt else now
    cooldown_retry = max(0, int((next_allowed - now).total_seconds() + 0.999))
    reservation_retry = _active_reservation_retry_after(row, now) if row else 0
    retry_after = max(cooldown_retry, reservation_retry)
    return {
        "allowed": retry_after == 0 and used < max_requests_per_day,
        "retry_after_seconds": retry_after,
        "next_allowed_at": (now + timedelta(seconds=retry_after)).isoformat(),
        "daily_requests_used": used,
        "daily_requests_limit": max_requests_per_day,
        "collection_in_progress": reservation_retry > 0,
    }


async def _locked_row(
    session: AsyncSession,
    tenant_id: int,
    site_id: int,
    *,
    current_day: date,
) -> SeoManualRankLimit:
    await session.execute(
        pg_insert(SeoManualRankLimit)
        .values(
            tenant_id=tenant_id,
            site_id=site_id,
            daily_date=current_day,
            daily_requests=0,
            reserved_requests=0,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "site_id"])
    )
    row = await session.scalar(
        select(SeoManualRankLimit)
        .where(
            SeoManualRankLimit.tenant_id == tenant_id,
            SeoManualRankLimit.site_id == site_id,
        )
        .with_for_update()
    )
    if row is None:
        raise ManualRankLimitError(
            "limit_state_unavailable",
            "排名采集限流状态不可用，请联系管理员",
            60,
        )
    return row


async def manual_rank_status(
    session: AsyncSession,
    tenant_id: int,
    site_id: int,
    *,
    cooldown_seconds: int,
    max_requests_per_day: int,
    now: datetime | None = None,
) -> dict:
    current = now or _utc_now()
    row = await session.scalar(
        select(SeoManualRankLimit).where(
            SeoManualRankLimit.tenant_id == tenant_id,
            SeoManualRankLimit.site_id == site_id,
        )
    )
    return _payload(
        row,
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
) -> ManualRankReservation:
    current = now or _utc_now()
    current_day = _local_day(current)
    cooldown = max(1, cooldown_seconds)
    daily_limit = max(1, max_requests_per_day)
    requested = max(1, int(request_count))
    row = await _locked_row(session, tenant_id, site_id, current_day=current_day)
    active_retry = _active_reservation_retry_after(row, current)
    if active_retry:
        await session.rollback()
        raise ManualRankLimitError(
            "collection_busy",
            "另一排名采集请求正在处理，请稍后重试",
            active_retry,
        )
    if row.reservation_token:
        row.reservation_token = None
        row.reserved_requests = 0
        row.reservation_expires_at = None
    if row.daily_date != current_day:
        row.daily_date = current_day
        row.daily_requests = 0
    status = _payload(
        row,
        now=current,
        cooldown_seconds=cooldown,
        max_requests_per_day=daily_limit,
    )
    if status["retry_after_seconds"]:
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
        await session.rollback()
        raise ManualRankLimitError(
            "daily_request_limit",
            "今日人工排名采集额度已用完，请明日再试",
            retry_after,
        )
    token = str(uuid4())
    row.last_attempt_at = _naive_utc(current)
    row.reservation_token = token
    row.reserved_requests = requested
    row.reservation_expires_at = _naive_utc(
        current + timedelta(seconds=MANUAL_RANK_RESERVATION_TTL_SECONDS)
    )
    await session.commit()
    return ManualRankReservation(
        token=token,
        requested=requested,
        status=_payload(
            row,
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
    row = await session.scalar(
        select(SeoManualRankLimit)
        .where(
            SeoManualRankLimit.tenant_id == tenant_id,
            SeoManualRankLimit.site_id == site_id,
        )
        .with_for_update()
    )
    if row is None or row.reservation_token != reservation.token:
        await session.rollback()
        raise ManualRankLimitError(
            "limit_reservation_lost",
            "排名采集配额结算失败，请联系管理员",
            60,
        )
    charged = min(reservation.requested, max(0, int(successful_requests)))
    row.daily_requests = int(row.daily_requests or 0) + charged
    row.reservation_token = None
    row.reserved_requests = 0
    row.reservation_expires_at = None
    await session.commit()
    return _payload(
        row,
        now=current,
        cooldown_seconds=max(1, cooldown_seconds),
        max_requests_per_day=max(1, max_requests_per_day),
    )
