"""SEO-only content distribution catalog and bounded publishing adapters."""

from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import json
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import jwt
from bs4 import BeautifulSoup

from app.security.crypto import decrypt, encrypt


_WECHAT_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_WECHAT_IMAGE_LIMIT = 20
_WECHAT_IMAGE_MAX_BYTES = 1024 * 1024


class SeoDistributionError(RuntimeError):
    pass


PLATFORM_CATALOG: dict[str, dict[str, Any]] = {
    "wordpress": {
        "name": "WordPress",
        "mode": "api",
        "available": True,
        "capabilities": ["connection_test", "draft", "publish", "status_link"],
        "credential_fields": [
            {"key": "username", "label": "用户名", "type": "text"},
            {"key": "application_password", "label": "应用密码", "type": "password"},
        ],
        "base_url_label": "WordPress 站点地址",
        "help": "推荐先创建草稿；使用可单独撤销的 Application Password。",
    },
    "ghost": {
        "name": "Ghost",
        "mode": "api",
        "available": True,
        "capabilities": ["connection_test", "draft", "publish", "status_link"],
        "credential_fields": [
            {"key": "admin_api_key", "label": "Admin API Key", "type": "password"},
        ],
        "base_url_label": "Ghost 站点地址",
        "help": "在 Ghost 后台创建 Custom Integration 后复制 Admin API Key。",
    },
    "zhihu": {
        "name": "知乎",
        "mode": "assisted",
        "available": True,
        "capabilities": ["adapt", "copy", "open_editor", "manual_confirm"],
        "credential_fields": [],
        "editor_url": "https://zhuanlan.zhihu.com/write",
        "help": "生成知乎适配稿并打开官方编辑器，由用户最终确认发布。",
    },
    "csdn": {
        "name": "CSDN",
        "mode": "assisted",
        "available": True,
        "capabilities": ["adapt", "copy", "open_editor", "manual_confirm"],
        "credential_fields": [],
        "editor_url": "https://editor.csdn.net/md/",
        "help": "复制适配稿并打开官方编辑器，不保存账号密码或 Cookie。",
    },
    "juejin": {
        "name": "掘金",
        "mode": "assisted",
        "available": True,
        "capabilities": ["adapt", "copy", "open_editor", "manual_confirm"],
        "credential_fields": [],
        "editor_url": "https://juejin.cn/editor/drafts/new?v=2",
        "help": "复制适配稿并打开官方编辑器，不调用非公开接口。",
    },
    "jianshu": {
        "name": "简书",
        "mode": "assisted",
        "available": True,
        "capabilities": ["adapt", "copy", "open_editor", "manual_confirm"],
        "credential_fields": [],
        "editor_url": "https://www.jianshu.com/writer",
        "help": "复制适配稿并打开官方编辑器，不调用非公开接口。",
    },
    "wechat_official": {
        "name": "微信公众号",
        "mode": "api",
        "available": True,
        "base_url_required": False,
        "capabilities": ["connection_test", "draft", "publish", "async_status"],
        "credential_fields": [
            {"key": "app_id", "label": "AppID", "type": "text"},
            {"key": "app_secret", "label": "AppSecret", "type": "password"},
            {"key": "thumb_media_id", "label": "永久封面素材 ID", "type": "text"},
        ],
        "help": "通过官方草稿箱与发布接口接入；账号需具备对应权限，并将服务器出口 IP 加入白名单。",
    },
    "weibo": {
        "name": "微博",
        "mode": "oauth",
        "available": False,
        "capabilities": ["publish", "async_status"],
        "credential_fields": [],
        "help": "需要 OAuth 回调和共享认证边界审批，当前只展示规划状态。",
    },
    "xiaohongshu": {
        "name": "小红书",
        "mode": "share",
        "available": False,
        "capabilities": ["adapt", "open_editor", "manual_confirm"],
        "credential_fields": [],
        "help": "官方能力需要拉起发布器并由用户确认，不做后台模拟登录。",
    },
    "douyin": {
        "name": "抖音图文",
        "mode": "share",
        "available": False,
        "capabilities": ["adapt", "open_editor", "manual_confirm"],
        "credential_fields": [],
        "help": "投稿能力需要平台准入，且更适合图集而非 SEO 长文章。",
    },
}


