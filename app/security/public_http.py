"""Bounded HTTP fetching with DNS pinning and per-hop SSRF validation."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpcore
import httpx


MAX_REDIRECTS = 5


class PublicHttpError(Exception):
    """Raised when an outbound URL is unsafe or cannot be fetched safely."""


@dataclass(frozen=True)
class PublicHttpResponse:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    redirect_chain: tuple[str, ...]


_PINNED_TARGETS: ContextVar[dict[tuple[str, int], str]] = ContextVar(
    "public_http_pinned_targets",
    default={},
)


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, backend: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        approved_ip = _PINNED_TARGETS.get().get((host.lower().rstrip("."), port))
        if approved_ip is None:
            raise httpcore.ConnectError("Outbound host was not approved by the SSRF validator")
        return await self._backend.connect_tcp(
            host=approved_ip,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix sockets are not allowed for public HTTP fetching")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self) -> None:
        super().__init__(trust_env=False)
        self._pool._network_backend = _PinnedNetworkBackend()


def normalize_public_url(value: str) -> str:
    raw = value.strip()
    try:
        parsed = urlparse(raw)
        port = parsed.port
    except ValueError as exc:
        raise PublicHttpError("URL 端口无效") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise PublicHttpError("只允许 http/https 公网地址")
    if parsed.username or parsed.password:
        raise PublicHttpError("URL 不允许包含用户名或密码")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".internal")):
        raise PublicHttpError("禁止访问本地或内网地址")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise PublicHttpError("禁止访问本地、内网或保留地址")
    rendered_host = f"[{host}]" if ":" in host else host
    netloc = rendered_host if port is None else f"{rendered_host}:{port}"
    return urlunparse((parsed.scheme.lower(), netloc, parsed.path or "/", "", parsed.query, ""))


def _ascii_host(url: str) -> str:
    """Return the exact ASCII host representation used by HTTPX/httpcore."""
    try:
        return httpx.URL(url).raw_host.decode("ascii").lower().rstrip(".")
    except (UnicodeError, httpx.InvalidURL) as exc:
        raise PublicHttpError("URL 主机名无效") from exc


async def _resolve_public_ip(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise PublicHttpError("URL 缺少主机名")
    host = _ascii_host(url)
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except (OSError, UnicodeError) as exc:
            raise PublicHttpError(f"域名解析失败: {host}") from exc
        addresses = list(dict.fromkeys(ipaddress.ip_address(info[4][0]) for info in infos))
    if not addresses or any(not address.is_global for address in addresses):
        raise PublicHttpError("禁止访问本地、内网或保留地址")
    return str(addresses[0])


async def fetch_public_url(
    url: str,
    *,
    timeout: float,
    max_response_bytes: int,
    headers: dict[str, str] | None = None,
    read_body: bool = True,
    _transport: httpx.AsyncBaseTransport | None = None,
) -> PublicHttpResponse:
    """Fetch a public URL while pinning DNS and validating every redirect hop."""
    requested = normalize_public_url(url)
    current = requested
    redirects: list[str] = []
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
        trust_env=False,
        transport=_transport or _PinnedAsyncHTTPTransport(),
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            hostname = _ascii_host(current)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            approved_ip = await _resolve_public_ip(current)
            token = _PINNED_TARGETS.set({(hostname, port): approved_ip})
            try:
                async with client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise PublicHttpError("重定向响应缺少目标地址")
                        current = normalize_public_url(urljoin(current, location))
                        redirects.append(current)
                        continue
                    body = b""
                    if read_body:
                        declared_size = response.headers.get("content-length")
                        if declared_size and declared_size.isdigit() and int(declared_size) > max_response_bytes:
                            raise PublicHttpError("响应内容超过允许大小")
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > max_response_bytes:
                                raise PublicHttpError("响应内容超过允许大小")
                            chunks.append(chunk)
                        body = b"".join(chunks)
                    return PublicHttpResponse(
                        requested_url=requested,
                        final_url=str(response.url),
                        status_code=response.status_code,
                        headers={key.lower(): value for key, value in response.headers.items()},
                        body=body,
                        redirect_chain=tuple(redirects),
                    )
            finally:
                _PINNED_TARGETS.reset(token)
    raise PublicHttpError("重定向次数过多")
