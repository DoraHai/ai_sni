"""Read-only public-page checks; bounded history, no publishing or metric completion."""
import asyncio
import hashlib
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import String, cast, func, select

from app.geo.audit import GeoAuditError, safe_fetch
from app.geo.publication_evidence import match_publication
from app.geo.verify import append_evidence
from app.models import GeoActionTicket, GeoChannelVariant, GeoContentTask, GeoPublication
from app.geo.tenant16_demo import DEMO_TENANT_ID

PREFIX = 'monitor:v1:'


def fingerprint(variant):
    return hashlib.sha256((str(variant.article_version_id) + '\n' + variant.title + '\n' + variant.body_markdown).encode()).hexdigest()


def initial_state(variant):
    return {'state': 'pending', 'expected_fingerprint': fingerprint(variant),
            'article_id': variant.article_version_id, 'failures': 0, 'history': []}


def state_for(variant, pub):
    return dict(((variant.adapt_meta or {}).get('publication_monitor') or {}).get(str(pub.id)) or {})


def store_state(variant, pub, state):
    meta = dict(variant.adapt_meta or {})
    entries = dict(meta.get('publication_monitor') or {})
    entries[str(pub.id)] = state
    variant.adapt_meta = {**meta, 'publication_monitor': entries}


def outcome(previous, state, now, **evidence):
    failures = 0 if state == 'healthy' else int(previous.get('failures') or 0) + 1
    stamp = now.isoformat() + 'Z'
    clean = {k: v for k, v in previous.items() if k not in {'expected_sha256', 'observed_sha256', 'observed_url', 'matched_passages', 'total_passages', 'last_error'}}
    return {**clean, **evidence, 'state': state, 'checked_at': stamp, 'failures': failures,
            'next_check_at': (now + timedelta(hours=24 if state == 'healthy' else 1)).isoformat() + 'Z',
            'history': [*(previous.get('history') or []), {'at': stamp, 'state': state}][-30:]}


async def follow_up(session, content, pub, state):
    code = PREFIX + str(pub.id)
    row = await session.scalar(select(GeoActionTicket).where(
        GeoActionTicket.tenant_id == content.tenant_id, GeoActionTicket.advice_code == code).with_for_update())
    # One failed fetch is unknown availability, not proof that the page was removed.
    actionable = state['state'] != 'healthy' and state['failures'] >= 2
    if row is None and not actionable:
        return
    if row is None:
        row = GeoActionTicket(tenant_id=content.tenant_id, content_task_id=content.id,
            advice_code=code, title=f'复查发布页 #{pub.id}', priority='high', status='todo',
            action=f'打开发布渠道核对页面：{pub.published_url}。确认内容、访问权限和网址后，在分发页重新检查。',
            acceptance_type='auto', acceptance_check='publication.monitor',
            acceptance_desc='实际重新抓取匹配登记版本的正文后，自动关闭异常工单；不代表 AI 可见度提升。')
        session.add(row)
    row.progress = {**(row.progress or {}), 'publication_monitor': state, 'publication_id': pub.id}
    row.last_verify_at = datetime.utcnow()
    row.last_note = {'healthy': '发布页正文匹配，异常已恢复', 'unreachable': '抓取失败，尚不能判断页面是否下线',
                     'mismatch': '抓回的正文未匹配登记稿件', 'version_changed': '稿件已变化，需确认原发布版本或登记新版发布'}[state['state']]
    row.last_verdict = 'pass' if state['state'] == 'healthy' else 'fail'
    if state['state'] == 'healthy':
        row.status, row.closed_at = 'done', row.closed_at or datetime.utcnow()
    elif row.status == 'done' and actionable:
        row.status, row.closed_at = 'reopened', None
    elif row.status == 'done':
        row.last_verdict = 'pending'
        row.last_note += '；单次异常待复查，尚未重新打开工单'
    row.evidence = append_evidence(row.evidence, check='publication.monitor', result=state['state'], note=row.last_note, limit=30)


