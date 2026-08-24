"""百度自然搜索前 50 结果采集与确定性品牌归属匹配。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from app.config import get_settings


CHINAZ_MAX_CONCURRENCY = 2
CHINAZ_MAX_CONNECTIONS = 2


class SerpProviderError(RuntimeError):
    """Safe provider failure that never embeds request parameters or secrets."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        timeout_phase: str | None = None,
        elapsed_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.retryable = retryable
        self.status_code = status_code
        self.timeout_phase = timeout_phase
        self.elapsed_ms = elapsed_ms


def create_chinaz_client() -> httpx.AsyncClient:
    """Create one bounded client for a complete SERP collection batch."""
    timeout_seconds = max(1.0, float(get_settings().chinaz_api_timeout_seconds))
    timeout = httpx.Timeout(
        timeout_seconds,
        connect=timeout_seconds,
        pool=min(2.0, timeout_seconds),
        write=timeout_seconds,
    )
    limits = httpx.Limits(
        max_connections=CHINAZ_MAX_CONNECTIONS,
        max_keepalive_connections=CHINAZ_MAX_CONNECTIONS,
    )
    return httpx.AsyncClient(timeout=timeout, limits=limits)


def _timeout_phase(exc: httpx.TimeoutException) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect"
    if isinstance(exc, httpx.ReadTimeout):
        return "read"
    if isinstance(exc, httpx.WriteTimeout):
        return "write"
    if isinstance(exc, httpx.PoolTimeout):
        return "pool"
    return "unknown"


def canonical_url(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return raw.rstrip("/")
    port = f":{parsed.port}" if parsed.port and parsed.port not in {80, 443} else ""
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    ignored = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "spm", "from"}
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in ignored])
    return urlunparse(("https", host + port, path, "", query, ""))


def url_domain(value: str | None) -> str:
    normalized = canonical_url(value)
    return (urlparse(normalized).hostname or "").lower().rstrip(".")


def rank_number(rank_label: Any, fallback: int) -> int:
    raw = str(rank_label or "").strip()
    if "-" in raw:
        page_raw, position_raw = raw.split("-", 1)
        try:
            page, position = int(page_raw), int(position_raw)
            if page >= 1 and position >= 1:
                return min(50, (page - 1) * 10 + position)
        except ValueError:
            pass
    try:
        value = int(raw)
        if 1 <= value <= 50:
            return value
    except ValueError:
        pass
    return fallback


def parse_top50_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SerpProviderError(
            "invalid_response",
            "站长之家接口返回格式异常",
        )
    try:
        state_code = int(payload.get("StateCode", -1))
    except (TypeError, ValueError) as exc:
        raise SerpProviderError(
            "invalid_response",
            "站长之家接口返回格式异常",
        ) from exc
    if state_code != 1:
        raise SerpProviderError(
            "provider_rejected",
            "站长之家未返回有效搜索结果",
        )
    result = payload.get("Result")
    if not isinstance(result, dict):
        raise SerpProviderError(
            "invalid_response",
            "站长之家接口返回格式异常",
        )
    ranks = result.get("Ranks") if isinstance(result.get("Ranks"), list) else []
    items: list[dict[str, Any]] = []
    for index, row in enumerate(ranks[:50], start=1):
        if not isinstance(row, dict):
            continue
        result_url = str(row.get("Url") or "").strip()
        if not result_url:
            continue
        rank_label = str(row.get("RankStr") or "").strip()
        items.append(
            {
                "rank": rank_number(rank_label, index),
                "rank_label": rank_label or str(index),
                "title": str(row.get("Title") or "").strip(),
                "description": str(row.get("Description") or "").strip(),
                "result_url": result_url,
                "domain": url_domain(result_url),
            }
        )
    items.sort(key=lambda item: item["rank"])
    return {
        "site_count": result.get("SiteCount"),
        "captured_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "items": items,
    }


