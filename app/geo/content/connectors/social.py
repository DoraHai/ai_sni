"""Social channel direct publish connector (wechat/zhihu/baijiahao/toutiao).

MVP: customer supplies HTTPS API endpoint + access_token (often their own
middleware in front of official platform APIs). We do not embed full OAuth
authorization code flows here — those stay env/ops configured externally.

Credentials JSON (auth_type=social_api):
{
  "platform": "wechat|zhihu|baijiahao|toutiao",
  "api_url": "https://api.example.com/geo/social/publish",
  "access_token": "…",
  "method": "POST",
  "headers": { "X-Extra": "…" },
  "mode_default": "draft"
}
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx

from app.geo.content.connectors.webhook import (
    ALLOWED_METHODS,
    WEBHOOK_TIMEOUT,
    WebhookConnectorError,
    decrypt_credentials_json,
    ensure_webhook_public_url,
)

SOCIAL_PLATFORMS = frozenset({"wechat", "zhihu", "baijiahao", "toutiao"})
SocialError = WebhookConnectorError


def normalize_social_credentials(raw: dict[str, Any]) -> dict[str, Any]:
    platform = str(raw.get("platform") or "").strip().lower()
    if platform not in SOCIAL_PLATFORMS:
        raise SocialError(
            f"platform 须为 {', '.join(sorted(SOCIAL_PLATFORMS))} 之一"
        )
    api_url = str(raw.get("api_url") or raw.get("webhook_url") or "").strip()
    if not api_url.startswith("https://"):
        raise SocialError("api_url 须为 https:// 地址（官方 API 或自建转发）")
    method = str(raw.get("method") or "POST").strip().upper()
    if method not in ALLOWED_METHODS:
        raise SocialError("method 仅支持 POST / PUT / PATCH")
    token = str(raw.get("access_token") or raw.get("token") or "").strip()
    if not token:
        raise SocialError("access_token 必填")
    headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}
    return {
        "platform": platform,
        "api_url": api_url,
        "method": method,
        "access_token": token,
        "headers": {str(k): str(v) for k, v in headers.items()},
        "mode_default": str(raw.get("mode_default") or "draft"),
        "app_id": str(raw.get("app_id") or "").strip() or None,
    }


def build_social_payload(
    *,
    platform: str,
    mode: str,
    tenant_id: int,
    task_id: int,
    channel: str,
    title: str,
    body_markdown: str,
    body_html: str | None = None,
) -> dict[str, Any]:
    """Platform-shaped payload; remotes may ignore unknown fields."""
    base = {
        "source": "growth-sniper-geo",
        "action": mode,
        "tenant_id": tenant_id,
        "task_id": task_id,
        "channel": channel,
        "platform": platform,
        "title": title,
        "content_markdown": body_markdown,
        "content_html": body_html or body_markdown,
    }
    if platform == "wechat":
        # Align with common draft-add style fields
        base["articles"] = [
            {
                "title": title[:64],
                "author": "GEO",
                "digest": (body_markdown or "")[:120],
                "content": body_html or body_markdown,
                "content_source_url": "",
            }
        ]
    elif platform == "zhihu":
        base["question_or_article"] = "article"
        base["content"] = body_markdown
    elif platform in {"baijiahao", "toutiao"}:
        base["article"] = {"title": title, "content": body_markdown}
    return base


async def post_social(
    credentials: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    creds = normalize_social_credentials(credentials)
    await ensure_webhook_public_url(creds["api_url"])
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {creds['access_token']}",
        "X-GEO-Platform": creds["platform"],
        **creds["headers"],
    }
    # Some WeChat-style APIs put token in query
    url = creds["api_url"]
    if "access_token=" not in url and creds["platform"] == "wechat":
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}access_token={creds['access_token']}"

    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT, follow_redirects=False) as client:
            resp = await client.request(
                creds["method"],
                url,
                headers=headers,
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
    except httpx.HTTPError as exc:
        raise SocialError(f"社交 API 请求失败: {exc}") from exc

    if resp.status_code >= 400:
        text = (resp.text or "")[:500]
        raise SocialError(f"社交 API 返回 HTTP {resp.status_code}: {text}")

    remote_url = None
    body: Any
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {"raw": (resp.text or "")[:1000]}
    if isinstance(body, dict):
        remote_url = body.get("url") or body.get("published_url") or body.get("link")
        data = body.get("data")
        if not remote_url and isinstance(data, dict):
            remote_url = data.get("url") or data.get("published_url")
    return {
        "ok": True,
        "http_status": resp.status_code,
        "platform": creds["platform"],
        "remote_url": remote_url,
        "response": body if isinstance(body, dict) else {"data": body},
        "host": (urlparse(url).hostname or ""),
    }


__all__ = [
    "SOCIAL_PLATFORMS",
    "SocialError",
    "build_social_payload",
    "decrypt_credentials_json",
    "normalize_social_credentials",
    "post_social",
]
