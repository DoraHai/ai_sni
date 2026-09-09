"""Trusted tenant-level GEO demo policy.

The control database owns the binding.  Clients never select a data source and
an isolated demo binding never falls back to production GEO data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import HTTPException, Request


DEMO_DATASET_KEY = "gsnipers_demo"
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
    demo_tenant_id: int | None = None
    dataset_key: str | None = None
    dataset_version: str | None = None
    binding_version: int | None = None
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


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GeoDemoBindingUnavailable(f"演示绑定字段 {field} 无效")
    return value


def policy_from_binding(tenant_id: int, binding: Any) -> GeoTenantPolicy:
    """Parse the 0098-protected server binding and fail closed on drift."""
    if not isinstance(binding, Mapping):
        raise GeoDemoBindingUnavailable()
    if not binding:
        return GeoTenantPolicy(tenant_id=tenant_id)
    allowed = {
        "tenant_id",
        "demo_tenant_id",
        "dataset_key",
        "dataset_version",
        "status",
        "version",
    }
    if set(binding) != allowed:
        raise GeoDemoBindingUnavailable()
    if (
        _positive_int(binding.get("tenant_id"), "tenant_id") != tenant_id
        or binding.get("dataset_key") != DEMO_DATASET_KEY
        or not isinstance(binding.get("dataset_version"), str)
        or not binding["dataset_version"].strip()
        or binding.get("status") != "active"
    ):
        raise GeoDemoBindingUnavailable()
    return GeoTenantPolicy(
        tenant_id=tenant_id,
        source_kind="isolated_demo",
        read_only=True,
        demo_tenant_id=_positive_int(binding.get("demo_tenant_id"), "demo_tenant_id"),
        dataset_key=DEMO_DATASET_KEY,
        dataset_version=binding["dataset_version"],
        binding_version=_positive_int(binding.get("version"), "version"),
        fixture_namespace=DEMO_FIXTURE_NAMESPACE,
    )


def enforce_demo_request(policy: GeoTenantPolicy, request: Request) -> None:
    if not policy.is_demo:
        return
    path = request.url.path.rstrip("/") or "/"
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"} and (
        path in DEMO_READ_PATHS
        or path.startswith("/api/v1/geo/integration/read/")
    ):
        return
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
