"""WeChat Official Account (公众号) native publish via open API.

Flow (server-side, not user OAuth page):
  1) GET access_token with app_id + app_secret (client_credential)
  2) POST draft/add with article HTML
  3) optional freepublish (mode=publish)

Credentials:
{
  "provider": "wechat_mp",
  "platform": "wechat",
  "app_id": "wx…",
  "app_secret": "…",
  "access_token": "cached optional",
  "token_expires_at": "2026-08-07T12:00:00"
}

Dev mock: set GEO_WECHAT_MP_MOCK=1 or app_id startswith "mock_".
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.geo.content.connectors.webhook import WebhookConnectorError, WEBHOOK_TIMEOUT

WechatMpError = WebhookConnectorError

TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
DRAFT_ADD_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"
FREE_PUBLISH_URL = "https://api.weixin.qq.com/cgi-bin/freepublish/submit"
# 永久素材：图文封面 thumb（type=thumb）
MEDIA_UPLOAD_URL = "https://api.weixin.qq.com/cgi-bin/material/add_material"


def wechat_mp_mock_enabled(app_id: str | None = None) -> bool:
    flag = str(os.environ.get("GEO_WECHAT_MP_MOCK") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if app_id and str(app_id).startswith("mock_"):
        return True
    return False


def _parse_expires(raw: Any) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", ""))
    except ValueError:
        return None


async def ensure_wechat_access_token(creds: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return (access_token, updated_creds_fields). May refresh token."""
    app_id = str(creds.get("app_id") or "").strip()
    app_secret = str(creds.get("app_secret") or "").strip()
    if not app_id or not app_secret:
        raise WechatMpError("wechat_mp 需要 app_id 与 app_secret")

    token = str(creds.get("access_token") or "").strip()
    exp = _parse_expires(creds.get("token_expires_at"))
    now = datetime.utcnow()
    if token and exp and exp > now + timedelta(minutes=5):
        return token, {}

    if wechat_mp_mock_enabled(app_id):
        new_token = f"mock_wx_token_{app_id[-6:]}"
        expires_at = (now + timedelta(hours=2)).isoformat(timespec="seconds")
        return new_token, {
            "access_token": new_token,
            "token_expires_at": expires_at,
        }

    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            resp = await client.get(
                TOKEN_URL,
                params={
                    "grant_type": "client_credential",
                    "appid": app_id,
                    "secret": app_secret,
                },
            )
    except httpx.HTTPError as exc:
        raise WechatMpError(f"微信 token 请求失败: {exc}") from exc

    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise WechatMpError(f"微信 token 响应非 JSON: {(resp.text or '')[:200]}") from exc

    if body.get("errcode"):
        raise WechatMpError(
            f"微信 token 失败 errcode={body.get('errcode')} errmsg={body.get('errmsg')}"
        )
    new_token = str(body.get("access_token") or "").strip()
    if not new_token:
        raise WechatMpError("微信 token 响应缺少 access_token")
    expires_in = int(body.get("expires_in") or 7200)
    expires_at = (now + timedelta(seconds=max(60, expires_in - 120))).isoformat(
        timespec="seconds"
    )
    return new_token, {
        "access_token": new_token,
        "token_expires_at": expires_at,
    }


async def download_image_bytes(url: str) -> tuple[bytes, str]:
    """Fetch cover image bytes; returns (data, filename)."""
    if not str(url).startswith(("https://", "http://")):
        raise WechatMpError("cover_image_url 须为 http(s) 地址")
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise WechatMpError(f"下载封面失败: {exc}") from exc
    if resp.status_code >= 400:
        raise WechatMpError(f"下载封面 HTTP {resp.status_code}")
    data = resp.content or b""
    if len(data) < 100:
        raise WechatMpError("封面图片过小或为空")
    if len(data) > 2 * 1024 * 1024:
        raise WechatMpError("封面图片超过 2MB")
    ctype = (resp.headers.get("content-type") or "").lower()
    ext = "jpg"
    if "png" in ctype:
        ext = "png"
    elif "gif" in ctype:
        ext = "gif"
    elif "webp" in ctype:
        ext = "jpg"
    return data, f"cover.{ext}"


