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
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_BASE_URL = "https://gsnipers.snipers.com.cn"
DEFAULT_TENANT_ID = 4
EXPECTED_DOMAIN = "tiger-coatings.cn"
TOKEN_ENV = "GSNIPERS_BEARER_TOKEN"
METRICS_PATH = "/api/v1/seo/metrics/snapshot"
REQUIRED_SEO_PERMISSIONS = (
    "seo.assets",
    "seo.content",
    "seo.site",
    "seo.keywords",
)
SELECTABLE_SITE_STATUSES = ["active"]
DISABLED_SITE_STATUSES = ["paused", "archived"]


class AcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Probe:
    name: str
    path: str
    params: dict[str, Any]


def _validated_base_origin(value: str) -> tuple[str, str, int]:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise AcceptanceError("invalid production origin port") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "gsnipers.snipers.com.cn"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise AcceptanceError(
            "production origin must be exactly https://gsnipers.snipers.com.cn"
        )
    return (parsed.scheme, parsed.hostname, 443)


class SameOriginRedirectHandler(HTTPRedirectHandler):
    """Follow redirects only while the bearer remains on the fixed origin."""

    allowed_origin = _validated_base_origin(DEFAULT_BASE_URL)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        absolute = urljoin(req.full_url, newurl)
        parsed = urlparse(absolute)
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise AcceptanceError("redirect has an invalid port") from exc
        target_origin = (parsed.scheme, parsed.hostname, port)
        if (
            parsed.username is not None
            or parsed.password is not None
            or target_origin != self.allowed_origin
        ):
            raise AcceptanceError("cross-origin redirect blocked before authorization forwarding")
        return super().redirect_request(req, fp, code, msg, headers, absolute)


class GetOnlyClient:
    def __init__(self, token: str, timeout: float = 20.0, opener=None):
        _validated_base_origin(DEFAULT_BASE_URL)
        if not token.strip():
            raise AcceptanceError(f"missing bearer token in {TOKEN_ENV}")
        self.base_url = DEFAULT_BASE_URL + "/"
        self._token = token.strip()
        self.timeout = timeout
        self._opener = opener or build_opener(SameOriginRedirectHandler())
        self.request_methods: list[str] = []

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        parsed_path = urlparse(path)
        if not path.startswith("/") or parsed_path.scheme or parsed_path.netloc:
            raise AcceptanceError("probe path must be relative to the fixed production origin")
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
            with self._opener.open(request, timeout=self.timeout) as response:
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


