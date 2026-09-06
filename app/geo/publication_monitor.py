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
    clean = {k: v for k, v in previous.items() if k not in {'expected_sha256', 'observed_sha256', 'observed_url', 'matched_passages', 'total_passages'}}
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
        row.status, row.closed_at = 'done', datetime.utcnow()
    elif row.status == 'done':
        row.status, row.closed_at = 'reopened', None
    row.evidence = append_evidence(row.evidence, check='publication.monitor', result=state['state'], note=row.last_note, limit=30)


async def check_publication(session, tenant_id, task_id, publication_id, *, scheduled=False):
    # Same lock order as publishing: content first, then variant. A transaction holds
    # ownership through the bounded fetch; a crash rolls it back without a stuck lease.
    content = await session.scalar(select(GeoContentTask).where(
        GeoContentTask.id == task_id, GeoContentTask.tenant_id == tenant_id,
        GeoContentTask.status != 'archived').with_for_update(skip_locked=scheduled))
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
            proof = match_publication(variant.title, variant.body_markdown, document.html)
            proof['observed_url'] = document.final_url
            state = 'healthy'
        except (GeoAuditError, TimeoutError):
            state = 'unreachable'
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            state = 'mismatch'
    fresh = outcome(old, state, now, **proof)
    store_state(variant, pub, fresh)
    await follow_up(session, content, pub, fresh)
    await session.commit()
    return fresh


async def list_monitor(session, tenant_id, task_id):
    exists = await session.scalar(select(GeoContentTask.id).where(
        GeoContentTask.id == task_id, GeoContentTask.tenant_id == tenant_id))
    if exists is None:
        raise HTTPException(404, '内容任务不存在')
    rows = (await session.execute(select(GeoPublication, GeoChannelVariant).join(
        GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).where(
        GeoChannelVariant.task_id == task_id, GeoPublication.status == 'published')
        .order_by(GeoPublication.id.desc()).limit(100))).all()
    return {'items': [{'publication_id': p.id, 'url': p.published_url, 'channel': p.channel,
                       **(state_for(v, p) or {'state': 'pending'})} for p, v in rows]}


async def run_monitor_batch():
    from app.database import async_session_factory
    import logging
    now = datetime.utcnow().isoformat() + 'Z'
    entry = GeoChannelVariant.adapt_meta['publication_monitor'][cast(GeoPublication.id, String)]
    due = func.coalesce(entry['next_check_at'].astext, '')
    async with async_session_factory() as session:
        rows = (await session.execute(select(GeoContentTask.tenant_id, GeoContentTask.id, GeoPublication.id)
            .join(GeoChannelVariant, GeoChannelVariant.task_id == GeoContentTask.id)
            .join(GeoPublication, GeoPublication.variant_id == GeoChannelVariant.id)
            .where(GeoContentTask.status != 'archived', GeoPublication.status == 'published',
                   GeoPublication.published_url.is_not(None), due <= now)
            .order_by(due, GeoPublication.id).limit(25))).all()
    for tenant_id, task_id, publication_id in rows:
        try:
            async with async_session_factory() as session:
                await check_publication(session, tenant_id, task_id, publication_id, scheduled=True)
        except Exception:
            logging.getLogger(__name__).exception('GEO publication monitor failed for record %s', publication_id)