def platform_catalog() -> list[dict[str, Any]]:
    return [{"code": code, **value} for code, value in PLATFORM_CATALOG.items()]


def platform_definition(code: str) -> dict[str, Any]:
    item = PLATFORM_CATALOG.get((code or "").strip().lower())
    if not item:
        raise SeoDistributionError("不支持的分发平台")
    return item


def normalize_base_url(value: str | None) -> str | None:
    raw = (value or "").strip().rstrip("/")
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SeoDistributionError("API 平台地址必须是完整的 HTTPS 公网地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SeoDistributionError("平台地址不能包含账号、密码、查询参数或锚点")
    if parsed.hostname.lower() == "localhost":
        raise SeoDistributionError("平台地址不能指向本机或内网")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise SeoDistributionError("平台地址不能指向本机或内网")
    return raw


async def ensure_public_endpoint(value: str) -> str:
    normalized = normalize_base_url(value)
    if not normalized:
        raise SeoDistributionError("API 平台必须填写站点地址")
    parsed = urlparse(normalized)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise SeoDistributionError("平台域名无法解析") from exc
    addresses = {item[4][0] for item in infos}
    if not addresses:
        raise SeoDistributionError("平台域名没有可用公网地址")
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise SeoDistributionError("平台域名解析到了本机或内网地址")
    return normalized


def normalize_credentials(platform_code: str, credentials: dict[str, Any] | None) -> dict[str, str]:
    definition = platform_definition(platform_code)
    raw = credentials or {}
    expected = [item["key"] for item in definition.get("credential_fields", [])]
    cleaned = {key: str(raw.get(key) or "").strip() for key in expected}
    if definition["mode"] == "api" and definition.get("available"):
        missing = [key for key, value in cleaned.items() if not value]
        if missing:
            raise SeoDistributionError("请完整填写平台授权信息")
    return cleaned


def encrypt_credentials(credentials: dict[str, str]) -> str | None:
    if not credentials:
        return None
    return encrypt(json.dumps(credentials, ensure_ascii=False, sort_keys=True))


def decrypt_credentials(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        result = json.loads(decrypt(value))
    except Exception as exc:
        raise SeoDistributionError("平台授权信息无法解密，请重新配置") from exc
    if not isinstance(result, dict):
        raise SeoDistributionError("平台授权信息格式错误，请重新配置")
    return {str(key): str(item) for key, item in result.items()}


def sanitize_article_html(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    blocked_tags = {"script", "style", "iframe", "object", "embed", "form", "input", "button", "link", "meta"}
    allowed_tags = {
        "p", "h1", "h2", "h3", "h4", "h5", "h6", "a", "img", "ul", "ol", "li",
        "strong", "b", "em", "i", "u", "s", "blockquote", "pre", "code", "br", "hr",
        "table", "thead", "tbody", "tr", "th", "td", "figure", "figcaption",
    }
    for tag in soup.find_all(blocked_tags):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if tag.name not in allowed_tags:
            tag.unwrap()
    allowed_attributes = {"href", "src", "data-src", "alt", "title"}
    for tag in soup.find_all(True):
        for attribute in list(tag.attrs):
            if attribute.lower() not in allowed_attributes:
                del tag.attrs[attribute]
        for attribute in ("href", "src", "data-src"):
            target = str(tag.attrs.get(attribute) or "").strip()
            if target and urlparse(target).scheme.lower() not in {"", "http", "https"}:
                del tag.attrs[attribute]
    return str(soup).strip()


def _safe_remote_page_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise SeoDistributionError("平台返回的文章链接不安全，请到平台后台核对发布结果")
    if parsed.username or parsed.password:
        raise SeoDistributionError("平台返回的文章链接不安全，请到平台后台核对发布结果")
    return raw


def prepare_content(title: str, content: str, platform_code: str) -> dict[str, str]:
    clean_title = " ".join((title or "").split()).strip()
    clean_content = (content or "").strip()
    if not clean_title:
        raise SeoDistributionError("文章缺少标题")
    if not clean_content:
        raise SeoDistributionError("文章缺少可发布正文")
    max_title = 32 if platform_code == "wechat_official" else 80 if platform_code in {"wordpress", "ghost"} else 60
    adapted_title = clean_title[:max_title]
    if "<p" in clean_content.lower() or "<h" in clean_content.lower():
        content_html = sanitize_article_html(clean_content)
        adapted_content = content_html
        plain = BeautifulSoup(content_html, "html.parser").get_text(" ", strip=True)
    else:
        paragraphs = [part.strip() for part in clean_content.splitlines() if part.strip()]
        content_html = "\n".join(f"<p>{html.escape(part)}</p>" for part in paragraphs)
        adapted_content = clean_content
        plain = clean_content
    excerpt = " ".join(plain.split())[:120 if platform_code == "wechat_official" else 160]
    return {
        "title": adapted_title,
        "excerpt": excerpt,
        "content": adapted_content,
        "content_html": content_html,
    }


def publication_idempotency_key(
    tenant_id: int,
    content_asset_id: int,
    connection_id: int,
    source_version: int,
    action: str,
) -> str:
    raw = f"{tenant_id}:{content_asset_id}:{connection_id}:{source_version}:{action}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ghost_token(admin_api_key: str) -> str:
    try:
        key_id, secret = admin_api_key.split(":", 1)
        secret_bytes = bytes.fromhex(secret)
    except (ValueError, TypeError) as exc:
        raise SeoDistributionError("Ghost Admin API Key 格式不正确") from exc
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp()), "aud": "/admin/"},
        secret_bytes,
        algorithm="HS256",
        headers={"kid": key_id, "typ": "JWT"},
    )


