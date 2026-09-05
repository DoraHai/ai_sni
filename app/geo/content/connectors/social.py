"""Social channel direct publish connector (wechat/zhihu/baijiahao/toutiao).

Providers:
  - gateway   : HTTPS middleware + access_token (legacy social_api)
  - wechat_mp : 微信公众号原生 draft/add (+ freepublish)
  - oauth2    : OAuth2 授权码/刷新后 POST api_url

Credentials examples — see docs/GEO_SOCIAL_OAUTH.md
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx

from app.geo.content.connectors.oauth2 import (
    OAuth2Error,
    refresh_access_token,
    token_needs_refresh,
)
from app.geo.content.connectors.webhook import (
    ALLOWED_METHODS,
    WEBHOOK_TIMEOUT,
    WebhookConnectorError,
    decrypt_credentials_json,
    ensure_webhook_public_url,
)
from app.geo.content.connectors.wechat_mp import WechatMpError, publish_wechat_mp

SOCIAL_PLATFORMS = frozenset({"wechat", "zhihu", "baijiahao", "toutiao"})
PROVIDERS = frozenset({"gateway", "wechat_mp", "oauth2"})
SocialError = WebhookConnectorError


def resolve_provider(raw: dict[str, Any], platform: str | None = None) -> str:
    p = str(raw.get("provider") or "").strip().lower()
    if p in PROVIDERS:
        return p
    # Heuristic: app_id+app_secret without api_url → wechat_mp
    if raw.get("app_id") and raw.get("app_secret") and not raw.get("api_url"):
        return "wechat_mp"
    if raw.get("authorize_url") and raw.get("token_url") and raw.get("client_id"):
        return "oauth2"
    return "gateway"


def normalize_social_credentials(raw: dict[str, Any]) -> dict[str, Any]:
    platform = str(raw.get("platform") or "").strip().lower()
    if platform and platform not in SOCIAL_PLATFORMS:
        raise SocialError(
            f"platform 须为 {', '.join(sorted(SOCIAL_PLATFORMS))} 之一"
        )
    provider = resolve_provider(raw, platform)

    if provider == "wechat_mp":
        app_id = str(raw.get("app_id") or "").strip()
        app_secret = str(raw.get("app_secret") or "").strip()
        if not app_id or not app_secret:
            raise SocialError("wechat_mp 需要 app_id 与 app_secret")
        return {
            "provider": "wechat_mp",
            "platform": "wechat",
            "app_id": app_id,
            "app_secret": app_secret,
            "access_token": str(raw.get("access_token") or "").strip() or None,
            "token_expires_at": raw.get("token_expires_at"),
            "mode_default": str(raw.get("mode_default") or "draft"),
        }

    if provider == "oauth2":
        api_url = str(raw.get("api_url") or "").strip()
        if api_url and not (
            api_url.startswith("https://")
            or api_url.startswith("http://127.0.0.1")
            or api_url.startswith("http://localhost")
        ):
            raise SocialError("oauth2 api_url 须为 https://（或本地开发 URL）")
        return {
            "provider": "oauth2",
            "platform": platform or "zhihu",
            "client_id": str(raw.get("client_id") or "").strip(),
            "client_secret": str(raw.get("client_secret") or "").strip(),
            "authorize_url": str(raw.get("authorize_url") or "").strip(),
            "token_url": str(raw.get("token_url") or "").strip(),
            "api_url": api_url,
            "redirect_uri": str(raw.get("redirect_uri") or "").strip(),
            "scope": str(raw.get("scope") or "").strip(),
            "access_token": str(raw.get("access_token") or "").strip() or None,
            "refresh_token": str(raw.get("refresh_token") or "").strip() or None,
            "token_expires_at": raw.get("token_expires_at"),
            "method": str(raw.get("method") or "POST").strip().upper(),
            "headers": {
                str(k): str(v)
                for k, v in (raw.get("headers") if isinstance(raw.get("headers"), dict) else {}).items()
            },
            "mode_default": str(raw.get("mode_default") or "draft"),
        }

    # gateway
    api_url = str(raw.get("api_url") or raw.get("webhook_url") or "").strip()
    if not api_url.startswith("https://"):
        raise SocialError("api_url 须为 https:// 地址（官方 API 或自建转发）")
    method = str(raw.get("method") or "POST").strip().upper()
    if method not in ALLOWED_METHODS:
        raise SocialError("method 仅支持 POST / PUT / PATCH")
    token = str(raw.get("access_token") or raw.get("token") or "").strip()
    if not token:
        raise SocialError("access_token 必填（gateway）")
    if not platform:
        raise SocialError("platform 必填")
    headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}
    return {
        "provider": "gateway",
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
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Platform-shaped payload for gateway/oauth2 publishers.

    Field shapes follow common open-platform conventions so middleware can
    map 1:1; remotes may ignore unknown keys.
    """
    md = body_markdown or ""
    html = body_html or md
    digest = md.replace("\n", " ").strip()[:120]
    base: dict[str, Any] = {
        "source": "growth-sniper-geo",
        "action": mode,
        "tenant_id": tenant_id,
        "task_id": task_id,
        "channel": channel,
        "platform": platform,
        "title": title,
        "content_markdown": md,
        "content_html": html,
        "summary": digest,
        "excerpt": digest[:100],
    }
    if platform == "wechat":
        # 对齐公众号草稿 articles[]（gateway 转发时可用）
        art: dict[str, Any] = {
            "title": (title or "")[:64],
            "author": "GEO",
            "digest": digest,
            "content": html,
            "content_source_url": "",
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }
        if extra and extra.get("thumb_media_id"):
            art["thumb_media_id"] = extra["thumb_media_id"]
        base["articles"] = [art]
    elif platform == "zhihu":
        # 知乎机构号常见：文章 title + content（markdown/html）
        base["type"] = "article"
        base["question_or_article"] = "article"
        base["content"] = md
        base["content_html"] = html
        base["zhihu"] = {
            "title": title,
            "content": md,
            "content_html": html,
            "excerpt": digest[:100],
            "can_reward": False,
        }
    elif platform == "baijiahao":
        # 百家号图文：title ≤40 汉字级、content HTML、is_original
        base["article"] = {
            "title": (title or "")[:40],
            "content": html,
            "origin_url": "",
            "cover_images": list((extra or {}).get("cover_images") or []),
            "is_original": 1,
            "abstract": digest[:80],
        }
        base["baijiahao"] = base["article"]
    elif platform == "toutiao":
        # 头条号常见 data 包裹
        base["data"] = {
            "title": title,
            "content": html,
            "content_markdown": md,
            "abstract": digest[:100],
            "article_type": 0,
            "cover_images": list((extra or {}).get("cover_images") or []),
        }
        base["article"] = base["data"]
        base["toutiao"] = base["data"]
    if extra:
        base["extra"] = extra
    return base


