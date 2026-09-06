"""Strictly query-only integration views; never call legacy reconciling GETs."""
import base64
import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, and_, select, text

from app.config import get_settings
from app.database import async_session_factory
from app.security.auth import require_scoped_auth
from app.models import (GeoAnswerSnapshot, GeoPrompt, GeoVisibilityPatrolRun, GeoTrackingEngine,
                        GeoPublishingChannel, GeoContentTask, GeoArticleVersion, GeoChannelVariant,
                        GeoPublication, GeoAsyncJob, GeoActionTicket, GeoAiSetting)
from app.geo.integration_metrics import load_weekly_snapshot, _load_snapshot_window, closed_week_end
from app.geo.content.time_windows import to_utc_naive
from app.geo.read_model import answer_payload, period_context, iso, ref
from app.geo.tenant_scope import require_geo_read_entitlement

router = APIRouter(prefix='/integration/read', tags=['GEO read-only workbench'],
                   dependencies=[Depends(require_geo_read_entitlement)])


async def read_session():
    async with async_session_factory(autoflush=False) as session:
        async with session.begin():
            # Set before the first data query. No persistent DB configuration change.
            await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            yield session


async def context_for(session, tenant_id, week_end):
    end = week_end or closed_week_end()
    try:
        current = await load_weekly_snapshot(session, tenant_id, end)
        previous = await _load_snapshot_window(session, tenant_id, end-timedelta(days=7))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return period_context(tenant_id, end, current, previous)


