"""百度自然搜索前 50 结果采集与确定性品牌归属匹配。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from app.config import get_settings


class SerpProviderError(RuntimeError):
    pass


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
    if not isinstance(payload, dict) or int(payload.get("StateCode", -1)) != 1:
        reason = payload.get("Reason") if isinstance(payload, dict) else "返回格式异常"
        raise SerpProviderError(str(reason or "站长之家未返回搜索结果"))
    result = payload.get("Result")
    if not isinstance(result, dict):
        raise SerpProviderError("站长之家未返回有效 Result")
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


async def fetch_baidu_top50(keyword: str, device: str) -> dict[str, Any]:
    if device not in {"desktop", "mobile"}:
        raise SerpProviderError("设备只支持 desktop 或 mobile")
    settings = get_settings()
    key = (
        settings.chinaz_baidu_pc_top50_api_key
        if device == "desktop"
        else settings.chinaz_baidu_mobile_top50_api_key
    ) or settings.chinaz_api_key
    if not settings.chinaz_api_enabled or not key:
        raise SerpProviderError(
            "未配置站长之家百度%s前50接口 Key" % ("PC" if device == "desktop" else "移动")
        )
    path = "baidupc_keywordtop50" if device == "desktop" else "baidumobile_keywordtop50"
    endpoint = f"{settings.chinaz_api_base_url.rstrip('/')}/{path}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                endpoint,
                params={"keyword": keyword, "APIKey": key, "ChinazVer": "1.0"},
                timeout=settings.chinaz_api_timeout_seconds,
            )
            response.raise_for_status()
            return parse_top50_response(response.json())
    except SerpProviderError:
        raise
    except Exception as exc:
        raise SerpProviderError(f"站长之家前50接口调用失败：{exc}") from exc


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
