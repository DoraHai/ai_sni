"""Tenant-scoped work tracking. Verification observes metrics; never executes ads."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sem_metrics import MetricSnapshot, snapshot
from app.config import get_settings
from app.database import get_session
from app.models.sem_task import SemTask
from app.module_scope import ensure_module_access
from app.security.auth import AuthContext, require_auth

MAX_ID = 2**63 - 1
TaskId = Annotated[int, Path(gt=0, le=MAX_ID)]
TenantId = Annotated[int, Query(gt=0, le=2**31 - 1)]
Status = Literal["open", "in_progress", "done", "cancelled"]
Role = Literal["operator", "admin"]
# Only current-state metrics with an unambiguous scope are supported initially.
# Spend/ratio targets need comparable periods and complete source evidence first.
TaskMetric = Literal["sem.accounts.active_count", "sem.approvals.pending_count",
                     "sem.identity.conflict_tenant_count"]


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_key: TaskMetric
    direction: Literal["up", "down"]
    target_value: int = Field(strict=True, ge=0, le=MAX_ID)

    @model_validator(mode="after")
    def direction_matches_action(self):
        expected = "up" if self.metric_key == "sem.accounts.active_count" else "down"
        if self.direction != expected:
            raise ValueError("该指标不支持此目标方向")
        if self.metric_key == "sem.identity.conflict_tenant_count" and self.target_value != 0:
            raise ValueError("身份冲突目标只能为 0")
        return self


class CreateTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action_type: Literal["metric_target"] = "metric_target"
    title: str = Field(min_length=1, max_length=300)
    params: Target
    assignee_role: Role = "operator"


class PatchTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    assignee_role: Role | None = None
    status: Literal["open", "in_progress", "cancelled"] | None = None

    @model_validator(mode="after")
    def nonempty_nonnull(self):
        if not self.model_fields_set or any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError("更新必须包含非空白名单字段")
        return self


class TaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    tenant_id: int
    module: Literal["sem"]
    action_type: Literal["metric_target"]
    title: str
    params: Target
    status: Status
    created_by: str
    assignee_role: Role
    baseline_snapshot: dict
    completion_evidence: dict | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    has_more: bool
    next_before_id: int | None


def enabled(response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not get_settings().sem_tasks_enabled:
        raise HTTPException(503, "SEM 任务尚未开放，需先完成独立 Schema 审核")


router = APIRouter(prefix="/api/v1/sem/tasks", tags=["SEM 任务"], dependencies=[Depends(enabled)])


async def access(request: Request, tenant_id: TenantId,
                 ctx: AuthContext = Depends(require_auth),
                 session: AsyncSession = Depends(get_session)) -> AuthContext:
    ctx.ensure_tenant(tenant_id)
    if not (ctx.can_view("monitor.dashboard") and ctx.can_view("verify.adjustments")):
        raise HTTPException(403, "需要数据看板及效果验证查看权限")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not ctx.can_edit("verify.adjustments") or not ctx.user_id or ctx.user_id <= 0:
            raise HTTPException(403, "任务变更需要实名用户及效果验证编辑权限")
    await ensure_module_access(session, ctx, tenant_id, "sem")
    return ctx


def public(row):
    keys = ("id", "tenant_id", "module", "action_type", "title", "params", "status",
            "created_by", "assignee_role", "baseline_snapshot", "completion_evidence",
            "created_at", "updated_at")
    return {key: getattr(row, key) for key in keys}


async def load(session, task_id, tenant_id, *, lock=False):
    query = select(SemTask).where(SemTask.id == task_id, SemTask.tenant_id == tenant_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(query)
    if row is None:
        raise HTTPException(404, "任务不存在")
    return row


async def observation(session, ctx, tenant_id, metric_key):
    result = await snapshot(tenant_id=tenant_id, ctx=ctx, session=session)
    selected = next((x for x in result["items"] if x["metric_key"] == metric_key), None)
    if selected is None:
        raise HTTPException(409, "指标不可用")
    item = MetricSnapshot.model_validate(selected)
    now = datetime.now(timezone.utc)
    if (item.data_status != "available" or item.value is None or item.as_of is None
            or not 0 <= (now - item.as_of).total_seconds() <= 300):
        raise HTTPException(409, "指标缺失、过期或身份冲突，不能核验")
    return {"tenant_id": tenant_id, "scope": "tenant", "source": "sem.metrics.snapshot.v1",
            "observed_at": now.isoformat(), "metric": item.model_dump(mode="json")}


@router.post("", status_code=201, response_model=TaskResponse)
async def create(req: CreateTask, tenant_id: TenantId, ctx: AuthContext = Depends(access),
                 session: AsyncSession = Depends(get_session)):
    baseline = await observation(session, ctx, tenant_id, req.params.metric_key)
    value = baseline["metric"]["value"]
    if (req.params.direction == "up" and req.params.target_value <= value
            or req.params.direction == "down" and req.params.target_value >= value):
        raise HTTPException(409, "目标必须相对基线产生真实变化")
    row = SemTask(tenant_id=tenant_id, module="sem", action_type=req.action_type, title=req.title,
                  params=req.params.model_dump(), status="open", created_by=f"user:{ctx.user_id}",
                  assignee_role=req.assignee_role, baseline_snapshot=baseline)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return public(row)


@router.get("", response_model=TaskListResponse)
async def list_tasks(tenant_id: TenantId, status: Status | None = None,
                     action_type: Literal["metric_target"] | None = None,
                     before_id: int | None = Query(None, gt=0, le=MAX_ID),
                     limit: int = Query(50, ge=1, le=100), ctx: AuthContext = Depends(access),
                     session: AsyncSession = Depends(get_session)):
    query = select(SemTask).where(SemTask.tenant_id == tenant_id)
    if status is not None:
        query = query.where(SemTask.status == status)
    if action_type is not None:
        query = query.where(SemTask.action_type == action_type)
    if before_id is not None:
        query = query.where(SemTask.id < before_id)
    rows = list((await session.scalars(query.order_by(SemTask.id.desc()).limit(limit + 1))).all())
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [public(row) for row in rows], "has_more": more,
            "next_before_id": rows[-1].id if more else None}


@router.get("/{task_id}", response_model=TaskResponse)
async def detail(task_id: TaskId, tenant_id: TenantId, ctx: AuthContext = Depends(access),
                 session: AsyncSession = Depends(get_session)):
    return public(await load(session, task_id, tenant_id))


def editable(row):
    if row.status not in {"open", "in_progress"}:
        raise HTTPException(409, "已完成或取消的任务不可修改")


@router.patch("/{task_id}", response_model=TaskResponse)
async def patch(task_id: TaskId, req: PatchTask, tenant_id: TenantId,
                ctx: AuthContext = Depends(access), session: AsyncSession = Depends(get_session)):
    row = await load(session, task_id, tenant_id, lock=True)
    editable(row)
    for key, value in req.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return public(row)


@router.delete("/{task_id}", response_model=TaskResponse)
async def cancel(task_id: TaskId, tenant_id: TenantId, ctx: AuthContext = Depends(access),
                 session: AsyncSession = Depends(get_session)):
    row = await load(session, task_id, tenant_id, lock=True)
    if row.status != "cancelled":
        editable(row)
        row.status = "cancelled"
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
    return public(row)


def validate_change(row, current):
    base = row.baseline_snapshot
    target = Target.model_validate(row.params)
    old, new = base["metric"], current["metric"]
    if (base["tenant_id"] != row.tenant_id or current["tenant_id"] != row.tenant_id
            or base["scope"] != current["scope"] or base["source"] != current["source"]
            or old["metric_key"] != new["metric_key"] or old["metric_key"] != target.metric_key
            or old["unit"] != new["unit"]
            or datetime.fromisoformat(new["as_of"]) <= datetime.fromisoformat(old["as_of"])):
        raise HTTPException(409, "证据客户、口径或时间不匹配")
    passed = (new["value"] >= target.target_value > old["value"] if target.direction == "up"
              else new["value"] <= target.target_value < old["value"])
    if not passed:
        raise HTTPException(409, "尚未观测到满足目标的指标变化")


@router.post("/{task_id}/verify", response_model=TaskResponse)
async def verify(task_id: TaskId, tenant_id: TenantId, ctx: AuthContext = Depends(access),
                 session: AsyncSession = Depends(get_session)):
    row = await load(session, task_id, tenant_id, lock=True)
    if row.status == "done":
        return public(row)  # Retrying verification never rewrites historical evidence.
    editable(row)
    current = await observation(session, ctx, tenant_id, row.params["metric_key"])
    validate_change(row, current)
    row.completion_evidence = {"baseline": row.baseline_snapshot, "result": current,
                               "target": row.params, "verified_by": f"user:{ctx.user_id}",
                               "verified_at": datetime.now(timezone.utc).isoformat(),
                               "meaning": "观测到目标变化，不证明任务与指标变化的因果关系"}
    row.status = "done"
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return public(row)
