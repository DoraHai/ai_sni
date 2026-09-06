"""GEO contract adapter; no outbound cockpit connection or schema migration."""
import json
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from app.database import get_session
from app.models import GeoActionTicket, Tenant
from app.security.auth import require_scoped_auth
from app.geo.integration_metrics import load_weekly_snapshot, metric_dictionary, MENTIONS, RATE, SCORE
from app.geo.tenant_scope import require_geo_read_entitlement

router = APIRouter(prefix='/integration', tags=['GEO shared contract'])
PREFIX = 'cockpit:v1:'
STATUS = {'todo': 'open', 'doing': 'in_progress', 'done': 'done', 'cancelled': 'cancelled'}
REVERSE_STATUS = {value:key for key,value in STATUS.items()}


class MetricTrend(BaseModel):
    model_config = ConfigDict(extra='forbid')
    direction: Literal['up', 'down', 'flat'] | None
    change_pct: float | None
    change_abs: int | float | None


class MetricSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metric_key: str
    value: int | float | None
    unit: str
    as_of: datetime
    trend_7d: MetricTrend | None


class TaskContract(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: int
    module: Literal['geo']
    action_type: str
    title: str
    params: dict
    status: Literal['open','in_progress','done','cancelled']
    created_by: Literal['cockpit'] | int
    assignee_role: str
    completion_evidence: dict | None
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    module: Literal['geo'] = 'geo'
    action_type: str = Field(min_length=1, max_length=80, pattern=r'^[a-z][a-z0-9_]*$')
    title: str = Field(min_length=1, max_length=300)
    params: dict = Field(default_factory=dict)
    status: Literal['open'] = 'open'
    created_by: Literal['cockpit'] | int | None = None
    assignee_role: str = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def validate_params(self):
        if not self.title.strip() or not self.assignee_role.strip():
            raise ValueError('标题和执行角色不能为空')
        if len(json.dumps(self.params, ensure_ascii=False, allow_nan=False)) > 20000:
            raise ValueError('params 超过 20000 字符')
        target = self.params.get('metric_key', MENTIONS)
        if not isinstance(target, str) or not target.startswith('geo.'):
            raise ValueError('params.metric_key 必须属于 GEO')
        if self.params.get('direction', 'increase') not in ('increase', 'decrease'):
            raise ValueError('direction 必须为 increase/decrease')
        content_id = self.params.get('content_task_id')
        if content_id is not None and (isinstance(content_id, bool) or not isinstance(content_id, int) or content_id <= 0):
            raise ValueError('content_task_id 必须为正整数')
        threshold = self.params.get('min_delta', 0)
        if isinstance(threshold, bool) or not isinstance(threshold, (int,float)) or not (0 <= threshold < float('inf')):
            raise ValueError('min_delta 必须为有限非负数')
        if target in (RATE, SCORE) and threshold > 100:
            raise ValueError('提及率和可见度分数的绝对变化量不能超过 100')
        return self


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['open', 'in_progress', 'done', 'cancelled']


def iso(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def task_payload(row):
    meta = row.progress_first or {}
    return dict(id=row.id, module='geo', action_type=meta['action_type'], title=row.title,
                params=meta['params'], status=STATUS[row.status], created_by=meta['created_by'],
                assignee_role=meta['assignee_role'], completion_evidence=(row.progress or {}).get('completion_evidence'),
                created_at=iso(row.created_at), updated_at=iso(row.updated_at))


async def ticket(session, tenant_id, task_id, *, lock=False):
    query = select(GeoActionTicket).where(GeoActionTicket.id == task_id,
        GeoActionTicket.tenant_id == tenant_id, GeoActionTicket.advice_code == PREFIX+'task')
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(query)
    if row is None:
        raise HTTPException(404, '任务不存在')
    return row


async def snapshot(session, tenant_id, week_end=None):
    try:
        return await load_weekly_snapshot(session, tenant_id, week_end)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def metric(state, key):
    return next((m for m in state['metrics'] if m['metric_key'] == key), None)


@router.get('/metrics/snapshot', response_model=list[MetricSnapshot], dependencies=[Depends(require_geo_read_entitlement)])
async def metrics_snapshot(tenant_id: int = Query(...), week_end: date | None = None,
                           ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    return (await snapshot(session, tenant_id, week_end))['metrics']


@router.get('/metrics/dictionary', dependencies=[Depends(require_geo_read_entitlement)])
async def metrics_dictionary(tenant_id: int = Query(...), week_end: date | None = None,
                             ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    state = await snapshot(session, tenant_id, week_end)
    return metric_dictionary(state['competitor_names'])


@router.post('/tasks', status_code=201, response_model=TaskContract)
async def create_task(req: TaskCreate, tenant_id: int = Query(...),
                      ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    creator = ctx.user_id if ctx.user_id is not None else 'cockpit'
    if req.created_by is not None and req.created_by != creator:
        raise HTTPException(403, 'created_by 必须与认证身份一致')
    if await session.get(Tenant, tenant_id) is None:
        raise HTTPException(404, '客户不存在')
    content_id = req.params.get('content_task_id')
    if content_id is not None:
        from app.models.geo_content import GeoContentTask
        # Serialize creations linked to this article, including request retries.
        content = await session.scalar(select(GeoContentTask).where(
            GeoContentTask.id == content_id, GeoContentTask.tenant_id == tenant_id
        ).with_for_update().execution_options(populate_existing=True))
        if content is None:
            raise HTTPException(404, '关联内容不存在')
        if content.status == 'archived':
            raise HTTPException(409, '归档内容不能建立新的验收任务')
        rows = await session.scalars(select(GeoActionTicket).where(
            GeoActionTicket.tenant_id == tenant_id,
            GeoActionTicket.advice_code == PREFIX+'task',
            GeoActionTicket.status.in_(['todo', 'doing']),
            GeoActionTicket.progress_first['params']['content_task_id'].as_integer() == content_id
        ).order_by(GeoActionTicket.id))
        for existing in rows:
            meta = existing.progress_first or {}
            if (meta.get('params') or {}).get('metric_key', MENTIONS) != req.params.get('metric_key', MENTIONS):
                continue
            if (meta.get('params') == req.params and existing.title == req.title.strip()
                    and meta.get('action_type') == req.action_type
                    and meta.get('assignee_role') == req.assignee_role.strip()
                    and meta.get('created_by') == creator):
                return task_payload(existing)
            raise HTTPException(409, f'该内容已有相同指标的进行中验收任务 #{existing.id}，请先处理现有任务')
    baseline = await snapshot(session, tenant_id)
    if metric(baseline, req.params.get('metric_key', MENTIONS)) is None:
        raise HTTPException(400, '未知指标，请使用指标字典中的 metric_key')
    now = datetime.utcnow()
    row = GeoActionTicket(tenant_id=tenant_id, title=req.title.strip(), advice_code=PREFIX+'task',
        status='todo', acceptance_type='manual', created_by=ctx.user_id, created_at=now, updated_at=now,
        progress_first=dict(action_type=req.action_type, params=req.params, created_by=creator,
                            assignee_role=req.assignee_role.strip()), baseline_snapshot=baseline,
        progress={'completion_evidence': None})
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return task_payload(row)


@router.get('/tasks', response_model=list[TaskContract])
async def list_tasks(tenant_id: int = Query(...), status: Literal['open','in_progress','done','cancelled'] | None = None,
                     limit: int = Query(100, ge=1, le=200), after_id: int = Query(0, ge=0),
                     ctx=Depends(require_scoped_auth), session=Depends(get_session), content_task_id: int | None = None):
    ctx.ensure_tenant(tenant_id)
    query = select(GeoActionTicket).where(GeoActionTicket.tenant_id == tenant_id,
        GeoActionTicket.advice_code == PREFIX+'task', GeoActionTicket.id > after_id)
    if content_task_id is not None:
        if content_task_id <= 0:
            raise HTTPException(422, 'content_task_id 必须为正整数')
        query = query.where(GeoActionTicket.progress_first['params']['content_task_id'].as_integer() == content_task_id)
    if status:
        query = query.where(GeoActionTicket.status == REVERSE_STATUS[status])
    rows = list(await session.scalars(query.order_by(GeoActionTicket.id).limit(limit)))
    return [task_payload(row) for row in rows]


@router.get('/tasks/{task_id}', response_model=TaskContract)
async def get_task(task_id: int, tenant_id: int = Query(...), ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    return task_payload(await ticket(session, tenant_id, task_id))


def completion_evidence(row, current, publication_proof=None, *, require_target=True):
    params = row.progress_first['params']
    key = params.get('metric_key', MENTIONS)
    baseline = row.baseline_snapshot or {}
    before, after = metric(baseline, key), metric(current, key)
    if not before or not after or before['value'] is None or after['value'] is None:
        raise HTTPException(409, '目标指标尚无足量真实样本，不能完成任务')
    if before['as_of'] >= after['as_of'] or datetime.fromisoformat(current['window_start'].replace('Z','+00:00')) < row.created_at.replace(tzinfo=timezone.utc):
        raise HTTPException(409, '需等待任务创建后一个完整自然周的观测结果')
    if baseline['cohort'] != current['cohort'] or baseline['own_domains'] != current['own_domains']:
        raise HTTPException(409, '前后问题、引擎或自有域口径发生变化，不能生成完成证据')
    if not baseline.get('questions') or baseline['questions'] != current.get('questions'):
        raise HTTPException(409, '题目原文变化或缺少记录，不能生成完成证据')
    if not baseline.get('sample_counts') or baseline['sample_counts'] != current.get('sample_counts'):
        raise HTTPException(409, '前后各问题与引擎的采样次数不一致或缺少记录，不能生成完成证据')
    from app.geo.integration_metrics import complete_model_counts
    if (not complete_model_counts(baseline.get('model_counts'))
            or baseline['model_counts'] != current.get('model_counts')):
        raise HTTPException(409, '模型或供应商分布变化或缺少来源记录，不能生成完成证据')
    if params.get('content_task_id'):
        proof = publication_proof or (row.progress or {}).get('publication_evidence') or {}
        first = proof.get('first_verified_at')
        if not first or datetime.fromisoformat(first.replace('Z', '+00:00')) > datetime.fromisoformat(current['window_start'].replace('Z', '+00:00')):
            raise HTTPException(409, '后测周须完整位于已核实发布之后')
    delta = after['value'] - before['value']
    signed = delta if params.get('direction','increase') == 'increase' else -delta
    if require_target and (signed <= 0 or signed < params.get('min_delta', 0)):
        raise HTTPException(409, '真实指标变化尚未达到任务目标')
    return dict(metric_key=key, before=before, after=after, delta=round(delta,4),
                before_snapshot_ids=baseline['sample_ids'], after_snapshot_ids=current['sample_ids'],
                before_sample_counts=baseline['sample_counts'], after_sample_counts=current['sample_counts'],
                before_model_counts=baseline['model_counts'], after_model_counts=current['model_counts'],
                source=f'/api/v1/geo/integration/metrics/snapshot?tenant_id={row.tenant_id}&week_end={after["as_of"][:10]}', verified_at=iso(datetime.utcnow()),
                note='同题同引擎周指标的实际观察变化，不证明本任务造成该变化。')


@router.patch('/tasks/{task_id}', response_model=TaskContract)
async def update_task(task_id: int, req: TaskUpdate, tenant_id: int = Query(...),
                      ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    row = await ticket(session, tenant_id, task_id, lock=True)
    if STATUS[row.status] == req.status:
        return task_payload(row)
    if row.status in {'done','cancelled'}:
        raise HTTPException(409, '已结束任务不能重写，请新建后续任务')
    if req.status == 'done':
        proof = None
        if row.progress_first['params'].get('content_task_id'):
            from app.geo.publication_evidence import verify_publication
            proof = (row.progress or {}).get('publication_evidence') or {}
            if not proof.get('publication_id'):
                raise HTTPException(409, '先核验真实发布页，不能以内容就绪代替上线')
            proof = await verify_publication(session, row, proof['publication_id'])
        current = await snapshot(session, tenant_id)
        evidence = completion_evidence(row, current, proof)
        fresh = await snapshot(session, tenant_id, date.fromisoformat(evidence['before']['as_of'][:10]))
        baseline = row.baseline_snapshot
        fresh_metric = metric(fresh, evidence['metric_key'])
        if (fresh_metric is None or fresh_metric['value'] != evidence['before']['value']
                or any(fresh.get(k) != baseline.get(k) for k in ['sample_ids', 'sample_counts', 'model_counts', 'questions', 'cohort', 'own_domains'])):
            raise HTTPException(409, '基线来源已被复核更正或口径变化，不能继续使用旧基线完成任务')
        row.progress = {**(row.progress or {}), 'completion_evidence': evidence}
        if proof:
            row.progress = {**row.progress, 'publication_evidence': proof}
        row.closed_at = datetime.utcnow()
    row.status = REVERSE_STATUS[req.status]
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return task_payload(row)


@router.post('/tasks/{task_id}/baseline', response_model=TaskContract)
async def capture_baseline(task_id: int, tenant_id: int = Query(...),
                           ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    row = await ticket(session, tenant_id, task_id, lock=True)
    key = row.progress_first['params'].get('metric_key', MENTIONS)
    old = metric(row.baseline_snapshot, key)
    if row.status in {'done','cancelled'} or (old and old['value'] is not None):
        raise HTTPException(409, '已有有效基线或任务已结束，不能覆盖证据')
    state = await snapshot(session, tenant_id)
    selected = metric(state, key)
    if selected is None or selected['value'] is None:
        from app.geo.integration_metrics import baseline_window_readiness
        diagnostic = await baseline_window_readiness(session, tenant_id, key)
        raise HTTPException(409, diagnostic['message'])
    row.baseline_snapshot = state
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return task_payload(row)


@router.get('/tasks/{task_id}/retest-plan')
async def get_retest_plan(task_id: int, tenant_id: int = Query(...),
                          ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    from app.geo.retest import prepare_retest
    ctx.ensure_tenant(tenant_id)
    row = await ticket(session, tenant_id, task_id)
    return await prepare_retest(session, row, check_window=False)


@router.post('/tasks/{task_id}/retest', status_code=202)
async def start_retest(task_id: int, background_tasks: BackgroundTasks, tenant_id: int = Query(...),
                       ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    from app.models import GeoVisibilityPatrolRun
    from app.geo.retest import prepare_retest
    from app.geo.content.patrol import run_patrol_in_background, count_patrol_runs_today
    from app.config import get_settings
    ctx.ensure_tenant(tenant_id)
    await session.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    row = await ticket(session, tenant_id, task_id, lock=True)
    from app.geo.integration_metrics import closed_week_end
    from app.geo.content.time_windows import shanghai_day_bounds_utc_naive
    period = shanghai_day_bounds_utc_naive(closed_week_end())[0].isoformat()
    progress = dict(row.progress or {})
    if period in progress.get('retest_runs', {}):
        return {'run_id': progress['retest_runs'][period], 'already_started': True}
    plan = await prepare_retest(session, row)
    limit = max(1, min(int(get_settings().geo_patrol_max_runs_per_day or 24), 500))
    if await count_patrol_runs_today(session, tenant_id) >= limit:
        raise HTTPException(429, '今日巡检次数已达上限')
    # Durable weekly reservation remains even if the worker fails or creates no samples.
    run = GeoVisibilityPatrolRun(tenant_id=tenant_id, status='pending', trigger='contract_retest',
        auto_persist=True, prefer_real=True, prompt_limit=len({c['prompt_id'] for c in plan['cells']}),
        engine_keys=sorted({c['engine'] for c in plan['cells']}), summary={'contract_plan': plan}, created_by=ctx.user_id)
    session.add(run)
    await session.flush()
    progress['retest_runs'] = {**progress.get('retest_runs', {}), plan['window_start']: run.id}
    row.progress = progress
    await session.commit()
    background_tasks.add_task(run_patrol_in_background, run.id)
    return {'run_id': run.id, 'already_started': False, 'plan': plan}


class PublicationCheck(BaseModel):
    model_config = ConfigDict(extra='forbid')
    publication_id: int = Field(gt=0)


@router.post('/tasks/{task_id}/publication-check', response_model=TaskContract)
async def check_publication(task_id: int, req: PublicationCheck, tenant_id: int = Query(...),
                            ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    from app.geo.publication_evidence import verify_publication
    ctx.ensure_tenant(tenant_id)
    row = await ticket(session, tenant_id, task_id, lock=True)
    if row.status in {'done', 'cancelled'}:
        raise HTTPException(409, '终态任务不能重写证据')
    proof = await verify_publication(session, row, req.publication_id)
    row.progress = {**(row.progress or {}), 'publication_evidence': proof}
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return task_payload(row)


@router.get('/tasks/{task_id}/execution-readiness')
async def execution_readiness(task_id: int, tenant_id: int = Query(...),
                              ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    from app.geo.content.multi_push import tenant_auto_push_matrix
    from app.geo.retest import prepare_retest
    ctx.ensure_tenant(tenant_id)
    row = await ticket(session, tenant_id, task_id)
    matrix = await tenant_auto_push_matrix(session, tenant_id=tenant_id)
    plan, blocker = None, None
    try:
        plan = await prepare_retest(session, row, check_window=False)
    except HTTPException as exc:
        blocker = exc.detail
    baseline = metric(row.baseline_snapshot or {'metrics': []}, row.progress_first['params'].get('metric_key', MENTIONS))
    baseline_valid = bool(baseline and baseline['value'] is not None)
    terminal = row.status in {'done', 'cancelled'}
    retest_blocker = blocker
    if plan and not terminal:
        try:
            await prepare_retest(session, row, check_window=True)
        except HTTPException as exc:
            retest_blocker = exc.detail
    publication_candidates = []
    content_id = row.progress_first['params'].get('content_task_id')
    if content_id:
        from app.models import GeoPublication, GeoChannelVariant, GeoContentTask, GeoArticleVersion
        latest_article = await session.scalar(select(GeoArticleVersion.id).join(
            GeoContentTask, GeoContentTask.id == GeoArticleVersion.task_id).where(
            GeoContentTask.id == content_id, GeoContentTask.tenant_id == tenant_id)
            .order_by(GeoArticleVersion.version_no.desc()).limit(1))
        if latest_article:
            publications = (await session.execute(select(GeoPublication, GeoChannelVariant.channel).join(
                GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).join(
                GeoContentTask, GeoContentTask.id == GeoChannelVariant.task_id).where(
                GeoContentTask.id == content_id, GeoContentTask.tenant_id == tenant_id,
                GeoChannelVariant.article_version_id == latest_article,
                GeoPublication.status == 'published', GeoPublication.published_url.is_not(None))
                .order_by(GeoPublication.id.desc()).limit(50))).all()
            publication_candidates = [{'id': pub.id, 'channel': channel, 'url': pub.published_url}
                                      for pub, channel in publications if pub.published_url]
    latest_retest = None
    reservations = (row.progress or {}).get('retest_runs') or {}
    if reservations:
        from app.models import GeoVisibilityPatrolRun
        period = max(reservations)
        run = await session.scalar(select(GeoVisibilityPatrolRun).where(
            GeoVisibilityPatrolRun.id == reservations[period], GeoVisibilityPatrolRun.tenant_id == tenant_id))
        if run:
            latest_retest = {'id': run.id, 'status': run.status, 'window_start': period,
                             'result': (run.summary or {}).get('retest_result'), 'error': run.error}
    return {'task_id': row.id, 'status': STATUS[row.status], 'retest_plan': plan, 'baseline_blocker': blocker,
            'baseline': baseline, 'baseline_valid': baseline_valid,
            'retest_blocker': retest_blocker, 'can_retest': bool(plan and not terminal and not retest_blocker),
            'latest_retest': latest_retest, 'publication_candidates': publication_candidates,
            'publication_evidence': (row.progress or {}).get('publication_evidence'),
            'outcome_review': (row.progress or {}).get('outcome_review'),
            'outcome_review_error': (row.progress or {}).get('outcome_review_error'),
            'publishing': matrix, 'completion_evidence': (row.progress or {}).get('completion_evidence')}


@router.get('/tasks/{task_id}/baseline-readiness')
async def baseline_readiness(task_id: int, tenant_id: int = Query(...),
                             ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    from app.geo.integration_metrics import baseline_window_readiness
    ctx.ensure_tenant(tenant_id)
    row = await ticket(session, tenant_id, task_id)
    key = (row.progress_first or {}).get('params', {}).get('metric_key', MENTIONS)
    try:
        return await baseline_window_readiness(session, tenant_id, key)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