async def check_publication(session, tenant_id, task_id, publication_id, *, scheduled=False):
    if scheduled:
        from app.geo.tenant_scope import ensure_geo_background_execution_allowed, ensure_geo_entitlement

        # Scheduled monitoring is customer business processing. Existing audit
        # records remain stored, but an expired tenant must not start a new fetch.
        ensure_geo_background_execution_allowed(tenant_id)
        await ensure_geo_entitlement(session, tenant_id)
    # Same lock order as publishing: content first, then variant. A transaction holds
    # ownership through the bounded fetch; a crash rolls it back without a stuck lease.
    content = await session.scalar(select(GeoContentTask).where(
        GeoContentTask.id == task_id, GeoContentTask.tenant_id == tenant_id,
        GeoContentTask.status.notin_(['archived', 'cancelled'])).with_for_update(skip_locked=scheduled))
    if content is None:
        if scheduled:
            return None
        raise HTTPException(404, '内容任务不存在')
    result = (await session.execute(select(GeoPublication, GeoChannelVariant).join(
        GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).where(
        GeoPublication.id == publication_id, GeoChannelVariant.task_id == task_id,
        GeoPublication.status == 'published', GeoPublication.published_url.is_not(None))
        .with_for_update(of=[GeoPublication, GeoChannelVariant]).execution_options(populate_existing=True))).first()
    if not result:
        raise HTTPException(404, '真实发布记录不存在')
    pub, variant = result
    old = state_for(variant, pub)
    now = datetime.utcnow()
    due = old.get('next_check_at') if scheduled else old.get('checked_at')
    if due:
        threshold = datetime.fromisoformat(due.rstrip('Z'))
        if not scheduled:
            threshold += timedelta(minutes=5)
        if threshold > now:
            return old
    if not old:
        # Legacy entries are compared with the current stored variant, not claimed
        # to have a historical publishing fingerprint that was never recorded.
        old = {**initial_state(variant), 'baseline_source': 'first_monitor_current_variant'}
    proof = {}
    if old.get('expected_fingerprint') != fingerprint(variant):
        state = 'version_changed'
    else:
        try:
            document = await asyncio.wait_for(safe_fetch(pub.published_url), timeout=25)
            if scheduled:
                # Discard an in-flight observation if access expired during fetch;
                # it must not become a verified success or open a follow-up ticket.
                await ensure_geo_entitlement(session, tenant_id)
            proof = match_publication(variant.title, variant.body_markdown, document.html)
            proof['observed_url'] = document.final_url
            state = 'healthy'
        except (GeoAuditError, TimeoutError):
            state = 'unreachable'
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            state = 'mismatch'
    fresh = outcome(old, state, now, checked_url=pub.published_url, **proof)
    if scheduled:
        await ensure_geo_entitlement(session, tenant_id)
    store_state(variant, pub, fresh)
    await follow_up(session, content, pub, fresh)
    await session.commit()
    return fresh


