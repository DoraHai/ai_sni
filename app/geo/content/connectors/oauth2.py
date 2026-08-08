"""Generic OAuth2 authorization-code + refresh for social publish.

Credentials shape (auth_type=oauth2 or social_api provider=oauth2):
{
  "provider": "oauth2",
  "platform": "zhihu|baijiahao|toutiao|wechat|…",
  "client_id": "…",
  "client_secret": "…",
  "authorize_url": "https://…/oauth/authorize",
  "token_url": "https://…/oauth/token",
  "api_url": "https://…/publish",   # used after token for gateway POST
  "redirect_uri": "https://your-host/api/v1/geo/oauth/social/callback",
  "scope": "write",
  "access_token": "…",
  "refresh_token": "…",
  "token_expires_at": "ISO"
}

State is HMAC-signed (tenant_id, account_id, exp) — no server-side store required.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.geo.content.connectors.webhook import WEBHOOK_TIMEOUT, WebhookConnectorError

OAuth2Error = WebhookConnectorError


def _secret_key() -> bytes:
    from app.config import get_settings

    settings = get_settings()
    raw = (
        str(getattr(settings, "jwt_secret", None) or "")
        or str(getattr(settings, "admin_api_key", None) or "")
        or "geo-oauth-dev-only"
    )
    return hashlib.sha256(raw.encode("utf-8")).digest()


def sign_oauth_state(*, tenant_id: int, account_id: int, ttl_sec: int = 600) -> str:
    payload = {
        "tid": int(tenant_id),
        "aid": int(account_id),
        "exp": int(time.time()) + int(ttl_sec),
    }
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    sig = hmac.new(_secret_key(), body.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def parse_oauth_state(state: str) -> dict[str, int]:
    try:
        body, sig = state.split(".", 1)
    except ValueError as exc:
        raise OAuth2Error("OAuth state 无效") from exc
    expect = hmac.new(_secret_key(), body.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expect, sig):
        raise OAuth2Error("OAuth state 签名校验失败")
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    except Exception as exc:  # noqa: BLE001
        raise OAuth2Error("OAuth state 无法解码") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise OAuth2Error("OAuth state 已过期，请重新授权")
    return {"tenant_id": int(payload["tid"]), "account_id": int(payload["aid"])}


def build_authorize_url(creds: dict[str, Any], *, state: str) -> str:
    authorize_url = str(creds.get("authorize_url") or "").strip()
    client_id = str(creds.get("client_id") or "").strip()
    redirect_uri = str(creds.get("redirect_uri") or "").strip()
    if not authorize_url.startswith("https://"):
        raise OAuth2Error("authorize_url 须为 https://")
    if not client_id:
        raise OAuth2Error("client_id 必填")
    if not redirect_uri.startswith("https://") and not redirect_uri.startswith(
        "http://127.0.0.1"
    ):
        # allow local dev callback
        if not redirect_uri.startswith("http://localhost"):
            raise OAuth2Error("redirect_uri 须为 https:// 或本地 http://127.0.0.1|localhost")
    q = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    scope = str(creds.get("scope") or "").strip()
    if scope:
        q["scope"] = scope
    sep = "&" if "?" in authorize_url else "?"
    return f"{authorize_url}{sep}{urlencode(q)}"


async def exchange_code_for_tokens(creds: dict[str, Any], *, code: str) -> dict[str, Any]:
    token_url = str(creds.get("token_url") or "").strip()
    client_id = str(creds.get("client_id") or "").strip()
    client_secret = str(creds.get("client_secret") or "").strip()
    redirect_uri = str(creds.get("redirect_uri") or "").strip()
    if not token_url.startswith("https://") and not token_url.startswith("http://127.0.0.1"):
        if not token_url.startswith("http://localhost"):
            raise OAuth2Error("token_url 须为 https://（或本地开发 URL）")
    if not client_id or not client_secret:
        raise OAuth2Error("client_id / client_secret 必填")

    # Dev mock token endpoint
    if "mock" in token_url.lower() or str(client_id).startswith("mock_"):
        now = datetime.utcnow()
        return {
            "access_token": f"mock_oauth_at_{code[:8]}",
            "refresh_token": f"mock_oauth_rt_{code[:8]}",
            "token_expires_at": (now + timedelta(hours=2)).isoformat(timespec="seconds"),
            "token_type": "Bearer",
            "mock": True,
        }

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            resp = await client.post(token_url, data=data)
    except httpx.HTTPError as exc:
        raise OAuth2Error(f"OAuth token 交换失败: {exc}") from exc

    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise OAuth2Error(f"OAuth token 响应非 JSON: {(resp.text or '')[:300]}") from exc

    if resp.status_code >= 400 or body.get("error"):
        raise OAuth2Error(
            f"OAuth token 失败: {body.get('error') or body.get('message') or resp.status_code}"
        )
    access = str(body.get("access_token") or "").strip()
    if not access:
        raise OAuth2Error("OAuth token 响应缺少 access_token")
    expires_in = int(body.get("expires_in") or 7200)
    patch = {
        "access_token": access,
        "refresh_token": str(body.get("refresh_token") or creds.get("refresh_token") or ""),
        "token_expires_at": (
            datetime.utcnow() + timedelta(seconds=max(60, expires_in - 120))
        ).isoformat(timespec="seconds"),
        "token_type": str(body.get("token_type") or "Bearer"),
    }
    return patch


async def refresh_access_token(creds: dict[str, Any]) -> dict[str, Any]:
    token_url = str(creds.get("token_url") or "").strip()
    client_id = str(creds.get("client_id") or "").strip()
    client_secret = str(creds.get("client_secret") or "").strip()
    refresh = str(creds.get("refresh_token") or "").strip()
    if not refresh:
        raise OAuth2Error("无 refresh_token，请重新 OAuth 授权")
    if str(client_id).startswith("mock_") or "mock" in token_url.lower():
        now = datetime.utcnow()
        return {
            "access_token": f"mock_oauth_at_refreshed_{int(now.timestamp())}",
            "refresh_token": refresh,
            "token_expires_at": (now + timedelta(hours=2)).isoformat(timespec="seconds"),
            "mock": True,
        }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            resp = await client.post(token_url, data=data)
    except httpx.HTTPError as exc:
        raise OAuth2Error(f"OAuth refresh 失败: {exc}") from exc
    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise OAuth2Error(f"OAuth refresh 非 JSON: {(resp.text or '')[:300]}") from exc
    if resp.status_code >= 400 or body.get("error"):
        raise OAuth2Error(f"OAuth refresh 失败: {body.get('error') or resp.status_code}")
    access = str(body.get("access_token") or "").strip()
    if not access:
        raise OAuth2Error("OAuth refresh 未返回 access_token")
    expires_in = int(body.get("expires_in") or 7200)
    return {
        "access_token": access,
        "refresh_token": str(body.get("refresh_token") or refresh),
        "token_expires_at": (
            datetime.utcnow() + timedelta(seconds=max(60, expires_in - 120))
        ).isoformat(timespec="seconds"),
    }


def token_needs_refresh(creds: dict[str, Any]) -> bool:
    exp_raw = creds.get("token_expires_at")
    token = str(creds.get("access_token") or "").strip()
    if not token:
        return True
    if not exp_raw:
        return False
    try:
        exp = datetime.fromisoformat(str(exp_raw).replace("Z", ""))
    except ValueError:
        return False
    return exp <= datetime.utcnow() + timedelta(minutes=5)