@dataclass
class RemotePublishResult:
    status: str
    external_id: str | None = None
    page_url: str | None = None
    response_summary: dict[str, Any] | None = None
    error: str | None = None


def _response_json(response: httpx.Response, action: str) -> dict[str, Any]:
    try:
        body = response.json() if response.content else {}
    except ValueError as exc:
        raise SeoDistributionError(f"{action}返回了无法识别的数据") from exc
    if response.status_code >= 400:
        raise SeoDistributionError(f"{action}失败（HTTP {response.status_code}）")
    if not isinstance(body, dict):
        raise SeoDistributionError(f"{action}返回了无法识别的数据")
    error_code = int(body.get("errcode") or 0)
    if error_code:
        message = str(body.get("errmsg") or "未知错误")[:200]
        raise SeoDistributionError(f"{action}失败（微信错误码 {error_code}：{message}）")
    return body


async def _wechat_access_token(client: httpx.AsyncClient, credentials: dict[str, str]) -> str:
    cache_key = hashlib.sha256(
        f"{credentials['app_id']}:{credentials['app_secret']}".encode("utf-8")
    ).hexdigest()
    cached = _WECHAT_TOKEN_CACHE.get(cache_key)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    response = await client.post(
        "https://api.weixin.qq.com/cgi-bin/stable_token",
        json={
            "grant_type": "client_credential",
            "appid": credentials["app_id"],
            "secret": credentials["app_secret"],
            "force_refresh": False,
        },
    )
    body = _response_json(response, "获取微信公众号调用凭证")
    token = str(body.get("access_token") or "")
    if not token:
        raise SeoDistributionError("微信公众号未返回调用凭证")
    expires_in = max(60, int(body.get("expires_in") or 300))
    _WECHAT_TOKEN_CACHE[cache_key] = (token, time.monotonic() + min(300, expires_in - 30))
    return token


