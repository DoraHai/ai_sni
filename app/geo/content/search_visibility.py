"""Independent DeepSeek search evidence. No answer metrics or SEM credentials."""

from __future__ import annotations

import asyncio
import csv
import io
import ipaddress
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy import select, text

from app.config import get_settings
from app.database import async_session_factory, engine
from app.geo.audit import safe_fetch
from app.models import (
    GeoAsyncJob, GeoChannelVariant, GeoContentTask, GeoMediaPlacement,
    GeoProject, GeoPublication, Tenant, TenantModule,
)
from app.module_scope import module_is_available

KIND = "search_visibility"
TZ = ZoneInfo("Asia/Shanghai")
PRICE = Decimal("0.005")
NOTICE = "这是 DeepSeek 搜索引擎能不能搜到你，不等于 DeepSeek 回答里会提到你"
MONTH_LIMIT = "本月额度已用完"
RUN_LIMIT = "本次请求已达上限"
BALANCE_LOW = "余额不足"
_LOCK_ID = 714061018  # Dedicated GEO search lock; never a SEM scheduler lock.


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def beijing(value: datetime) -> datetime:
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(TZ)


def month_key(value: datetime | None = None) -> str:
    return beijing(value or now_utc()).strftime("%Y-%m")


def week_start(value: datetime | None = None) -> datetime:
    local = beijing(value or now_utc())
    start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def url_host(value: str) -> str:
    return (urlsplit(value).hostname or "").lower().rstrip(".").encode("idna").decode("ascii")


def is_zhihu(value: str) -> bool:
    host = url_host(value)
    return host == "zhihu.com" or host.endswith(".zhihu.com")


