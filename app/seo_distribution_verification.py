"""Recover durable verification intents; never publish or replay device events."""
from bs4 import BeautifulSoup
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.database import async_session_factory
from app.models.module_workspace import TenantModule
from app.models.seo_page_capture import SeoPageCapture
from app.seo_distribution_protocol import KEY, enabled, registry
from app import seo_distribution_report as report


def verification_result(body, capture):
    body_state = body.get('state')
    if body_state == 'not_observed':
        state, reason = 'failed', 'text_not_found'
    elif body_state != 'content_observed':
        state, reason = 'unavailable', body.get('reason', 'page_unavailable')
    elif capture != 'succeeded':
        state, reason = 'unavailable', 'capture_unavailable'
    else:
        state, reason = 'verified', 'full_body_and_capture_observed'
    return {'state': state, 'reason': reason, 'checkedAt': report.now_ms(),
            'body': {'state': body_state, 'reason': body.get('reason')},
            'capture': {'state': capture},
            'meaning': '公开页面正文及截图证据；不证明账号归属、平台审核结论或阅读量'}


async def current_snapshot(session, module, state, task):
    try:
        return await report.native_snapshot(session, module.tenant_id, task['site_id'], task['publication_id'], task=task)
    except HTTPException as exc:
        if exc.status_code not in {404, 409}:
            raise
        task['verification'] = {'state': 'version_changed', 'reason': 'source_or_review_changed', 'checkedAt': report.now_ms()}
        task['verify_claim_until'] = 0
        report.store(module, state)
        await session.commit()
        return None


async def verify_one(tenant_id, task_id):
    from app.api import seo as api
    from app.seo_backlinks import fetch_backlink_page, discover_backlinks
    from app.seo_qa import observe_answer
    async with async_session_factory() as session:
        settings = await session.scalar(select(TenantModule.module_settings).where(
            TenantModule.tenant_id == tenant_id, TenantModule.module_code == 'seo'))
        hint = registry(settings)['tasks'].get(task_id)
        if not hint:
            return
        await report.site_scope(session, tenant_id, hint['site_id'])
        module = await report.locked_module(session, tenant_id)
        state = registry(module.module_settings)
        task = state['tasks'].get(task_id)
        if not task or task['outcome'] != 'human-reported-published' or not enabled(state, task['site_id']):
            return
        device = state['devices'].get(task['target']['deviceId'])
        if not device or device['revoked']:
            return
        await report.live_task(session, module, device, task, success=False)
        current = await current_snapshot(session, module, state, task)
        if current is None:
            return
        row, content, snapshot, _ = current
        if row.page_url != task['page_url']:
            task['verification'] = {'state': 'version_changed', 'reason': 'publication_url_changed', 'checkedAt': report.now_ms()}
            report.store(module, state)
            await session.commit()
            return
        url, site_id, publication_id, expected_digest = row.page_url, task['site_id'], row.id, task['content_digest']
        body = BeautifulSoup(snapshot['body'], 'html.parser').get_text(' ', strip=True)
        # Persist a bounded claim before network I/O. A crashed process is
        # eligible again after five minutes; no database lock spans a fetch.
        if task.get('verify_claim_until', 0) > report.now_ms():
            return
        task['verify_claim_until'] = report.now_ms() + 300000
        report.store(module, state)
        await session.commit()
        background = BackgroundTasks()
        capture_info = await api._queue_published_page_verification(session, row, content, background)
        await background()
    fetched = await fetch_backlink_page(url)
    body_evidence = observe_answer(fetched, body, url)
    async with async_session_factory() as session:
        await report.site_scope(session, tenant_id, site_id)
        module = await report.locked_module(session, tenant_id)
        state = registry(module.module_settings)
        task = state['tasks'].get(task_id)
        if not task or not enabled(state, site_id) or task['content_digest'] != expected_digest:
            return
        device = state['devices'].get(task['target']['deviceId'])
        if not device or device['revoked']:
            return
        await report.live_task(session, module, device, task, success=False)
        current = await current_snapshot(session, module, state, task)
        if current is None:
            return
        row, _, _, _ = current
        if row.page_url != url:
            task['verification'] = {'state': 'version_changed', 'reason': 'publication_url_changed', 'checkedAt': report.now_ms()}
        else:
            capture = await session.get(SeoPageCapture, capture_info.get('capture_id')) if capture_info.get('capture_id') else None
            capture_state = (capture.status if capture and capture.tenant_id == tenant_id
                             and capture.site_id == site_id and capture.relation_type == 'publication'
                             and capture.relation_id == publication_id and capture.source_url == url
                             else capture_info.get('reason') or 'not_queued')
            task['verification'] = verification_result(body_evidence, capture_state)
            # Existing backlink discovery receives the same safely fetched page;
            # its native storage and scheduled follow-up remain unchanged.
            site = await report.site_scope(session, tenant_id, site_id)
            backlink = await discover_backlinks(session, tenant_id, site_id, url, site.canonical_domain, fetched_page=fetched)
            row.link_discovery = backlink
            task['verification']['backlinks'] = {'state': backlink.get('state'), 'found': backlink.get('found', 0)}
        task['verify_claim_until'] = 0
        report.store(module, state)
        await session.commit()


async def recover_report_verification():
    """Bounded retry from both post-commit work and the existing SEO scheduler."""
    async with async_session_factory() as session:
        rows = list((await session.execute(select(TenantModule.tenant_id, TenantModule.module_settings)
            .where(TenantModule.module_code == 'seo', TenantModule.module_settings.has_key(KEY))
            .order_by(TenantModule.id))).all())
    pending = []
    for tenant_id, settings in rows:
        try:
            state = registry(settings)
        except Exception:
            continue
        for task_id, task in state['tasks'].items():
            checked = task['verification'].get('checkedAt') or 0
            if (task['outcome'] == 'human-reported-published' and enabled(state, task['site_id'])
                    and task['verification']['state'] in {'pending', 'unavailable'}
                    and checked < report.now_ms() - 300000):
                pending.append((tenant_id, task_id))
                if len(pending) >= 20:
                    break
        if len(pending) >= 20:
            break
    for tenant_id, task_id in pending:
        try:
            await verify_one(tenant_id, task_id)
        except Exception:
            # Retain the intent for a later run. No arbitrary exception text,
            # device credential or article data is included in scheduler logs.
            continue
