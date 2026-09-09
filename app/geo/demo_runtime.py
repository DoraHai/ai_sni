"""Fail-closed controls for the isolated GEO demo runtime."""

from __future__ import annotations

import os
from typing import Mapping

from fastapi import HTTPException, Request

from app.config import get_settings
from app.geo.demo_database_guard import EXTERNAL_CREDENTIAL_KEYS, REQUIRED_RUNTIME_FLAGS


DEMO_RUNTIME_FLAG = "GEO_DEMO_RUNTIME"
DEMO_DISABLE_FLAGS = {
    key: key.lower()
    for key, value in REQUIRED_RUNTIME_FLAGS.items()
    if key.startswith("GEO_") and key != DEMO_RUNTIME_FLAG and value == "false"
}

_DEMO_READ_PREFIXES = ("/api/v1/geo/integration/",)
_DEMO_READ_EXACT = {"/api/v1/geo/tenants"}


class GeoDemoRuntimeConfigurationError(RuntimeError):
    """Raised before startup without echoing secrets."""


def _raw(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    return str(value).strip().lower() if value is not None else None


def is_demo_environment(settings=None) -> bool:
    settings = settings or get_settings()
    return str(settings.app_env or "").strip().lower() == "demo"


def validate_geo_demo_runtime(settings=None, env: Mapping[str, str] | None = None) -> bool:
    """Validate explicit demo shutdown controls; return False outside demo."""
    settings = settings or get_settings()
    if not is_demo_environment(settings):
        return False
    env = os.environ if env is None else env
    errors = []
    if _raw(env, DEMO_RUNTIME_FLAG) != "true" or settings.geo_demo_runtime is not True:
        errors.append(f"{DEMO_RUNTIME_FLAG} must be explicitly true")
    for env_key, field_name in DEMO_DISABLE_FLAGS.items():
        if _raw(env, env_key) != "false":
            errors.append(f"{env_key} must be explicitly false")
        if getattr(settings, field_name, None) is not False:
            errors.append(f"{field_name} must be false")
    if _raw(env, "BAIDU_WRITE_DRY_RUN") != "true" or settings.baidu_write_dry_run is not True:
        errors.append("BAIDU_WRITE_DRY_RUN must be explicitly true")
    if _raw(env, "CHINAZ_API_ENABLED") != "false" or settings.chinaz_api_enabled is not False:
        errors.append("CHINAZ_API_ENABLED must be explicitly false")
    if _raw(env, "SEO_RANK_SCHEDULER_ENABLED") != "false" or settings.seo_rank_scheduler_enabled is not False:
        errors.append("SEO_RANK_SCHEDULER_ENABLED must be explicitly false")
    populated = []
    for env_key in EXTERNAL_CREDENTIAL_KEYS:
        if str(getattr(settings, env_key.lower(), "") or "").strip():
            populated.append(env_key)
    if populated:
        errors.append("external credentials must be empty: " + ", ".join(populated))
    if errors:
        raise GeoDemoRuntimeConfigurationError("; ".join(errors))
    return True


def demo_request_is_read_only(request: Request) -> bool:
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        return False
    path = request.url.path.rstrip("/") or "/"
    return path in _DEMO_READ_EXACT or any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in _DEMO_READ_PREFIXES
    )


async def require_geo_demo_safe_request(request: Request) -> None:
    """Block every non-whitelisted GEO route while APP_ENV=demo."""
    settings = get_settings()
    if not is_demo_environment(settings):
        return
    # Validate on every request as defense in depth against a mutated settings
    # object or a process that bypassed the standalone lifespan.
    validate_geo_demo_runtime(settings)
    if demo_request_is_read_only(request):
        return
    raise HTTPException(
        403,
        {
            "code": "geo_demo_runtime_read_only",
            "message": "全虚拟演示环境仅允许认证后的 GEO 只读接口",
        },
    )