def valid_url(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 2048 or re.search(r"[\s\\\x00-\x1f]", value):
        raise ValueError("链接须为 2048 字以内的 http(s) 地址")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("链接须为 http(s) 地址，不能包含账号密码")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("链接只支持标准网页端口")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError("链接必须指向公网网站")
        encoded = host.encode("idna").decode("ascii")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", encoded):
            raise ValueError("网站域名格式不正确")
    else:
        if not address.is_global:
            raise ValueError("链接不能指向内网或保留地址")
    return value


def canonical_url(value: str) -> str:
    """Keep query (often the article ID), normalize only host/scheme/fragment."""
    p = urlsplit(valid_url(value))
    host = url_host(value).removeprefix("www.")
    return urlunsplit(("https", host, p.path.rstrip("/") or "/", p.query, ""))


Term = Annotated[str, Field(min_length=1, max_length=128)]


class VisibilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    enabled: StrictBool = False
    domains: list[str] = Field(default_factory=list, max_length=3)
    zh_url: str = ""
    brand_terms: list[Term] = Field(default_factory=list, max_length=5)
    core_terms: list[Term] = Field(default_factory=list, max_length=20)
    extra_article_urls: list[str] = Field(default_factory=list, max_length=20)
    customer_visible: StrictBool = False

    @field_validator("domains")
    @classmethod
    def domains_valid(cls, values: list[str]) -> list[str]:
        out = []
        for raw in values:
            raw = raw.strip().lower().rstrip(".")
            if "://" in raw or any(c in raw for c in "/:?#@"):
                raise ValueError("域名只填网站域名，不带协议或路径")
            valid_url("https://" + raw)
            raw = raw.encode("idna").decode("ascii")
            if len("site:" + raw) > 128:
                raise ValueError("域名过长，搜索词不能超过 128 字")
            out.append(raw)
        return list(dict.fromkeys(out))

    @field_validator("zh_url")
    @classmethod
    def homepage_valid(cls, value: str) -> str:
        return valid_url(value) if value else ""

    @field_validator("extra_article_urls")
    @classmethod
    def articles_valid(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(valid_url(v) for v in values))

    @field_validator("brand_terms", "core_terms")
    @classmethod
    def terms_unique(cls, values: list[str]) -> list[str]:
        if any(re.search(r"[\x00-\x1f]", v) for v in values):
            raise ValueError("搜索词不能包含控制字符")
        return list(dict.fromkeys(values))


def resolve_config(project: GeoProject, tenant: Tenant, override: dict | None = None) -> VisibilityConfig:
    raw = override if override is not None else (project.project_settings or {}).get("deepseek_visibility", {})
    try:
        domain = url_host(project.primary_domain if "://" in (project.primary_domain or "") else "https://" + (project.primary_domain or ""))
        domains = VisibilityConfig(domains=[domain]).domains if domain else []
    except ValueError:
        domains = []
    try:
        homepage = valid_url(project.default_url) if project.default_url else ""
    except ValueError:
        homepage = ""
    defaults = {
        "domains": domains,
        "zh_url": homepage,
        "brand_terms": list(dict.fromkeys(v.strip()[:128] for v in [project.brand_name, *(tenant.brand_terms or [])] if isinstance(v, str) and v.strip()))[:5],
    }
    return VisibilityConfig.model_validate({**defaults, **raw})


def is_admin(ctx) -> bool:
    return ctx.tenant_id is None and (ctx.is_superadmin or (
        ctx.can_edit("settings.accounts") and ctx.can_edit("settings.customers")
    ))


def is_advisor(ctx) -> bool:
    # Same permission pair as existing advisor-account eligibility, no role-name guesses.
    return is_admin(ctx) or (ctx.can_edit("geo.assets") and ctx.can_edit("geo.content"))


def access_state(config: VisibilityConfig, ctx, settings=None) -> dict:
    if not is_advisor(ctx) and not config.customer_visible:
        return {"state": "not_open", "message": "暂未开放"}
    settings = settings or get_settings()
    if not config.enabled or not settings.deepseek_search_api_key.strip():
        return {"state": "not_enabled", "message": "待启用"}
    return {"state": "ready", "message": "已启用"}


class StopRun(Exception):
    pass


class ProcessLimiter:
    """Process-wide spacing, also applied to retries and balance checks."""
    def __init__(self):
        self.lock = asyncio.Lock()
        self.last = 0.0
        self.domains: dict[str, float] = {}

    async def wait(self, qps: float, domain: str | None = None):
        async with self.lock:
            current = time.monotonic()
            delay = max(0, self.last + 1 / min(4, qps) - current)
            if domain:
                delay = max(delay, self.domains.get(domain, 0) + 1 - current)
            if delay:
                await asyncio.sleep(delay)
            self.last = time.monotonic()
            if domain:
                self.domains[domain] = self.last


LIMITER = ProcessLimiter()


def empty_result(config: VisibilityConfig, article_count: int) -> dict:
    return {"summary": {
        "indexed": None, "indexed_count": 0, "brand_hit": 0,
        "brand_total": len(config.brand_terms), "core_hit": 0,
        "core_total": len(config.core_terms), "articles_alive": 0,
        "articles_total": article_count, "requests": 0, "billable": 0,
        "cost_cny": 0, "reserved_cny": 0, "stopped_reason": None,
    }, "items": [], "monthly_usage": {}}


def usage_from_results(results: list[dict], month: str) -> dict:
    requests = billable = reserved = 0
    for result in results:
        bucket = (result or {}).get("monthly_usage", {}).get(month, {})
        requests += int(bucket.get("requests", 0))
        billable += int(bucket.get("billable", 0))
        reserved += int(bucket.get("reserved_billable", 0))
    return {"month": month, "requests": requests, "billable": billable,
            "cost_cny": float(PRICE * billable), "reserved_cny": float(PRICE * reserved)}


class SearchClient:
    def __init__(self, http: httpx.AsyncClient, config: VisibilityConfig, result: dict,
                 *, settings=None, checkpoint: Callable[[], Awaitable[None]],
                 monthly_usage: Callable[[str], Awaitable[dict]]):
        self.http, self.config, self.result = http, config, result
        self.settings = settings or get_settings()
        self.checkpoint, self.monthly_usage = checkpoint, monthly_usage

    async def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        summary = self.result["summary"]
        domain = url_host(payload["url"]) if path.endswith("fetch") else None
        last_status = None
        for attempt in range(3):
            if summary["requests"] >= self.settings.deepseek_search_run_request_limit:
                raise StopRun(RUN_LIMIT)
            await LIMITER.wait(self.settings.deepseek_search_qps, domain)
            month = month_key()
            used = await self.monthly_usage(month)
            chargeable = method == "POST"
            projected = Decimal(str(used["cost_cny"])) + Decimal(str(used["reserved_cny"])) + (PRICE if chargeable else 0)
            if projected > Decimal(str(self.settings.deepseek_search_monthly_limit_cny)) or (
                not chargeable and projected >= Decimal(str(self.settings.deepseek_search_monthly_limit_cny))
            ):
                raise StopRun(MONTH_LIMIT)
            bucket = self.result["monthly_usage"].setdefault(month, {"requests": 0, "billable": 0, "reserved_billable": 0})
            summary["requests"] += 1
            bucket["requests"] += 1
            if chargeable:
                bucket["reserved_billable"] += 1
                summary["reserved_cny"] = float(Decimal(str(summary["reserved_cny"])) + PRICE)
            # Write before transport: a crash cannot erase potentially billed attempts.
            await self.checkpoint()
            data = {}
            known = False
            retryable = False
            try:
                response = await self.http.request(method, path, json=payload if payload else None)
                last_status = response.status_code
                known = True
                try:
                    data = response.json()
                except ValueError:
                    data = {}
                if not isinstance(data, dict):
                    data = {}
                field = "results" if path.endswith("search") else "content"
                valid = isinstance(data.get(field), list if field == "results" else str) if chargeable else isinstance(data.get("is_available"), bool)
                billable = last_status == 200 and valid and bool(data.get(field)) if chargeable else False
                # Malformed 200 bodies remain reserved: billing outcome is unknown.
                known = last_status != 200 or valid
                if billable:
                    bucket["billable"] += 1
                    summary["billable"] += 1
                    summary["cost_cny"] = float(PRICE * summary["billable"])
                retryable = last_status in {408, 429} or last_status >= 500
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                retryable = True
                last_status = None
            if chargeable and known:
                bucket["reserved_billable"] -= 1
                summary["reserved_cny"] = float(max(Decimal("0"), Decimal(str(summary["reserved_cny"])) - PRICE))
            await self.checkpoint()
            if last_status == 402:
                raise StopRun(BALANCE_LOW)
            if retryable and attempt < 2:
                await asyncio.sleep((2, 5)[attempt])
                continue
            okay = last_status == 200 and valid
            return {"ok": okay, "http_status": last_status,
                    "retries": attempt, "data": data,
                    "error": None if okay else (f"请求失败或结果格式不正确（HTTP {last_status}）" if last_status else "请求连接中断或超时")}
        raise AssertionError("unreachable")


def matches(url: str, domains: list[str], articles: list[str]) -> bool:
    try:
        host = url_host(valid_url(url))
        if any(host == d or host.endswith("." + d) for d in domains):
            return True
        return canonical_url(url) in {canonical_url(a) for a in articles}
    except (ValueError, AttributeError):
        return False


def search_items(data: dict, count: int) -> list[dict]:
    values = data.get("results", [])
    if not isinstance(values, list):
        return []
    out = []
    for rank, row in enumerate(values[:count], 1):
        if not isinstance(row, dict):
            continue
        item = {"rank": rank}
        for key in ("url", "title", "site_name", "date", "authority", "rerank_score"):
            value = row.get(key)
            item[key] = value[:2048] if isinstance(value, str) else value if isinstance(value, (int, float)) else None
        try:
            item["url"] = valid_url(item.get("url") or "")
        except ValueError:
            item["url"] = None
        out.append(item)
    return out


def page_info(content: str, title: str = "", *, markdown: bool = False) -> dict:
    if markdown:
        # Treat Markdown as text before HTML parsing: URLs/formatting are not body evidence.
        content = re.sub(r"```.*?```", "", content, flags=re.S)
        content = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", content)
        content = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|[-*>]\s+)", "", content)
    soup = BeautifulSoup(content, "html.parser")
    for node in soup(["script", "style", "nav", "footer"]):
        node.decompose()
    text_value = soup.get_text(" ", strip=True)
    # Supplier returns Markdown; link destinations are not body words/language evidence.
    text_value = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text_value)
    text_value = re.sub(r"https?://\S+", "", text_value)
    letters = re.findall(r"[a-zA-Z\u4e00-\u9fff]", text_value)
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text_value))
    return {"title": (title or (soup.title.get_text(strip=True) if soup.title else ""))[:500],
            "body_chars": len(re.sub(r"\s", "", text_value)),
            "foreign_language": len(letters) >= 20 and chinese / len(letters) < 0.1}


