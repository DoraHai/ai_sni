"""Google Search Console integration for verified, site-scoped organic traffic."""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import jwt

from app.config import get_settings


GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GSC_API = "https://www.googleapis.com/webmasters/v3"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GscError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.status_code = status_code


def _credentials() -> dict[str, str]:
    encoded = get_settings().seo_gsc_service_account_json_b64.strip()
    if not encoded:
        raise GscError("provider_not_configured", "生产环境尚未配置 Google Search Console 服务账号")
    try:
        payload = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GscError("invalid_credentials", "Google Search Console 服务账号配置无效") from exc
    required = ("client_email", "private_key")
    if not isinstance(payload, dict) or any(not str(payload.get(key) or "").strip() for key in required):
        raise GscError("invalid_credentials", "Google Search Console 服务账号配置不完整")
    token_uri = str(payload.get("token_uri") or GOOGLE_TOKEN_URI)
    if token_uri != GOOGLE_TOKEN_URI:
        raise GscError("invalid_credentials", "Google Search Console token 地址无效")
    return {"client_email": str(payload["client_email"]), "private_key": str(payload["private_key"])}


def gsc_status() -> dict[str, Any]:
    try:
        credentials = _credentials()
    except GscError:
        return {"configured": False, "provider": "google_search_console", "service_account_email": None}
    return {"configured": True, "provider": "google_search_console", "service_account_email": credentials["client_email"]}


def validate_property(property_url: str, canonical_domain: str) -> str:
    value = str(property_url or "").strip()
    domain = canonical_domain.lower().strip().rstrip(".")
    if value.startswith("sc-domain:"):
        property_domain = value.removeprefix("sc-domain:").lower().strip().rstrip(".")
        if property_domain != domain and not domain.endswith(f".{property_domain}"):
            raise GscError("property_mismatch", "Search Console 域名资产与当前 SEO 网站不匹配")
        return f"sc-domain:{property_domain}"
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        raise GscError("invalid_property", "请输入有效的 Search Console 网址前缀或 sc-domain: 域名资产")
    if host != domain and not host.endswith(f".{domain}") and not domain.endswith(f".{host}"):
        raise GscError("property_mismatch", "Search Console 网址资产与当前 SEO 网站不匹配")
    return value.rstrip("/") + "/"


async def _access_token(client: httpx.AsyncClient) -> str:
    credentials = _credentials()
    now = int(datetime.now(timezone.utc).timestamp())
    assertion = jwt.encode(
        {"iss": credentials["client_email"], "scope": GSC_SCOPE, "aud": GOOGLE_TOKEN_URI, "iat": now, "exp": now + 3600},
        credentials["private_key"],
        algorithm="RS256",
    )
    response = await client.post(GOOGLE_TOKEN_URI, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
    response.raise_for_status()
    token = str(response.json().get("access_token") or "")
    if not token:
        raise GscError("auth_failed", "Google Search Console 未返回访问令牌")
    return token


async def query_gsc_traffic(property_url: str, *, days: int = 28) -> dict[str, Any]:
    settings = get_settings()
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=days - 1)
    try:
        async with httpx.AsyncClient(timeout=max(1.0, settings.seo_gsc_timeout_seconds)) as client:
            token = await _access_token(client)
            response = await client.post(
                f"{GSC_API}/sites/{quote(property_url, safe='')}/searchAnalytics/query",
                headers={"Authorization": f"Bearer {token}"},
                json={"startDate": start_date.isoformat(), "endDate": end_date.isoformat(), "type": "web"},
            )
            response.raise_for_status()
            payload = response.json()
    except GscError:
        raise
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        message = "Search Console 资产未授权给服务账号" if status in {401, 403, 404} else "Google Search Console 接口返回错误"
        raise GscError("property_not_authorized" if status in {401, 403, 404} else "provider_http_error", message, status_code=status) from exc
    except (httpx.RequestError, ValueError, jwt.PyJWTError) as exc:
        raise GscError("provider_error", "Google Search Console 采集失败") from exc
    rows = payload.get("rows") if isinstance(payload, dict) and isinstance(payload.get("rows"), list) else []
    row = rows[0] if rows and isinstance(rows[0], dict) else {}
    return {
        "start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "days": days,
        "clicks": float(row.get("clicks") or 0), "impressions": float(row.get("impressions") or 0),
        "ctr": float(row.get("ctr") or 0), "position": float(row.get("position") or 0),
    }
