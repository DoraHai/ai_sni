"""Server-owned, bounded sampling plans copied from verified weekly evidence."""
from collections import Counter
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.geo.integration_metrics import MENTIONS, closed_week_end, complete_model_counts
from app.geo.content.time_windows import shanghai_day_bounds_utc_naive, to_utc_naive
from app.models import GeoPrompt, GeoVisibilityPatrolRun, GeoAnswerSnapshot


def plan_from_baseline(task):
    state = task.baseline_snapshot or {}
    key = (task.progress_first or {}).get('params', {}).get('metric_key', MENTIONS)
    metric = next((m for m in state.get('metrics', []) if m['metric_key'] == key), None)
    if task.status in {'done', 'cancelled'}:
        raise HTTPException(409, '已结束任务不能启动复测')
    if not metric or metric['value'] is None:
        raise HTTPException(409, '请先取得完整周的有效基线')
    questions = {int(pid): question for pid, question in state.get('questions', [])}
    if len(questions) != len(state.get('questions', [])):
        raise HTTPException(409, '同一基线问题含多个原文版本，不能精确复测')
    fingerprints = state.get('model_counts')
    if not complete_model_counts(fingerprints):
        raise HTTPException(409, '基线缺少模型或供应商记录，不能精确复测')
    cells = []
    seen = set()
    for pid, engine, count in state.get('sample_counts', []):
        if not isinstance(count, int) or isinstance(count, bool) or count < 1 or (pid, engine) in seen:
            raise HTTPException(409, '基线采样矩阵不完整')
        if not questions.get(pid):
            raise HTTPException(409, '基线缺少题目原文，不能猜测复测口径')
        versions = [c for c in fingerprints if c[0] == pid and c[1] == engine]
        if len(versions) != 1 or versions[0][4] != count:
            raise HTTPException(409, '基线同题同引擎存在混合模型或次数不一致，不能精确复测')
        cells.append({'prompt_id': pid, 'engine': engine, 'count': count, 'question': questions[pid],
                      'provider': versions[0][2], 'model': versions[0][3]})
        seen.add((pid, engine))
    if not cells or sum(c['count'] for c in cells) > 200:
        raise HTTPException(409, '复测需1至200次明确采样')
    return {'task_id': task.id, 'baseline_as_of': metric['as_of'], 'cells': cells,
            'total_samples': sum(c['count'] for c in cells)}


def validate_plan_prompts(plan, prompts):
    by_id = {p.id: p for p in prompts}
    for cell in plan['cells']:
        prompt = by_id.get(cell['prompt_id'])
        if (not prompt or prompt.status != 'active' or prompt.is_brand_probe
                or prompt.question.strip() != cell['question']):
            raise HTTPException(409, '基线题目被修改、停用或不属于当前客户，停止复测')


def engines_for_prompt(plan, prompt_id):
    return [cell['engine'] for cell in plan['cells'] if cell['prompt_id'] == prompt_id
            for _ in range(cell['count'])]


async def prepare_retest(session, task, *, check_window=True):
    plan = plan_from_baseline(task)
    ids = {c['prompt_id'] for c in plan['cells']}
    prompts = list(await session.scalars(select(GeoPrompt).where(
        GeoPrompt.tenant_id == task.tenant_id, GeoPrompt.id.in_(ids))))
    validate_plan_prompts(plan, prompts)
    if check_window:
        start = shanghai_day_bounds_utc_naive(closed_week_end())[0]
        end = start + timedelta(days=7)
        if (task.progress_first or {}).get('params', {}).get('content_task_id'):
            proof = (task.progress or {}).get('publication_evidence') or {}
            first = proof.get('first_verified_at')
            if not first or to_utc_naive(datetime.fromisoformat(first.replace('Z', '+00:00'))) > start:
                raise HTTPException(409, '需真实发布核验之后的完整自然周才能复测')
        if (start < to_utc_naive(task.created_at)
                or to_utc_naive(datetime.fromisoformat(plan['baseline_as_of'])) > start):
            raise HTTPException(409, '复测必须处于任务创建后且基线结束后的完整自然周')
        existing = await session.scalar(select(GeoVisibilityPatrolRun.id).where(
            GeoVisibilityPatrolRun.tenant_id == task.tenant_id,
            GeoVisibilityPatrolRun.status.in_(['pending', 'running'])).limit(1))
        sampled = await session.scalar(select(GeoAnswerSnapshot.id).where(
            GeoAnswerSnapshot.tenant_id == task.tenant_id,
            GeoAnswerSnapshot.captured_at >= start, GeoAnswerSnapshot.captured_at < end).limit(1))
        reservation = await reserved_week(session, task.tenant_id)
        if existing or sampled or reservation:
            raise HTTPException(409, '本周已有样本或在途巡检，不能追加采样改变统计权重')
        plan['window_start'] = start.isoformat()
        plan['window_end'] = end.isoformat()
    return plan


def validate_run_result(plan, items):
    expected = Counter({(c['prompt_id'], c['engine']): c['count'] for c in plan['cells']})
    actual = Counter((c.get('prompt_id'), c.get('engine')) for c in items if c.get('ok')
                     and c.get('sample_mode') == 'openai_compat' and not c.get('simulated')
                     and c.get('analysis_status') == 'completed' and c.get('snapshot_id'))
    return {'comparable': actual == expected,
            'expected_samples': sum(expected.values()), 'qualified_samples': sum(actual.values()),
            'missing': [{'prompt_id': p, 'engine': e, 'count': n}
                        for (p, e), n in (expected - actual).items()]}


async def reserved_week(session, tenant_id):
    period = shanghai_day_bounds_utc_naive(closed_week_end())[0].isoformat()
    return await session.scalar(select(GeoVisibilityPatrolRun.id).where(
        GeoVisibilityPatrolRun.tenant_id == tenant_id,
        GeoVisibilityPatrolRun.summary['contract_plan']['window_start'].astext == period).limit(1))


def validate_plan_model(plan, prompt_id, engine, llm):
    cell = next(c for c in plan['cells'] if c['prompt_id'] == prompt_id and c['engine'] == engine)
    if any(str(llm.get(k) or '').strip() != cell[k] for k in ('provider', 'model')):
        raise ValueError('当前模型或供应商与基线不同，停止该单元复测')
