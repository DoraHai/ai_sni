"""Bounded recovery for committed central publication captures only.

No new tables: dispatch leases live in a private capture warnings member. A
dedicated PostgreSQL session advisory lock spans the external read; transactions
do not. Claim tokens fence completion and retries reuse the same capture row.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import logging
import threading
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.database import async_session_factory
from app.models.seo_page_capture import SeoPageCapture
from app.seo_demo_runtime import seo_scheduler_may_start
from app.seo_distribution_results import content_digest
from app.seo_distribution_sources import load_source

logger=logging.getLogger(__name__)
META='_publication_dispatch'
MAX_ATTEMPTS=3
RETRYABLE={'timeout','worker_error','storage_error','dispatch_unavailable'}
HOLDS={'project_paused','project_ended','capture_disabled'}
_execution_slots=threading.BoundedSemaphore(2)


def now_ms():
    return int(datetime.now(timezone.utc).timestamp()*1000)


def metadata(row):
    value=(row.warnings if isinstance(row.warnings,dict) else {}).get(META)
    return dict(value) if isinstance(value,dict) else {}


def number(value,default=0):
    return value if type(value) is int and 0<=value<=9007199254740991 else default


def _due_ms(key,fallback):
    # Only constant internal keys/expressions. Match number() without unsafe
    # casts of arbitrary JSON strings, arrays, fractions or huge numbers.
    value=f"c.warnings#>>'{{{META},{key}}}'"
    return (f"CASE WHEN jsonb_typeof(c.warnings#>'{{{META},{key}}}')='number' "
            f"AND ({value}) ~ '^[0-9]{{1,16}}$' THEN "
            f"CASE WHEN ({value})::numeric<=9007199254740991 THEN ({value})::numeric ELSE {fallback} END "
            f"ELSE {fallback} END")


def enabled():
    settings=get_settings()
    return (seo_scheduler_may_start(settings) and settings.seo_page_capture_enabled
            and bool(getattr(settings,'seo_external_actions_enabled',True)))


def blocked(code):
    return HTTPException(409,{'code':code,'message':'页面检查当前不允许执行'})


async def gate(db,row,token=None):
    """Current central owner/state, native entitlement/role/review and URL gates."""
    if token is not None and metadata(row).get('token')!=token: raise blocked('lease_lost')
    if not enabled(): raise blocked('capture_disabled')
    event=(await db.execute(text('SELECT e.*,p.page_url,p.status AS publication_status '
        'FROM seo_distribution_result_events e JOIN seo_content_publications p ON p.id=e.publication_id '
        'JOIN seo_content_assets a ON a.id=p.content_asset_id '
        'WHERE e.publication_id=:publication AND e.tenant_id=:tenant AND e.site_id=:site '
        'AND p.tenant_id=:tenant AND a.tenant_id=:tenant AND a.site_id=:site '
        'ORDER BY e.created_at,e.event_id LIMIT 1'),
        {'publication':row.relation_id,'tenant':row.tenant_id,'site':row.site_id})).mappings().first()
    if not event or row.relation_type!='publication' or row.source!='auto': raise blocked('publication_unavailable')
    project=(await db.execute(text("SELECT state,owner_user_id FROM distribution_controls "
        "WHERE module='seo' AND tenant_id=:tenant AND scope_id=:site"),
        {'tenant':row.tenant_id,'site':row.site_id})).mappings().one_or_none()
    if project is None: raise blocked('project_unavailable')
    if project['state']!='running': raise blocked('project_'+project['state'])
    if project['owner_user_id']!=event['actor_user_id']: raise blocked('advisor_unavailable')
    if event['publication_status']!='published' or row.source_url!=event['page_url'] or row.source_url!=event['payload']['public_url']:
        raise blocked('publication_url_mismatch')
    try:
        snapshot=await load_source(db,event['actor_user_id'],row.tenant_id,row.site_id,event['variant_id'],event['payload']['platform'])
    except HTTPException as exc:
        if exc.status_code>=500: raise
        raise blocked('advisor_unavailable' if exc.status_code==403 else 'source_changed') from None
    if (snapshot['source_revision']!=event['payload']['source_revision']
            or content_digest(snapshot['content'])!=event['payload']['content_digest']):
        raise blocked('source_changed')


def store(row,value):
    row.warnings={**(row.warnings if isinstance(row.warnings,dict) else {}),META:value}


def settle_hold(row,code):
    """Same transaction as the pause result; clearing the token refunds once."""
    meta=metadata(row)
    attempts=number(meta.get('attempts'))
    row.status,row.error_code='pending',code
    store(row,{**meta,'attempts':max(0,attempts-1) if meta.get('token') else attempts,
               'token':None,'terminal':False,'lease_until':None,'next_attempt_at':None,'last_error':code})


async def run_capture(capture_id,*,sessions=None):
    """All entry paths for central-backed publications acquire the same DB lock."""
    if not enabled(): return 'disabled'
    if not _execution_slots.acquire(blocking=False): return 'busy'
    try:
        return await _with_database_lock(capture_id,sessions or async_session_factory)
    finally:
        _execution_slots.release()


async def _with_database_lock(capture_id,sessions):
    sessions=sessions or async_session_factory
    engine=sessions.kw['bind']
    key=int.from_bytes(hashlib.sha256(f'seo-publication-capture:{capture_id}'.encode()).digest()[:8],'big',signed=True)
    try:
        async with engine.connect() as lock_connection:
            try:
                held=await lock_connection.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':key})
                await lock_connection.commit()
            except BaseException:
                # Acquisition may have reached PostgreSQL before cancellation.
                # Closing the physical session releases even an ambiguous lock.
                await lock_connection.invalidate()
                raise
            if not held: return 'busy'
            try:
                # Claim, gates and result persistence run sequentially on this
                # same checked-out connection. Never borrow a second pool slot.
                bound=async_sessionmaker(bind=lock_connection,expire_on_commit=False)
                return await _run_locked(bound,capture_id)
            finally:
                try:
                    await lock_connection.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':key})
                    await lock_connection.commit()
                except BaseException:
                    # Never return a pooled connection retaining a session lock.
                    await lock_connection.invalidate()
                    raise
    except (SQLAlchemyError,OSError,TimeoutError):
        logger.warning('SEO publication capture unavailable: capture_id=%s',capture_id)
        return 'unavailable'
    except HTTPException as exc:
        if exc.status_code<500: raise
        logger.warning('SEO publication capture authority unavailable: capture_id=%s',capture_id)
        return 'unavailable'


async def _run_locked(sessions,capture_id):
    from app.api import seo_page_captures as api
    async with sessions.begin() as db:
        row=await db.get(SeoPageCapture,capture_id,with_for_update=True)
        if row is None or row.status=='succeeded' or row.source!='auto': return 'finished'
        if row.status in {'pending','failed'} and row.error_code in HOLDS and metadata(row).get('token'):
            # Recover the old commit-before-settlement crash window exactly once.
            settle_hold(row,row.error_code)
        meta=metadata(row)
        if meta.get('terminal'): return 'finished'
        now=now_ms()
        if number(meta.get('next_attempt_at'))>now: return 'deferred'
        if row.status=='running':
            # Recover a crashed worker only after its durable lease expires.
            lease=number(meta.get('lease_until'),int(row.captured_at.timestamp()*1000)+(get_settings().seo_page_capture_timeout_seconds+60)*1000)
            if lease>now: return 'leased'
        if row.status=='failed' and row.error_code not in RETRYABLE|HOLDS:
            store(row,{**meta,'terminal':True,'next_attempt_at':None})
            return 'finished'
        attempts=number(meta.get('attempts'))
        if attempts>=MAX_ATTEMPTS:
            row.status,row.error_code='failed','retry_exhausted'
            store(row,{**meta,'terminal':True,'next_attempt_at':None})
            return 'exhausted'
        try:
            await gate(db,row)
        except HTTPException as exc:
            if exc.status_code>=500: raise
            code=exc.detail['code']
            # Project pause/end is a hold, not a failed external request.
            if code in HOLDS:
                row.status,row.error_code='pending',code
                store(row,{**meta,'next_attempt_at':None})
                return 'paused'
            row.status,row.error_code='failed',code
            store(row,{**meta,'terminal':True,'next_attempt_at':None})
            logger.info('SEO publication capture blocked: capture_id=%s code=%s',capture_id,code)
            return 'blocked'
        token=str(uuid4())
        row.status,row.error_code='pending',None
        store(row,{'attempts':attempts+1,'token':token,'lease_until':now+(get_settings().seo_page_capture_timeout_seconds+60)*1000,
                   'next_attempt_at':None,'terminal':False})
    # No uncommitted reservation or claim can be observed by the renderer.
    async def check(db,row):
        await gate(db,row,token)
    await api._execute_page_capture(capture_id,gate=check,sessions=sessions)
    async with sessions.begin() as db:
        row=await db.get(SeoPageCapture,capture_id,with_for_update=True)
        if row is None: return 'superseded'
        if metadata(row).get('token')!=token:
            return 'paused' if row.status=='pending' and row.error_code in HOLDS else 'superseded'
        meta=metadata(row)
        if row.error_code in HOLDS:
            settle_hold(row,row.error_code)
            return 'paused'
        if row.status in {'pending','running'}: return 'interrupted'
        retry=row.status=='failed' and row.error_code in RETRYABLE and meta['attempts']<MAX_ATTEMPTS
        last_error=row.error_code
        if row.status=='failed' and row.error_code in RETRYABLE and meta['attempts']>=MAX_ATTEMPTS:
            row.error_code='retry_exhausted'
        store(row,{**meta,'terminal':not retry,'lease_until':None,'last_error':last_error,
                   'next_attempt_at':now_ms()+[60000,300000][meta['attempts']-1] if retry else None})
        logger.info('SEO publication capture settled: capture_id=%s state=%s attempt=%s retry=%s code=%s',
                    capture_id,row.status,meta['attempts'],retry,row.error_code)
        return 'retry' if retry else row.status


async def run_publication_captures():
    """Minute scheduler; inspect only committed, central-backed running projects."""
    if not enabled(): return {'state':'disabled','checked':0}
    try:
        async with async_session_factory() as db:
            present=await db.scalar(text("SELECT to_regclass('seo_distribution_result_events') IS NOT NULL "
                "AND to_regclass('distribution_controls') IS NOT NULL"))
            if not present:
                logger.info('SEO publication capture scheduler unavailable: integration schema missing')
                return {'state':'unavailable','checked':0}
            next_due=_due_ms('next_attempt_at','0')
            lease_due=_due_ms('lease_until','(EXTRACT(EPOCH FROM c.captured_at)*1000+:lease_ms)')
            ids=(await db.execute(text("SELECT DISTINCT c.id,c.captured_at FROM seo_page_captures c "
                "JOIN seo_distribution_result_events e ON e.publication_id=c.relation_id "
                "AND e.tenant_id=c.tenant_id AND e.site_id=c.site_id "
                "JOIN distribution_controls p ON p.module='seo' AND p.tenant_id=e.tenant_id AND p.scope_id=e.site_id "
                "AND p.owner_user_id=e.actor_user_id AND p.state='running' "
                "WHERE c.source='auto' AND c.relation_type='publication' AND c.status IN ('pending','running','failed') "
                "AND c.warnings->'_publication_dispatch'->>'terminal' IS DISTINCT FROM 'true' "
                f"AND ({next_due})<=:now AND (c.status<>'running' OR ({lease_due})<=:now) "
                "ORDER BY c.captured_at,c.id LIMIT 20"),{'now':now_ms(),
                    'lease_ms':(get_settings().seo_page_capture_timeout_seconds+60)*1000})).all()
        semaphore=asyncio.Semaphore(2)
        async def one(row):
            async with semaphore:
                try:
                    return await run_capture(row.id)
                except Exception:
                    logger.warning('SEO publication capture dispatch failed: capture_id=%s',row.id)
                    return 'failed'
        states=await asyncio.gather(*(one(row) for row in ids))
        return {'state':'ready','checked':len(ids),'failed':sum(state in {'failed','unavailable','blocked','exhausted'} for state in states)}
    except (SQLAlchemyError,OSError,TimeoutError):
        logger.warning('SEO publication capture scheduler unavailable')
        return {'state':'unavailable','checked':0}