async def wechat_upload_thumb(
    *,
    access_token: str,
    image_bytes: bytes,
    filename: str = "cover.jpg",
    app_id: str | None = None,
) -> str:
    """Upload permanent thumb material; returns media_id."""
    if wechat_mp_mock_enabled(app_id):
        return f"mock_thumb_{abs(hash(filename + str(len(image_bytes)))) % 10_000_000}"

    url = f"{MEDIA_UPLOAD_URL}?access_token={access_token}&type=thumb"
    files = {"media": (filename, image_bytes, "application/octet-stream")}
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            resp = await client.post(url, files=files)
    except httpx.HTTPError as exc:
        raise WechatMpError(f"微信上传封面失败: {exc}") from exc
    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise WechatMpError(f"微信上传封面非 JSON: {(resp.text or '')[:300]}") from exc
    if body.get("errcode") not in (None, 0):
        raise WechatMpError(
            f"微信上传封面失败 errcode={body.get('errcode')} errmsg={body.get('errmsg')}"
        )
    mid = str(body.get("media_id") or body.get("thumb_media_id") or "").strip()
    if not mid:
        raise WechatMpError("微信上传封面未返回 media_id")
    return mid


async def resolve_thumb_media_id(
    credentials: dict[str, Any],
    *,
    access_token: str,
) -> tuple[str | None, dict[str, Any]]:
    """Resolve cover: thumb_media_id | cover_image_url | cover_image_base64.

    Returns (thumb_media_id, credential_patch) — patch may cache uploaded id.
    """
    existing = str(credentials.get("thumb_media_id") or "").strip()
    if existing:
        return existing, {}

    app_id = str(credentials.get("app_id") or "")
    patch: dict[str, Any] = {}

    b64 = str(credentials.get("cover_image_base64") or "").strip()
    if b64:
        import base64

        raw = b64.split(",", 1)[-1]
        try:
            data = base64.b64decode(raw, validate=False)
        except Exception as exc:  # noqa: BLE001
            raise WechatMpError("cover_image_base64 无效") from exc
        if len(data) < 8:
            raise WechatMpError("cover_image_base64 解码后为空")
        mid = await wechat_upload_thumb(
            access_token=access_token,
            image_bytes=data,
            filename="cover.jpg",
            app_id=app_id,
        )
        patch["thumb_media_id"] = mid
        return mid, patch

    cover_url = str(credentials.get("cover_image_url") or "").strip()
    if cover_url:
        data, fname = await download_image_bytes(cover_url)
        mid = await wechat_upload_thumb(
            access_token=access_token,
            image_bytes=data,
            filename=fname,
            app_id=app_id,
        )
        patch["thumb_media_id"] = mid
        return mid, patch

    # optional: default mock thumb so draft always has a cover in mock mode
    if wechat_mp_mock_enabled(app_id):
        mid = "mock_thumb_default"
        return mid, {}

    return None, {}