async def collect(client: SearchClient, articles: list[str]):
    config, result = client.config, client.result
    summary = result["summary"]
    targets = ([config.zh_url] if config.zh_url else []) + articles
    expected = len(config.domains) + len(config.brand_terms) + len(config.core_terms) + sum(not is_zhihu(url) for url in targets)
    used = await client.monthly_usage(month_key())
    if Decimal(str(used["cost_cny"])) + Decimal(str(used["reserved_cny"])) + PRICE * expected > Decimal(str(client.settings.deepseek_search_monthly_limit_cny)):
        raise StopRun(MONTH_LIMIT)
    balance = await client.request("GET", "/user/balance")
    if not balance["ok"] or balance["data"].get("is_available") is not True:
        raise StopRun("余额暂不可查询，本次未运行")
    indexed_seen = set()
    indexed_ok = True
    for domain in config.domains:
        reply = await client.request("POST", "/v1/tools/search", {"query": "site:" + domain, "count": 50})
        rows = search_items(reply["data"], 50)
        # Index evidence must actually belong to this site, not merely be returned by search.
        hits = [r for r in rows if r["url"] and matches(r["url"], [domain], [])]
        indexed_seen.update(canonical_url(r["url"]) for r in hits)
        indexed_ok = indexed_ok and reply["ok"]
        summary["index_query_ok"] = indexed_ok
        summary["indexed_count"] = len(indexed_seen)
        summary["indexed"] = bool(indexed_seen) if indexed_ok else (True if indexed_seen else None)
        result["items"].append({"kind": "index", "query": "site:" + domain, "results": rows,
                                "count": len(hits), "error": reply["error"], "http_status": reply["http_status"], "retries": reply["retries"]})
        await client.checkpoint()
    for kind, terms in (("brand", config.brand_terms), ("core", config.core_terms)):
        for term in terms:
            reply = await client.request("POST", "/v1/tools/search", {"query": term, "count": 20})
            rows = search_items(reply["data"], 20)
            best = next((r["rank"] for r in rows if r["url"] and matches(r["url"], config.domains, articles)), None)
            summary[kind + "_hit"] += int(best is not None)
            result["items"].append({"kind": kind, "query": term, "best_rank": best, "results": rows,
                                    "error": reply["error"], "http_status": reply["http_status"], "retries": reply["retries"]})
            await client.checkpoint()
    targets = [("homepage", config.zh_url)] if config.zh_url else []
    targets += [("article", url) for url in articles]
    for kind, url in targets:
        item = {"kind": kind, "url": url, "source": "deepseek", "alive": None,
                "http_status": None, "title": "", "body_chars": 0, "retries": 0}
        if is_zhihu(url):
            item.update(source="skipped", error="知乎暂不能自动核对")
        else:
            reply = await client.request("POST", "/v1/tools/fetch", {"url": url})
            content = reply["data"].get("content")
            content = content if isinstance(content, str) else ""
            page_status = reply["data"].get("status_code", reply["http_status"])
            alive = bool(reply["ok"] and content.strip() and isinstance(page_status, int) and 200 <= page_status < 400)
            item.update(http_status=page_status, api_http_status=reply["http_status"], retries=reply["retries"],
                        error=reply["error"], alive=alive, **page_info(content, str(reply["data"].get("title") or ""), markdown=True))
            if item["foreign_language"]:
                item["warning"] = "被跳到外语版"
                try:
                    document = await safe_fetch(url)
                    fallback_info = page_info(document.html)
                    item["fallback"] = {"source": "local_safe_fetch", "http_status": 200,
                                        "alive": fallback_info["body_chars"] > 0, **fallback_info}
                    item["source"] = "deepseek+local_safe_fetch"
                    item["alive"] = item["alive"] or item["fallback"]["alive"]
                    item["effective_title"] = fallback_info["title"]
                    item["effective_body_chars"] = fallback_info["body_chars"]
                    item["effective_foreign_language"] = fallback_info["foreign_language"]
                except Exception:
                    item["fallback"] = {"source": "local_safe_fetch", "error": "本机兜底抓取未成功"}
        summary["articles_alive"] += int(kind == "article" and item["alive"] is True)
        result["items"].append(item)
        await client.checkpoint()