@router.get('/period-context')
async def get_period_context(tenant_id: int, week_end: date | None = None,
                             ctx=Depends(require_scoped_auth), session=Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    return await context_for(session, tenant_id, week_end)


def encode_cursor(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    signature = hmac.new(get_settings().admin_api_key.encode(), raw, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=') + '.' + signature


def decode_cursor(value):
    try:
        if len(value) > 4096:
            raise ValueError()
        encoded, signature = value.split('.')
        raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        expected = hmac.new(get_settings().admin_api_key.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError()
        result = json.loads(raw)
        if result['v'] != 1 or not isinstance(result['max_id'], int) or not isinstance(result['last_id'], int):
            raise ValueError()
        return result
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, {'code': 'invalid_cursor', 'message': '分页游标无效，请重新查询'}) from None


def source_expression():
    mode = func.trim(func.coalesce(GeoAnswerSnapshot.sample_mode, 'unknown'))
    note = func.coalesce(GeoAnswerSnapshot.note, '')
    return case((or_(GeoAnswerSnapshot.simulated.is_(True), mode == 'mock_persona', note.contains('模拟')), 'simulated'),
                (mode == 'openai_compat', 'real'), (mode == 'manual', 'manual'),
                (or_(note.contains('真采样'), note.contains('openai_compat', autoescape=True)), 'real'), else_='unknown')


@router.get('/answers')
async def get_answers(tenant_id: int, week_end: date | None = None, prompt_id: int | None = None,
                      engine_key: str | None = None, patrol_run_id: int | None = None,
                      source_kind: Literal['real', 'manual', 'simulated', 'unknown'] | None = None,
                      captured_from: datetime | None = None, captured_to: datetime | None = None,
                      limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
                      ctx=Depends(require_scoped_auth), session=Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    if any(value is not None and value.utcoffset() is None for value in (captured_from, captured_to)):
        raise HTTPException(400, '观察时间必须包含明确时区')
    if captured_from and captured_to and captured_from >= captured_to:
        raise HTTPException(400, '观察区间必须起点早于终点，右端不包含')
    decoded = decode_cursor(cursor) if cursor else None
    # Keep the first page's canonical week even when the calendar rolls over.
    end = week_end or (date.fromisoformat(decoded['week_end']) if decoded else closed_week_end())
    filters = {'tenant_id': tenant_id, 'week_end': str(end), 'prompt_id': prompt_id, 'engine_key': engine_key,
               'patrol_run_id': patrol_run_id, 'source_kind': source_kind,
               'captured_from': iso(captured_from), 'captured_to': iso(captured_to), 'limit': limit}
    fingerprint = hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()
    if decoded and decoded.get('filters') != fingerprint:
        raise HTTPException(400, {'code': 'invalid_cursor', 'message': '租户或筛选条件已改变，请重新查询'})
    context = await context_for(session, tenant_id, end)
    conditions = [GeoAnswerSnapshot.tenant_id == tenant_id, GeoPrompt.tenant_id == tenant_id]
    for column, value in ((GeoAnswerSnapshot.prompt_id, prompt_id), (GeoAnswerSnapshot.engine, engine_key),
                          (GeoAnswerSnapshot.patrol_run_id, patrol_run_id), (source_expression(), source_kind)):
        if value is not None:
            conditions.append(column == value)
    base = select(GeoAnswerSnapshot, GeoPrompt).join(GeoPrompt, GeoPrompt.id == GeoAnswerSnapshot.prompt_id).where(*conditions)
    unknown = await session.scalar(select(func.count()).select_from(base.where(GeoAnswerSnapshot.captured_at.is_(None)).subquery()))
    if captured_from:
        base = base.where(GeoAnswerSnapshot.captured_at >= to_utc_naive(captured_from))
    if captured_to:
        base = base.where(GeoAnswerSnapshot.captured_at < to_utc_naive(captured_to))
    max_id = decoded['max_id'] if decoded else (await session.scalar(select(func.max(GeoAnswerSnapshot.id)).where(GeoAnswerSnapshot.tenant_id == tenant_id)) or 0)
    base = base.where(GeoAnswerSnapshot.id <= max_id)
    if decoded:
        last = datetime.fromisoformat(decoded['last_at']) if decoded['last_at'] else None
        if last is None:
            base = base.where(GeoAnswerSnapshot.captured_at.is_(None), GeoAnswerSnapshot.id < decoded['last_id'])
        else:
            base = base.where(or_(GeoAnswerSnapshot.captured_at < last, GeoAnswerSnapshot.captured_at.is_(None),
                                 and_(GeoAnswerSnapshot.captured_at == last, GeoAnswerSnapshot.id < decoded['last_id'])))
    pairs = (await session.execute(base.order_by(GeoAnswerSnapshot.captured_at.desc().nullslast(), GeoAnswerSnapshot.id.desc()).limit(limit+1))).all()
    page = pairs[:limit]
    runs = list(await session.scalars(select(GeoVisibilityPatrolRun).where(GeoVisibilityPatrolRun.tenant_id == tenant_id,
                       GeoVisibilityPatrolRun.id.in_({row.patrol_run_id for row, _ in page if row.patrol_run_id})))) if page else []
    by_id = {run.id: run for run in runs}
    next_cursor = None
    if len(pairs) > limit:
        last = page[-1][0]
        next_cursor = encode_cursor({'v': 1, 'week_end': str(end), 'filters': fingerprint, 'max_id': max_id,
                                     'last_at': to_utc_naive(last.captured_at).isoformat() if last.captured_at else None, 'last_id': last.id})
    return {'tenant_id': tenant_id, 'evaluated_at': context['evaluated_at'], 'timezone': 'Asia/Shanghai',
            'official_week_end': str(end), 'observation_window': {'start': iso(captured_from, True), 'end': iso(captured_to, True)},
            'unknown_time_count': unknown, 'period_context_url': f'/api/v1/geo/integration/read/period-context?tenant_id={tenant_id}&week_end={end}',
            'pagination': {'limit': limit, 'has_more': bool(next_cursor), 'next_cursor': next_cursor, 'watermark_max_id': max_id},
            'items': [answer_payload(row, prompt, by_id.get(row.patrol_run_id), context) for row, prompt in page]}


async def tenant_object(session, model, tenant_id, ident):
    row = await session.scalar(select(model).where(model.id == ident, model.tenant_id == tenant_id))
    if row is None:
        raise HTTPException(404, '对象不存在')
    return row


@router.get('/answers/{snapshot_id}')
async def get_answer(snapshot_id: int, tenant_id: int, week_end: date | None = None,
                     ctx=Depends(require_scoped_auth), session=Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    row = await tenant_object(session, GeoAnswerSnapshot, tenant_id, snapshot_id)
    prompt = await tenant_object(session, GeoPrompt, tenant_id, row.prompt_id)
    run = await session.scalar(select(GeoVisibilityPatrolRun).where(GeoVisibilityPatrolRun.id == row.patrol_run_id,
                                                                  GeoVisibilityPatrolRun.tenant_id == tenant_id)) if row.patrol_run_id else None
    context = await context_for(session, tenant_id, week_end)
    return {'tenant_id': tenant_id, 'evaluated_at': context['evaluated_at'], 'official_week_end': context['week_end'],
            'period_context_url': f'/api/v1/geo/integration/read/period-context?tenant_id={tenant_id}&week_end={context["week_end"]}',
            'item': answer_payload(row, prompt, run, context, detail=True)}


@router.get('/capabilities')
async def get_capabilities(tenant_id: int, ctx=Depends(require_scoped_auth), session=Depends(read_session)):
    from app.geo.content.engine_providers import platform_engine_public_status
    ctx.ensure_tenant(tenant_id)
    ai_setting = await session.scalar(select(GeoAiSetting).where(GeoAiSetting.tenant_id == tenant_id))
    stance = (ai_setting.monitoring_stance if ai_setting else None) or 'hybrid'
    engines = list(await session.scalars(select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == tenant_id)))
    channels = list(await session.scalars(select(GeoPublishingChannel).where(GeoPublishingChannel.tenant_id == tenant_id)))
    history = list(await session.scalars(select(GeoAnswerSnapshot.engine).where(GeoAnswerSnapshot.tenant_id == tenant_id).distinct()))
    engine_items = []
    for row in engines:
        platform = platform_engine_public_status(row.engine_key)
        engine_items.append({'engine_key': row.engine_key, 'display_name': row.display_name, 'enabled': row.enabled,
                             'stored_sample_mode': row.sample_mode, 'configured': bool(platform['configured']),
                             'effective_mode': None, 'monitoring_stance': stance,
                             'mode_basis': 'execution_request_required',
                             'configured_mode': ('mock_persona' if stance == 'simulation' else
                                                 'openai_compat' if platform['configured'] else
                                                 'unavailable' if stance == 'real_only' else 'mock_persona'),
                             'connection_verified': False, 'may_fallback': stance != 'real_only',
                             'reason_codes': [] if platform['configured'] else ['missing_platform_credentials'],
                             'historical_model': None})
    return {'tenant_id': tenant_id, 'evaluated_at': iso(datetime.now(timezone.utc)), 'read_only': True,
            'engines': engine_items, 'historical_engine_keys': history,
            'channels': [{'id': r.id, 'name': r.name, 'channel_type': r.channel_type, 'enabled': r.enabled} for r in channels],
            'configuration_status': 'configured' if engines else 'unconfigured',
            'actions_enabled': False, 'note': '仅按已有配置推断，未试连；不保证真实采集，不初始化配置。'}


def safe_error(value):
    # Provider failures can contain echoed credentials and URLs. Use a classified
    # message rather than returning arbitrary provider bodies or request metadata.
    if not value:
        return None
    raw = str(value).lower()
    for marker, message in {'skipped:real_only_no_platform_key': '要求真实采样，但没有该引擎的平台凭证',
                            'skipped:dashscope_only_for_deepseek': '现有平台能力不能用于该引擎的真实采样'}.items():
        if raw == marker:
            return {'code': marker.removeprefix('skipped:'), 'message': message}
    for tokens, code, message in [(['timeout', '超时'], 'timeout', '执行超时'),
                                  (['429', 'quota', '配额'], 'quota_exceeded', '供应商限流或配额不足'),
                                  (['401', '403', 'api key', '凭证', '授权'], 'authorization_failed', '供应商授权不可用'),
                                  (['取消', 'cancel'], 'cancelled', '任务已取消')]:
        if any(token in raw for token in tokens):
            return {'code': code, 'message': message}
    return {'code': 'execution_failed', 'message': '执行失败，请在 GEO 任务中查看并处理'}


async def progress_payload(session, row, tenant_id, kind):
    is_job = kind == 'async_job'
    if is_job:
        from app.geo.content.async_jobs import _stale_limits
        pending_limit, running_limit = _stale_limits()
    else:
        from app.geo.content.patrol import STALE_PENDING_SECONDS, STALE_RUNNING_SECONDS
        pending_limit, running_limit = STALE_PENDING_SECONDS, STALE_RUNNING_SECONDS
    anchor = row.started_at or row.created_at
    stale = bool(row.status in {'pending', 'running'} and anchor and
                 (datetime.now(timezone.utc).replace(tzinfo=None) - to_utc_naive(anchor)).total_seconds() >=
                 (pending_limit if row.status == 'pending' else running_limit))
    payload = {'tenant_id': tenant_id, 'evaluated_at': iso(datetime.now(timezone.utc)), 'ref': ref(kind, row.id), 'stored_status': row.status, 'stale': stale,
               'stale_reason': 'elapsed_threshold_exceeded' if stale else None,
               'created_at': iso(row.created_at), 'started_at': iso(row.started_at), 'finished_at': iso(row.finished_at),
               'error': safe_error(row.error), 'relations': [], 'result_refs': []}
    if is_job:
        progress = (row.request_meta or {}).get('progress') or {}
        pct = progress.get('pct')
        payload.update(progress_pct=pct if isinstance(pct, (float, int)) and not isinstance(pct, bool) and 0 <= pct <= 100 else None,
                       progress_label={'pending': '排队中', 'running': '执行中', 'succeeded': '已完成', 'failed': '执行失败', 'cancelled': '已取消'}.get(row.status, '状态未知'))
        if row.ref_type == 'content_task' and row.ref_id:
            task = await session.scalar(select(GeoContentTask).where(GeoContentTask.tenant_id == tenant_id, GeoContentTask.id == row.ref_id))
            if task:
                payload['relations'].append({'relation': 'runs_for', 'target': ref('content_task', task.id)})
                article_id = (row.result_meta or {}).get('article_id')
                if row.status == 'succeeded' and isinstance(article_id, int):
                    article = await session.scalar(select(GeoArticleVersion).where(GeoArticleVersion.task_id == task.id, GeoArticleVersion.id == article_id))
                    if article:
                        payload['result_refs'].append(ref('article_version', article.id))
    else:
        cells = [c for c in row.items or [] if isinstance(c, dict)]
        ids = {c['snapshot_id'] for c in cells if isinstance(c.get('snapshot_id'), int)}
        valid_ids = set(await session.scalars(select(GeoAnswerSnapshot.id).where(GeoAnswerSnapshot.tenant_id == tenant_id,
                       GeoAnswerSnapshot.patrol_run_id == row.id, GeoAnswerSnapshot.id.in_(ids)))) if ids else set()
        payload['items'] = [{'prompt_id': c.get('prompt_id'), 'engine_key': c.get('engine'), 'ok': bool(c.get('ok')),
                             'error': safe_error(c.get('error')), 'skipped_reason': safe_error(c.get('skipped_reason')),
                             'fallback_reason': safe_error(c.get('fallback_reason')),
                             'snapshot_ref': ref('answer_snapshot', c['snapshot_id']) if c.get('snapshot_id') in valid_ids else None} for c in cells]
        payload['summary'] = {key: (row.summary or {}).get(key) for key in ('cells_ok', 'cells_fail', 'cells_total', 'truncated')}
        payload['progress_pct'] = 100 if row.status == 'completed' else None
        metric_id = ((row.summary or {}).get('contract_plan') or {}).get('task_id')
        if isinstance(metric_id, int):
            task = await session.scalar(select(GeoActionTicket).where(GeoActionTicket.id == metric_id, GeoActionTicket.tenant_id == tenant_id,
                                        GeoActionTicket.advice_code == 'cockpit:v1:task'))
            if task:
                payload['relations'].append({'relation': 'retests', 'target': ref('metric_task', task.id)})
    return payload


@router.get('/async-jobs/{async_job_id}')
async def get_async_job(async_job_id: int, tenant_id: int, ctx=Depends(require_scoped_auth), session=Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    return await progress_payload(session, await tenant_object(session, GeoAsyncJob, tenant_id, async_job_id), tenant_id, 'async_job')


@router.get('/patrol-runs/{patrol_run_id}')
async def get_patrol_run(patrol_run_id: int, tenant_id: int, ctx=Depends(require_scoped_auth), session=Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    return await progress_payload(session, await tenant_object(session, GeoVisibilityPatrolRun, tenant_id, patrol_run_id), tenant_id, 'patrol_run')


async def progress_list(session, tenant_id, model, kind, limit, before_id):
    query = select(model).where(model.tenant_id == tenant_id)
    if before_id is not None:
        query = query.where(model.id < before_id)
    rows = list(await session.scalars(query.order_by(model.id.desc()).limit(limit+1)))
    return {'tenant_id': tenant_id, 'evaluated_at': iso(datetime.now(timezone.utc)),
            'items': [await progress_payload(session, row, tenant_id, kind) for row in rows[:limit]],
            'next_before_id': rows[limit-1].id if len(rows) > limit else None}


@router.get('/async-jobs')
async def get_async_jobs(tenant_id: int, limit: int = Query(20, ge=1, le=50), before_id: int | None = None,
                         ctx=Depends(require_scoped_auth), session=Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    return await progress_list(session, tenant_id, GeoAsyncJob, 'async_job', limit, before_id)


@router.get('/patrol-runs')
async def get_patrol_runs(tenant_id: int, limit: int = Query(20, ge=1, le=50), before_id: int | None = None,
                          ctx=Depends(require_scoped_auth), session=Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    return await progress_list(session, tenant_id, GeoVisibilityPatrolRun, 'patrol_run', limit, before_id)


@router.get('/content-tasks/{content_task_id}')
async def get_content_task(content_task_id: int, tenant_id: int, ctx=Depends(require_scoped_auth), session=Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    task = await tenant_object(session, GeoContentTask, tenant_id, content_task_id)
    articles = list(await session.scalars(select(GeoArticleVersion).where(GeoArticleVersion.task_id == task.id).order_by(GeoArticleVersion.version_no.desc())))
    variants = list(await session.scalars(select(GeoChannelVariant).where(GeoChannelVariant.task_id == task.id)))
    publications = list(await session.scalars(select(GeoPublication).join(GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).where(GeoChannelVariant.task_id == task.id)))
    metric_tasks = list(await session.scalars(select(GeoActionTicket).where(GeoActionTicket.tenant_id == tenant_id, GeoActionTicket.advice_code == 'cockpit:v1:task')))
    versions = []
    for article in articles:
        meta = article.generation_meta or {}
        item = {'ref': ref('article_version', article.id), 'version_no': article.version_no,
                'title': article.title, 'source': meta.get('source'), 'from_version': meta.get('from_version'),
                'created_at': iso(article.created_at), 'relations': []}
        job_id = meta.get('async_job_id')
        if isinstance(job_id, int):
            job = await session.scalar(select(GeoAsyncJob).where(GeoAsyncJob.id == job_id, GeoAsyncJob.tenant_id == tenant_id,
                                       GeoAsyncJob.ref_type == 'content_task', GeoAsyncJob.ref_id == task.id))
            if job:
                item['relations'].append({'relation': 'generated_by', 'target': ref('async_job', job.id)})
        versions.append(item)
    article_ids = {a.id for a in articles}
    valid_variants = [r for r in variants if r.article_version_id in article_ids]
    variant_ids = {r.id for r in valid_variants}
    return {'tenant_id': tenant_id, 'evaluated_at': iso(datetime.now(timezone.utc)), 'ref': ref('content_task', task.id),
            'title': task.title, 'stored_status': task.status, 'review_status': task.review_status, 'brief': task.brief or {},
            'article': ({**versions[0], 'body_markdown': articles[0].body_markdown} if versions else None),
            'versions': versions,
            'variants': [{'ref': ref('channel_variant', r.id), 'article_ref': ref('article_version', r.article_version_id),
                          'channel': r.channel, 'stored_status': r.status} for r in valid_variants],
            'publications': [{'ref': ref('publication', r.id), 'variant_ref': ref('channel_variant', r.variant_id),
                              'published_url': r.published_url, 'stored_status': r.status} for r in publications if r.variant_id in variant_ids],
            'relations': [{'relation': 'measured_by', 'target': ref('metric_task', r.id)} for r in metric_tasks
                          if ((r.progress_first or {}).get('params') or {}).get('content_task_id') == task.id]}
