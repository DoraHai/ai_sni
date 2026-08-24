"""Cross-worker limits for user-triggered SEO rank collection on one SEO host."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.process_lock import acquire_file_lock, release_file_lock


_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_DEFAULT_STATE_PATH = Path(tempfile.gettempdir()) / "seo_manual_rank_limits.json"
SEO_RANK_COLLECTION_LOCK_PATH = Path(tempfile.gettempdir()) / "seo_rank_collection.lock"


@dataclass
class ManualRankLimitError(Exception):
    code: str
    message: str
    retry_after: int

    def __str__(self) -> str:
        return self.message


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read_state(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
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
    return {str(key): item for key, item in value.items() if isinstance(item, dict)}


def _write_state(path: Path, state: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    os.replace(temporary, path)


def _payload(
    entry: dict,
    *,
    now: datetime,
    cooldown_seconds: int,
    max_requests_per_day: int,
) -> dict:
    last_attempt = _parse_time(entry.get("last_attempt_at"))
    next_allowed = last_attempt + timedelta(seconds=cooldown_seconds) if last_attempt else now
    retry_after = max(0, int((next_allowed - now).total_seconds() + 0.999))
    local_day = now.astimezone(_SHANGHAI_TZ).date().isoformat()
    used = int(entry.get("daily_requests") or 0) if entry.get("daily_date") == local_day else 0
    return {
        "allowed": retry_after == 0 and used < max_requests_per_day,
        "retry_after_seconds": retry_after,
        "next_allowed_at": next_allowed.astimezone(timezone.utc).isoformat(),
        "daily_requests_used": used,
        "daily_requests_limit": max_requests_per_day,
    }


def manual_rank_status(
    tenant_id: int,
    site_id: int,
    *,
    cooldown_seconds: int,
    max_requests_per_day: int,
    state_path: Path | None = None,
    now: datetime | None = None,
) -> dict:
    path = state_path or _DEFAULT_STATE_PATH
    lock_handle = acquire_file_lock(path.with_suffix(f"{path.suffix}.lock"))
    if lock_handle is None:
        raise ManualRankLimitError("collection_busy", "另一排名采集请求正在处理，请稍后重试", 5)
    try:
        state = _read_state(path)
        return _payload(
            state.get(f"{tenant_id}:{site_id}", {}),
            now=now or _utc_now(),
            cooldown_seconds=max(1, cooldown_seconds),
            max_requests_per_day=max(1, max_requests_per_day),
        )
    finally:
        release_file_lock(lock_handle)


def reserve_manual_rank_collection(
    tenant_id: int,
    site_id: int,
    request_count: int,
    *,
    cooldown_seconds: int,
    max_requests_per_day: int,
    state_path: Path | None = None,
    now: datetime | None = None,
) -> dict:
    path = state_path or _DEFAULT_STATE_PATH
    lock_handle = acquire_file_lock(path.with_suffix(f"{path.suffix}.lock"))
    if lock_handle is None:
        raise ManualRankLimitError("collection_busy", "另一排名采集请求正在处理，请稍后重试", 5)
    try:
        current = now or _utc_now()
        cooldown = max(1, cooldown_seconds)
        daily_limit = max(1, max_requests_per_day)
        state = _read_state(path)
        key = f"{tenant_id}:{site_id}"
        entry = state.get(key, {})
        status = _payload(
            entry,
            now=current,
            cooldown_seconds=cooldown,
            max_requests_per_day=daily_limit,
        )
        if status["retry_after_seconds"]:
            raise ManualRankLimitError(
                "collection_cooldown",
                f"排名刚刚更新过，请在 {status['retry_after_seconds']} 秒后再试",
                status["retry_after_seconds"],
            )
        requested = max(1, int(request_count))
        if status["daily_requests_used"] + requested > daily_limit:
            local_now = current.astimezone(_SHANGHAI_TZ)
            tomorrow = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            retry_after = max(1, int((tomorrow - local_now).total_seconds()))
            raise ManualRankLimitError(
                "daily_request_limit",
                "今日人工排名采集额度已用完，请明日再试",
                retry_after,
            )
        local_day = current.astimezone(_SHANGHAI_TZ).date().isoformat()
        entry = {
            "last_attempt_at": current.isoformat(),
            "daily_date": local_day,
            "daily_requests": status["daily_requests_used"] + requested,
        }
        state[key] = entry
        _write_state(path, state)
        return _payload(
            entry,
            now=current,
            cooldown_seconds=cooldown,
            max_requests_per_day=daily_limit,
        )
    finally:
        release_file_lock(lock_handle)