async def fetch_baidu_top50(
    keyword: str,
    device: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    if device not in {"desktop", "mobile"}:
        raise SerpProviderError(
            "invalid_device",
            "设备只支持 desktop 或 mobile",
        )
    settings = get_settings()
    key = (
        settings.chinaz_baidu_pc_top50_api_key
        if device == "desktop"
        else settings.chinaz_baidu_mobile_top50_api_key
    ) or settings.chinaz_api_key
    if not settings.chinaz_api_enabled or not key:
        raise SerpProviderError(
            "provider_not_configured",
            "未配置站长之家百度%s前50接口 Key" % ("PC" if device == "desktop" else "移动"),
        )
    path = "baidupc_keywordtop50" if device == "desktop" else "baidumobile_keywordtop50"
    endpoint = f"{settings.chinaz_api_base_url.rstrip('/')}/{path}"
    started_at = perf_counter()

    async def request(provider_client: httpx.AsyncClient) -> dict[str, Any]:
        response = await provider_client.get(
            endpoint,
            params={"keyword": keyword, "APIKey": key, "ChinazVer": "1.0"},
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise SerpProviderError(
                "invalid_response",
                "站长之家接口返回格式异常",
            ) from exc
        return parse_top50_response(payload)

    try:
        if client is not None:
            return await request(client)
        async with create_chinaz_client() as owned_client:
            return await request(owned_client)
    except SerpProviderError as exc:
        if exc.elapsed_ms is None:
            exc.elapsed_ms = max(0, round((perf_counter() - started_at) * 1000))
        raise
    except httpx.TimeoutException as exc:
        raise SerpProviderError(
            "provider_timeout",
            "站长之家前50接口请求超时",
            retryable=True,
            timeout_phase=_timeout_phase(exc),
            elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
        ) from exc
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 429:
            code, message, retryable = (
                "provider_rate_limited",
                "站长之家接口请求受限",
                False,
            )
        elif status_code in {401, 403}:
            code, message, retryable = (
                "provider_auth_failed",
                "站长之家接口认证失败",
                False,
            )
        elif 500 <= status_code < 600:
            code, message, retryable = (
                "provider_unavailable",
                "站长之家接口暂时不可用",
                True,
            )
        elif 400 <= status_code < 500:
            code, message, retryable = (
                "provider_request_rejected",
                "站长之家接口拒绝请求",
                False,
            )
        else:
            code, message, retryable = (
                "provider_http_error",
                "站长之家接口返回 HTTP 错误",
                False,
            )
        raise SerpProviderError(
            code,
            message,
            retryable=retryable,
            status_code=status_code,
            elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
        ) from exc
    except httpx.RequestError as exc:
        raise SerpProviderError(
            "provider_network_error",
            "站长之家接口网络连接失败",
            elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
        ) from exc
    except Exception as exc:
        raise SerpProviderError(
            "provider_error",
            "站长之家前50接口调用失败",
            elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
        ) from exc


async def fetch_baidu_top50_batch(
    requests: list[tuple[str, str]],
) -> list[tuple[dict[str, Any] | None, SerpProviderError | None]]:
    """Fetch a bounded batch with one shared connection pool and no retries."""
    semaphore = asyncio.Semaphore(CHINAZ_MAX_CONCURRENCY)

    async with create_chinaz_client() as provider_client:
        async def fetch_one(
            keyword: str,
            device: str,
        ) -> tuple[dict[str, Any] | None, SerpProviderError | None]:
            try:
                async with semaphore:
                    result = await fetch_baidu_top50(
                        keyword,
                        device,
                        client=provider_client,
                    )
                return result, None
            except SerpProviderError as exc:
                return None, exc

        return await asyncio.gather(
            *(fetch_one(keyword, device) for keyword, device in requests)
        )


def deterministic_match(
    item: dict[str, Any],
    *,
    official_domains: set[str],
    content_urls: set[str],
    account_patterns: list[tuple[int, str]],
    explicit_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    """先做可解释规则匹配；AI 只处理返回 unresolved 的结果。"""
    target_url = canonical_url(item.get("result_url"))
    target_domain = url_domain(target_url)
    for asset in explicit_assets:
        kind = asset["asset_type"]
        value = str(asset["match_value"] or "").strip()
        if kind == "content_url" and canonical_url(value) == target_url:
            return {"ownership_type": "brand_content", "match_method": "exact_url", "confidence": 100, "matched_asset_id": asset["id"], "is_confirmed": True}
        if kind == "official_domain" and url_domain(value) == target_domain:
            return {"ownership_type": "official_site", "match_method": "official_domain", "confidence": 100, "matched_asset_id": asset["id"], "is_confirmed": True}
    if target_url in content_urls:
        return {"ownership_type": "brand_content", "match_method": "published_url", "confidence": 100, "matched_asset_id": None, "is_confirmed": True}
    if target_domain and target_domain in official_domains:
        return {"ownership_type": "official_site", "match_method": "site_domain", "confidence": 100, "matched_asset_id": None, "is_confirmed": True}
    haystack = " ".join((target_url, str(item.get("title") or ""), str(item.get("description") or ""))).lower()
    for asset_id, pattern in account_patterns:
        if pattern and pattern.lower() in haystack:
            return {"ownership_type": "brand_content", "match_method": "platform_account", "confidence": 95, "matched_asset_id": asset_id, "is_confirmed": True}
    return {"ownership_type": "unresolved", "match_method": "none", "confidence": None, "matched_asset_id": None, "is_confirmed": False}
