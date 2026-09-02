"""多搜索引擎自然排名采集与确定性品牌归属匹配。"""

from __future__ import annotations

import asyncio
import random
import re
import unicodedata
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from app.config import get_settings


CHINAZ_MAX_CONCURRENCY = 1
CHINAZ_MAX_CONNECTIONS = 1
CHINAZ_MAX_ATTEMPTS = 3
CHINAZ_RETRY_BASE_SECONDS = 0.25
CHINAZ_BATCH_REQUEST_INTERVAL_SECONDS = 1.0
CHINAZ_RATE_LIMIT_RETRY_SECONDS = 5.0
DATAFORSEO_ENGINES = {"google", "bing"}
DATAFORSEO_MAX_CONCURRENCY = 2
DATAFORSEO_MAX_ATTEMPTS = 3
DATAFORSEO_RETRY_BASE_SECONDS = 0.5
CHINAZ_DOMESTIC_ENGINES = {"baidu", "360", "sogou"}

_CHINAZ_PROVIDER_HEALTH: dict[tuple[str, str], dict[str, Any]] = {}


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
        attempts: int = 1,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.retryable = retryable
        self.status_code = status_code
        self.timeout_phase = timeout_phase
        self.elapsed_ms = elapsed_ms
        self.attempts = attempts
        self.retry_after_seconds = retry_after_seconds