async def ensure_oauth_token(credentials: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Refresh oauth2 token if needed. Returns (creds_for_post, patch)."""
    creds = dict(credentials)
    if resolve_provider(creds) != "oauth2":
        return creds, {}
    if not token_needs_refresh(creds):
        return creds, {}
    try:
        patch = await refresh_access_token(creds)
    except OAuth2Error as exc:
        raise SocialError(str(exc)) from exc
    creds.update(patch)
    return creds, patch


async def post_social(
    credentials: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch by provider. May return credential_patch for persistence."""
    provider = resolve_provider(credentials)
    platform = str(
        credentials.get("platform") or payload.get("platform") or ""
    ).lower()

    if provider == "wechat_mp":
        try:
            result = await publish_wechat_mp(
                credentials,
                mode=str(payload.get("action") or "draft"),
                title=str(payload.get("title") or ""),
                body_markdown=str(payload.get("content_markdown") or ""),
                body_html=payload.get("content_html"),
            )
            return result
        except WechatMpError as exc:
            raise SocialError(str(exc)) from exc

    # oauth2 / gateway → HTTPS POST with Bearer token
    creds = credentials
    patch: dict[str, Any] = {}
    if provider == "oauth2":
        creds, patch = await ensure_oauth_token(credentials)
        if not creds.get("access_token"):
            raise SocialError("OAuth 未授权：请先完成授权回调获取 access_token")
        if not creds.get("api_url"):
            raise SocialError("oauth2 推送需要 api_url（发布接口）")

    try:
        norm = normalize_social_credentials({**creds, "provider": "gateway" if provider == "oauth2" else provider})
    except SocialError:
        # oauth2 already validated partly
        if provider != "oauth2":
            raise
        norm = {
            "provider": "oauth2",
            "platform": platform or "zhihu",
            "api_url": creds["api_url"],
            "method": str(creds.get("method") or "POST").upper(),
            "access_token": creds["access_token"],
            "headers": creds.get("headers") or {},
        }

    api_url = str(norm.get("api_url") or "")
    if api_url.startswith("https://"):
        await ensure_webhook_public_url(api_url)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {norm['access_token']}",
        "X-GEO-Platform": str(norm.get("platform") or platform),
        **(norm.get("headers") or {}),
    }
    url = api_url
    if "access_token=" not in url and str(norm.get("platform")) == "wechat":
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}access_token={norm['access_token']}"

    method = str(norm.get("method") or "POST").upper()
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT, follow_redirects=False, trust_env=False, limits=httpx.Limits(max_keepalive_connections=0)) as client:
            from app.geo.content.connectors.safe_http import public_request
            resp = await public_request(client,
                method,
                url,
                headers=headers,
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
    except httpx.HTTPError as exc:
        raise SocialError(f"社交 API 请求失败: {type(exc).__name__}") from exc

    if not 200 <= resp.status_code < 300:
        text = (resp.text or "")[:500]
        raise SocialError(f"社交 API 返回 HTTP {resp.status_code}")

    remote_url = None
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {"raw": (resp.text or "")[:1000]}
    if isinstance(body, dict):
        remote_url = body.get("url") or body.get("published_url") or body.get("link")
        data = body.get("data")
        if not remote_url and isinstance(data, dict):
            remote_url = data.get("url") or data.get("published_url")
    out = {
        "ok": True,
        "http_status": resp.status_code,
        "platform": norm.get("platform") or platform,
        "provider": provider,
        "remote_url": remote_url,
        "response": body if isinstance(body, dict) else {"data": body},
        "host": (urlparse(url).hostname or ""),
    }
    if patch:
        out["credential_patch"] = patch
    return out


__all__ = [
    "PROVIDERS",
    "SOCIAL_PLATFORMS",
    "SocialError",
    "build_social_payload",
    "decrypt_credentials_json",
    "ensure_oauth_token",
    "normalize_social_credentials",
    "post_social",
    "resolve_provider",
]
