"""SEO-only content distribution catalog and bounded publishing adapters."""

from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import json
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt
from bs4 import BeautifulSoup

from app.security.crypto import decrypt, encrypt


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
        "available": False,
        "capabilities": ["draft", "publish", "async_status", "media_upload"],
        "credential_fields": [],
        "help": "需要公众号发布接口权限、封面素材和正文图片转存，安排在下一接入阶段。",
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


def _sanitize_article_html(value: str) -> str:
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
    allowed_attributes = {"href", "src", "alt", "title"}
    for tag in soup.find_all(True):
        for attribute in list(tag.attrs):
            if attribute.lower() not in allowed_attributes:
                del tag.attrs[attribute]
        for attribute in ("href", "src"):
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
    max_title = 80 if platform_code in {"wordpress", "ghost"} else 60
    adapted_title = clean_title[:max_title]
    if "<p" in clean_content.lower() or "<h" in clean_content.lower():
        content_html = _sanitize_article_html(clean_content)
        adapted_content = content_html
        plain = BeautifulSoup(content_html, "html.parser").get_text(" ", strip=True)
    else:
        paragraphs = [part.strip() for part in clean_content.splitlines() if part.strip()]
        content_html = "\n".join(f"<p>{html.escape(part)}</p>" for part in paragraphs)
        adapted_content = clean_content
        plain = clean_content
    excerpt = " ".join(plain.split())[:160]
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
    endpoint = await ensure_public_endpoint(base_url or "")
    timeout = httpx.Timeout(15.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
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
    endpoint = await ensure_public_endpoint(base_url or "")
    target_status = "draft" if action == "draft" else "publish"
    timeout = httpx.Timeout(25.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
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