async def _ensure_public_image_url(value: str) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise SeoDistributionError("正文图片必须使用完整的 HTTP/HTTPS 公网地址")
    if parsed.username or parsed.password:
        raise SeoDistributionError("正文图片地址不能包含账号或密码")
    if parsed.hostname.lower() == "localhost":
        raise SeoDistributionError("正文图片不能指向本机或内网地址")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise SeoDistributionError("正文图片不能指向本机或内网地址")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise SeoDistributionError("正文图片域名无法解析") from exc
    addresses = {item[4][0] for item in infos}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise SeoDistributionError("正文图片域名解析到了本机或内网地址")
    return raw


async def _download_wechat_image(value: str, position: int) -> tuple[str, bytes, str]:
    url = value
    timeout = httpx.Timeout(15.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(4):
            url = await _ensure_public_image_url(url)
            try:
                async with client.stream("GET", url, headers={"Accept": "image/png,image/jpeg"}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise SeoDistributionError(f"第 {position} 张图片重定向地址无效")
                        url = urljoin(url, location)
                        continue
                    if response.status_code >= 400:
                        raise SeoDistributionError(
                            f"第 {position} 张图片下载失败（HTTP {response.status_code}）"
                        )
                    declared_size = int(response.headers.get("content-length") or 0)
                    if declared_size > _WECHAT_IMAGE_MAX_BYTES:
                        raise SeoDistributionError(f"第 {position} 张图片超过微信 1MB 限制")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > _WECHAT_IMAGE_MAX_BYTES:
                            raise SeoDistributionError(f"第 {position} 张图片超过微信 1MB 限制")
                    raw = bytes(data)
                    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
                        return f"article-{position}.png", raw, "image/png"
                    if raw.startswith(b"\xff\xd8\xff"):
                        return f"article-{position}.jpg", raw, "image/jpeg"
                    raise SeoDistributionError(f"第 {position} 张图片不是微信支持的 JPG/PNG 格式")
            except httpx.HTTPError as exc:
                raise SeoDistributionError(f"第 {position} 张图片下载失败") from exc
    raise SeoDistributionError(f"第 {position} 张图片重定向次数过多")


async def _rewrite_wechat_images(
    client: httpx.AsyncClient,
    token: str,
    content_html: str,
) -> tuple[str, int]:
    soup = BeautifulSoup(content_html, "html.parser")
    images = list(soup.find_all("img"))
    if len(images) > _WECHAT_IMAGE_LIMIT:
        raise SeoDistributionError(f"单篇文章最多自动处理 {_WECHAT_IMAGE_LIMIT} 张正文图片")
    uploaded: dict[str, str] = {}
    for position, tag in enumerate(images, 1):
        source = str(tag.attrs.get("src") or tag.attrs.get("data-src") or "").strip()
        if not source:
            raise SeoDistributionError(f"第 {position} 张图片缺少有效地址")
        if source not in uploaded:
            filename, data, content_type = await _download_wechat_image(source, position)
            try:
                response = await client.post(
                    "https://api.weixin.qq.com/cgi-bin/media/uploadimg",
                    params={"access_token": token},
                    files={"media": (filename, data, content_type)},
                )
            except httpx.HTTPError as exc:
                raise SeoDistributionError(f"第 {position} 张图片上传微信失败") from exc
            body = _response_json(response, f"上传第 {position} 张公众号正文图片")
            uploaded[source] = _safe_remote_page_url(body.get("url")) or ""
            if not uploaded[source]:
                raise SeoDistributionError(f"第 {position} 张图片上传后未返回素材地址")
        tag.attrs["src"] = uploaded[source]
        tag.attrs.pop("data-src", None)
    return str(soup), len(images)


async def test_connection(
    platform_code: str,
    base_url: str | None,
    credentials: dict[str, str],
) -> dict[str, Any]:
    definition = platform_definition(platform_code)
    if definition["mode"] == "assisted":
        return {"status": "ready", "message": "半自动发布无需保存平台账号密码"}
    if not definition.get("available"):
        raise SeoDistributionError("该平台尚未开放连接，请使用人工登记")
    timeout = httpx.Timeout(15.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            if platform_code == "wechat_official":
                await _wechat_access_token(client, credentials)
                return {"status": "connected", "message": "微信公众号授权验证通过"}
            endpoint = await ensure_public_endpoint(base_url or "")
            if platform_code == "wordpress":
                response = await client.get(
                    f"{endpoint}/wp-json/wp/v2/users/me",
                    params={"context": "edit"},
                    auth=(credentials["username"], credentials["application_password"]),
                )
            elif platform_code == "ghost":
                response = await client.get(
                    f"{endpoint}/ghost/api/admin/site/",
                    headers={"Authorization": f"Ghost {_ghost_token(credentials['admin_api_key'])}"},
                )
            else:
                raise SeoDistributionError("该平台连接器尚未实现")
        except httpx.HTTPError as exc:
            raise SeoDistributionError("连接平台失败，请检查地址、网络和授权信息") from exc
    if response.status_code >= 400:
        raise SeoDistributionError(f"平台拒绝连接（HTTP {response.status_code}）")
    return {"status": "connected", "message": "连接测试通过"}


async def publish_content(
    platform_code: str,
    base_url: str | None,
    credentials: dict[str, str],
    prepared: dict[str, str],
    action: str,
) -> RemotePublishResult:
    definition = platform_definition(platform_code)
    if definition["mode"] == "assisted":
        return RemotePublishResult(
            status="manual_required",
            page_url=None,
            response_summary={"handoff_url": definition.get("editor_url")},
        )
    if action not in {"draft", "publish"}:
        raise SeoDistributionError("不支持的发布方式")
    if not definition.get("available"):
        raise SeoDistributionError("该平台尚未开放 API 发布")
    target_status = "draft" if action == "draft" else "publish"
    timeout = httpx.Timeout(25.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            if platform_code == "wechat_official":
                token = await _wechat_access_token(client, credentials)
                wechat_content, image_count = await _rewrite_wechat_images(
                    client,
                    token,
                    prepared["content_html"],
                )
                response = await client.post(
                    "https://api.weixin.qq.com/cgi-bin/draft/add",
                    params={"access_token": token},
                    json={
                        "articles": [
                            {
                                "article_type": "news",
                                "title": prepared["title"],
                                "digest": prepared["excerpt"],
                                "content": wechat_content,
                                "thumb_media_id": credentials["thumb_media_id"],
                                "need_open_comment": 0,
                                "only_fans_can_comment": 0,
                            }
                        ]
                    },
                )
                draft = _response_json(response, "创建微信公众号草稿")
                media_id = str(draft.get("media_id") or "")
                if not media_id:
                    raise SeoDistributionError("微信公众号未返回草稿素材 ID")
                if action == "draft":
                    return RemotePublishResult(
                        status="draft_created",
                        external_id=media_id,
                        response_summary={"media_id": media_id, "image_count": image_count},
                    )
                response = await client.post(
                    "https://api.weixin.qq.com/cgi-bin/freepublish/submit",
                    params={"access_token": token},
                    json={"media_id": media_id},
                )
                submitted = _response_json(response, "提交微信公众号发布")
                publish_id = str(submitted.get("publish_id") or "")
                if not publish_id:
                    raise SeoDistributionError("微信公众号未返回发布任务 ID")
                return RemotePublishResult(
                    status="publishing",
                    external_id=publish_id,
                    response_summary={
                        "media_id": media_id,
                        "publish_id": publish_id,
                        "image_count": image_count,
                    },
                )
            endpoint = await ensure_public_endpoint(base_url or "")
            if platform_code == "wordpress":
                response = await client.post(
                    f"{endpoint}/wp-json/wp/v2/posts",
                    auth=(credentials["username"], credentials["application_password"]),
                    json={
                        "title": prepared["title"],
                        "content": prepared["content_html"],
                        "excerpt": prepared["excerpt"],
                        "status": target_status,
                    },
                )
                body = response.json() if response.content else {}
                external_id = str(body.get("id") or "") or None
                page_url = _safe_remote_page_url(body.get("link"))
            elif platform_code == "ghost":
                response = await client.post(
                    f"{endpoint}/ghost/api/admin/posts/",
                    params={"source": "html"},
                    headers={"Authorization": f"Ghost {_ghost_token(credentials['admin_api_key'])}"},
                    json={
                        "posts": [
                            {
                                "title": prepared["title"],
                                "html": prepared["content_html"],
                                "custom_excerpt": prepared["excerpt"],
                                "status": "draft" if action == "draft" else "published",
                            }
                        ]
                    },
                )
                body = response.json() if response.content else {}
                post = (body.get("posts") or [{}])[0]
                external_id = str(post.get("id") or "") or None
                page_url = _safe_remote_page_url(post.get("url"))
            else:
                raise SeoDistributionError("该平台连接器尚未实现")
        except (httpx.HTTPError, ValueError) as exc:
            raise SeoDistributionError("平台发布请求失败，请稍后重试并先检查平台后台") from exc
    if response.status_code >= 400:
        raise SeoDistributionError(f"平台发布失败（HTTP {response.status_code}）")
    if not external_id:
        raise SeoDistributionError("平台未返回文章 ID，已停止自动重试以避免重复发布")
    return RemotePublishResult(
        status="draft_created" if action == "draft" else "published",
        external_id=external_id,
        page_url=page_url,
        response_summary={"http_status": response.status_code, "external_id": external_id},
    )


async def sync_publish_status(
    platform_code: str,
    credentials: dict[str, str],
    external_id: str | None,
) -> RemotePublishResult:
    if platform_code != "wechat_official":
        raise SeoDistributionError("该平台没有需要手动同步的异步发布任务")
    if not external_id:
        raise SeoDistributionError("发布任务缺少平台任务 ID")
    timeout = httpx.Timeout(15.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            token = await _wechat_access_token(client, credentials)
            response = await client.post(
                "https://api.weixin.qq.com/cgi-bin/freepublish/get",
                params={"access_token": token},
                json={"publish_id": external_id},
            )
            body = _response_json(response, "同步微信公众号发布状态")
        except httpx.HTTPError as exc:
            raise SeoDistributionError("同步微信公众号发布状态失败，请稍后重试") from exc
    publish_status = int(body.get("publish_status", 1))
    summary = {
        "publish_id": external_id,
        "publish_status": publish_status,
        "article_id": str(body.get("article_id") or "") or None,
        "fail_idx": body.get("fail_idx") or [],
    }
    if publish_status == 1:
        return RemotePublishResult(status="publishing", external_id=external_id, response_summary=summary)
    if publish_status == 0:
        articles = ((body.get("article_detail") or {}).get("item") or [])
        page_url = _safe_remote_page_url(articles[0].get("article_url")) if articles else None
        return RemotePublishResult(
            status="published",
            external_id=summary["article_id"] or external_id,
            page_url=page_url,
            response_summary=summary,
        )
    messages = {
        2: "微信公众号原创校验失败",
        3: "微信公众号发布失败",
        4: "微信公众号平台审核未通过",
        5: "微信公众号文章发布后被用户删除",
        6: "微信公众号文章发布后被系统封禁",
    }
    return RemotePublishResult(
        status="failed",
        external_id=external_id,
        response_summary=summary,
        error=messages.get(publish_status, f"微信公众号返回未知发布状态 {publish_status}"),
    )
