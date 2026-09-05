"""任务台账的临时存储。

现在是进程内内存字典，重启即丢——这在骨架阶段没问题，管道打通、契约稳定
之后再换成真正的数据库表。换存储时只需要重写这个文件，main.py 里的路由
不用动。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.contracts import CompletionEvidence, Task, TaskCreate

_TASKS: dict[str, Task] = {}


def create_task(payload: TaskCreate) -> Task:
    now = datetime.now(timezone.utc)
    task = Task(
        id=f"task-{uuid.uuid4().hex[:10]}",
        module=payload.module,
        action_type=payload.action_type,
        title=payload.title,
        params=payload.params,
        status="open",
        created_by=payload.created_by,
        assignee_role=payload.assignee_role,
        completion_evidence=None,
        created_at=now,
        updated_at=now,
    )
    _TASKS[task.id] = task
    return task


def list_tasks(module: str | None = None) -> list[Task]:
    tasks = list(_TASKS.values())
    if module is not None:
        tasks = [t for t in tasks if t.module == module]
    return sorted(tasks, key=lambda t: t.created_at, reverse=True)


def get_task(task_id: str) -> Task | None:
    return _TASKS.get(task_id)


def mark_status(
    task_id: str,
    status: str,
    evidence: CompletionEvidence | None = None,
) -> Task | None:
    task = _TASKS.get(task_id)
    if task is None:
        return None
    updated = task.model_copy(
        update={
            "status": status,
            "completion_evidence": evidence or task.completion_evidence,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    _TASKS[task_id] = updated
    return updated