async def article_urls(session, tenant_id: int, config: VisibilityConfig) -> list[str]:
    publications = await session.scalars(
        select(GeoPublication.published_url)
        .join(GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id)
        .join(GeoContentTask, GeoContentTask.id == GeoChannelVariant.task_id)
        .where(GeoContentTask.tenant_id == tenant_id, GeoPublication.published_url.is_not(None))
        .order_by(GeoPublication.id.desc()).limit(100)
    )
    placements = await session.scalars(select(GeoMediaPlacement.published_url).where(
        GeoMediaPlacement.tenant_id == tenant_id, GeoMediaPlacement.published_url.is_not(None)
    ).order_by(GeoMediaPlacement.id.desc()).limit(100))
    out, seen = [], set()
    for url in [*publications, *placements, *config.extra_article_urls]:
        try:
            key = canonical_url(url)
        except (ValueError, TypeError):
            continue
        if key not in seen:
            out.append(url)
            seen.add(key)
    return out[:20]


async def month_usage(session, month: str | None = None) -> dict:
    # All statuses, including running/failed with reserved unknown attempts.
    month = month or month_key()
    buckets = await session.scalars(select(GeoAsyncJob.result_meta["monthly_usage"][month]).where(GeoAsyncJob.kind == KIND))
    return usage_from_results([{"monthly_usage": {month: bucket or {}}} for bucket in buckets], month)


