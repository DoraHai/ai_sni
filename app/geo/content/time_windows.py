"""GEO 时间窗：统一 Asia/Shanghai 日历日，与存储的 naive UTC captured_at 互转。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Tuple
from zoneinfo import ZoneInfo

# 产品默认租户时区（中国客户）；后续可升为租户字段
TENANT_TZ = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc


def now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def shanghai_today() -> date:
    return datetime.now(TENANT_TZ).date()


def to_utc_naive(dt: datetime) -> datetime:
    """任意 datetime → 存库用的 naive UTC。"""
    if dt.tzinfo is None:
        # 约定：无 tz 的 captured_at 已是 UTC
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def shanghai_day_of_utc_naive(dt: datetime | None) -> date | None:
    """naive UTC datetime → 上海日历日。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        aware = dt.replace(tzinfo=UTC)
    else:
        aware = dt
    return aware.astimezone(TENANT_TZ).date()


def shanghai_day_bounds_utc_naive(day: date) -> Tuple[datetime, datetime]:
    """上海本地某日 [00:00, 24:00) 对应的 naive UTC 区间（右开）。"""
    start_local = datetime.combine(day, time.min, tzinfo=TENANT_TZ)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=TENANT_TZ)
    start_utc = start_local.astimezone(UTC).replace(tzinfo=None)
    end_utc = end_local.astimezone(UTC).replace(tzinfo=None)
    return start_utc, end_utc


def default_observation_window(
    *, days: int = 14, end: date | None = None
) -> tuple[date, date]:
    """默认观察期：含 end 在内的最近 N 个上海日历日。"""
    end_d = end or shanghai_today()
    start_d = end_d - timedelta(days=max(1, days) - 1)
    return start_d, end_d
