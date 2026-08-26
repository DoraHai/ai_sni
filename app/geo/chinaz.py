"""站长之家公开 SEO 指标适配器。

第三方指标只作为诊断参考，不参与 16 项基础规则计分。API Key 仅从后端环境读取。
关键词接口只读取第一页样本；覆盖总量使用接口返回的 Total，避免无意义消耗额度。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.geo.audit import normalize_url


CHINAZ_CACHE_SECONDS = 6 * 60 * 60
BAIDU_INDEX_SOURCE_URL = "https://www.chinaz.net/mall/a_NUBNVBol1f.html"
BAIDU_PC_KEYWORDS_SOURCE_URL = "https://www.chinaz.net/mall/a_OQ9HvBsn0v.html"
BAIDU_MOBILE_KEYWORDS_SOURCE_URL = "https://www.chinaz.net/mall/a_wt07WJNGtE.html"
WEIGHT_ALL_SOURCE_URL = "https://www.chinaz.net/mall/a_t302FUj62I.html"
WHOIS_SOURCE_URL = "https://www.chinaz.net/mall/a_wdZE9ixQgu.html"

_baidu_index_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_metric_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _domain_from_url(url: str) -> str:
    return (urlparse(normalize_url(url)).hostname or "").lower().rstrip(".")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_code(payload: Any) -> int:
    if not isinstance(payload, dict):
        return -1
    try:
        return int(payload.get("StateCode", -1))
    except (TypeError, ValueError):
        return -1


def _as_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        values = value
    elif isinstance(value, str):
        values = value.replace(";", ",").replace("\n", ",").split(",")
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()]


def _parse_date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _completed_years(value: Any) -> int | None:
    created = _parse_date(value)
    if created is None:
        return None
    today = datetime.now(timezone.utc).date()
    created_date = created.date()
    if created_date > today:
        return None
    return today.year - created_date.year - ((today.month, today.day) < (created_date.month, created_date.day))


def _base_payload(
    domain: str,
    *,
    metric: str,
    source_url: str,
    methodology: str,
) -> dict[str, Any]:
    return {
        "provider": "chinaz",
        "metric": metric,
        "domain": domain,
        "status": "unavailable",
        "reason": "",
        "queried_at": None,
        "cache_hit": False,
        "is_estimate": True,
        "source_url": source_url,
        "methodology": methodology,
    }


def _provider_error(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("Reason") or "第三方接口暂未返回数据").strip()[:160]
    return "第三方接口返回格式异常"


def _endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _cache_get(cache: dict, key: Any) -> dict[str, Any] | None:
    cached = cache.get(key)
    if cached and time.monotonic() - cached[0] < CHINAZ_CACHE_SECONDS:
        return {**cached[1], "cache_hit": True}
    return None


def _cache_put(cache: dict, key: Any, result: dict[str, Any]) -> None:
    if result.get("status") == "available":
        cache[key] = (time.monotonic(), result)


async def _request_json(
    *,
    client: httpx.AsyncClient,
    endpoint: str,
    key: str,
    domain: str,
    timeout: float,
    extra_params: dict[str, Any] | None = None,
) -> Any:
    response = await client.get(
        endpoint,
        params={
            "domain": domain,
            "APIKey": key,
            "ChinazVer": "1.0",
            **(extra_params or {}),
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _parse_baidu_index_response(payload: Any, domain: str) -> dict[str, Any]:
    metric = _base_payload(
        domain,
        metric="baidu_index_count",
        source_url=BAIDU_INDEX_SOURCE_URL,
        methodology="站长之家按域名查询的百度收录量估算，不等同于百度搜索资源平台官方数据。",
    )
    metric["site_count"] = None
    if _state_code(payload) != 1:
        metric.update(status="error", reason=_provider_error(payload))
        return metric
    result = payload.get("Result") if isinstance(payload, dict) else None
    site_count = _as_int(result.get("SiteCount")) if isinstance(result, dict) else None
    if site_count is None:
        metric.update(status="error", reason="第三方接口未返回有效收录量")
        return metric
    metric.update(status="available", site_count=site_count, reason="查询成功", queried_at=_now_iso())
    return metric


def _keyword_payload(domain: str, *, mobile: bool) -> dict[str, Any]:
    return {
        **_base_payload(
            domain,
            metric="baidu_mobile_keywords" if mobile else "baidu_pc_keywords",
            source_url=BAIDU_MOBILE_KEYWORDS_SOURCE_URL if mobile else BAIDU_PC_KEYWORDS_SOURCE_URL,
            methodology=(
                "站长之家按域名估算的百度移动端关键词覆盖与排名；异地节点可能产生差异。"
                if mobile
                else "站长之家按域名估算的百度 PC 端关键词覆盖与排名；异地节点可能产生差异。"
            ),
        ),
        "total": None,
        "pages": None,
        "uv": None,
        "sample_count": 0,
        "keywords": [],
    }


def _parse_keyword_response(payload: Any, domain: str, *, mobile: bool) -> dict[str, Any]:
    metric = _keyword_payload(domain, mobile=mobile)
    if _state_code(payload) != 1:
        metric.update(status="error", reason=_provider_error(payload))
        return metric
    result = payload.get("Result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        metric.update(status="error", reason="第三方接口未返回有效关键词数据")
        return metric
    total = _as_int(result.get("Total"))
    rows = result.get("List") if isinstance(result.get("List"), list) else []
    keywords = []
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        keyword = str(row.get("Keyword") or "").strip()
        if not keyword:
            continue
        keywords.append(
            {
                "keyword": keyword,
                "rank": str(row.get("RankStr") or "").strip(),
                "index": _as_int(row.get("Index")),
                "title": str(row.get("Title") or "").strip(),
                "url": str(row.get("Url") or "").strip(),
                "catalog": str(row.get("Calalog") or row.get("Catalog") or "").strip(),
            }
        )
    if total is None:
        total = len(keywords) if rows else None
    if total is None:
        metric.update(status="error", reason="第三方接口未返回关键词总量")
        return metric
    metric.update(
        status="available",
        reason="查询成功",
        queried_at=_now_iso(),
        total=total,
        pages=_as_int(result.get("Pages")),
        uv=str(result.get("Uv") or "").strip() or None,
        sample_count=len(keywords),
        keywords=keywords,
    )
    return metric


def _parse_weight_response(payload: Any, domain: str) -> dict[str, Any]:
    metric = {
        **_base_payload(
            domain,
            metric="comprehensive_weight",
            source_url=WEIGHT_ALL_SOURCE_URL,
            methodology="站长之家综合权重为第三方估算，用于比较搜索覆盖趋势，不代表搜索引擎官方评级。",
        ),
        "baidu_pc": {"weight": None, "keyword_count": None, "uv": None},
        "baidu_mobile": {"weight": None, "keyword_count": None, "uv": None},
    }
    if _state_code(payload) != 1:
        metric.update(status="error", reason=_provider_error(payload))
        return metric
    result = payload.get("Result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        metric.update(status="error", reason="第三方接口未返回有效权重数据")
        return metric
    pc_weight = _as_int(result.get("BaidupcBr"))
    mobile_weight = _as_int(result.get("BaiduMobileBr"))
    if pc_weight is None and mobile_weight is None:
        metric.update(status="error", reason="第三方接口未返回百度权重数据")
        return metric
    metric.update(
        status="available",
        reason="查询成功",
        queried_at=_now_iso(),
        baidu_pc={
            "weight": pc_weight,
            "keyword_count": _as_int(result.get("BaidupcKwcount")),
            "uv": str(result.get("BaidupcUvcount") or "").replace("IP", "").strip() or None,
        },
        baidu_mobile={
            "weight": mobile_weight,
            "keyword_count": _as_int(result.get("BaiduMobileKwcount")),
            "uv": str(result.get("BaiduMobileUvcount") or "").replace("IP", "").strip() or None,
        },
    )
    return metric


def _whois_payload(domain: str) -> dict[str, Any]:
    return {
        **_base_payload(
            domain,
            metric="whois",
            source_url=WHOIS_SOURCE_URL,
            methodology=(
                "站长之家标准 Whois 查询结果，用于展示域名注册时间、到期时间与注册商；"
                "结果可能存在缓存，续费与权属判断应以注册局实时数据为准。"
            ),
        ),
        "host": domain,
        "registrar": None,
        "creation_date": None,
        "expiration_date": None,
        "domain_age_years": None,
        "whois_server": None,
        "dns_servers": [],
        "domain_status": [],
    }


def _parse_whois_response(payload: Any, domain: str) -> dict[str, Any]:
    metric = _whois_payload(domain)
    if _state_code(payload) != 1:
        metric.update(status="error", reason=_provider_error(payload))
        return metric
    nested = payload.get("Result") if isinstance(payload, dict) else None
    result = nested if isinstance(nested, dict) else payload
    if not isinstance(result, dict):
        metric.update(status="error", reason="第三方接口未返回有效 Whois 数据")
        return metric
    creation_date = str(result.get("CreationDate") or "").strip() or None
    expiration_date = str(result.get("ExpirationDate") or "").strip() or None
    registrar = str(result.get("Registrar") or "").strip() or None
    if creation_date is None and expiration_date is None and registrar is None:
        metric.update(status="error", reason="第三方接口未返回有效域名资产信息")
        return metric
    metric.update(
        status="available",
        reason="查询成功",
        queried_at=_now_iso(),
        is_estimate=False,
        host=str(result.get("Host") or domain).strip() or domain,
        registrar=registrar,
        creation_date=creation_date,
        expiration_date=expiration_date,
        domain_age_years=_completed_years(creation_date),
        whois_server=str(result.get("WhoisServer") or "").strip() or None,
        dns_servers=_as_string_list(result.get("DnsServer")),
        domain_status=_as_string_list(result.get("DomainStatus")),
    )
    return metric


async def fetch_baidu_index_count(
    url: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """按网站域名获取百度收录量；失败时返回可展示状态，不中断主诊断。"""
    domain = _domain_from_url(url)
    metric = _parse_baidu_index_response({}, domain)
    metric.update(status="unavailable", reason="站长之家 BD 收录量接口尚未配置")
    if api_key is not None and not api_key.strip():
        return metric
    settings = get_settings() if api_key is None or base_url is None or timeout is None else None
    key = api_key if api_key is not None else (
        settings.chinaz_baidu_index_api_key or settings.chinaz_api_key
    )
    if not (key or "").strip():
        return metric
    cached = _cache_get(_baidu_index_cache, domain)
    if cached:
        return cached
    request_base = base_url or settings.chinaz_api_base_url
    request_timeout = timeout or settings.chinaz_api_timeout_seconds
    owns_client = client is None
    http_client = client or httpx.AsyncClient()
    try:
        payload = await _request_json(
            client=http_client,
            endpoint=_endpoint(request_base, "baidupc_domaininclude"),
            key=key,
            domain=domain,
            timeout=request_timeout,
        )
        result = _parse_baidu_index_response(payload, domain)
    except (httpx.HTTPError, ValueError):
        metric.update(status="error", reason="站长之家收录量查询暂时失败")
        return metric
    finally:
        if owns_client:
            await http_client.aclose()
    _cache_put(_baidu_index_cache, domain, result)
    return result


async def _fetch_keywords(
    url: str,
    *,
    mobile: bool,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    domain = _domain_from_url(url)
    metric = _keyword_payload(domain, mobile=mobile)
    label = "BD 移动网站关键词" if mobile else "BD_PC 网站关键词"
    metric["reason"] = f"站长之家 {label}接口尚未配置"
    if api_key is not None and not api_key.strip():
        return metric
    settings = get_settings() if api_key is None or base_url is None or timeout is None else None
    configured = (
        settings.chinaz_baidu_mobile_keywords_api_key
        if mobile
        else settings.chinaz_baidu_pc_keywords_api_key
    ) if settings else ""
    key = api_key if api_key is not None else (configured or settings.chinaz_api_key)
    if not (key or "").strip():
        return metric
    cache_key = ("mobile_keywords" if mobile else "pc_keywords", domain)
    cached = _cache_get(_metric_cache, cache_key)
    if cached:
        return cached
    request_base = base_url or settings.chinaz_api_base_url
    request_timeout = timeout or settings.chinaz_api_timeout_seconds
    owns_client = client is None
    http_client = client or httpx.AsyncClient()
    try:
        payload = await _request_json(
            client=http_client,
            endpoint=_endpoint(request_base, "keyword_baidumobile" if mobile else "baidupckeyword"),
            key=key,
            domain=domain,
            timeout=request_timeout,
            extra_params={"page": 1},
        )
        result = _parse_keyword_response(payload, domain, mobile=mobile)
    except (httpx.HTTPError, ValueError):
        metric.update(status="error", reason=f"站长之家{label}查询暂时失败")
        return metric
    finally:
        if owns_client:
            await http_client.aclose()
    _cache_put(_metric_cache, cache_key, result)
    return result


async def fetch_baidu_pc_keywords(url: str, **kwargs: Any) -> dict[str, Any]:
    return await _fetch_keywords(url, mobile=False, **kwargs)


async def fetch_baidu_mobile_keywords(url: str, **kwargs: Any) -> dict[str, Any]:
    return await _fetch_keywords(url, mobile=True, **kwargs)


async def fetch_comprehensive_weight(
    url: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    domain = _domain_from_url(url)
    metric = _parse_weight_response({}, domain)
    metric.update(status="unavailable", reason="站长之家综合权重接口尚未配置")
    if api_key is not None and not api_key.strip():
        return metric
    settings = get_settings() if api_key is None or base_url is None or timeout is None else None
    key = api_key if api_key is not None else (
        settings.chinaz_weight_all_api_key or settings.chinaz_api_key
    )
    if not (key or "").strip():
        return metric
    cache_key = ("weight_all", domain)
    cached = _cache_get(_metric_cache, cache_key)
    if cached:
        return cached
    request_base = base_url or settings.chinaz_api_base_url
    request_timeout = timeout or settings.chinaz_api_timeout_seconds
    owns_client = client is None
    http_client = client or httpx.AsyncClient()
    try:
        payload = await _request_json(
            client=http_client,
            endpoint=_endpoint(request_base, "weight_all"),
            key=key,
            domain=domain,
            timeout=request_timeout,
        )
        result = _parse_weight_response(payload, domain)
    except (httpx.HTTPError, ValueError):
        metric.update(status="error", reason="站长之家综合权重查询暂时失败")
        return metric
    finally:
        if owns_client:
            await http_client.aclose()
    _cache_put(_metric_cache, cache_key, result)
    return result


async def fetch_whois(
    url: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """获取公开域名资产信息；不保留联系人、邮箱、电话等隐私字段。"""
    domain = _domain_from_url(url)
    metric = _whois_payload(domain)
    metric.update(status="unavailable", reason="站长之家 Whois 查询接口尚未配置")
    if api_key is not None and not api_key.strip():
        return metric
    settings = get_settings() if api_key is None or base_url is None or timeout is None else None
    key = api_key if api_key is not None else (
        settings.chinaz_whois_api_key or settings.chinaz_api_key
    )
    if not (key or "").strip():
        return metric
    cache_key = ("whois", domain)
    cached = _cache_get(_metric_cache, cache_key)
    if cached:
        return cached
    request_base = base_url or settings.chinaz_api_base_url
    request_timeout = timeout or settings.chinaz_api_timeout_seconds
    owns_client = client is None
    http_client = client or httpx.AsyncClient()
    try:
        payload = await _request_json(
            client=http_client,
            endpoint=_endpoint(request_base, "whois"),
            key=key,
            domain=domain,
            timeout=request_timeout,
        )
        result = _parse_whois_response(payload, domain)
    except (httpx.HTTPError, ValueError):
        metric.update(status="error", reason="站长之家 Whois 查询暂时失败")
        return metric
    finally:
        if owns_client:
            await http_client.aclose()
    _cache_put(_metric_cache, cache_key, result)
    return result


async def fetch_chinaz_seo_metrics(url: str) -> dict[str, dict[str, Any]]:
    """一次诊断并发获取五项指标；每项独立降级，任一失败不阻断主诊断。"""
    if not get_settings().chinaz_api_enabled:
        baidu_index, pc_keywords, mobile_keywords, weight, whois = await asyncio.gather(
            fetch_baidu_index_count(url, api_key=""),
            fetch_baidu_pc_keywords(url, api_key=""),
            fetch_baidu_mobile_keywords(url, api_key=""),
            fetch_comprehensive_weight(url, api_key=""),
            fetch_whois(url, api_key=""),
        )
        disabled = {
            "baidu_index": baidu_index,
            "baidu_pc_keywords": pc_keywords,
            "baidu_mobile_keywords": mobile_keywords,
            "comprehensive_weight": weight,
            "whois": whois,
        }
        for metric in disabled.values():
            metric.update(status="unavailable", reason="站长之家数据查询已暂停")
        return disabled

    async with httpx.AsyncClient() as client:
        baidu_index, pc_keywords, mobile_keywords, weight, whois = await asyncio.gather(
            fetch_baidu_index_count(url, client=client),
            fetch_baidu_pc_keywords(url, client=client),
            fetch_baidu_mobile_keywords(url, client=client),
            fetch_comprehensive_weight(url, client=client),
            fetch_whois(url, client=client),
        )
    return {
        "baidu_index": baidu_index,
        "baidu_pc_keywords": pc_keywords,
        "baidu_mobile_keywords": mobile_keywords,
        "comprehensive_weight": weight,
        "whois": whois,
    }