async def create_run(session, project: GeoProject, config: VisibilityConfig, *, trigger: str, actor: int | None):
    # Project row lock makes daily and in-flight dedup atomic across HTTP/scheduler workers.
    await session.execute(select(GeoProject.id).where(GeoProject.id == project.id).with_for_update())
    today = beijing(now_utc()).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    rows = list(await session.scalars(select(GeoAsyncJob).where(
        GeoAsyncJob.kind == KIND, GeoAsyncJob.ref_type == "geo_project", GeoAsyncJob.ref_id == project.id,
        GeoAsyncJob.tenant_id == project.tenant_id,
    ).order_by(GeoAsyncJob.id.desc())))
    if any(r.status in {"pending", "running"} for r in rows):
        raise StopRun("该项目已有任务正在运行")
    if trigger == "manual" and any(r.created_at >= today and (r.request_meta or {}).get("trigger") == "manual" for r in rows):
        raise StopRun("每个项目每天最多立即运行一次")
    if trigger == "schedule" and any(r.status == "succeeded" and r.created_at >= week_start() for r in rows):
        return None
    articles = await article_urls(session, project.tenant_id, config)
    row = GeoAsyncJob(tenant_id=project.tenant_id, kind=KIND, status="pending", ref_type="geo_project",
                      ref_id=project.id, created_by=actor, created_at=now_utc(),
                      request_meta={"config": config.model_dump(), "trigger": trigger, "article_urls": articles},
                      result_meta=empty_result(config, len(articles)))
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@asynccontextmanager
async def execution_lock():
    """Wait without occupying pool connections, so queued jobs cannot starve the owner."""
    while True:
        async with engine.connect() as connection:
            try:
                acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_ID})
            except BaseException:
                await connection.invalidate()
                raise
            if acquired:
                try:
                    yield connection
                finally:
                    try:
                        await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_ID})
                    except BaseException:
                        # A pooled physical connection must never retain our session lock.
                        await connection.invalidate()
                        raise
                return
        await asyncio.sleep(1)


