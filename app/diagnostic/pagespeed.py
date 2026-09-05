"""网站访问体验适配器。

大陆服务器优先运行本地 Lighthouse，提供 Performance、LCP、CLS 实验室数据。
如未来恢复 Google PageSpeed/CrUX，则可继续补充 INP 真实用户数据。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.diagnostic.audit import normalize_url, safe_fetch


PAGESPEED_SOURCE_URL = "https://developers.google.com/speed/docs/insights/v5/about"
PAGESPEED_CACHE_SECONDS = 6 * 60 * 60

_pagespeed_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_lighthouse_lock = asyncio.Lock()


def _base_payload(url: str, strategy: str) -> dict[str, Any]:
    return {
        "provider": "local_lighthouse",
        "status": "unavailable",
        "reason": "",
        "requested_url": url,
        "final_url": "",
        "strategy": strategy,
        "performance_score": None,
        "field_data_source": None,
        "field_data_category": None,
        "metrics": {"lcp": None, "cls": None, "inp": None},
        "queried_at": None,
        "cache_hit": False,
        "source_url": PAGESPEED_SOURCE_URL,
        "methodology": (
            "Performance、LCP、CLS 来自服务器本地 Lighthouse 移动端实验室测试；"
            "INP 必须基于真实用户交互样本，实验室测试不生成该值。"
        ),
    }


def _status(value: float, good: float, poor: float) -> str:
    if value <= good:
        return "good"
    if value <= poor:
        return "needs_improvement"
    return "poor"


def _metric(
    value: float | None,
    *,
    unit: str,
    source: str,
    good: float,
    poor: float,
    category: str | None = None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "value": round(value, 3),
        "unit": unit,
        "source": source,
        "status": _status(value, good, poor),
        "category": category,
    }


def _field_metric(
    metrics: dict[str, Any], key: str, *, divisor: float, unit: str, good: float, poor: float
) -> dict[str, Any] | None:
    item = metrics.get(key)
    if not isinstance(item, dict):
        return None
    try:
        value = float(item["percentile"]) / divisor
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    return _metric(
        value,
        unit=unit,
        source="crux",
        good=good,
        poor=poor,
        category=str(item.get("category") or "").lower() or None,
    )


def _lab_value(audits: dict[str, Any], key: str) -> float | None:
    item = audits.get(key)
    if not isinstance(item, dict):
        return None
    try:
        return float(item["numericValue"])
    except (KeyError, TypeError, ValueError):
        return None


def _parse_response(payload: Any, requested_url: str, strategy: str) -> dict[str, Any]:
    result = _base_payload(requested_url, strategy)
    if not isinstance(payload, dict):
        result.update(status="error", reason="PageSpeed 返回格式异常")
        return result

    lighthouse = payload.get("lighthouseResult")
    if not isinstance(lighthouse, dict):
        result.update(status="error", reason="PageSpeed 未返回 Lighthouse 检测结果")
        return result

    categories = lighthouse.get("categories") or {}
    performance = categories.get("performance") if isinstance(categories, dict) else None
    try:
        performance_score = round(float(performance["score"]) * 100)
    except (KeyError, TypeError, ValueError):
        performance_score = None

    page_field = payload.get("loadingExperience")
    origin_field = payload.get("originLoadingExperience")
    field_block: dict[str, Any] = {}
    field_source = None
    for source, candidate in (("url", page_field), ("origin", origin_field)):
        if isinstance(candidate, dict) and isinstance(candidate.get("metrics"), dict) and candidate["metrics"]:
            field_block = candidate
            field_source = source
            break
    field_metrics = field_block.get("metrics") or {}

    lcp = _field_metric(
        field_metrics,
        "LARGEST_CONTENTFUL_PAINT_MS",
        divisor=1000,
        unit="s",
        good=2.5,
        poor=4.0,
    )
    cls = _field_metric(
        field_metrics,
        "CUMULATIVE_LAYOUT_SHIFT_SCORE",
        divisor=100,
        unit="",
        good=0.1,
        poor=0.25,
    )
    inp = _field_metric(
        field_metrics,
        "INTERACTION_TO_NEXT_PAINT",
        divisor=1,
        unit="ms",
        good=200,
        poor=500,
    )

    audits = lighthouse.get("audits") or {}
    if not isinstance(audits, dict):
        audits = {}
    if lcp is None:
        lab_lcp = _lab_value(audits, "largest-contentful-paint")
        lcp = _metric(
            lab_lcp / 1000 if lab_lcp is not None else None,
            unit="s",
            source="lighthouse",
            good=2.5,
            poor=4.0,
        )
    if cls is None:
        cls = _metric(
            _lab_value(audits, "cumulative-layout-shift"),
            unit="",
            source="lighthouse",
            good=0.1,
            poor=0.25,
        )

    result.update(
        status="available",
        reason="查询成功",
        final_url=str(lighthouse.get("finalUrl") or ""),
        performance_score=performance_score,
        field_data_source=field_source,
        field_data_category=(
            str(field_block.get("overall_category") or "").lower() or None
        ),
        metrics={"lcp": lcp, "cls": cls, "inp": inp},
        queried_at=datetime.now(timezone.utc).isoformat(),
    )
    return result


def _parse_lighthouse_report(
    report: Any, requested_url: str, strategy: str
) -> dict[str, Any]:
    """Normalize a Lighthouse CLI JSON report to the existing frontend contract."""
    result = _base_payload(requested_url, strategy)
    if not isinstance(report, dict):
        result.update(status="error", reason="Lighthouse 返回格式异常")
        return result

    categories = report.get("categories") or {}
    performance = categories.get("performance") if isinstance(categories, dict) else None
    try:
        performance_score = round(float(performance["score"]) * 100)
    except (KeyError, TypeError, ValueError):
        performance_score = None

    audits = report.get("audits") or {}
    if not isinstance(audits, dict):
        audits = {}
    lab_lcp = _lab_value(audits, "largest-contentful-paint")
    lcp = _metric(
        lab_lcp / 1000 if lab_lcp is not None else None,
        unit="s",
        source="lighthouse",
        good=2.5,
        poor=4.0,
    )
    cls = _metric(
        _lab_value(audits, "cumulative-layout-shift"),
        unit="",
        source="lighthouse",
        good=0.1,
        poor=0.25,
    )
    if performance_score is None and lcp is None and cls is None:
        result.update(status="error", reason="Lighthouse 未返回有效性能指标")
        return result

    result.update(
        status="available",
        reason="查询成功",
        final_url=str(report.get("finalUrl") or report.get("finalDisplayedUrl") or ""),
        performance_score=performance_score,
        metrics={"lcp": lcp, "cls": cls, "inp": None},
        queried_at=datetime.now(timezone.utc).isoformat(),
    )
    return result


def _resolve_executable(configured: str, candidates: tuple[str, ...]) -> str | None:
    if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
        return configured
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


async def _run_local_lighthouse(
    url: str,
    *,
    strategy: str,
    cli_path: str,
    chrome_path: str,
    timeout: float,
) -> dict[str, Any]:
    result = _base_payload(url, strategy)
    lighthouse = _resolve_executable(cli_path, ("lighthouse",))
    chrome = _resolve_executable(
        chrome_path,
        ("chromium-browser", "chromium", "google-chrome-stable", "google-chrome"),
    )
    if not lighthouse or not chrome:
        result.update(status="unavailable", reason="本地 Lighthouse 运行环境尚未安装")
        return result

    # Validate the complete main-document redirect chain before handing the URL to Chrome.
    document = await safe_fetch(url)
    target_url = document.final_url
    form_factor = "desktop" if strategy == "desktop" else "mobile"
    command = (
        lighthouse,
        target_url,
        "--output=json",
        "--output-path=stdout",
        "--only-categories=performance",
        f"--form-factor={form_factor}",
        f"--chrome-path={chrome}",
        "--chrome-flags=--headless --no-sandbox --disable-dev-shm-usage --disable-gpu",
        "--max-wait-for-load=45000",
        "--quiet",
    )
    async with _lighthouse_lock:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            result.update(status="error", reason="本地 Lighthouse 检测超时，请稍后重试")
            return result

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip().splitlines()
        reason = detail[-1][:120] if detail else "运行失败"
        result.update(status="error", reason=f"本地 Lighthouse 检测失败：{reason}")
        return result
    try:
        report = json.loads(stdout.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        result.update(status="error", reason="本地 Lighthouse 返回格式异常")
        return result
    return _parse_lighthouse_report(report, url, strategy)


async def fetch_pagespeed_insights(
    url: str,
    *,
    strategy: str = "mobile",
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    normalized_url = normalize_url(url)
    normalized_strategy = strategy if strategy in {"mobile", "desktop"} else "mobile"
    result = _base_payload(normalized_url, normalized_strategy)

    cache_key = (normalized_url, normalized_strategy)
    cached = _pagespeed_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < PAGESPEED_CACHE_SECONDS:
        return {**cached[1], "cache_hit": True}

    # Explicit test/provider arguments preserve the PageSpeed adapter path. Production
    # requests have no explicit provider arguments and therefore use local Lighthouse.
    use_remote = api_key is not None or base_url is not None or client is not None
    if not use_remote:
        settings = get_settings()
        parsed = await _run_local_lighthouse(
            normalized_url,
            strategy=normalized_strategy,
            cli_path=getattr(
                settings,
                "lighthouse_cli_path",
                "/opt/lighthouse-runner/node_modules/.bin/lighthouse",
            ),
            chrome_path=getattr(
                settings,
                "lighthouse_chrome_path",
                "/usr/bin/chromium-browser",
            ),
            timeout=timeout or getattr(settings, "lighthouse_timeout_seconds", 90.0),
        )
        if parsed["status"] == "available":
            _pagespeed_cache[cache_key] = (time.monotonic(), parsed)
        return parsed

    if api_key is not None and not api_key.strip():
        result["reason"] = "Google PageSpeed Insights API 尚未配置"
        return result
    settings = get_settings() if api_key is None or base_url is None or timeout is None else None
    key = settings.pagespeed_api_key if api_key is None and settings else api_key
    if not (key or "").strip():
        result["reason"] = "Google PageSpeed Insights API 尚未配置"
        return result
    endpoint = base_url or (settings.pagespeed_api_base_url if settings else "")
    request_timeout = timeout or (settings.pagespeed_api_timeout_seconds if settings else 60.0)
    owns_client = client is None
    http_client = client or httpx.AsyncClient()
    try:
        response = await http_client.get(
            endpoint,
            params={
                "url": normalized_url,
                "strategy": normalized_strategy,
                "category": "performance",
                "locale": "zh_CN",
                "key": key,
            },
            timeout=request_timeout,
        )
        response.raise_for_status()
        parsed = _parse_response(response.json(), normalized_url, normalized_strategy)
    except httpx.TimeoutException:
        result.update(status="error", reason="PageSpeed 检测超时，请稍后重试")
        return result
    except (httpx.HTTPError, ValueError):
        result.update(status="error", reason="PageSpeed 检测暂时失败")
        return result
    finally:
        if owns_client:
            await http_client.aclose()

    if parsed["status"] == "available":
        _pagespeed_cache[cache_key] = (time.monotonic(), parsed)
    return parsed
