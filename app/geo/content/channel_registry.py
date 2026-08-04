"""Resolve tenant publishing-channel registry against adapt profiles."""

from __future__ import annotations

from typing import Any

from app.geo.content.channel_profiles import (
    CHANNEL_PROFILES,
    DEFAULT_TARGET_CHANNELS,
    get_profile,
    list_profiles,
)

# Registry channel_type → adapt profile key (only types with adapt support).
REGISTRY_TO_PROFILE: dict[str, str] = {
    "website": "website",
    "docs": "website",  # full master; docs share website adapt
    "wechat": "wechat",
    "zhihu": "zhihu",
    "baijiahao": "baijiahao",
    "toutiao": "toutiao",
    "industry_media": "toutiao",
    "community_qa": "zhihu",
    "encyclopedia": "zhihu",
    "visual_content": "toutiao",
}


def profile_key_for_registry_type(channel_type: str | None) -> str | None:
    key = str(channel_type or "").strip().lower()
    mapped = REGISTRY_TO_PROFILE.get(key)
    if mapped and mapped in CHANNEL_PROFILES:
        return mapped
    if key in CHANNEL_PROFILES:
        return key
    return None


def adapt_key_from_target(raw: str) -> str | None:
    """Normalize a target_channels entry to an adapt profile key."""
    key = str(raw or "").strip().lower()
    if key in CHANNEL_PROFILES:
        return key
    return profile_key_for_registry_type(key)


def filter_channels_by_registry(
    channels: list[str] | None,
    *,
    enabled_types: set[str] | None,
) -> list[str]:
    """Keep adapt keys that are allowed by enabled registry channel_types.

    If ``enabled_types`` is None/empty (no registry rows yet), fall back to
    profile normalization only.
    """
    raw = channels or list(DEFAULT_TARGET_CHANNELS)
    out: list[str] = []
    for item in raw:
        adapt = adapt_key_from_target(item)
        if not adapt or adapt in out:
            continue
        if enabled_types:
            # allow if any enabled registry type maps to this adapt key
            allowed = False
            for ctype in enabled_types:
                if profile_key_for_registry_type(ctype) == adapt or ctype == adapt:
                    allowed = True
                    break
            if not allowed and adapt not in enabled_types:
                continue
        out.append(adapt)
    return out or list(DEFAULT_TARGET_CHANNELS)


def channel_options_from_registry(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build editor options: enabled registry channels with adapt profile info."""
    profiles = {p["key"]: p for p in list_profiles()}
    options: list[dict[str, Any]] = []
    seen_adapt: set[str] = set()
    for row in rows:
        if not row.get("enabled", True):
            continue
        ctype = str(row.get("channel_type") or "").strip().lower()
        adapt = profile_key_for_registry_type(ctype)
        if not adapt or adapt in seen_adapt:
            continue
        profile = profiles.get(adapt) or (
            get_profile(adapt).to_dict() if get_profile(adapt) else None
        )
        options.append(
            {
                "publishing_channel_id": row.get("id"),
                "name": row.get("name"),
                "channel_type": ctype,
                "publish_mode": row.get("publish_mode"),
                "enabled": True,
                "adapt_key": adapt,
                "adapt_profile": profile,
                "default_selected": bool(profile and profile.get("default_selected")),
            }
        )
        seen_adapt.add(adapt)
    return options


def publish_mode_for_channel(
    channel: str,
    rows: list[dict[str, Any]],
) -> str:
    """Pick registry publish_mode for an adapt channel key; default manual_only."""
    adapt = adapt_key_from_target(channel) or channel
    for row in rows:
        if not row.get("enabled", True):
            continue
        ctype = str(row.get("channel_type") or "").strip().lower()
        if profile_key_for_registry_type(ctype) == adapt or ctype == adapt:
            mode = str(row.get("publish_mode") or "manual_only")
            return mode
    return "manual_only"


def publication_publish_mode(registry_mode: str | None) -> str:
    """Map registry publish_mode onto GeoPublication.publish_mode values."""
    mode = str(registry_mode or "manual_only").strip().lower()
    if mode == "manual_only":
        return "manual_export"
    if mode in {"auto_publish", "draft_then_manual", "manual_export"}:
        return mode
    return "manual_export"


def enabled_types_from_rows(rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("channel_type") or "").strip().lower()
        for row in rows
        if row.get("enabled", True) and row.get("channel_type")
    }


def registry_row_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    """Normalize ORM or dict rows for registry helpers."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
            continue
        out.append(
            {
                "id": getattr(row, "id", None),
                "name": getattr(row, "name", None),
                "channel_type": getattr(row, "channel_type", None),
                "publish_mode": getattr(row, "publish_mode", None),
                "enabled": bool(getattr(row, "enabled", True)),
                "sort_order": getattr(row, "sort_order", 0),
            }
        )
    return out
