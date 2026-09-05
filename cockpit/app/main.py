"""驾驶舱聚合服务——第一步骨架。

职责边界：只做"拉取三个模块的指标/信号、暴露给前端、接收任务创建请求"，
不直接连 SEM/SEO/GEO 的数据库，不复用任何一个模块的代码库。
现在 sources.py / signals.py 都是假数据，接口形状先定下来，
三个开发窗口的真实接口做好之后，把 sources.py 换成真实 HTTP 调用即可。
"""
from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.contracts import CompletionEvidence, Metric, Signal, Task, TaskCreate
from app.signals import evaluate_signals
from app.sources import SOURCES
from app.store import create_task, get_task, list_tasks, mark_status

app = FastAPI(title="经营驾驶舱聚合服务", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 骨架阶段先放开，接真实前端时收紧到实际域名
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "sources": list(SOURCES.keys())}


@app.get("/api/v1/cockpit/metrics", response_model=list[Metric])
async def get_metrics(tenant_id: str) -> list[Metric]:
    """并发拉取三个模块的指标快照并合并返回。

    某一个模块的数据源挂了，不应该拖垮另外两个——这里对每个数据源单独兜底，
    这是以后接真实 HTTP 调用时最容易踩的坑，先把兜底的形状定下来。
    """
    async def _safe_fetch(source) -> list[Metric]:
        try:
            return await source.fetch_metrics(tenant_id)
        except Exception:  # noqa: BLE001 —— 骨架阶段先兜底，真实实现要落日志/告警
            return []

    results = await asyncio.gather(*(_safe_fetch(s) for s in SOURCES.values()))
    return [metric for group in results for metric in group]


@app.get("/api/v1/cockpit/signals", response_model=list[Signal])
async def get_signals(tenant_id: str) -> list[Signal]:
    return await evaluate_signals(tenant_id)


@app.post("/api/v1/cockpit/tasks", response_model=Task)
async def post_task(payload: TaskCreate) -> Task:
    return create_task(payload)


@app.get("/api/v1/cockpit/tasks", response_model=list[Task])
async def get_tasks(module: str | None = None) -> list[Task]:
    return list_tasks(module)


@app.patch("/api/v1/cockpit/tasks/{task_id}/complete", response_model=Task)
async def complete_task(task_id: str, evidence: CompletionEvidence) -> Task:
    """标记任务完成——必须带 completion_evidence，不接受裸的状态翻转。"""
    task = mark_status(task_id, "done", evidence)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


@app.get("/api/v1/cockpit/tasks/{task_id}", response_model=Task)
async def get_task_detail(task_id: str) -> Task:
    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task