async def check_publication_controlled(session, tenant_id: int, project_id: int,
                                       automation_token: dict):
    """Run one admitted public-page observation for an exact typed target."""
    from app import automation_project_v2 as automation_v2
    from app import automation_projects as automation_core
    from app.automation_project_contract import ConfigurationV2
    from app.geo.automation_v2_adapter import validate_configuration
    from app.geo.tenant_scope import (ensure_geo_background_execution_allowed,
                                      ensure_geo_entitlement)

    ensure_geo_background_execution_allowed(tenant_id)

    async def validate_current():
        _, run, _ = await automation_core.check_step(session, automation_token)
        await validate_configuration(
            session, tenant_id, project_id,
            ConfigurationV2.model_validate(run["configuration"]),
            int(automation_token["owner_user_id"]),
            current_targets=[automation_token["target"]],
        )

    await validate_current()
    await ensure_geo_entitlement(session, tenant_id)
    publication_id = int(automation_token["target"]["object_id"])
    identity = (await session.execute(select(
        GeoContentTask.id, GeoPublication.published_url
    ).join(GeoChannelVariant, GeoChannelVariant.task_id == GeoContentTask.id)
     .join(GeoPublication, GeoPublication.variant_id == GeoChannelVariant.id)
     .where(GeoContentTask.tenant_id == tenant_id,
            GeoContentTask.status.notin_(["archived", "cancelled"]),
            GeoPublication.id == publication_id,
            GeoPublication.status == "published",
            GeoPublication.published_url.is_not(None)))).first()
    if identity is None:
        raise automation_core.problem("automation_target_changed", "发布记录已变化，请刷新")
    task_id, published_url = int(identity.id), str(identity.published_url)
    class RequestGate:
        def __init__(self):
            self.admitted = None
            self.finished = set()

        async def before(self, _url, hop):
            await validate_current()
            await ensure_geo_entitlement(session, tenant_id)
            call_key = f"publication_{publication_id}:hop_{hop + 1}"
            if not await automation_v2.begin_call(
                    session, automation_token, call_key, kind="http"):
                raise automation_core.problem(
                    "automation_dispatch_replay", "发布页请求已准入过，禁止重复发送"
                )
            self.admitted = hop
            await session.commit()

        async def after(self, hop, state):
            call_key = f"publication_{publication_id}:hop_{hop + 1}"
            await automation_v2.finish_call(
                session, automation_token, call_key, state=state,
                fee_state="not_called",
                evidence_refs=(f"geo_publication:{publication_id}",),
            )
            self.finished.add(hop)
            await session.commit()

        async def abort(self):
            if self.admitted is not None and self.admitted not in self.finished:
                await self.after(self.admitted, "unknown")

    proof = {}
    gate = RequestGate()
    try:
        document = await asyncio.wait_for(
            safe_fetch(published_url, request_gate=gate), timeout=25
        )
        fetched = True
    except (GeoAuditError, TimeoutError):
        await gate.abort()
        document, fetched = None, False

    # Admission released locks before network I/O. Reacquire the current
    # generation and business rows, then validate the exact target again.
    await validate_current()
    await ensure_geo_entitlement(session, tenant_id)
    content = await session.scalar(select(GeoContentTask).where(
        GeoContentTask.id == task_id, GeoContentTask.tenant_id == tenant_id,
        GeoContentTask.status.notin_(["archived", "cancelled"])).with_for_update())
    result = (await session.execute(select(GeoPublication, GeoChannelVariant).join(
        GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).where(
        GeoPublication.id == publication_id, GeoChannelVariant.task_id == task_id,
        GeoPublication.status == "published", GeoPublication.published_url == published_url)
        .with_for_update(of=[GeoPublication, GeoChannelVariant])
        .execution_options(populate_existing=True))).first()
    if content is None or result is None:
        raise automation_core.problem("automation_target_changed", "发布记录已变化，请刷新")
    pub, variant = result
    await validate_current()
    old = state_for(variant, pub) or {
        **initial_state(variant), "baseline_source": "first_monitor_current_variant"
    }
    now = datetime.utcnow()
    if old.get("expected_fingerprint") != fingerprint(variant):
        state = "version_changed"
    elif not fetched:
        state = "unreachable"
    else:
        try:
            proof = match_publication(variant.title, variant.body_markdown, document.html)
            proof["observed_url"] = document.final_url
            state = "healthy"
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            state = "mismatch"
    fresh = outcome(old, state, now, checked_url=published_url, **proof)
    await ensure_geo_entitlement(session, tenant_id)
    store_state(variant, pub, fresh)
    await follow_up(session, content, pub, fresh)
    await session.commit()
    return fresh


def report_check(variant, pub, latest_article_id):
    """Project actual page observations without inferring citation accuracy."""
    state = state_for(variant, pub)
    current = (state.get('expected_fingerprint') == fingerprint(variant)
               and variant.article_version_id == latest_article_id
               and state.get('checked_url') == pub.published_url)
    verified = bool(current and state.get('state') == 'healthy'
                    and state.get('observed_sha256') and state.get('expected_sha256'))
    return {'state': state.get('state', 'pending') if current else 'unverified',
            'verified': verified, 'checked_at': state.get('checked_at'),
            'article_id': variant.article_version_id, 'observed_url': state.get('observed_url'),
            'expected_sha256': state.get('expected_sha256') if verified else None,
            'observed_sha256': state.get('observed_sha256') if verified else None,
            'citation_accuracy': 'not_evaluated'}


