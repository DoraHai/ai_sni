"""Read-only platform inventory for authenticated, global administrators.

Optional SEO/GEO tables are inspected through fixed projections, so independently
deployed modules do not require importing their models or exposing JSON secrets.
The snapshot remains read-only. A separate guarded route edits only API policies
with atomic audit; neither route executes jobs, calls providers or migrates DBs.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response, Request
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.security.auth import AuthContext, require_auth
from app.api_cost_summary import read_api_costs
from app.api_controls import read_controls, mutate, enabled as controls_enabled, ControlConflict


async def require_console_admin(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    # The console uses an ordinary named account; an operational API key does
    # not become a browser identity. Both global management permissions apply.
    if ctx.user_id is None or ctx.tenant_id is not None or not all(
        ctx.can_edit(key) for key in ("settings.accounts", "settings.customers")
    ):
        raise HTTPException(403, "仅全局超级管理员可以访问管理工作台")
    return ctx


router = APIRouter(
    prefix="/api/v1/admin/console", tags=["超级管理员工作台"],
    dependencies=[Depends(require_console_admin)],
)
_read_slots = asyncio.BoundedSemaphore(2)

# Table/column names come solely from this source allowlist, never from a URL.
PROJECTIONS = {
    "tenants": ("id", "name", "industry", "created_at"),
    "users": ("id", "username", "display_name", "role_id", "tenant_id", "is_active", "last_login_at"),
    "roles": ("id", "name", "description", "permissions", "is_system"),
    "tenant_modules": ("id", "tenant_id", "module_code", "status", "expires_at"),
    "seo_sites": ("id", "tenant_id", "name", "domain", "status"),
    "geo_projects": ("id", "tenant_id", "name", "primary_domain", "status"),
    "api_audit_logs": ("id", "tenant_id", "endpoint", "request_id", "status_code", "error_code", "latency_ms", "created_at"),
    "seo_tasks": ("id", "tenant_id", "title", "status", "updated_at"),
    "sem_tasks": ("id", "tenant_id", "title", "status", "updated_at"),
    "geo_async_jobs": ("id", "tenant_id", "kind", "status", "created_at"),
    "geo_action_tickets": ("id", "tenant_id", "title", "status", "updated_at"),
    "seo_ai_operations": ("id", "tenant_id", "kind", "status", "charged_on", "created_at"),
    "geo_tracking_engines": ("id", "tenant_id", "engine_key", "display_name", "enabled", "sample_mode", "model"),
    "baidu_oauth_grants": ("id", "tenant_id", "status", "expires_at"),
    "seo_analytics_sources": ("id", "tenant_id", "site_id", "provider", "status"),
}


def safe_endpoint(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        # Never return query strings, fragments, usernames or passwords.
        return ((parsed.hostname or "") + parsed.path)[:200]
    except ValueError:
        return "接口地址不可解析"


def machine_code(value: str | None) -> str | None:
    return value if value and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", value) else None


async def table_catalog(session: AsyncSession) -> dict[str, set[str]]:
    rows = (await session.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ANY(:names)"
    ), {"names": list(PROJECTIONS)})).all()
    catalog: dict[str, set[str]] = {}
    for name, column in rows:
        catalog.setdefault(name, set()).add(column)
    return catalog


async def read_table(session: AsyncSession, catalog: dict, name: str, *, limit=200, recent=False) -> dict:
    columns = PROJECTIONS[name]
    if not set(columns).issubset(catalog.get(name, set())):
        return {"state": "unavailable", "total": None, "rows": [], "truncated": False}
    order = "created_at DESC, id DESC" if recent and "created_at" in columns else "id DESC"
    total = int(await session.scalar(text(f'SELECT count(*) FROM "{name}"')))
    rows = [dict(row) for row in (await session.execute(text(
        f'SELECT {", ".join(columns)} FROM "{name}" ORDER BY {order} LIMIT :limit'
    ), {"limit": limit})).mappings()]
    for row in rows:
        for key, value in row.items():
            if isinstance(value, datetime) and value.tzinfo is None:
                row[key] = value.replace(tzinfo=timezone.utc)
    if name == "api_audit_logs":
        for row in rows:
            row["endpoint"] = safe_endpoint(row["endpoint"])
            row["error_code"] = machine_code(row["error_code"])
            row["request_id"] = machine_code(row["request_id"])
    return {"state": "available", "total": total, "rows": rows, "truncated": total > len(rows)}


async def read_usage(session: AsyncSession, catalog: dict, today: str) -> list[dict]:
    if "module_settings" not in catalog.get("tenant_modules", set()):
        return []
    # Only extract known counters; do not fetch/return the rest of settings.
    rows = (await session.execute(text(
        "SELECT tenant_id, module_settings->'seo_daily_usage'->>'date' AS date, "
        "module_settings->'seo_daily_usage'->>'ai_requests' AS ai_requests, "
        "module_settings->'seo_daily_usage'->>'crawl_urls' AS crawl_urls, "
        "module_settings->'seo_daily_usage'->>'workbench_chat_requests' AS chat_requests "
        "FROM tenant_modules WHERE module_code = 'seo' "
        "AND module_settings->'seo_daily_usage'->>'date' = :today "
        "ORDER BY tenant_id LIMIT 1000"
    ), {"today": today})).mappings()
    def counter(value):
        return min(int(value), 10**12) if value and re.fullmatch(r"\d{1,13}", str(value)) else 0
    return [{"tenant_id": row["tenant_id"], "date": today,
             **{key: counter(row[key]) for key in ("ai_requests", "crawl_urls", "chat_requests")}}
            for row in rows]


async def build_snapshot(session: AsyncSession) -> dict:
    catalog = await table_catalog(session)
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    sources = {}
    for name in PROJECTIONS:
        sources[name] = await read_table(
            session, catalog, name, limit=50 if name == "api_audit_logs" else
            30 if name in {"seo_tasks", "sem_tasks", "geo_async_jobs", "geo_action_tickets", "seo_ai_operations"} else 1000,
            recent=name in {"api_audit_logs", "seo_ai_operations", "geo_async_jobs"},
        )
    calls = {"state": sources["api_audit_logs"]["state"], "period": "last_24_hours",
             "total": None, "failed": None, "average_latency_ms": None,
             "coverage": "recorded_only"}
    if calls["state"] == "available":
        row = (await session.execute(text(
            "SELECT count(*) AS total, count(*) FILTER (WHERE status_code >= 400 OR error_code IS NOT NULL) AS failed, "
            "avg(latency_ms) AS average_latency_ms FROM api_audit_logs "
            "WHERE created_at >= (CURRENT_TIMESTAMP - INTERVAL '24 hours')"
        ))).mappings().one()
        calls.update(total=int(row["total"]), failed=int(row["failed"]),
                     average_latency_ms=round(float(row["average_latency_ms"]), 1)
                     if row["average_latency_ms"] is not None else None)
    alerts = []
    api_costs = await read_api_costs(session)
    if api_costs['state'] in {'recording', 'ready'}:
        calls = api_costs['calls_24h_summary']
    controls = await read_controls(session)
    for budget in controls['budgets']:
        if budget['status'] != 'normal':
            target = budget['target']
            alerts.append({'kind': 'api_budget', 'severity': 'warning',
                           'tenant_id': int(target.split(':')[1]) if target.startswith('tenant:') else None,
                           'message': f"API 预算 {target}：" + {'warning': '接近上限', 'blocked': '已达到上限，新请求暂停',
                                                               'unknown': '存在未知费用，金额预算暂停新请求'}[budget['status']]})
    for row in sources["baidu_oauth_grants"]["rows"]:
        expiry = row["expires_at"]
        if row["status"] == "active" and expiry and expiry <= now:
            alerts.append({"kind": "authorization_expired", "severity": "warning",
                           "tenant_id": row["tenant_id"], "message": "百度推广授权已过期，请核对授权状态"})
    for row in sources["tenant_modules"]["rows"]:
        expiry = row["expires_at"]
        if row["status"] == "active" and expiry and expiry.isoformat() < today:
            alerts.append({"kind": "service_expired", "severity": "warning",
                           "tenant_id": row["tenant_id"], "message": f'{row["module_code"].upper()} 服务已到期'})
    for name in ("geo_async_jobs", "seo_ai_operations"):
        for row in sources[name]["rows"]:
            if row["status"] == "failed":
                alerts.append({"kind": "task_failed", "severity": "error", "tenant_id": row["tenant_id"],
                               "message": "GEO 异步任务失败" if name == "geo_async_jobs" else "SEO AI 操作失败"})
    if calls["failed"]:
        alerts.append({"kind": "api_errors", "severity": "error", "tenant_id": None,
                       "message": f'近 24 小时已记录 {calls["failed"]} 次接口异常'})
    return {
        "schema": 1, "generated_at": now.isoformat(), "mode": "read_only_inventory",
        "sources": sources, "calls": calls, "alerts": alerts[:100],
        "api_costs": api_costs, "controls": controls,
        "costs": {"state": "metering_incomplete", "date": today, "currency": "CNY",
                  "actual_amount": None, "estimated_amount": None,
                  "usage": await read_usage(session, catalog, today),
                  "note": "已有部分调用次数与抓取配额；尚未统一记录 token、单价、金额及账单。"},
        "coverage": {"api": "调用与费用共用真实外部请求台账，覆盖已接入计量的服务商。",
                     "tasks": "显示各模块最近任务，完整处理沿用模块工作区。",
                     "credentials": "可管理已登记接口开关、单价及密钥轮换。密钥加密保存且不回显；百度 OAuth 沿用原授权流程。",
                     "backup": "备份状态与恢复演练记录尚未接入此页面。",
                     "audit": "预算、接口开关、单价及密钥变更均记录管理员、时间、版本与变更前后状态。"},
    }


@router.get("/snapshot")
async def console_snapshot(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Vary"] = "Authorization"
    # Separate bounded read-only transaction; auth dependency has its own session.
    try:
        async with asyncio.timeout(12):
            async with _read_slots, async_session_factory() as session:
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                await session.execute(text("SET LOCAL statement_timeout = '3000ms'"))
                return await build_snapshot(session)
    except TimeoutError:
        raise HTTPException(503, "平台盘点读取超时，请稍后重试") from None


@router.post('/controls')
async def console_control(request: Request, response: Response,
                          ctx: AuthContext = Depends(require_console_admin)):
    response.headers['Cache-Control'] = 'no-store, private'
    response.headers['Vary'] = 'Authorization'
    if not controls_enabled():
        raise HTTPException(503, 'API 管理配置等待启用')
    # Manual parsing avoids validation responses echoing password/key inputs.
    try:
        size = request.headers.get('content-length')
        if size and int(size) > 8192:
            raise ValueError
        raw = b''
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > 8192:
                raise ValueError
        import json
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {'request_id', 'kind', 'key', 'expected_revision', 'value'}:
            raise ValueError
        data['request_id'] = str(UUID(data['request_id']))
        if data['kind'] not in {'budget', 'provider', 'rate', 'credential'} or not isinstance(data['key'], str):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, '管理请求格式无效') from None
    try:
        async with asyncio.timeout(8), async_session_factory() as session:
            return await mutate(session, actor_id=ctx.user_id, **data)
    except ControlConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(503, '管理配置未保存，请刷新核对后重试') from None
