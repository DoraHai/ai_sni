"""Landing page health rule for adgroup final URLs."""
import asyncio
import hashlib
import logging
import time
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Adgroup, Tenant
from app.module_scope import list_active_module_tenants
from app.rules.base import AlertDraft
from app.rules.engine import _upsert_entity_alerts, merge_duplicate_alerts
from app.security.public_http import fetch_public_url

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10
SLOW_THRESHOLD_MS = 3000
MAX_CONCURRENT_PROBES = 10


def _url_entity_ref(url: str) -> str:
    return f"url:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:24]}"


class SiteHealthRule:
    code = "R-SITE"
    priority = "P2"

    async def evaluate(
        self, session: AsyncSession, tenant: Tenant, target_date: date
    ) -> list[AlertDraft]:
        adgroups = (
            await session.scalars(
                select(Adgroup).where(
                    Adgroup.tenant_id == tenant.id,
                    Adgroup.pause.isnot(True),
                )
            )
        ).all()

        url_to_adgroups: dict[str, list[Adgroup]] = {}
        for adgroup in adgroups:
            for url in (adgroup.pc_final_url, adgroup.mobile_final_url):
                if url and url.startswith(("http://", "https://")):
                    url_to_adgroups.setdefault(url, []).append(adgroup)

        if not url_to_adgroups:
            return []

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROBES)

        async def probe(url: str) -> tuple[str, dict]:
            async with semaphore:
                try:
                    started = time.monotonic()
                    resp = await fetch_public_url(
                        url,
                        timeout=TIMEOUT_SECONDS,
                        max_response_bytes=0,
                        read_body=False,
                    )
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    return url, {
                        "ok": resp.status_code < 400,
                        "status_code": resp.status_code,
                        "elapsed_ms": elapsed_ms,
                        "error": None,
                        "url": url,
                    }
                except Exception as exc:  # noqa: BLE001 - one bad landing page must not abort the batch
                    return url, {
                        "ok": False,
                        "status_code": None,
                        "elapsed_ms": None,
                        "error": str(exc)[:200],
                        "url": url,
                    }

        results = await asyncio.gather(*(probe(url) for url in url_to_adgroups))
        drafts: list[AlertDraft] = []
        for url, result in results:
            adgroups_for_url = url_to_adgroups[url]
            adgroup_names = "、".join(
                a.adgroup_name or str(a.adgroup_id) for a in adgroups_for_url[:3]
            )
            if not result["ok"]:
                details = (
                    f"，错误：{result['error']}"
                    if result["error"]
                    else f"，状态码：{result['status_code']}"
                )
                drafts.append(
                    AlertDraft(
                        rule_code=self.code,
                        priority="P0",
                        title="落地页无法访问",
                        message=f"URL 无法打开：{url}（涉及单元：{adgroup_names}）{details}",
                        report_date=target_date,
                        entity_ref=_url_entity_ref(url),
                        metrics=result,
                    )
                )
            elif result["elapsed_ms"] and result["elapsed_ms"] > SLOW_THRESHOLD_MS:
                drafts.append(
                    AlertDraft(
                        rule_code=self.code,
                        priority=self.priority,
                        title="落地页响应时间过长",
                        message=(
                            f"URL 响应耗时 {result['elapsed_ms']}ms：{url}"
                            f"（涉及单元：{adgroup_names}）"
                        ),
                        report_date=target_date,
                        entity_ref=_url_entity_ref(url),
                        metrics=result,
                    )
                )
        return drafts


async def run_site_health_for_tenant(
    session: AsyncSession, tenant: Tenant, target_date: date
) -> int:
    drafts = await SiteHealthRule().evaluate(session, tenant, target_date)
    records = [
        {
            "tenant_id": tenant.id,
            "rule_code": d.rule_code,
            "priority": d.priority,
            "title": d.title,
            "message": d.message,
            "report_date": d.report_date,
            "keyword_id": d.keyword_id,
            "keyword": d.keyword,
            "campaign_id": d.campaign_id,
            "campaign_name": d.campaign_name,
            "entity_ref": d.entity_ref,
            "metrics": d.metrics,
        }
        for d in drafts
        if d.entity_ref
    ]
    await _upsert_entity_alerts(session, records)
    await session.commit()
    await merge_duplicate_alerts(session, tenant.id)
    return len(records)


async def run_site_health_for_all_tenants(
    session: AsyncSession, target_date: date
) -> dict[str, int]:
    tenants = await list_active_module_tenants(session, "sem")
    result: dict[str, int] = {}
    for tenant in tenants:
        try:
            result[tenant.name] = await run_site_health_for_tenant(session, tenant, target_date)
        except Exception:  # noqa: BLE001
            logger.exception("tenant %s site health rule failed", tenant.name)
            result[tenant.name] = -1
    return result
