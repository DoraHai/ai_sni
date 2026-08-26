"""Pure helpers for account-scoped SEM asset sync state."""

import re
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4


ASSET_SYNC_DIMENSIONS = (
    "reports",
    "campaigns",
    "adgroups",
    "keywords",
    "search_terms",
    "price_strategies",
)
HEALTHY_SYNC_STATUSES = {"success", "empty", "preserved"}
_SECRET_PATTERN = re.compile(
    r"(?i)(access[_-]?token|refresh[_-]?token|password|secret|authorization)(\s*[:=]\s*)[^\s,;]+"
)


def utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def safe_sync_error(exc: Exception) -> str:
    message = _SECRET_PATTERN.sub(r"\1\2[REDACTED]", str(exc)).strip()
    return (message or exc.__class__.__name__)[:300]


def public_sync_error(message: str | None) -> str | None:
    """Map internal provider diagnostics to stable, non-sensitive user copy."""
    if not message:
        return None
    lowered = str(message).lower()
    if "89501" in lowered or "not authorized" in lowered or "unauthorized" in lowered:
        return "当前百度账户无权读取该数据维度，请检查授权范围"
    if "token" in lowered or "authorization" in lowered or "认证" in lowered:
        return "百度账户授权已失效或权限不足，请重新授权后再试"
    if "429" in lowered or "rate" in lowered or "频率" in lowered:
        return "百度接口访问频率受限，请稍后重试"
    return "该数据维度同步失败，请稍后重试或联系管理员"


def normalize_dimensions(dimensions: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not dimensions:
        return ASSET_SYNC_DIMENSIONS
    invalid = sorted(set(dimensions) - set(ASSET_SYNC_DIMENSIONS))
    if invalid:
        raise ValueError(f"不支持的同步维度：{', '.join(invalid)}")
    requested = set(dimensions)
    return tuple(item for item in ASSET_SYNC_DIMENSIONS if item in requested)


def begin_sync_run(existing: dict | None, dimensions: tuple[str, ...]) -> tuple[dict, str]:
    state = deepcopy(existing) if isinstance(existing, dict) else {}
    run_id = uuid4().hex
    now = utc_iso()
    state.update({"run_id": run_id, "started_at": now, "finished_at": None})
    dimension_state = deepcopy(state.get("dimensions") or {})
    for dimension in dimensions:
        dimension_state[dimension] = {
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "rows": None,
            "error": None,
        }
    state["dimensions"] = dimension_state
    return state, run_id


def update_dimension(
    state: dict,
    run_id: str,
    dimension: str,
    status: str,
    *,
    rows: int | dict | None = None,
    error: str | None = None,
) -> dict:
    """Return a copied state; ignore a stale worker from an older run."""
    if state.get("run_id") != run_id:
        return state
    updated = deepcopy(state)
    now = utc_iso()
    item = deepcopy((updated.get("dimensions") or {}).get(dimension) or {})
    if status == "syncing":
        item["started_at"] = now
        item["finished_at"] = None
    else:
        item["finished_at"] = now
    item.update({"status": status, "rows": rows, "error": error})
    updated.setdefault("dimensions", {})[dimension] = item
    return updated


def finish_sync_run(state: dict, run_id: str) -> dict:
    if state.get("run_id") != run_id:
        return state
    updated = deepcopy(state)
    updated["finished_at"] = utc_iso()
    return updated


def aggregate_sync_status(state: dict) -> str:
    dimensions = state.get("dimensions") or {}
    statuses = {item.get("status") for item in dimensions.values() if isinstance(item, dict)}
    if "syncing" in statuses or "pending" in statuses:
        return "syncing"
    if statuses and statuses <= HEALTHY_SYNC_STATUSES and all(
        name in dimensions for name in ASSET_SYNC_DIMENSIONS
    ):
        return "synced"
    if "failed" in statuses or statuses:
        return "partial"
    return "pending"
