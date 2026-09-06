"""Create review work only from comparable, closed-week observations."""
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from app.geo.integration import completion_evidence, metric, snapshot
from app.geo.verify import append_evidence
from app.models import GeoActionTicket
from app.geo.followup_lifecycle import active_review_source


async def assess_outcome(session, row):
    current = await snapshot(session, row.tenant_id)
    evidence = completion_evidence(row, current, require_target=False)
    fresh = await snapshot(session, row.tenant_id, date.fromisoformat(evidence['before']['as_of'][:10]))
    baseline = row.baseline_snapshot
    before = metric(fresh, evidence['metric_key'])
    if (not before or before['value'] != evidence['before']['value'] or
        any(fresh.get(k) != baseline.get(k) for k in ['sample_ids', 'sample_counts', 'model_counts', 'questions', 'cohort', 'own_domains'])):
        raise HTTPException(409, '基线来源已变化，需重新核实后再复盘')
    params = row.progress_first['params']
    delta = evidence['after']['value'] - evidence['before']['value']
    signed = delta if params.get('direction', 'increase') == 'increase' else -delta
    met = signed > 0 and signed >= params.get('min_delta', 0)
    return {'state': 'target_met' if met else 'needs_review', 'evidence': evidence,
            'checked_at': datetime.utcnow().isoformat() + 'Z'}


async def update_outcome_review(session, task_id):
    row = await session.scalar(select(GeoActionTicket).where(GeoActionTicket.id == task_id,
        GeoActionTicket.advice_code.like('cockpit:v1:%'), GeoActionTicket.status.in_(['todo', 'doing']), active_review_source())
        .with_for_update(skip_locked=True))
    if row is None or not (row.progress_first or {}).get('params', {}).get('content_task_id'):
        return
    try:
        assessment = await assess_outcome(session, row)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        assessment = {'state': 'waiting', 'reason': exc.detail, 'checked_at': datetime.utcnow().isoformat() + 'Z'}
    row.progress = {**(row.progress or {}), 'outcome_review': assessment, 'outcome_review_error': None,
                    'outcome_review_next_at': (datetime.utcnow() + timedelta(hours=24)).isoformat() + 'Z'}
    if assessment['state'] == 'needs_review':
        code = 'review:v1:' + str(row.id)
        follow = await session.scalar(select(GeoActionTicket).where(
            GeoActionTicket.tenant_id == row.tenant_id, GeoActionTicket.advice_code == code).order_by(GeoActionTicket.id).limit(1).with_for_update())
        evidence = assessment['evidence']
        if follow is None:
            follow = GeoActionTicket(tenant_id=row.tenant_id, content_task_id=row.progress_first['params']['content_task_id'],
                advice_code=code, title=f'复盘任务 #{row.id}：完整周指标尚未达标', status='todo', priority='medium',
                action='比较前后周原始回答、被引用来源和竞品内容，记录未达标原因及下一项具体修改；客户确认后执行。',
                acceptance_type='manual', acceptance_desc='记录复盘结论和下一步行动。复盘完成不等于原指标任务达标。')
            session.add(follow)
        previous = (follow.progress or {}).get('outcome_review', {}).get('evidence', {}).get('after', {}).get('as_of')
        if previous != evidence['after']['as_of']:
            if follow.status == 'done':
                follow.status, follow.closed_at = 'reopened', None
                follow.last_verdict = None
            follow.evidence = append_evidence(follow.evidence, check=evidence['metric_key'], result='needs_review',
                note=f"{evidence['before']['value']} → {evidence['after']['value']}，周结束 {evidence['after']['as_of']}；{evidence['source']}", limit=30)
        follow.progress = {**(follow.progress or {}), 'source_task_id': row.id, 'outcome_review': assessment, 'current_outcome_review': assessment}
        follow.title = f'复盘任务 #{row.id}：完整周指标尚未达标'
        follow.last_note = '完整周实际观察尚未达到目标，请记录复盘结论与下一步行动'
    else:
        # Keep the historical review and human conclusion, but expose the latest
        # observation so old work cannot advertise an obsolete metric result.
        follow = await session.scalar(select(GeoActionTicket).where(
            GeoActionTicket.tenant_id == row.tenant_id,
            GeoActionTicket.advice_code == 'review:v1:' + str(row.id))
            .order_by(GeoActionTicket.id).limit(1).with_for_update())
        if follow is not None:
            follow.title = f'复盘任务 #{row.id}：历史观察复盘'
            follow.progress = {**(follow.progress or {}), 'current_outcome_review': assessment}
            follow.last_note = ('当前观察已达目标；历史复盘记录保留，原指标任务须单独验收'
                               if assessment['state'] == 'target_met'
                               else '当前待观察：' + assessment.get('reason', '缺少可比数据'))
    await session.commit()


async def run_outcome_reviews():
    from app.database import async_session_factory
    import logging
    due = func.coalesce(GeoActionTicket.progress['outcome_review_next_at'].astext, '')
    now = datetime.utcnow().isoformat() + 'Z'
    async with async_session_factory() as session:
        ids = list(await session.scalars(select(GeoActionTicket.id).where(
            GeoActionTicket.advice_code.like('cockpit:v1:%'), GeoActionTicket.status.in_(['todo', 'doing']),
            active_review_source(), due <= now)
            .order_by(due, GeoActionTicket.id).limit(100)))
    for task_id in ids:
        try:
            async with async_session_factory() as session:
                await update_outcome_review(session, task_id)
        except Exception:
            logging.getLogger(__name__).exception('GEO outcome review failed for task %s', task_id)
            try:
                async with async_session_factory() as session:
                    row = await session.scalar(select(GeoActionTicket).where(
                        GeoActionTicket.id == task_id, GeoActionTicket.advice_code.like('cockpit:v1:%'))
                        .with_for_update(skip_locked=True))
                    if row is not None:
                        now = datetime.utcnow()
                        row.progress = {**(row.progress or {}), 'outcome_review_error': '本次评估执行失败，稍后自动重试',
                                        'outcome_review_next_at': (now + timedelta(hours=1)).isoformat() + 'Z'}
                        await session.commit()
            except Exception:
                logging.getLogger(__name__).exception('Could not defer GEO outcome task %s', task_id)
