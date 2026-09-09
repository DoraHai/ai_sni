"""Trusted tenant-level GEO demo policy.

The control database owns the binding.  Clients never select a data source and
an isolated demo binding never falls back to production GEO data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import HTTPException, Request


DEMO_DATABASE_KEY = "gsnipers_demo"
DEMO_FIXTURE_NAMESPACE = "g-snipers-geo-demo-v1"
DEMO_READ_PATHS = {
    "/api/v1/geo/integration/metrics/snapshot",
    "/api/v1/geo/integration/metrics/dictionary",
}


@dataclass(frozen=True)
class GeoTenantPolicy:
    tenant_id: int
    source_kind: str = "production"
    read_only: bool = False
    database_key: str | None = None
    fixture_namespace: str | None = None

    @property
    def is_demo(self) -> bool:
        return self.source_kind == "isolated_demo"


class GeoDemoBindingUnavailable(HTTPException):
    def __init__(self, message: str = "演示客户数据源绑定不可用") -> None:
        super().__init__(503, {"code": "geo_demo_binding_unavailable", "message": message})


class GeoDemoExecutionBlocked(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            403,
            {
                "code": "geo_demo_tenant_read_only",
                "message": "全虚拟演示客户仅允许认证后的只读展示",
            },
        )


def policy_from_module_settings(tenant_id: int, module_settings: Any) -> GeoTenantPolicy:
    """Parse only the server-owned module_settings value and fail closed on drift."""
    if not isinstance(module_settings, Mapping):
        raise GeoDemoBindingUnavailable()
    raw = module_settings.get("geo_data_source")
    if raw is None:
        return GeoTenantPolicy(tenant_id=tenant_id)
    if not isinstance(raw, Mapping):
        raise GeoDemoBindingUnavailable()
    allowed = {"kind", "database_key", "fixture_namespace", "read_only"}
    if set(raw) != allowed:
        raise GeoDemoBindingUnavailable()
    if (
        raw.get("kind") != "isolated_demo"
        or raw.get("database_key") != DEMO_DATABASE_KEY
        or raw.get("fixture_namespace") != DEMO_FIXTURE_NAMESPACE
        or raw.get("read_only") is not True
    ):
        raise GeoDemoBindingUnavailable()
    return GeoTenantPolicy(
        tenant_id=tenant_id,
        source_kind="isolated_demo",
        read_only=True,
        database_key=DEMO_DATABASE_KEY,
        fixture_namespace=DEMO_FIXTURE_NAMESPACE,
    )


def enforce_demo_request(policy: GeoTenantPolicy, request: Request) -> None:
    if not policy.is_demo:
        return
    path = request.url.path.rstrip("/") or "/"
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"} and path in DEMO_READ_PATHS:
        return
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"} and path.startswith(
        "/api/v1/geo/integration/"
    ):
        # No fixed database_key -> DSN resolver has been approved yet.  Refuse
        # the request instead of accidentally reading the production session.
        raise GeoDemoBindingUnavailable("演示只读数据源尚未配置")
    raise GeoDemoExecutionBlocked()


def demo_metric_rows(*, as_of: str) -> list[dict[str, Any]]:
    return [
        {
            "metric_key": key,
            "value": None,
            "unit": unit,
            "as_of": as_of,
            "trend_7d": None,
        }
        for key, unit in (
            ("geo.visibility.ai_mention_count_7d", "count"),
            ("geo.visibility.ai_visibility_score", "score"),
            ("geo.visibility.ai_mention_rate_7d", "percent"),
        )
    ]