def _canonical_domain(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().rstrip(".")
    return host.removeprefix("www.") or None


def _route_is_mounted(openapi: Any, path: str) -> bool:
    paths = openapi.get("paths") if isinstance(openapi, dict) else None
    operations = paths.get(path) if isinstance(paths, dict) else None
    return isinstance(operations, dict) and isinstance(operations.get("get"), dict)


def _identity_user(payload: Any) -> dict[str, Any]:
    user = payload.get("user") if isinstance(payload, dict) else None
    if not isinstance(user, dict):
        raise AcceptanceError("GET /api/v1/auth/me did not return the user envelope")
    if not isinstance(user.get("id"), int) or isinstance(user.get("id"), bool):
        raise AcceptanceError("GET /api/v1/auth/me returned an invalid user id")
    permissions = user.get("permissions")
    if not isinstance(permissions, dict):
        raise AcceptanceError("GET /api/v1/auth/me returned invalid permissions")
    missing = [
        key
        for key in REQUIRED_SEO_PERMISSIONS
        if permissions.get(key) not in {"view", "edit"}
    ]
    if missing:
        raise AcceptanceError(
            "ordinary SEO acceptance identity lacks required view permission: "
            + ", ".join(missing)
        )
    return user


def _selection_policy_matches(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    policy = payload.get("selection_policy")
    return isinstance(policy, dict) and (
        policy.get("selectable_statuses") == SELECTABLE_SITE_STATUSES
        and policy.get("disabled_statuses") == DISABLED_SITE_STATUSES
    )


def run_acceptance(
    get_json: Callable[[str, dict[str, Any] | None], Any],
    *,
    public_preflight: Path | None = None,
) -> dict[str, Any]:
    tenant_id = DEFAULT_TENANT_ID
    expected_domain = EXPECTED_DOMAIN
    report: dict[str, Any] = {
        "contract": "tiger-seo-readonly-v1",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tenant_id": tenant_id,
        "expected_domain": expected_domain,
        "request_policy": "GET-only",
        "production_mutations": 0,
        "probes": [],
    }

    openapi = get_json("/openapi.json", None)
    if not _route_is_mounted(openapi, METRICS_PATH):
        raise AcceptanceError(f"required GET route is not mounted: {METRICS_PATH}")
    report["route_contract"] = {"path": METRICS_PATH, "get_mounted": True}

    identity_payload = get_json("/api/v1/auth/me", None)
    identity = _identity_user(identity_payload)
    identity_tenant = identity.get("tenant_id")
    # This acceptance is intentionally scoped to an ordinary Tiger account.
    if identity_tenant != tenant_id:
        raise AcceptanceError(
            f"identity is bound to tenant {identity_tenant}, expected {tenant_id}"
        )
    report["identity"] = {
        "id": identity.get("id"),
        "tenant_id": identity_tenant,
        "permission_keys": sorted(identity["permissions"].keys()),
        "required_permission_keys": list(REQUIRED_SEO_PERMISSIONS),
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
    admin_domain_candidates = [
        item
        for item in admin_items
        if _canonical_domain(item.get("domain")) == expected_domain
    ]
    matches = [
        item
        for item in admin_domain_candidates
        if item.get("canonical_domain") == expected_domain
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
    if not _selection_policy_matches(sites_workbench):
        report["status"] = "site_unavailable"
        report["site_unavailable_reasons"] = ["selection_policy_mismatch"]
        return report
    if not matches:
        if admin_domain_candidates:
            report["status"] = "site_unavailable"
            report["site_unavailable_reasons"] = [
                "canonical_domain_mismatch_in_admin_list"
            ]
            return report
        report["status"] = "empty_site"
        if public_preflight is not None:
            report["public_preflight"] = summarize_public_preflight(public_preflight)
        return report
    if len(matches) != 1:
        report["status"] = "site_unavailable"
        report["site_unavailable_reasons"] = ["expected_domain_duplicate_in_admin_list"]
        return report

    admin_site = matches[0]
    site_id = admin_site.get("id")
    if not isinstance(site_id, int) or isinstance(site_id, bool):
        raise AcceptanceError("matched site has no integer id")
    workbench_matches = [item for item in workbench_items if item.get("id") == site_id]
    workbench_domain_matches = [
        item
        for item in workbench_items
        if item.get("domain") == admin_site.get("domain")
    ]
    drift_reasons: list[str] = []
    if len(workbench_matches) != 1:
        drift_reasons.append("site_id_missing_or_duplicate_in_workbench_list")
    else:
        workbench_site = workbench_matches[0]
        if workbench_site.get("domain") != admin_site.get("domain"):
            drift_reasons.append("domain_mismatch_between_site_lists")
        if workbench_site.get("status") != admin_site.get("status"):
            drift_reasons.append("status_mismatch_between_site_lists")
    if len(workbench_domain_matches) != 1:
        drift_reasons.append("expected_domain_missing_or_duplicate_in_workbench_list")
    elif workbench_domain_matches[0].get("id") != site_id:
        drift_reasons.append("site_id_mismatch_for_expected_domain")
    if admin_site.get("status") not in SELECTABLE_SITE_STATUSES:
        drift_reasons.append("site_status_not_selectable")
    if drift_reasons:
        report["status"] = "site_unavailable"
        report["site_id"] = site_id
        report["site_unavailable_reasons"] = drift_reasons
        return report
    report["site_id"] = site_id

    probes = [
        Probe("content", "/api/v1/seo/content-assets", {"tenant_id": tenant_id, "site_id": site_id, "page": 1, "page_size": 1}),
        Probe("publications", "/api/v1/seo/content-distribution/publications", {"tenant_id": tenant_id, "site_id": site_id}),
        Probe("pages", "/api/v1/seo/site-pages", {"tenant_id": tenant_id, "site_id": site_id, "page": 1, "page_size": 1}),
        Probe("gsc", "/api/v1/seo/traffic/gsc", {"tenant_id": tenant_id, "site_id": site_id}),
        Probe("metrics", METRICS_PATH, {"tenant_id": tenant_id, "site_id": site_id}),
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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--public-preflight", type=Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    token = os.environ.get(TOKEN_ENV, "")
    try:
        client = GetOnlyClient(token, timeout=args.timeout)
        report = run_acceptance(
            client.get_json,
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