async def list_monitor(session, tenant_id, task_id):
    exists = await session.scalar(select(GeoContentTask.status).where(
        GeoContentTask.id == task_id, GeoContentTask.tenant_id == tenant_id))
    if exists is None:
        raise HTTPException(404, '内容任务不存在')
    rows = (await session.execute(select(GeoPublication, GeoChannelVariant).join(
        GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).where(
        GeoChannelVariant.task_id == task_id, GeoPublication.status == 'published')
        .order_by(GeoPublication.id.desc()).limit(100))).all()
    return {'monitoring_active': exists not in {'archived', 'cancelled'}, 'items': [{'publication_id': p.id, 'url': p.published_url, 'channel': p.channel,
                       **(state_for(v, p) or {'state': 'pending'}),
                       'can_check': bool(p.published_url) and exists not in {'archived', 'cancelled'}} for p, v in rows]}


async def run_monitor_batch():
    from app.database import async_session_factory
    from app.geo.tenant_scope import GeoEntitlementUnavailable
    import logging
    now = datetime.utcnow().isoformat() + 'Z'
    entry = GeoChannelVariant.adapt_meta['publication_monitor'][cast(GeoPublication.id, String)]
    due = func.coalesce(entry['next_check_at'].astext, '')
    async with async_session_factory() as session:
        rows = (await session.execute(select(GeoContentTask.tenant_id, GeoContentTask.id, GeoPublication.id)
            .join(GeoChannelVariant, GeoChannelVariant.task_id == GeoContentTask.id)
            .join(GeoPublication, GeoPublication.variant_id == GeoChannelVariant.id)
            .where(GeoContentTask.tenant_id != DEMO_TENANT_ID,
                   GeoContentTask.status.notin_(['archived', 'cancelled']), GeoPublication.status == 'published',
                   GeoPublication.published_url.is_not(None), due <= now)
            .order_by(due, GeoPublication.id).limit(25))).all()
    for tenant_id, task_id, publication_id in rows:
        try:
            async with async_session_factory() as session:
                from app.geo.automation_v2_adapter import (PUBLICATION_OPERATION,
                                                            owned_target_ids)
                if int(publication_id) in await owned_target_ids(
                        session, int(tenant_id), PUBLICATION_OPERATION, "publication"):
                    continue
                await check_publication(session, tenant_id, task_id, publication_id, scheduled=True)
        except GeoEntitlementUnavailable:
            # Expiry is an intentional stop, not a monitor failure. Do not write
            # backoff/error state for a customer whose GEO access is unavailable.
            continue
        except Exception as exc:
            from app.geo.scheduler import record_followup_failure

            record_followup_failure('geo_publication_monitor', exc)
            logging.getLogger(__name__).exception('GEO publication monitor failed for record %s', publication_id)
            try:
                async with async_session_factory() as session:
                    await defer_monitor_failure(session, tenant_id, task_id, publication_id)
            except GeoEntitlementUnavailable:
                pass
            except Exception as exc:
                from app.geo.scheduler import record_followup_failure

                record_followup_failure('geo_publication_monitor', exc)
                logging.getLogger(__name__).exception('Could not defer GEO publication %s', publication_id)


async def defer_monitor_failure(session, tenant_id, task_id, publication_id):
    from app.geo.tenant_scope import ensure_geo_entitlement

    await ensure_geo_entitlement(session, tenant_id)
    content = await session.scalar(select(GeoContentTask).where(
        GeoContentTask.id == task_id, GeoContentTask.tenant_id == tenant_id,
        GeoContentTask.status.notin_(['archived', 'cancelled'])).with_for_update(skip_locked=True))
    if content is None:
        return
    result = (await session.execute(select(GeoPublication, GeoChannelVariant).join(
        GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).where(
        GeoPublication.id == publication_id, GeoChannelVariant.task_id == task_id,
        GeoPublication.status == 'published').with_for_update(of=[GeoPublication, GeoChannelVariant])
        .execution_options(populate_existing=True))).first()
    if not result:
        return
    pub, variant = result
    old = state_for(variant, pub) or {**initial_state(variant), 'baseline_source': 'first_monitor_current_variant'}
    now = datetime.utcnow()
    # Keep the last actual observation. A failed worker is not a failed public page.
    store_state(variant, pub, {**old, 'last_error': {'at': now.isoformat() + 'Z', 'kind': 'check_incomplete'},
                              'next_check_at': (now + timedelta(hours=1)).isoformat() + 'Z'})
    await ensure_geo_entitlement(session, tenant_id)
    await session.commit()
