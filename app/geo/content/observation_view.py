"""Saved observations only: scoped aggregates, explicit attempt states and keyset pages."""
import re

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import GeoAnswerSnapshot as Answer, GeoPrompt, GeoTrackingEngine
from app.models import GeoVisibilityPatrolRun as Run, GeoVisibilityPatrolSettings as Plan
from app.security.advisor_write_reads import filter_query

STANDARD_ENGINES = ('doubao', 'deepseek', 'qwen', 'hunyuan', 'wenxin', 'kimi')
SENTIMENTS = ('positive', 'neutral', 'negative')
NOT_CONFIGURED = {'skipped:real_only_no_platform_key', 'skipped:prefer_real_no_platform_key',
                  'skipped:dashscope_only_for_deepseek'}


def safe_alias(value):
    # Only provider/model aliases; never forward upstream errors, URLs or configuration.
    return value if isinstance(value, str) and re.fullmatch(r'[\w. /:+-]{1,80}', value) else None


def model_state(*, saved, evaluated, configured, attempt):
    if saved:
        return 'evaluated' if evaluated else 'saved_unscored'
    if attempt:
        if attempt.get('skipped_reason') in NOT_CONFIGURED:
            return 'not_configured'
        if attempt.get('ok') is False:
            return 'failed'
        return 'attempted_unsaved'
    return 'not_attempted' if configured else 'not_configured'


async def observation_page(session, ctx, tenant_id, prompt_id, *, page_size=20,
                           before_id=None, watermark=None):
    ctx.ensure_tenant(tenant_id)
    stmt = await filter_query(session, ctx, select(GeoPrompt).where(
        GeoPrompt.tenant_id == tenant_id, GeoPrompt.id == prompt_id), GeoPrompt)
    prompt = await session.scalar(stmt)
    if prompt is None:
        raise HTTPException(404, '问题不存在或不在授权范围')
    scope = [Answer.tenant_id == tenant_id, Answer.prompt_id == prompt_id]
    if watermark is None:
        watermark = int(await session.scalar(select(func.max(Answer.id)).where(*scope)) or 0)
    scope.append(Answer.id <= watermark)
    groups = (await session.execute(select(Answer.engine, Answer.mentions_brand, Answer.sentiment,
        func.count()).where(*scope).group_by(Answer.engine, Answer.mentions_brand, Answer.sentiment))).all()
    counts = {}
    for engine, mentioned, sentiment, n in groups:
        item = counts.setdefault(engine, {'saved': 0, 'mentioned': 0, 'evaluated': 0,
                                         **dict.fromkeys(SENTIMENTS, 0)})
        item['saved'] += n
        item['mentioned'] += n if mentioned is True else 0
        if mentioned is True and sentiment in SENTIMENTS:
            item['evaluated'] += n
            item[sentiment] += n
    # Select no credential columns. A configured engine is a plan selection, not a success.
    engines = (await session.execute(select(GeoTrackingEngine.engine_key, GeoTrackingEngine.enabled)
        .where(GeoTrackingEngine.tenant_id == tenant_id))).all()
    enabled = {key for key, on in engines if on}
    plan = await session.scalar(select(Plan).where(Plan.tenant_id == tenant_id))
    selected = set(plan.engine_keys) if plan and plan.engine_keys is not None else enabled
    models = []
    for engine in dict.fromkeys((*STANDARD_ENGINES, *sorted(enabled | selected | set(counts)))):
        run = await session.scalar(select(Run).where(Run.tenant_id == tenant_id,
            Run.items.contains([{'prompt_id': prompt_id, 'engine': engine}]))
            .order_by(Run.id.desc()).limit(1))
        attempt = next((c for c in (run.items or []) if isinstance(c, dict)
            and c.get('prompt_id') == prompt_id and c.get('engine') == engine), None) if run else None
        c = counts.get(engine, {'saved': 0, 'mentioned': 0, 'evaluated': 0,
                                **dict.fromkeys(SENTIMENTS, 0)})
        configured = engine in enabled and engine in selected and prompt.status == 'active'
        state = model_state(saved=c['saved'], evaluated=c['evaluated'], configured=configured, attempt=attempt)
        models.append({'engine': engine, **c, 'state': state, 'in_plan': configured,
            'last_attempt_at': (run.finished_at or run.started_at).isoformat()
                if run and (run.finished_at or run.started_at) else None,
            'provider': safe_alias(attempt.get('provider')) if attempt else None,
            'model': safe_alias(attempt.get('model')) if attempt else None,
            'attempt_state': ('failed' if attempt.get('ok') is False else 'recorded') if attempt else 'no_record',
            'reason_code': 'attempt_failed' if state == 'failed' else None})
    evidence_scope = list(scope)
    if before_id is not None:
        evidence_scope.append(Answer.id < before_id)
    rows = list(await session.scalars(select(Answer).where(*evidence_scope)
        .order_by(Answer.id.desc()).limit(page_size + 1)))
    page = rows[:page_size]
    totals = {key: sum(c[key] for c in counts.values())
              for key in ('saved', 'mentioned', 'evaluated', *SENTIMENTS)}
    return {'rows': page, 'models': models, 'summary': totals,
        'plan_enabled': plan.enabled if plan else False,
        'plan_scope': 'tenant_monitoring_selection_not_success_or_prompt_schedule_guarantee',
        'pagination': {'total_count': totals['saved'], 'watermark': watermark,
            'next_before_id': page[-1].id if len(rows) > page_size and page else None,
            'has_more': len(rows) > page_size}}