async def wechat_draft_add(
    *,
    access_token: str,
    title: str,
    content_html: str,
    author: str = "GEO",
    digest: str = "",
    thumb_media_id: str | None = None,
    app_id: str | None = None,
) -> dict[str, Any]:
    if wechat_mp_mock_enabled(app_id):
        return {
            "ok": True,
            "mock": True,
            "media_id": f"mock_media_{abs(hash(title)) % 10_000_000}",
            "thumb_media_id": thumb_media_id or "mock_thumb_default",
            "http_status": 200,
        }

    article: dict[str, Any] = {
        "title": (title or "未命名")[:64],
        "author": (author or "GEO")[:16],
        "digest": (digest or content_html or "")[:120],
        "content": content_html or "",
        "content_source_url": "",
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }
    if thumb_media_id:
        article["thumb_media_id"] = thumb_media_id
    payload = {"articles": [article]}
    url = f"{DRAFT_ADD_URL}?access_token={access_token}"
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise WechatMpError(f"微信 draft/add 失败: {exc}") from exc

    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise WechatMpError(f"微信 draft/add 非 JSON: {(resp.text or '')[:300]}") from exc

    if body.get("errcode") not in (None, 0):
        raise WechatMpError(
            f"微信 draft/add 失败 errcode={body.get('errcode')} errmsg={body.get('errmsg')}"
        )
    media_id = body.get("media_id")
    if not media_id:
        raise WechatMpError("微信 draft/add 未返回 media_id")
    return {
        "ok": True,
        "media_id": media_id,
        "http_status": resp.status_code,
        "response": body,
    }


async def wechat_freepublish(
    *,
    access_token: str,
    media_id: str,
    app_id: str | None = None,
) -> dict[str, Any]:
    if wechat_mp_mock_enabled(app_id):
        return {
            "ok": True,
            "mock": True,
            "publish_id": f"mock_pub_{media_id[-8:]}",
            "http_status": 200,
        }

    url = f"{FREE_PUBLISH_URL}?access_token={access_token}"
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            resp = await client.post(url, json={"media_id": media_id})
    except httpx.HTTPError as exc:
        raise WechatMpError(f"微信 freepublish 失败: {exc}") from exc

    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise WechatMpError(f"微信 freepublish 非 JSON: {(resp.text or '')[:300]}") from exc

    if body.get("errcode") not in (None, 0):
        raise WechatMpError(
            f"微信 freepublish 失败 errcode={body.get('errcode')} errmsg={body.get('errmsg')}"
        )
    return {
        "ok": True,
        "publish_id": body.get("publish_id"),
        "http_status": resp.status_code,
        "response": body,
    }


async def publish_wechat_mp(
    credentials: dict[str, Any],
    *,
    mode: str,
    title: str,
    body_markdown: str,
    body_html: str | None = None,
) -> dict[str, Any]:
    """Full draft (+ optional freepublish). Returns connector result + credential patch.

    Cover resolution order: credentials.thumb_media_id → cover_image_url → cover_image_base64.
    Uploaded thumb_media_id is cached back into credentials for reuse.
    """
    token, patch = await ensure_wechat_access_token(credentials)
    app_id = str(credentials.get("app_id") or "")
    thumb_id, thumb_patch = await resolve_thumb_media_id(
        {**credentials, **patch},
        access_token=token,
    )
    if thumb_patch:
        patch = {**patch, **thumb_patch}

    content = body_html or body_markdown or ""
    draft = await wechat_draft_add(
        access_token=token,
        title=title,
        content_html=content,
        digest=(body_markdown or "")[:120],
        thumb_media_id=thumb_id,
        app_id=app_id,
    )
    result: dict[str, Any] = {
        "ok": True,
        "platform": "wechat",
        "provider": "wechat_mp",
        "http_status": draft.get("http_status", 200),
        "remote_url": None,
        "media_id": draft.get("media_id"),
        "thumb_media_id": thumb_id or draft.get("thumb_media_id"),
        "host": "api.weixin.qq.com",
        "response": draft.get("response") or draft,
        "credential_patch": patch,
        "mock": bool(draft.get("mock")),
    }
    if str(mode or "").lower() in {"publish", "freepublish", "release"}:
        pub = await wechat_freepublish(
            access_token=token,
            media_id=str(draft["media_id"]),
            app_id=str(credentials.get("app_id") or ""),
        )
        result["publish_id"] = pub.get("publish_id")
        result["response"] = {
            "draft": draft.get("response") or draft,
            "publish": pub.get("response") or pub,
        }
        if pub.get("mock"):
            result["mock"] = True
    return result
