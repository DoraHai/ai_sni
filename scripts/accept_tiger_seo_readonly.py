#!/usr/bin/env python3
"""GET-only production acceptance for Tiger's SEO workbench scope.

The bearer token is read from an environment variable and is never serialized.
This script deliberately has no generic HTTP method helper: every request flows
through ``get_json`` so adding a write request requires an obvious code change.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://gsnipers.snipers.com.cn"
DEFAULT_TENANT_ID = 4
EXPECTED_DOMAIN = "tiger-coatings.cn"
TOKEN_ENV = "GSNIPERS_BEARER_TOKEN"


class AcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Probe:
    name: str
    path: str
    params: dict[str, Any]


class GetOnlyClient:
    def __init__(self, base_url: str, token: str, timeout: float = 20.0):
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise AcceptanceError("base URL must be an absolute HTTPS URL")
        if not token.strip():
            raise AcceptanceError(f"missing bearer token in {TOKEN_ENV}")
        self.base_url = base_url.rstrip("/") + "/"
        self._token = token.strip()
        self.timeout = timeout
        self.request_methods: list[str] = []

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = urlencode(
            {key: value for key, value in (params or {}).items() if value is not None}
        )
        url = urljoin(self.base_url, path.lstrip("/"))
        if query:
            url += "?" + query
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "gsnipers-seo-readonly-acceptance/1",
            },
        )
        self.request_methods.append(request.get_method())
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise AcceptanceError(f"GET {path} returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise AcceptanceError(f"GET {path} failed: {exc.reason}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise AcceptanceError(f"GET {path} did not return JSON") from exc


def _items(payload: Any, *keys: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _count(payload: Any, *keys: str) -> int:
    if isinstance(payload, dict):
        for key in ("total", "count"):
            value = payload.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return len(_items(payload, *keys))


def _timestamps(value: Any) -> list[str]:
    found: list[str] = []
    timestamp_keys = {
        "observed_at",
        "updated_at",
        "published_at",
        "checked_at",
        "fetched_at",
        "synced_at",
        "created_at",
        "completed_at",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            if key in timestamp_keys and isinstance(child, str) and child:
                found.append(child)
            elif isinstance(child, (dict, list)):
                found.extend(_timestamps(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_timestamps(child))
    return found


def _latest_timestamp(payload: Any) -> str | None:
    values = _timestamps(payload)
    parsed: list[tuple[datetime, str]] = []
    for value in values:
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)
            parsed.append((instant.astimezone(timezone.utc), value))
        except ValueError:
            continue
    return max(parsed, key=lambda item: item[0])[1] if parsed else None


def _coverage(payload: Any) -> Any:
    direct: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key in (
            "coverage",
            "coverage_status",
            "completeness",
            "data_quality",
            "status_counts",
            "selection_policy",
        ):
            if key in payload:
                direct[key] = payload[key]
    values = _items(payload, "items", "metrics")
    for key in ("status", "source", "data_quality", "completeness"):
        observed = sorted(
            {
                str(item[key])
                for item in values
                if isinstance(item, dict) and item.get(key) is not None
            }
        )
        if observed:
            direct[f"item_{key}"] = observed
    return direct or None


def _summarize(name: str, payload: Any, *item_keys: str) -> dict[str, Any]:
    return {
        "name": name,
        "count": _count(payload, *item_keys),
        "coverage": _coverage(payload),
        "freshness": _latest_timestamp(payload),
    }


def summarize_public_preflight(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    crawl = payload.get("crawl") if isinstance(payload, dict) else None
    snapshots = crawl.get("snapshots", []) if isinstance(crawl, dict) else []
    return {
        "source": "public_preflight",
        "production_data": False,
        "captured_at": payload.get("captured_at"),
        "candidate_domain": (payload.get("candidate_site") or {}).get("canonical_domain"),
        "discovered": crawl.get("discovered") if isinstance(crawl, dict) else None,
        "snapshots": len(snapshots),
        "http_200": sum(item.get("status_code") == 200 for item in snapshots),
        "fetch_errors": sum(bool(item.get("fetch_error")) for item in snapshots),
    }


def run_acceptance(
    get_json: Callable[[str, dict[str, Any] | None], Any],
    *,
    tenant_id: int = DEFAULT_TENANT_ID,
    expected_domain: str = EXPECTED_DOMAIN,
    public_preflight: Path | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "contract": "tiger-seo-readonly-v1",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tenant_id": tenant_id,
        "expected_domain": expected_domain,
        "request_policy": "GET-only",
        "production_mutations": 0,
        "probes": [],
    }

    identity = get_json("/api/v1/auth/me", None)
    identity_tenant = identity.get("tenant_id") if isinstance(identity, dict) else None
    # Superadmins can be unbound; ordinary users must be bound to Tiger.
    if identity_tenant not in (None, tenant_id):
        raise AcceptanceError(
            f"identity is bound to tenant {identity_tenant}, expected {tenant_id}"
        )
    report["identity"] = {
        "id": identity.get("id") if isinstance(identity, dict) else None,
        "tenant_id": identity_tenant,
        "is_superadmin": bool(identity.get("is_superadmin")) if isinstance(identity, dict) else False,
        "permission_keys": sorted((identity.get("permissions") or {}).keys())
        if isinstance(identity, dict) and isinstance(identity.get("permissions"), dict)
        else [],
    }

    modules = get_json("/api/v1/auth/modules", None)
    module_items = _items(modules, "modules")
    seo_modules = [item for item in module_items if item.get("module_code") == "seo"]
    report["module"] = {
        "seo_entries": len(seo_modules),
        "available": any(item.get("available") is True for item in seo_modules),
        "entries": seo_modules,
    }
    if not report["module"]["available"]:
        report["status"] = "seo_module_unavailable"
        return report

    sites_admin = get_json("/api/v1/seo/sites", {"tenant_id": tenant_id})
    sites_workbench = get_json(
        "/api/v1/seo/workbench/sites", {"tenant_id": tenant_id}
    )
    admin_items = _items(sites_admin, "sites")
    workbench_items = _items(sites_workbench, "sites")
    matches = [
        item
        for item in admin_items
        if item.get("canonical_domain") == expected_domain
        or item.get("domain", "").lower().replace("https://", "").replace("http://", "").strip("/").removeprefix("www.")
        == expected_domain
    ]
    report["sites"] = {
        "stored_count": len(admin_items),
        "workbench_count": len(workbench_items),
        "selection_policy": sites_workbench.get("selection_policy")
        if isinstance(sites_workbench, dict)
        else None,
        "expected_domain_matches": len(matches),
        "items": workbench_items,
    }
    if not matches:
        report["status"] = "empty_site"
        if public_preflight is not None:
            report["public_preflight"] = summarize_public_preflight(public_preflight)
        return report
    if len(matches) != 1:
        raise AcceptanceError(
            f"expected exactly one {expected_domain} site, found {len(matches)}"
        )

    site_id = matches[0].get("id")
    if not isinstance(site_id, int) or isinstance(site_id, bool):
        raise AcceptanceError("matched site has no integer id")
    report["site_id"] = site_id

    probes = [
        Probe("content", "/api/v1/seo/content-assets", {"tenant_id": tenant_id, "site_id": site_id, "page": 1, "page_size": 1}),
        Probe("publications", "/api/v1/seo/content-distribution/publications", {"tenant_id": tenant_id, "site_id": site_id}),
        Probe("pages", "/api/v1/seo/site-pages", {"tenant_id": tenant_id, "site_id": site_id, "page": 1, "page_size": 1}),
        Probe("gsc", "/api/v1/seo/traffic/gsc", {"tenant_id": tenant_id, "site_id": site_id}),
        Probe("metrics", "/api/v1/seo/cockpit/metrics/snapshot", {"tenant_id": tenant_id, "site_id": site_id}),
    ]
    payloads: dict[str, Any] = {}
    for probe in probes:
        payload = get_json(probe.path, probe.params)
        payloads[probe.name] = payload
        report["probes"].append(
            _summarize(probe.name, payload, "items", "sites", "metrics")
        )

    report["states"] = {
        "no_content": _count(payloads["content"], "items") == 0,
        "no_publications": _count(payloads["publications"], "items") == 0,
        "no_pages": _count(payloads["pages"], "items") == 0,
        "no_gsc": not bool(payloads["gsc"].get("enabled"))
        if isinstance(payloads["gsc"], dict)
        else True,
    }
    report["status"] = "readable"
    if public_preflight is not None:
        report["public_preflight"] = summarize_public_preflight(public_preflight)
    return report


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--tenant-id", type=int, default=DEFAULT_TENANT_ID)
    parser.add_argument("--expected-domain", default=EXPECTED_DOMAIN)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--public-preflight", type=Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    token = os.environ.get(TOKEN_ENV, "")
    try:
        client = GetOnlyClient(args.base_url, token, timeout=args.timeout)
        report = run_acceptance(
            client.get_json,
            tenant_id=args.tenant_id,
            expected_domain=args.expected_domain,
            public_preflight=args.public_preflight,
        )
        if any(method != "GET" for method in client.request_methods):
            raise AcceptanceError("non-GET request detected")
        report["client_request_methods"] = client.request_methods
        report["client_non_get_requests"] = 0
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        return 0
    except (AcceptanceError, OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"acceptance failed: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
