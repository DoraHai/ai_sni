"""Read-only AI automation governance projection for the platform console.

The projection uses the reviewed provider-attempt ledger when it exists.  It
never probes providers, reads prompts, returns credentials, or assumes that an
independently deployed module is configured merely because its table is quiet.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlsplit

from sqlalchemy import text

from app import api_controls, api_metering
from app.config import get_server_settings

MODULES = ("sem", "seo", "geo")
WINDOW_HOURS = 24
AI_BINDING_MARKERS = (
    ".dashscope", ".deepseek", ".openai", ".qwen", ".doubao",
    ".hunyuan", ".qianfan", ".kimi", ".perplexity",
)


def _amount(value) -> str:
    return str(value if value is not None else Decimal("0"))


def _safe_budget(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    fields = ("daily_calls", "monthly_calls", "daily_cny", "monthly_cny", "warning_percent", "max_concurrent")
    return {field: value.get(field) for field in fields if field in value}


def _runtime_sem_configuration(settings=None) -> dict:
    settings = settings or get_server_settings()
    dash_key = str(getattr(settings, "dashscope_api_key", "") or "").strip()
    deep_key = str(getattr(settings, "deepseek_api_key", "") or "").strip()
    if dash_key:
        base_url = getattr(settings, "dashscope_base_url", "")
        model = getattr(settings, "dashscope_model", "") or "deepseek-v3"
    elif deep_key:
        base_url = getattr(settings, "deepseek_base_url", "")
        model = getattr(settings, "deepseek_model", "") or "deepseek-chat"
    else:
        return {
            "state": "available", "source": "sem_runtime",
            "provider": None, "model": None, "configured": False,
        }
    try:
        provider = urlsplit(str(base_url)).hostname or None
    except ValueError:
        provider = None
    return {
        "state": "available",
        "source": "sem_runtime",
        "provider": provider,
        "model": str(model) or None,
        "configured": True,
    }


def _unknown_configuration(module: str) -> dict:
    return {
        "state": "unavailable",
        "source": "independent_module_runtime_not_visible",
        "provider": None,
        "model": None,
        "configured": None,
        "note": f"{module.upper()} 由独立服务运行；本进程不读取其环境变量。",
    }


def _is_ai_binding(row: dict) -> bool:
    label = str(row.get("label") or "").lower()
    return any(marker in label for marker in AI_BINDING_MARKERS)


def _empty_calls(window: dict, state: str) -> dict:
    available = state == "available"
    return {
        "state": state,
        "source": "api_usage_events",
        "window": window,
        "total": 0 if available else None,
        "failed": 0 if available else None,
        "unknown": 0 if available else None,
        "pending": 0 if available else None,
        "unpriced": 0 if available else None,
        "known_amount": "0" if available else None,
        "estimated_amount": "0" if available else None,
        "currency": "CNY",
        "attribution": {
            "tenant_attributed": 0 if available else None,
            "user_attributed": 0 if available else None,
            "scope_attributed": 0 if available else None,
        },
        "features": [],
        "observed_providers": [],
    }


def _calls(row: dict, window: dict) -> dict:
    total = int(row.get("total") or 0)
    unpriced = int(row.get("unpriced") or 0)
    known = _amount(row.get("known_amount"))
    return {
        "state": "available",
        "source": "api_usage_events",
        "window": window,
        "total": total,
        "failed": int(row.get("failed") or 0),
        "unknown": int(row.get("unknown") or 0),
        "pending": int(row.get("pending") or 0),
        "unpriced": unpriced,
        "known_amount": known,
        # A known subtotal is not represented as the total when any event has
        # no price or complete usage.
        "estimated_amount": known if unpriced == 0 else None,
        "currency": "CNY",
        "attribution": {
            "tenant_attributed": int(row.get("tenant_attributed") or 0),
            "user_attributed": int(row.get("user_attributed") or 0),
            "scope_attributed": int(row.get("scope_attributed") or 0),
        },
        "features": [],
        "observed_providers": [],
    }


def _breakdown(row: dict) -> dict:
    total = int(row.get("total") or 0)
    unpriced = int(row.get("unpriced") or 0)
    known = _amount(row.get("known_amount"))
    return {
        "total": total,
        "failed": int(row.get("failed") or 0),
        "unknown": int(row.get("unknown") or 0),
        "pending": int(row.get("pending") or 0),
        "unpriced": unpriced,
        "known_amount": known,
        "estimated_amount": known if unpriced == 0 else None,
    }


async def _table_exists(session, name: str) -> bool:
    return bool(await session.scalar(text(
        "SELECT to_regclass(current_schema() || :name) IS NOT NULL"
    ), {"name": "." + name}))


async def _ledger(session, start: datetime, end: datetime) -> tuple[dict, list[dict], list[dict]]:
    metrics = """count(*) AS total,
        count(*) FILTER (WHERE state='error') AS failed,
        count(*) FILTER (WHERE state='unknown') AS unknown,
        count(*) FILTER (WHERE state='requested') AS pending,
        count(*) FILTER (WHERE estimated_amount IS NULL) AS unpriced,
        count(*) FILTER (WHERE tenant_id IS NOT NULL) AS tenant_attributed,
        count(*) FILTER (WHERE user_id IS NOT NULL) AS user_attributed,
        count(*) FILTER (WHERE job_ref IS NOT NULL) AS scope_attributed,
        coalesce(sum(estimated_amount),0) AS known_amount"""
    params = {"start": start, "end": end, "modules": list(MODULES)}
    totals = [dict(row) for row in (await session.execute(text(f"""
        SELECT module,{metrics} FROM api_usage_events
        WHERE started_at>=:start AND started_at<:end AND module=ANY(:modules)
        GROUP BY module ORDER BY module
    """), params)).mappings()]
    providers = [dict(row) for row in (await session.execute(text(f"""
        SELECT module,provider,model,{metrics} FROM api_usage_events
        WHERE started_at>=:start AND started_at<:end AND module=ANY(:modules)
        GROUP BY module,provider,model ORDER BY module,provider,model
    """), params)).mappings()]
    features = [dict(row) for row in (await session.execute(text(f"""
        SELECT module,operation,{metrics} FROM api_usage_events
        WHERE started_at>=:start AND started_at<:end AND module=ANY(:modules)
        GROUP BY module,operation ORDER BY module,operation
    """), params)).mappings()]
    return {row["module"]: row for row in totals}, providers, features


async def _control_state(session) -> dict:
    settings_ready = await _table_exists(session, "api_control_settings")
    bindings_ready = await _table_exists(session, "api_control_bindings")
    audit_ready = await _table_exists(session, "api_control_audit")
    credentials_ready = await _table_exists(session, "api_control_credentials")
    reservation_ready = bool(await session.scalar(text("""SELECT EXISTS(
        SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema()
            AND table_name='api_usage_events' AND column_name='reserved_amount')""")))
    schema_ready = settings_ready and bindings_ready and audit_ready and credentials_ready and reservation_ready
    enabled = api_controls.enabled()
    result = {
        "schema": "ready" if schema_ready else "schema_pending",
        "enabled": bool(enabled and schema_ready),
        "editing": "enabled" if enabled and schema_ready else "disabled",
        "source": "api_control_settings",
        "global_budget": None,
        "provider_policies": {},
        "bindings": [],
        "incident_handling": {
            "state": "schema_pending" if not audit_ready else "available",
            "source": "api_control_audit",
            "resolved": None if not audit_ready else 0,
            "in_progress": None if not audit_ready else 0,
            "open": None if not audit_ready else 0,
        },
    }
    if settings_ready:
        rows = [dict(row) for row in (await session.execute(text("""
            SELECT key,kind,value,revision FROM api_control_settings
            WHERE key='budget:global' OR kind='provider' ORDER BY key
        """))).mappings()]
        for row in rows:
            if row["key"] == "budget:global":
                result["global_budget"] = {
                    "value": _safe_budget(row["value"]), "revision": row["revision"]
                }
            elif row["kind"] == "provider":
                result["provider_policies"][row["key"].removeprefix("provider:")] = {
                    "enabled": row["value"].get("enabled") if isinstance(row["value"], dict) else None,
                    "revision": row["revision"],
                }
    if bindings_ready:
        result["bindings"] = [dict(row) for row in (await session.execute(text("""
            SELECT module,label,host,model,configured,seen_at FROM api_control_bindings
            WHERE module=ANY(:modules) ORDER BY module,label
        """), {"modules": list(MODULES)})).mappings()]
    if audit_ready:
        rows = [dict(row) for row in (await session.execute(text("""
            SELECT DISTINCT ON (resource) resource,after_value FROM api_control_audit
            WHERE resource LIKE 'alert:%' AND action=ANY(:actions)
            ORDER BY resource,(after_value->>'revision')::bigint DESC,created_at DESC,id DESC
        """), {"actions": ["alert.claim", "alert.resolve", "alert.reopen"]})).mappings()]
        counts = {"resolved": 0, "in_progress": 0, "open": 0}
        for row in rows:
            status = row["after_value"].get("status") if isinstance(row["after_value"], dict) else None
            if status in counts:
                counts[status] += 1
        result["incident_handling"].update(counts)
    return result


def _limits(module: str, controls: dict, hosts: set[str]) -> list[dict]:
    limits = [{
        "kind": "calls",
        "key": "module_autonomous",
        "scope": module,
        "state": "unavailable",
        "value": None,
        "source": "module_runtime_not_shared" if module != "sem" else "not_configured",
    }]
    budget = controls["global_budget"]
    if controls["schema"] == "schema_pending":
        limits.append({
            "kind": "budget", "key": "global", "scope": "global",
            "state": "schema_pending", "value": None, "source": "api_control_settings",
        })
    elif budget is None or not controls["enabled"]:
        limits.append({
            "kind": "budget", "key": "global", "scope": "global",
            "state": "disabled", "value": None, "source": "api_control_settings",
        })
    else:
        values = budget["value"] or {}
        for field in ("daily_calls", "monthly_calls", "daily_cny", "monthly_cny", "max_concurrent"):
            if values.get(field) is None:
                continue
            limits.append({
                "kind": "concurrency" if field == 'max_concurrent' else "calls" if field.endswith("calls") else "budget",
                "key": "global." + field, "scope": "global", "state": "enabled",
                "value": values[field], "source": "api_control_settings",
            })
        if len(limits) == 1:
            limits.append({
                "kind": "budget", "key": "global", "scope": "global",
                "state": "disabled", "value": None, "source": "api_control_settings",
            })
    for host in sorted(hosts):
        policy = controls["provider_policies"].get(host)
        if controls["schema"] == "schema_pending":
            state, value = "schema_pending", None
        elif not controls["enabled"]:
            state, value = "disabled", None
        elif policy is None:
            state, value = "enabled", True
        else:
            value = policy["enabled"]
            state = "enabled" if value is True else "disabled" if value is False else "unavailable"
            if state == "unavailable":
                value = None
        limits.append({
            "kind": "scope", "key": "provider:" + host, "scope": host,
            "state": state, "value": value, "source": "api_control_settings",
        })
    # The SEM process flag and shared settings do not prove that a separately
    # deployed SEO/GEO worker implements and enables the same admission code.
    if module != 'sem' and controls['schema'] == 'ready':
        for limit in limits:
            if limit['source'] == 'api_control_settings':
                limit['state'] = 'runtime_unverified'
    return limits


async def read_ai_governance(session, *, now: datetime | None = None, settings=None) -> dict:
    runtime_settings = settings or get_server_settings()
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - timedelta(hours=WINDOW_HOURS)
    window = {"kind": "last_24_hours", "start": start.isoformat(), "end": end.isoformat()}
    metering_ready = await _table_exists(session, "api_usage_events")
    controls = await _control_state(session)

    totals: dict[str, dict] = {}
    providers: list[dict] = []
    features: list[dict] = []
    if metering_ready:
        totals, providers, features = await _ledger(session, start, end)

    binding_by_module: dict[str, list[dict]] = {module: [] for module in MODULES}
    for row in controls["bindings"]:
        if row["module"] in binding_by_module and _is_ai_binding(row):
            binding_by_module[row["module"]].append(row)
    provider_by_module: dict[str, list[dict]] = {module: [] for module in MODULES}
    for row in providers:
        if row["module"] in provider_by_module:
            provider_by_module[row["module"]].append(row)
    feature_by_module: dict[str, list[dict]] = {module: [] for module in MODULES}
    for row in features:
        if row["module"] in feature_by_module:
            feature_by_module[row["module"]].append(row)

    modules = []
    for module in MODULES:
        configuration = _runtime_sem_configuration(runtime_settings) if module == "sem" else _unknown_configuration(module)
        bindings = binding_by_module[module]
        if bindings:
            configured = [row for row in bindings if row["configured"]]
            primary = configured[0] if configured else bindings[0]
            configuration = {
                "state": "available", "source": "api_control_bindings",
                "provider": primary["host"] or None, "model": primary["model"],
                "configured": bool(configured), "seen_at": primary["seen_at"],
            }
        calls = _calls(totals[module], window) if module in totals else _empty_calls(
            window, "available" if metering_ready else "schema_pending"
        )
        calls["observed_providers"] = [
            {"provider": row["provider"], "model": row["model"], **_breakdown(row)}
            for row in provider_by_module[module]
        ]
        calls["features"] = [
            {"feature": row["operation"], **_breakdown(row)}
            for row in feature_by_module[module]
        ]
        hosts = {row["provider"] for row in provider_by_module[module] if row.get("provider")}
        if configuration.get("provider"):
            hosts.add(configuration["provider"])
        metering_state = "schema_pending"
        if metering_ready:
            if module == "sem":
                metering_state = "recording" if api_metering.enabled() else "schema_ready"
            else:
                metering_state = "observed" if module in totals else "available_no_recent_events"
        modules.append({
            "module": module,
            "provider": configuration.get("provider"),
            "model": configuration.get("model"),
            "configured": configuration.get("configured"),
            "configuration": configuration,
            "metering": {
                "state": metering_state, "source": "api_usage_events",
                "runtime_enabled": api_metering.enabled() if module == "sem" else None,
            },
            "limits": _limits(module, controls, hosts),
            "controls": {
                "schema": controls['schema'],
                "runtime_enabled": controls['enabled'] if module == 'sem' else None,
                "state": 'schema_pending' if controls['schema'] == 'schema_pending'
                    else ('enabled' if controls['enabled'] else 'disabled') if module == 'sem' else 'runtime_unverified',
            },
            "calls": calls,
        })

    return {
        "schema": 1,
        "state": "available" if metering_ready else "schema_pending",
        "generated_at": end.isoformat(),
        "observation_window": window,
        "modules": modules,
        "controls": {
            "schema": controls["schema"], "enabled": controls["enabled"],
            "editing": controls["editing"],
            "note": "控制结构未经人工审核或未启用时仅提供只读计量，不开放编辑。",
        },
        "capabilities": {
            "ai_proposal": {"enabled": None, "status": "module_owned_human_review_required"},
            "human_review": {"required": True, "status": "required"},
            "website_execution": {"enabled": False, "status": "reserved"},
            "sem_funds_execution": {
                # Turning dry-run off is only one of several existing gates;
                # never claim live execution without an account/scope decision.
                "enabled": False if bool(getattr(runtime_settings, "baidu_write_dry_run", True)) else None,
                "status": "dry_run" if bool(getattr(runtime_settings, "baidu_write_dry_run", True))
                else "conditional_account_policy",
            },
        },
        "incidents": controls["incident_handling"],
        "ledger": {
            "details_endpoint": "/api/v1/admin/console/usage",
            "dimensions": ["tenant_id", "user_id", "module", "feature", "scope_ref", "provider", "model"],
            "field_mapping": {"feature": "operation", "scope_ref": "job_ref"},
            "access": "superadmin_only",
        },
        "coverage": {
            "metering": "仅统计 api_usage_events 已接入的真实外部请求；无记录不代表没有业务任务。",
            "configuration": "SEM 读取当前进程脱敏配置；SEO/GEO 仅使用其已登记 binding，未登记时不跨进程或跨库推断。",
            "cost": "未定价、用量缺失、失败及 unknown 保留未知；known_amount 只是已知小计。",
            "tasks": "本接口不跨库汇总 SEO/GEO 任务，也不创建虚假任务。",
        },
    }