def _remember_chinaz_health(
    engine: str,
    device: str,
    error: SerpProviderError | None = None,
) -> None:
    _CHINAZ_PROVIDER_HEALTH[(engine, device)] = {
        "status": "ready" if error is None else (
            "supplier_error"
            if error.code in {"provider_quota_exceeded", "provider_ip_rejected", "provider_auth_failed"}
            else "temporarily_unavailable"
        ),
        "reason": None if error is None else error.public_message,
        "code": None if error is None else error.code,
        "status_code": None if error is None else error.status_code,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _chinaz_http_error(
    status_code: int,
    *,
    elapsed_ms: int,
    retry_after_raw: str = "",
) -> SerpProviderError:
    retry_after_seconds: float | None = None
    if status_code in {429, 531}:
        try:
            retry_after_seconds = min(60.0, max(0.0, float(retry_after_raw)))
        except ValueError:
            retry_after_seconds = CHINAZ_RATE_LIMIT_RETRY_SECONDS
        return SerpProviderError(
            "provider_rate_limited",
            "站长之家接口请求受限",
            retryable=True,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            retry_after_seconds=retry_after_seconds,
        )
    if status_code == 436:
        return SerpProviderError(
            "provider_quota_exceeded",
            "站长之家供应商额度或 APIKey 异常",
            status_code=status_code,
            elapsed_ms=elapsed_ms,
        )
    if status_code == 437:
        return SerpProviderError(
            "provider_ip_rejected",
            "站长之家供应商 IP 白名单异常",
            status_code=status_code,
            elapsed_ms=elapsed_ms,
        )
    if status_code in {401, 403, 431, 432, 433, 434}:
        return SerpProviderError(
            "provider_auth_failed",
            "站长之家接口认证失败",
            status_code=status_code,
            elapsed_ms=elapsed_ms,
        )
    if 500 <= status_code < 600:
        return SerpProviderError(
            "provider_unavailable",
            "站长之家接口暂时不可用",
            retryable=True,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
        )
    return SerpProviderError(
        "provider_request_rejected" if 400 <= status_code < 500 else "provider_http_error",
        "站长之家接口拒绝请求" if 400 <= status_code < 500 else "站长之家接口返回 HTTP 错误",
        status_code=status_code,
        elapsed_ms=elapsed_ms,
    )


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


def create_dataforseo_client() -> httpx.AsyncClient:
    """Create one bounded client for a complete paid DataForSEO batch."""
    timeout_seconds = max(
        1.0, float(get_settings().seo_dataforseo_timeout_seconds)
    )
    timeout = httpx.Timeout(
        timeout_seconds,
        connect=timeout_seconds,
        pool=min(2.0, timeout_seconds),
        write=timeout_seconds,
    )
    limits = httpx.Limits(
        max_connections=DATAFORSEO_MAX_CONCURRENCY,
        max_keepalive_connections=DATAFORSEO_MAX_CONCURRENCY,
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


def _normalized_match_domain(value: str | None) -> str:
    host = url_domain(value)
    return host[4:] if host.startswith("www.") else host


def domain_matches(candidate: str, official: str) -> bool:
    """Match an official host and its real subdomains, never suffix lookalikes."""
    candidate_host = _normalized_match_domain(candidate)
    official_host = _normalized_match_domain(official)
    return bool(
        candidate_host
        and official_host
        and (
            candidate_host == official_host
            or candidate_host.endswith(f".{official_host}")
        )
    )


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
    operation_started_at = perf_counter()

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

    async def request_once(provider_client: httpx.AsyncClient) -> dict[str, Any]:
        started_at = perf_counter()
        try:
            return await request(provider_client)
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
            raise _chinaz_http_error(
                status_code,
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
                retry_after_raw=exc.response.headers.get("retry-after", ""),
            ) from exc
        except httpx.RequestError as exc:
            raise SerpProviderError(
                "provider_network_error",
                "站长之家接口网络连接失败",
                retryable=True,
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
            ) from exc
        except Exception as exc:
            raise SerpProviderError(
                "provider_error",
                "站长之家前50接口调用失败",
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
            ) from exc

    async def request_with_retry(provider_client: httpx.AsyncClient) -> dict[str, Any]:
        for attempt in range(1, CHINAZ_MAX_ATTEMPTS + 1):
            try:
                return await request_once(provider_client)
            except SerpProviderError as exc:
                if not exc.retryable or attempt >= CHINAZ_MAX_ATTEMPTS:
                    exc.attempts = attempt
                    exc.elapsed_ms = max(
                        0, round((perf_counter() - operation_started_at) * 1000)
                    )
                    raise
                backoff = CHINAZ_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                jitter = random.uniform(0, CHINAZ_RETRY_BASE_SECONDS)
                await asyncio.sleep(max(backoff + jitter, exc.retry_after_seconds or 0))
        raise AssertionError("unreachable")

    if client is not None:
        try:
            result = await request_with_retry(client)
        except SerpProviderError as exc:
            _remember_chinaz_health("baidu", device, exc)
            raise
        _remember_chinaz_health("baidu", device)
        return result
    async with create_chinaz_client() as owned_client:
        try:
            result = await request_with_retry(owned_client)
        except SerpProviderError as exc:
            _remember_chinaz_health("baidu", device, exc)
            raise
        _remember_chinaz_health("baidu", device)
        return result


async def fetch_baidu_top50_batch(
    requests: list[tuple[str, str]],
) -> list[tuple[dict[str, Any] | None, SerpProviderError | None]]:
    """Fetch a provider-safe serial batch with pacing and bounded retries."""
    results: list[tuple[dict[str, Any] | None, SerpProviderError | None]] = []

    async with create_chinaz_client() as provider_client:
        for index, (keyword, device) in enumerate(requests):
            if index:
                await asyncio.sleep(CHINAZ_BATCH_REQUEST_INTERVAL_SECONDS)
            try:
                result = await fetch_baidu_top50(
                    keyword,
                    device,
                    client=provider_client,
                )
                results.append((result, None))
            except SerpProviderError as exc:
                results.append((None, exc))
    return results


def _normalized_keyword(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def parse_domain_ranking_response(payload: Any) -> dict[str, Any]:
    """Normalize Chinaz domain+keyword ranking products into SERP-shaped data."""
    if not isinstance(payload, dict):
        raise SerpProviderError("invalid_response", "站长之家接口返回格式异常")
    try:
        state_code = int(payload.get("StateCode", -1))
    except (TypeError, ValueError) as exc:
        raise SerpProviderError("invalid_response", "站长之家接口返回格式异常") from exc
    if state_code != 1:
        raise SerpProviderError("provider_rejected", "站长之家未返回有效排名结果")
    result = payload.get("Result")
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise SerpProviderError("invalid_response", "站长之家接口返回格式异常")
    ranks = result.get("Ranks") if isinstance(result.get("Ranks"), list) else []
    if not ranks and any(result.get(key) for key in ("RankStr", "Url", "Title")):
        ranks = [result]
    if not ranks and any(payload.get(key) for key in ("RankStr", "Url", "Title")):
        ranks = [payload]
    items: list[dict[str, Any]] = []
    for index, row in enumerate(ranks[:1], start=1):
        if not isinstance(row, dict):
            continue
        result_url = str(row.get("Url") or "").strip()
        rank_label = str(row.get("RankStr") or "").strip()
        if not result_url or not rank_label:
            continue
        items.append({
            "rank": rank_number(rank_label, index),
            "rank_label": rank_label,
            "title": str(row.get("Title") or "").strip(),
            "description": str(row.get("Description") or "").strip(),
            "result_url": result_url,
            "domain": url_domain(result_url),
        })
    return {
        "site_count": result.get("SiteCount", payload.get("SiteCount")),
        "captured_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "items": items,
    }


def parse_domain_keyword_response(payload: Any) -> dict[str, Any]:
    """Normalize one page of a Chinaz website-keyword product."""
    if not isinstance(payload, dict):
        raise SerpProviderError("invalid_response", "站长之家接口返回格式异常")
    try:
        state_code = int(payload.get("StateCode", -1))
    except (TypeError, ValueError) as exc:
        raise SerpProviderError("invalid_response", "站长之家接口返回格式异常") from exc
    if state_code == 10006:
        return {"items": [], "page": 1, "pages": 1}
    if state_code != 1:
        raise SerpProviderError("provider_rejected", "站长之家未返回有效网站关键词")
    result = payload.get("Result")
    if not isinstance(result, dict):
        raise SerpProviderError("invalid_response", "站长之家接口返回格式异常")
    rows = result.get("List") if isinstance(result.get("List"), list) else []
    items: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        keyword = str(row.get("Keyword") or "").strip()
        result_url = str(row.get("Url") or "").strip()
        rank_label = str(row.get("RankStr") or "").strip()
        if not keyword or not result_url or not rank_label:
            continue
        items.append({
            "keyword": keyword,
            "rank": rank_number(rank_label, index),
            "rank_label": rank_label,
            "title": str(row.get("Title") or "").strip(),
            "description": str(row.get("Description") or "").strip(),
            "result_url": result_url,
            "domain": url_domain(result_url),
        })
    try:
        page = max(1, int(result.get("Current") or 1))
        pages = max(page, int(result.get("Pages") or page))
    except (TypeError, ValueError):
        page = pages = 1
    return {"items": items, "page": page, "pages": pages}


async def _chinaz_get_json(
    *,
    endpoint: str,
    params: dict[str, Any],
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    operation_started_at = perf_counter()
    for attempt in range(1, CHINAZ_MAX_ATTEMPTS + 1):
        started_at = perf_counter()
        try:
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("not an object")
            return payload
        except httpx.TimeoutException as exc:
            error = SerpProviderError(
                "provider_timeout",
                "站长之家接口请求超时",
                retryable=True,
                timeout_phase=_timeout_phase(exc),
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
            )
        except httpx.HTTPStatusError as exc:
            error = _chinaz_http_error(
                exc.response.status_code,
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
                retry_after_raw=exc.response.headers.get("retry-after", ""),
            )
        except httpx.RequestError as exc:
            error = SerpProviderError(
                "provider_network_error",
                "站长之家接口网络连接失败",
                retryable=True,
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
            )
        except (ValueError, TypeError) as exc:
            error = SerpProviderError(
                "invalid_response",
                "站长之家接口返回格式异常",
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
            )
        if not error.retryable or attempt >= CHINAZ_MAX_ATTEMPTS:
            error.attempts = attempt
            error.elapsed_ms = max(0, round((perf_counter() - operation_started_at) * 1000))
            raise error
        backoff = CHINAZ_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
        jitter = random.uniform(0, CHINAZ_RETRY_BASE_SECONDS)
        await asyncio.sleep(max(backoff + jitter, error.retry_after_seconds or 0))
    raise AssertionError("unreachable")


def _chinaz_direct_rank_config(settings: Any, engine: str, device: str) -> tuple[str, str]:
    mapping = {
        ("baidu", "desktop"): ("baidupc_keywordranking", "chinaz_baidu_pc_ranking_api_key"),
        ("baidu", "mobile"): ("baidumobile_keywordranking", "chinaz_baidu_mobile_ranking_api_key"),
        ("360", "desktop"): ("sopc_keywordranking", "chinaz_360_pc_ranking_api_key"),
    }
    path, setting_name = mapping.get((engine, device), ("", ""))
    return path, str(getattr(settings, setting_name, "") or "")


def _chinaz_domain_list_config(settings: Any, engine: str, device: str) -> tuple[str, str]:
    mapping = {
        ("sogou", "desktop"): ("keyword_sogoupc", "chinaz_sogou_pc_keywords_api_key"),
        ("sogou", "mobile"): ("keyword_sogoumobile", "chinaz_sogou_mobile_keywords_api_key"),
        ("360", "mobile"): ("keyword_360mobile", "chinaz_360_mobile_keywords_api_key"),
    }
    path, setting_name = mapping.get((engine, device), ("", ""))
    return path, str(getattr(settings, setting_name, "") or "")


def chinaz_rank_status() -> dict[str, dict[str, Any]]:
    settings = get_settings()
    result: dict[str, dict[str, Any]] = {}
    for engine in sorted(CHINAZ_DOMESTIC_ENGINES):
        devices: dict[str, dict[str, Any]] = {}
        for device in ("desktop", "mobile"):
            direct_path, direct_key = _chinaz_direct_rank_config(settings, engine, device)
            list_path, list_key = _chinaz_domain_list_config(settings, engine, device)
            configured = bool(settings.chinaz_api_enabled and (direct_key or list_key))
            health = _CHINAZ_PROVIDER_HEALTH.get((engine, device), {})
            devices[device] = {
                "configured": configured,
                "provider": "chinaz" if configured else None,
                "mode": "keyword_ranking" if direct_path else "domain_keyword_list" if list_path else None,
                "status": health.get("status") if configured else "not_configured",
                "reason": health.get("reason") if configured else "未配置站长之家接口 Key",
                "code": health.get("code") if configured else "provider_not_configured",
                "status_code": health.get("status_code") if configured else None,
                "checked_at": health.get("checked_at") if configured else None,
            }
            if configured and not devices[device]["status"]:
                devices[device]["status"] = "ready"
        result[engine] = {
            "configured": any(item["configured"] for item in devices.values()),
            "provider": "chinaz",
            "devices": devices,
        }
    return result


async def fetch_chinaz_domestic_rank_batch(
    engine: str,
    domain: str,
    requests: list[tuple[str, str]],
) -> list[tuple[dict[str, Any] | None, SerpProviderError | None]]:
    """Collect Baidu/360 direct rankings or match Sogou/360 domain keyword lists."""
    settings = get_settings()
    if engine not in CHINAZ_DOMESTIC_ENGINES:
        error = SerpProviderError("unsupported_engine", "该搜索引擎暂不支持站长之家自动采集")
        return [(None, error) for _ in requests]
    async with create_chinaz_client() as client:
        direct_requests: list[tuple[int, str, str, str, str]] = []
        grouped_lists: dict[str, list[tuple[int, str]]] = {}
        aligned: list[
            tuple[dict[str, Any] | None, SerpProviderError | None] | None
        ] = [None] * len(requests)
        for index, (keyword, device) in enumerate(requests):
            path, key = _chinaz_direct_rank_config(settings, engine, device)
            if path and key and settings.chinaz_api_enabled:
                direct_requests.append((index, keyword, device, path, key))
                continue
            list_path, list_key = _chinaz_domain_list_config(settings, engine, device)
            if list_path and list_key and settings.chinaz_api_enabled:
                grouped_lists.setdefault(device, []).append((index, keyword))
                continue
            error = SerpProviderError("provider_not_configured", "未配置站长之家排名接口 Key")
            _remember_chinaz_health(engine, device, error)
            aligned[index] = (None, error)

        for sequence, (index, keyword, device, path, key) in enumerate(direct_requests):
            if sequence:
                await asyncio.sleep(CHINAZ_BATCH_REQUEST_INTERVAL_SECONDS)
            endpoint = f"{settings.chinaz_api_base_url.rstrip('/')}/{path}"
            try:
                payload = await _chinaz_get_json(
                    endpoint=endpoint,
                    params={"domain": domain, "keyword": keyword, "APIKey": key, "ChinazVer": "1.0"},
                    client=client,
                )
                parsed = parse_domain_ranking_response(payload)
                _remember_chinaz_health(engine, device)
                aligned[index] = (parsed, None)
            except SerpProviderError as exc:
                _remember_chinaz_health(engine, device, exc)
                aligned[index] = (None, exc)

        for device, indexed_keywords in grouped_lists.items():
            path, key = _chinaz_domain_list_config(settings, engine, device)
            endpoint = f"{settings.chinaz_api_base_url.rstrip('/')}/{path}"
            wanted = {_normalized_keyword(keyword): (index, keyword) for index, keyword in indexed_keywords}
            matched: dict[str, dict[str, Any]] = {}
            max_pages = max(1, min(100, int(getattr(settings, "chinaz_domain_keyword_max_pages", 10))))
            page = 1
            try:
                while page <= max_pages and len(matched) < len(wanted):
                    payload = await _chinaz_get_json(
                        endpoint=endpoint,
                        params={"domain": domain, "page": page, "APIKey": key, "ChinazVer": "1.0"},
                        client=client,
                    )
                    parsed_page = parse_domain_keyword_response(payload)
                    for item in parsed_page["items"]:
                        normalized = _normalized_keyword(item.pop("keyword", ""))
                        if normalized in wanted and normalized not in matched:
                            matched[normalized] = item
                    if page >= min(max_pages, int(parsed_page["pages"])):
                        break
                    page += 1
                    await asyncio.sleep(CHINAZ_BATCH_REQUEST_INTERVAL_SECONDS)
                _remember_chinaz_health(engine, device)
                captured_at = datetime.now(timezone.utc).replace(tzinfo=None)
                for normalized, (index, _keyword) in wanted.items():
                    item = matched.get(normalized)
                    if item is None:
                        aligned[index] = (
                            None,
                            SerpProviderError(
                                "keyword_not_found",
                                "站长之家站点词表未包含该监控词，请使用人工导入",
                            ),
                        )
                    else:
                        aligned[index] = ({"site_count": None, "captured_at": captured_at, "items": [item]}, None)
            except SerpProviderError as exc:
                _remember_chinaz_health(engine, device, exc)
                for index, _keyword in indexed_keywords:
                    aligned[index] = (None, exc)
    fallback = SerpProviderError("provider_error", "站长之家排名采集未完成")
    return [item if item is not None else (None, fallback) for item in aligned]


def dataforseo_status() -> dict[str, Any]:
    settings = get_settings()
    configured = bool(
        settings.seo_dataforseo_login.strip()
        and settings.seo_dataforseo_password.strip()
    )
    return {
        "configured": configured,
        "engines": sorted(DATAFORSEO_ENGINES),
        "provider": "dataforseo_live",
    }


def _dataforseo_error(status_code: int) -> SerpProviderError:
    """Classify documented DataForSEO internal codes without leaking messages."""
    if status_code == 40100:
        return SerpProviderError(
            "provider_auth_failed", "多搜索引擎接口认证失败"
        )
    if status_code in {40202, 40209}:
        return SerpProviderError(
            "provider_rate_limited",
            "多搜索引擎接口请求受限",
            retryable=True,
        )
    if status_code in {40200, 40203, 40210}:
        return SerpProviderError(
            "provider_quota_exceeded", "多搜索引擎接口额度不可用"
        )
    retryable = status_code in {40101, 40103, 40601, 40602} or (
        50000 <= status_code < 50500 and status_code != 50100
    )
    return SerpProviderError(
        "provider_unavailable" if retryable else "provider_rejected",
        "多搜索引擎接口暂时不可用"
        if retryable
        else "多搜索引擎接口未返回有效搜索结果",
        retryable=retryable,
    )


def parse_dataforseo_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        raise SerpProviderError("invalid_response", "多搜索引擎接口返回格式异常")
    try:
        response_status = int(payload.get("status_code", 20000))
    except (TypeError, ValueError) as exc:
        raise SerpProviderError("invalid_response", "多搜索引擎接口返回格式异常") from exc
    if response_status != 20000:
        raise _dataforseo_error(response_status)
    task = payload["tasks"][0] if payload["tasks"] else None
    if not isinstance(task, dict):
        raise SerpProviderError("invalid_response", "多搜索引擎接口未返回采集任务")
    try:
        status_code = int(task.get("status_code", 0))
    except (TypeError, ValueError) as exc:
        raise SerpProviderError("invalid_response", "多搜索引擎接口返回格式异常") from exc
    if status_code == 40102:
        return {
            "site_count": 0,
            "captured_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "items": [],
        }
    if status_code != 20000:
        raise _dataforseo_error(status_code)
    results = task.get("result") if isinstance(task.get("result"), list) else []
    result = results[0] if results and isinstance(results[0], dict) else {}
    rows = result.get("items") if isinstance(result.get("items"), list) else []
    items: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or row.get("type") != "organic":
            continue
        result_url = str(row.get("url") or "").strip()
        if not result_url:
            continue
        try:
            rank = int(row.get("rank_group") or row.get("rank_absolute") or index)
        except (TypeError, ValueError):
            rank = index
        items.append({
            "rank": rank,
            "rank_label": str(rank),
            "title": str(row.get("title") or "").strip(),
            "description": str(row.get("description") or "").strip(),
            "result_url": result_url,
            "domain": str(row.get("domain") or url_domain(result_url)).lower().rstrip("."),
        })
    items.sort(key=lambda item: item["rank"])
    return {
        "site_count": result.get("se_results_count"),
        "captured_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "items": items[:100],
    }


async def fetch_dataforseo_serp(
    engine: str,
    keyword: str,
    device: str,
    *,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    if engine not in DATAFORSEO_ENGINES:
        raise SerpProviderError("unsupported_engine", "该搜索引擎暂不支持自动采集")
    if device not in {"desktop", "mobile"}:
        raise SerpProviderError("invalid_device", "设备只支持 desktop 或 mobile")
    settings = get_settings()
    if not dataforseo_status()["configured"]:
        raise SerpProviderError("provider_not_configured", "未配置 Google/Bing 实时排名服务")
    endpoint = (
        f"{settings.seo_dataforseo_base_url.rstrip('/')}/serp/{engine}/organic/live/regular"
    )
    operation_started_at = perf_counter()

    async def request_once() -> dict[str, Any]:
        started_at = perf_counter()
        try:
            response = await client.post(
                endpoint,
                auth=(settings.seo_dataforseo_login, settings.seo_dataforseo_password),
                json=[{
                    "keyword": keyword,
                    "location_code": settings.seo_dataforseo_location_code,
                    "language_code": settings.seo_dataforseo_language_code,
                    "device": device,
                    "depth": 100,
                }],
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise SerpProviderError(
                    "invalid_response", "多搜索引擎接口返回格式异常"
                ) from exc
            return parse_dataforseo_response(payload)
        except SerpProviderError as exc:
            if exc.elapsed_ms is None:
                exc.elapsed_ms = max(0, round((perf_counter() - started_at) * 1000))
            raise
        except httpx.TimeoutException as exc:
            raise SerpProviderError(
                "provider_timeout",
                "多搜索引擎接口请求超时",
                retryable=True,
                timeout_phase=_timeout_phase(exc),
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retry_after_seconds = None
            if status == 429:
                retry_after_raw = exc.response.headers.get("retry-after", "")
                try:
                    retry_after_seconds = min(60.0, max(0.0, float(retry_after_raw)))
                except ValueError:
                    retry_after_seconds = None
                code, message, retryable = (
                    "provider_rate_limited", "多搜索引擎接口请求受限", True
                )
            elif status in {401, 403}:
                code, message, retryable = (
                    "provider_auth_failed", "多搜索引擎接口认证失败", False
                )
            elif 500 <= status < 600:
                code, message, retryable = (
                    "provider_unavailable", "多搜索引擎接口暂时不可用", True
                )
            elif 400 <= status < 500:
                code, message, retryable = (
                    "provider_request_rejected", "多搜索引擎接口拒绝请求", False
                )
            else:
                code, message, retryable = (
                    "provider_http_error", "多搜索引擎接口返回 HTTP 错误", False
                )
            raise SerpProviderError(
                code,
                message,
                retryable=retryable,
                status_code=status,
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
                retry_after_seconds=retry_after_seconds,
            ) from exc
        except httpx.RequestError as exc:
            raise SerpProviderError(
                "provider_network_error",
                "多搜索引擎接口网络连接失败",
                retryable=True,
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
            ) from exc
        except Exception as exc:
            raise SerpProviderError(
                "provider_error",
                "多搜索引擎接口调用失败",
                elapsed_ms=max(0, round((perf_counter() - started_at) * 1000)),
            ) from exc

    for attempt in range(1, DATAFORSEO_MAX_ATTEMPTS + 1):
        try:
            return await request_once()
        except SerpProviderError as exc:
            if not exc.retryable or attempt >= DATAFORSEO_MAX_ATTEMPTS:
                exc.attempts = attempt
                exc.elapsed_ms = max(
                    0, round((perf_counter() - operation_started_at) * 1000)
                )
                raise
            backoff = DATAFORSEO_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            jitter = random.uniform(0, DATAFORSEO_RETRY_BASE_SECONDS)
            await asyncio.sleep(max(backoff + jitter, exc.retry_after_seconds or 0))
    raise AssertionError("unreachable")


async def fetch_dataforseo_serp_batch(
    engine: str,
    requests: list[tuple[str, str]],
) -> list[tuple[dict[str, Any] | None, SerpProviderError | None]]:
    semaphore = asyncio.Semaphore(DATAFORSEO_MAX_CONCURRENCY)
    async with create_dataforseo_client() as client:
        async def fetch_one(keyword: str, device: str):
            try:
                async with semaphore:
                    return await fetch_dataforseo_serp(engine, keyword, device, client=client), None
            except SerpProviderError as exc:
                return None, exc
        return await asyncio.gather(*(fetch_one(keyword, device) for keyword, device in requests))


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
        if kind == "official_domain" and domain_matches(target_domain, value):
            return {"ownership_type": "official_site", "match_method": "official_domain", "confidence": 100, "matched_asset_id": asset["id"], "is_confirmed": True}
    if target_url in content_urls:
        return {"ownership_type": "brand_content", "match_method": "published_url", "confidence": 100, "matched_asset_id": None, "is_confirmed": True}
    if target_domain and any(domain_matches(target_domain, value) for value in official_domains):
        return {"ownership_type": "official_site", "match_method": "site_domain", "confidence": 100, "matched_asset_id": None, "is_confirmed": True}
    haystack = " ".join((target_url, str(item.get("title") or ""), str(item.get("description") or ""))).lower()
    for asset_id, pattern in account_patterns:
        if pattern and pattern.lower() in haystack:
            return {"ownership_type": "brand_content", "match_method": "platform_account", "confidence": 95, "matched_asset_id": asset_id, "is_confirmed": True}
    return {"ownership_type": "unresolved", "match_method": "none", "confidence": None, "matched_asset_id": None, "is_confirmed": False}
