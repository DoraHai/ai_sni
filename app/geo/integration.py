"""GEO contract adapter; no outbound cockpit connection or schema migration."""
import json
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from app.database import get_session
from app.models import GeoActionTicket, Tenant
from app.security.auth import require_scoped_auth
from app.geo.integration_metrics import load_weekly_snapshot, metric_dictionary, MENTIONS

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
        if self.params.get('direction', 'increase') not in {'increase', 'decrease'}:
            raise ValueError('direction 必须为 increase/decrease')
        threshold = self.params.get('min_delta', 0)
        if isinstance(threshold, bool) or not isinstance(threshold, (int,float)) or not (0 <= threshold < float('inf')):
            raise ValueError('min_delta 必须为有限非负数')
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


@router.get('/metrics/snapshot', response_model=list[MetricSnapshot])
async def metrics_snapshot(tenant_id: int = Query(...), week_end: date | None = None,
                           ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    return (await snapshot(session, tenant_id, week_end))['metrics']


@router.get('/metrics/dictionary')
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
                     ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    query = select(GeoActionTicket).where(GeoActionTicket.tenant_id == tenant_id,
        GeoActionTicket.advice_code == PREFIX+'task', GeoActionTicket.id > after_id)
    if status:
        query = query.where(GeoActionTicket.status == REVERSE_STATUS[status])
    rows = list(await session.scalars(query.order_by(GeoActionTicket.id).limit(limit)))
    return [task_payload(row) for row in rows]


@router.get('/tasks/{task_id}', response_model=TaskContract)
async def get_task(task_id: int, tenant_id: int = Query(...), ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    return task_payload(await ticket(session, tenant_id, task_id))


def completion_evidence(row, current):
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
    delta = after['value'] - before['value']
    signed = delta if params.get('direction','increase') == 'increase' else -delta
    if signed <= 0 or signed < params.get('min_delta', 0):
        raise HTTPException(409, '真实指标变化尚未达到任务目标')
    return dict(metric_key=key, before=before, after=after, delta=round(delta,4),
                before_snapshot_ids=baseline['sample_ids'], after_snapshot_ids=current['sample_ids'],
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
        current = await snapshot(session, tenant_id)
        evidence = completion_evidence(row, current)
        row.progress = {'completion_evidence': evidence}
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
        raise HTTPException(409, '当前仍无有效基线，请先完成真实采样')
    row.baseline_snapshot = state
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return task_payload(row)
