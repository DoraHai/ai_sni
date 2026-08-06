"""Website/docs webhook publisher (Phase 2 MVP)."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urlparse

import httpx

from app.geo.audit import GeoAuditError, _ensure_public_host
from app.security.crypto import decrypt

ALLOWED_METHODS = frozenset({"POST", "PUT", "PATCH"})
WEBHOOK_TIMEOUT = 20.0

# Local demo under Clash/Surge fake-ip (198.18.0.0/15) resolves public hosts as
# "non-global". Allow well-known HTTPS sinks only when env is dev/test.
_DEV_WEBHOOK_HOST_ALLOWLIST = frozenset(
    {
        "httpbin.org",
        "www.httpbin.org",
        "postman-echo.com",
        "www.postman-echo.com",
        "webhook.site",
        "eoq9x.wiremockapi.cloud",
        # Local step-2 smoke: no outbound needed (fake-ip VPN / blocked public sinks)
        "geo-dev-sink.local",
    }
)


class WebhookConnectorError(ValueError):
    """User-facing connector validation / remote failure."""


async def ensure_webhook_public_url(url: str) -> None:
    """SSRF guard with optional dev hostname allowlist for demo sinks."""
    from app.config import get_settings

    host = (urlparse(url).hostname or "").lower()
    settings = get_settings()
    env = str(
        getattr(settings, "app_env", None)
        or getattr(settings, "env", None)
        or ""
    ).lower()
    if env in {"dev", "test", "local", "development"} and host in _DEV_WEBHOOK_HOST_ALLOWLIST:
        return
    try:
        await _ensure_public_host(url)
    except GeoAuditError as exc:
        raise WebhookConnectorError(str(exc)) from exc


def decrypt_credentials_json(encrypted: str | None) -> dict[str, Any]:
    if not encrypted:
        raise WebhookConnectorError("账号未配置凭证")
    try:
        raw = decrypt(encrypted)
    except Exception as exc:  # noqa: BLE001
        raise WebhookConnectorError("凭证解密失败") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WebhookConnectorError("凭证不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise WebhookConnectorError("凭证 JSON 须为对象")
    return data


def normalize_webhook_credentials(raw: dict[str, Any]) -> dict[str, Any]:
    url = str(raw.get("webhook_url") or "").strip()
    if not url.startswith("https://"):
        raise WebhookConnectorError("webhook_url 须为 https:// 地址")
    method = str(raw.get("method") or "POST").strip().upper()
    if method not in ALLOWED_METHODS:
        raise WebhookConnectorError("method 仅支持 POST / PUT / PATCH")
    headers_in = raw.get("headers") or {}
    if not isinstance(headers_in, dict):
        raise WebhookConnectorError("headers 须为对象")
    headers: dict[str, str] = {}
    for key, value in headers_in.items():
        k = str(key).strip()
        if not k or k.lower() in {"host", "content-length", "connection"}:
            continue
        headers[k] = str(value)
    secret = str(raw.get("secret") or "").strip() or None
    return {
        "webhook_url": url,
        "method": method,
        "headers": headers,
        "secret": secret,
    }


def extract_remote_url(response_json: Any) -> str | None:
    if not isinstance(response_json, dict):
        return None
    for key in ("url", "published_url", "permalink", "html_url"):
        value = response_json.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value.strip()
    data = response_json.get("data")
    if isinstance(data, dict):
        return extract_remote_url(data)
    return None


def build_webhook_payload(
    *,
    action: str,
    tenant_id: int,
    task_id: int,
    channel: str,
    channel_type: str,
    title: str,
    body_markdown: str,
    export_format: str,
    base_url: str | None,
) -> dict[str, Any]:
    return {
        "action": action,
        "tenant_id": tenant_id,
        "task_id": task_id,
        "channel": channel,
        "channel_type": channel_type,
        "title": title,
        "body_markdown": body_markdown,
        "export_format": export_format or "markdown",
        "base_url": base_url,
    }


async def post_webhook(
    credentials: dict[str, Any],
    payload: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Send webhook; returns {http_status, remote_url, response_json}."""
    creds = normalize_webhook_credentials(credentials)
    await ensure_webhook_public_url(creds["webhook_url"])

    host = (urlparse(creds["webhook_url"]).hostname or "").lower()
    from app.config import get_settings

    env = str(getattr(get_settings(), "app_env", "") or "").lower()
    # Dev sink: complete 审校→推送 without relying on public network / fake-ip.
    if env in {"dev", "test", "local", "development"} and host == "geo-dev-sink.local":
        task_id = payload.get("task_id") or "0"
        published = f"https://example.com/geo/published/{task_id}"
        return {
            "http_status": 200,
            "remote_url": published,
            "webhook_host": host,
            "response_json": {"ok": True, "url": published, "sink": "geo-dev-sink"},
        }

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "GrowthSniper-GEO-Webhook/1.0",
        **creds["headers"],
    }
    if creds["secret"]:
        digest = hmac.new(
            creds["secret"].encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        headers["X-GEO-Signature"] = f"sha256={digest}"

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT, follow_redirects=False)
    try:
        response = await http.request(
            creds["method"],
            creds["webhook_url"],
            content=body,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise WebhookConnectorError(f"Webhook 请求失败: {exc}") from exc
    finally:
        if owns_client:
            await http.aclose()

    if response.status_code < 200 or response.status_code >= 300:
        snippet = (response.text or "")[:200]
        raise WebhookConnectorError(
            f"Webhook 返回 HTTP {response.status_code}: {snippet}"
        )

    parsed: Any = None
    remote_url = None
    ctype = (response.headers.get("content-type") or "").lower()
    if "json" in ctype or (response.text or "").lstrip().startswith("{"):
        try:
            parsed = response.json()
            remote_url = extract_remote_url(parsed)
        except Exception:  # noqa: BLE001
            parsed = None
    return {
        "http_status": response.status_code,
        "remote_url": remote_url,
        "response_json": parsed if isinstance(parsed, dict) else None,
        "webhook_host": urlparse(creds["webhook_url"]).hostname,
    }