async def execute_run(job_id: int):
    """Dedicated session advisory lock serializes budget + retries across GEO processes.

    A busy worker leaves pending evidence; it never calls a provider concurrently.
    Request reservations survive a crash and conservatively consume monthly headroom.
    """
    async with execution_lock() as owner_connection:
        async with async_session_factory() as session:
            job = await session.scalar(select(GeoAsyncJob).where(GeoAsyncJob.id == job_id, GeoAsyncJob.kind == KIND).with_for_update())
            if job is None or job.status not in {"pending", "running"}:
                return
            if job.status == "running":
                # Acquiring the global lock proves the previous owner is gone.
                from copy import deepcopy
                result = deepcopy(job.result_meta or {})
                reason = "上次运行被中断，已保留用量记录；本次未重新请求"
                result.setdefault("summary", {})["stopped_reason"] = reason
                job.result_meta, job.status, job.error = result, "failed", reason
                job.finished_at = now_utc()
                await session.commit()
                return
            project = await session.get(GeoProject, job.ref_id)
            module = await session.get(TenantModule, project.tenant_module_id) if project else None
            try:
                if (not project or project.tenant_id != job.tenant_id or project.status != "active"
                    or not module or module.tenant_id != job.tenant_id or module.module_code != "geo"
                    or not module_is_available(module)):
                    raise StopRun("项目或 GEO 服务已停用")
                tenant = await session.get(Tenant, job.tenant_id)
                current = resolve_config(project, tenant)
                if not current.enabled or not get_settings().deepseek_search_api_key.strip():
                    raise StopRun("待启用")
                config = VisibilityConfig.model_validate(job.request_meta["config"])
                from copy import deepcopy
                result = deepcopy(job.result_meta)
                job.status, job.started_at = "running", now_utc()
                await session.commit()

                async def checkpoint():
                    from copy import deepcopy
                    # A lost owner connection cannot silently reconnect and continue dispatching.
                    if owner_connection.invalidated:
                        raise RuntimeError("execution owner unavailable")
                    await owner_connection.execute(text("SELECT 1"))
                    job.result_meta = deepcopy(result)
                    await session.commit()

                async def usage(month):
                    return await month_usage(session, month)

                settings = get_settings()
                # Credentials must never be sent to a configurable third-party origin.
                if settings.deepseek_search_base_url.rstrip("/") != "https://api.deepseek.com":
                    raise StopRun("搜索接口地址配置不正确")
                async with httpx.AsyncClient(base_url=settings.deepseek_search_base_url,
                                             headers={"Authorization": "Bearer " + settings.deepseek_search_api_key},
                                             timeout=30, follow_redirects=False, trust_env=False) as http:
                    client = SearchClient(http, config, result, checkpoint=checkpoint, monthly_usage=usage)
                    await collect(client, job.request_meta["article_urls"])
                errors = any(i.get("error") and i.get("source") != "skipped" for i in result["items"])
                job.status = "failed" if errors else "succeeded"
                job.error = "部分项目查询失败，请查看明细" if errors else None
            except StopRun as exc:
                job.status, job.error = "failed", str(exc)
            except Exception:
                # No provider body/URL/header/exception text is persisted or logged.
                await session.rollback()
                job = await session.get(GeoAsyncJob, job_id)
                job.status, job.error = "failed", "查询未完成，请稍后检查任务状态"
            from copy import deepcopy
            final = deepcopy(job.result_meta or {})
            if job.error:
                final.setdefault("summary", {})["stopped_reason"] = job.error
            job.result_meta = final
            job.finished_at = now_utc()
            await session.commit()


def run_payload(job, *, advisor: bool) -> dict:
    from copy import deepcopy
    data = deepcopy(job.result_meta or {})
    if not advisor:
        for item in data.get("items", []):
            for key in ("error", "warning", "fallback", "http_status", "api_http_status", "retries"):
                item.pop(key, None)
        data.get("summary", {}).pop("stopped_reason", None)
        for key in ("requests", "billable", "cost_cny", "reserved_cny"):
            data.get("summary", {}).pop(key, None)
        data.pop("monthly_usage", None)
    return {"id": job.id, "status": job.status,
            "created_at": beijing(job.created_at).strftime("%Y-%m-%d %H:%M"),
            "finished_at": beijing(job.finished_at).strftime("%Y-%m-%d %H:%M") if job.finished_at else None,
            "result": data, "error": job.error if advisor else None}


def csv_text(payload: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["类型", "搜索词或链接", "最好名次", "标题", "链接", "核对结果"])
    def cell(value):
        value = str(value if value is not None else "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    for item in payload.get("result", {}).get("items", []):
        kind = {"index": "网站收录", "brand": "品牌词", "core": "核心词", "homepage": "中文首页", "article": "已发文章"}.get(item["kind"], "查询")
        rows = item.get("results") or [item]
        note = item.get("error") or item.get("warning")
        if not note:
            if item["kind"] in {"homepage", "article"}:
                note = "可访问" if item.get("alive") else "未确认" if item.get("alive") is None else "无法访问"
            else:
                note = "查询完成"
        for row in rows:
            writer.writerow([cell(v) for v in [kind, item.get("query", item.get("url")),
                             item.get("best_rank") or ("前 20 名没有" if item["kind"] in {"brand", "core"} and not item.get("error") else ""),
                             row.get("title"), row.get("url"), note]])
    return "\ufeff" + buffer.getvalue()
