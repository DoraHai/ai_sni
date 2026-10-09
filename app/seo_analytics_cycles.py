"""Restart-safe analytics collection using the site's existing durable settings.

Claims commit before provider I/O. Only a current claim, configuration and
entitlement may persist its result; a paused or revoked site discards it.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.database import async_session_factory
from app.models.module_workspace import SeoSite
from app.models.seo import SeoSiteAdvisorAssignment
from app.models.seo_site_analytics import SeoSiteAnalyticsMonthly, SeoSiteAnalyticsSource
from app.models.user import User
from app.models.role import Role
from app.module_scope import seo_site_is_operational
from app.seo_content_workflow import plan_for, utc
from app.seo_service_plan import service_plan_is_paused
from app.seo_site_analytics import AnalyticsError, ProviderClient, fetch_provider, validate_month

logger = logging.getLogger(__name__)
AUTH_ERRORS = {"baidu_auth_missing", "baidu_auth_expired", "baidu_invalid_client", "baidu_auth_failed",
               "baidu_site_forbidden", "baidu_site_missing", "ga4_auth_missing", "ga4_token_failed",
               "ga4_forbidden", "ga4_not_found", "invalid_credentials"}
LEASE_SECONDS = 600
MAX_ATTEMPTS = 3


def configuration_version(source):
    material = json.dumps([source.config, source.secret_ciphertext, source.updated_by], sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()


def cycle_enabled(site):
    plan = plan_for(site)
    return bool(plan.get("revision") and not service_plan_is_paused(site)
                and (plan.get("analytics_cycle_enabled") is True or plan.get("report_cycle_enabled") is True))


def due(cursor, version, now):
    if cursor.get("state") == "running" and utc(datetime.fromisoformat(cursor["lease_until"])) > now:
        return False
    if cursor.get("configuration_version") != version:
        return True
    if cursor.get("state") in {"authorization_required", "needs_attention", "complete"}:
        return False
    return not cursor.get("next_due_at") or utc(datetime.fromisoformat(cursor["next_due_at"])) <= now


async def eligible(session, site):
    return (site is not None and cycle_enabled(site)
            and await seo_site_is_operational(session, site.tenant_id, site.id)
            and await session.scalar(select(SeoSiteAdvisorAssignment.id).join(User,
                User.id == SeoSiteAdvisorAssignment.advisor_user_id).join(Role, Role.id == User.role_id).where(
                SeoSiteAdvisorAssignment.tenant_id == site.tenant_id,
                SeoSiteAdvisorAssignment.site_id == site.id,
                SeoSiteAdvisorAssignment.active.is_(True), User.is_active.is_(True),
                User.tenant_id.is_(None) | (User.tenant_id == site.tenant_id),
                Role.permissions["seo.site"].as_string() == "edit", Role.permissions["seo.content"].as_string() == "edit"
                ).limit(1)) is not None)


def public_cycles(site):
    """No credentials, claim tokens or configuration fingerprints in read APIs."""
    allowed = {"source", "month", "state", "attempts", "last_run_attempts", "last_attempt_at", "next_due_at", "error_code", "fetched_at"}
    return [{key: value for key, value in cursor.items() if key in allowed}
            for cursor in ((site.site_settings or {}).get("seo_analytics_cycles") or {}).values()]


async def collect_site_analytics(site_id, *, provider=None, now=None, session_factory=None):
    session_factory = session_factory or async_session_factory
    now = now or datetime.now(timezone.utc)
    tz = timezone(timedelta(hours=8))
    current = now.astimezone(tz).strftime("%Y-%m")
    previous = (now.astimezone(tz).replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    async with session_factory() as session:
        site = await session.get(SeoSite, site_id, with_for_update=True)
        if site is None or not cycle_enabled(site):
            return
        sources = list(await session.scalars(select(SeoSiteAnalyticsSource).where(
            SeoSiteAnalyticsSource.tenant_id == site.tenant_id, SeoSiteAnalyticsSource.site_id == site_id,
            SeoSiteAnalyticsSource.enabled.is_(True)).order_by(SeoSiteAnalyticsSource.id)))
        if not sources or not await eligible(session, site):
            return
        settings = dict(site.site_settings or {})
        cycles = dict(settings.get("seo_analytics_cycles") or {})
        # One external request per site/tick, regardless of process count.
        if any(c.get("state") == "running" and utc(datetime.fromisoformat(c["lease_until"])) > now
               for c in cycles.values()):
            return
        choice = None
        for month in (previous, current):
            for source in sources:
                key = f"{source.source}:{month}"
                cursor = cycles.get(key) or {}
                version = configuration_version(source)
                if any(c.get("source") == source.source and c.get("state") == "authorization_required"
                       and c.get("configuration_version") == version for c in cycles.values()):
                    continue
                if due(cursor, version, now):
                    choice = (key, month, source, cursor, version)
                    break
            if choice:
                break
        if choice is None:
            return
        key, month, source, cursor, version = choice
        cycles = {k: c for k, c in cycles.items() if c.get("source") != source.source
                  or c.get("configuration_version") == version}
        if cursor.get("configuration_version") == version and int(cursor.get("attempts") or 0) >= MAX_ATTEMPTS:
            cycles[key] = {**cursor, "state": "needs_attention", "error_code": "collection_attempts_exhausted"}
            cycles[key].pop("token", None)
            cycles[key].pop("lease_until", None)
            settings["seo_analytics_cycles"] = cycles
            site.site_settings = settings
            await session.commit()
            return
        token = str(uuid4())
        revision, tenant_id, source_id = plan_for(site)["revision"], site.tenant_id, source.id
        attempts = int(cursor.get("attempts") or 0) if cursor.get("configuration_version") == version else 0
        cycles[key] = {"source": source.source, "month": month, "state": "running", "token": token,
            "configuration_version": version, "attempts": attempts + 1,
            "last_attempt_at": now.isoformat(), "lease_until": (now + timedelta(seconds=LEASE_SECONDS)).isoformat()}
        # Bound retained state to the current and preceding reporting month.
        settings["seo_analytics_cycles"] = {k: v for k, v in cycles.items() if v.get("month") in {previous, current}}
        site.site_settings = settings
        await session.commit()
        # Source is detached after this block; refresh credentials stay local until validation.

    start, end, partial = validate_month(month, now)
    failure, values = None, None
    try:
        if provider is None:
            async with httpx.AsyncClient(timeout=30) as http:
                values = await fetch_provider(ProviderClient(http), source, start, end)
        else:
            values = await fetch_provider(provider, source, start, end)
    except AnalyticsError as exc:
        failure = exc.code
    except Exception:
        # Supplier exception text can contain URLs, tokens or customer data.
        failure = "provider_error"

    async with session_factory() as session:
        site = await session.get(SeoSite, site_id, with_for_update=True)
        if site is None:
            return
        settings = dict(site.site_settings or {})
        cycles = dict(settings.get("seo_analytics_cycles") or {})
        cursor = cycles.get(key) or {}
        if cursor.get("token") != token or cursor.get("state") != "running":
            return
        configured = await session.get(SeoSiteAnalyticsSource, source_id, with_for_update=True)
        valid = (await eligible(session, site) and plan_for(site).get("revision") == revision
                 and configured is not None and configured.tenant_id == tenant_id
                 and configured.site_id == site_id and configured.enabled
                 and configuration_version(configured) == version)
        if not valid:
            cursor = {**cursor, "state": "discarded", "error_code": "scope_or_configuration_changed",
                      "next_due_at": now.isoformat()}
        else:
            row = await session.scalar(select(SeoSiteAnalyticsMonthly).where(
                SeoSiteAnalyticsMonthly.tenant_id == tenant_id, SeoSiteAnalyticsMonthly.site_id == site_id,
                SeoSiteAnalyticsMonthly.source == configured.source, SeoSiteAnalyticsMonthly.month == month).with_for_update())
            if row is None:
                row = SeoSiteAnalyticsMonthly(tenant_id=tenant_id, site_id=site_id, source=configured.source,
                    month=month, status="failed", raw_meta={})
                session.add(row)
            row.last_attempt_at = now
            if failure:
                row.last_error_code, row.last_error_message = failure, "周期取数失败，请检查数据源或重试"
                if row.status != "ok":
                    row.status, row.error_code, row.error_message = "failed", failure, row.last_error_message
                cursor = {**cursor, "state": "authorization_required" if failure in AUTH_ERRORS else
                          "needs_attention" if cursor["attempts"] >= MAX_ATTEMPTS else "retry_wait",
                          "error_code": failure, "next_due_at": (now + timedelta(minutes=15 * 2**(cursor["attempts"]-1))).isoformat()}
            else:
                uv, pv, meta = values
                row.uv, row.pv, row.status = uv, pv, "ok" if uv is not None or pv is not None else "no_data"
                row.fetched_at, row.fetched_by = now, None
                row.error_code = row.error_message = row.last_error_code = row.last_error_message = None
                row.raw_meta = {**meta, "partial": partial, "start_date": start, "end_date": end, "trigger": "service_cycle"}
                configured.secret_ciphertext, configured.token_expires_at = source.secret_ciphertext, source.token_expires_at
                cursor = {**cursor, "state": "refresh_wait" if partial else "complete", "attempts": 0,
                          "last_run_attempts": cursor["attempts"],
                          "error_code": None, "fetched_at": now.isoformat(),
                          "configuration_version": configuration_version(configured),
                          "next_due_at": (now + timedelta(hours=24)).isoformat()}
        cursor.pop("token", None)
        cursor.pop("lease_until", None)
        cycles[key] = cursor
        settings["seo_analytics_cycles"] = cycles
        site.site_settings = settings
        await session.commit()
