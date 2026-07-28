"""AI 对话助手接口（欢迎页对话框）。

- POST /chat：多轮对话（无状态，前端传 history 滑动窗口）。数据摘要每轮实时算。
- 记忆 CRUD：AI 抽取的关键信息经用户确认后落库（开放记忆，不硬加字段），每轮喂回 prompt。
归 assistant 菜单（欢迎页，内置角色都有 view）。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assistant import (
    ADOPT_TYPES,
    MESSAGE_RETAIN_DAYS,
    adopt_action,
    chat_turn,
    get_active_memories,
    load_history,
)
from app.database import get_session
from app.models import MEMORY_TYPE_LABELS, TenantMemory
from app.security.auth import AuthContext, require_scoped_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/assistant",
    tags=["AI 助手"],
    dependencies=[Depends(require_scoped_auth)],
)


class ChatRequest(BaseModel):
    tenant_id: int
    message: str  # 新的用户提问（历史由后端从库读，前端不必回传）


@router.post("/chat")
async def chat(
    req: ChatRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """一轮对话：存用户消息→读窗口→LLM→存回复。历史持久化、保留近 90 天。"""
    ctx.ensure_tenant(req.tenant_id)
    if not req.message.strip():
        raise HTTPException(400, "消息不能为空")
    return await chat_turn(session, req.tenant_id, ctx.user_id, req.message.strip())


class AdoptRequest(BaseModel):
    tenant_id: int
    type: str  # pause | adjust_bid | negative | set_budget
    keywords: list[str] = []
    adjust_pct: float | None = None  # 仅 adjust_bid（负数=降价）
    match_mode: str = "exact"  # 仅 negative
    budget: float | None = None  # 仅 set_budget（账户日预算，元）


@router.post("/adopt")
async def adopt(
    req: AdoptRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """一键采纳 AI 建议并执行（暂停/调价/加否词/设日预算）。受 dry-run + 护栏 + 台账保护。"""
    ctx.ensure_tenant(req.tenant_id)
    if req.type not in ADOPT_TYPES:
        raise HTTPException(400, f"不支持的动作类型：{req.type}")
    if req.type == "set_budget":
        if req.budget is None:
            raise HTTPException(400, "设日预算需要 budget 金额")
    elif not req.keywords:
        raise HTTPException(400, "没有可执行的关键词")
    try:
        return await adopt_action(
            session, req.tenant_id, req.type, req.keywords,
            adjust_pct=req.adjust_pct, match_mode=req.match_mode, budget=req.budget,
            operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/history")
async def history(
    tenant_id: int = Query(..., description="本地租户 ID"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """加载对话历史（保留期内，时间正序）。"""
    ctx.ensure_tenant(tenant_id)
    msgs = await load_history(session, tenant_id, ctx.user_id)
    return {
        "retain_days": MESSAGE_RETAIN_DAYS,
        "messages": [
            {"role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in msgs
        ],
    }


def _mem_dict(m: TenantMemory) -> dict:
    return {
        "id": m.id,
        "mem_type": m.mem_type,
        "type_label": MEMORY_TYPE_LABELS.get(m.mem_type, m.mem_type),
        "content": m.content,
        "source": m.source,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/memories")
async def list_memories(
    tenant_id: int = Query(..., description="本地租户 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """当前生效的客户记忆（目标/约束/偏好…）。"""
    mems = await get_active_memories(session, tenant_id)
    return {"memories": [_mem_dict(m) for m in mems]}


class MemoryCreate(BaseModel):
    tenant_id: int
    mem_type: str = "other"
    content: str
    source: str = "assistant"  # assistant=AI抽取经确认 / manual=手动


@router.post("/memories")
async def create_memory(
    req: MemoryCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """确认/新增一条客户记忆（AI 抽取的待确认条目经用户点确认后调此入库）。"""
    ctx.ensure_tenant(req.tenant_id)
    if not req.content.strip():
        raise HTTPException(400, "记忆内容不能为空")
    mem_type = req.mem_type if req.mem_type in MEMORY_TYPE_LABELS else "other"
    mem = TenantMemory(
        tenant_id=req.tenant_id,
        mem_type=mem_type,
        content=req.content.strip(),
        source=req.source,
        confirmed=True,
        active=True,
        operator_user_id=ctx.user_id,
        operator_name=ctx.username,
    )
    session.add(mem)
    await session.commit()
    await session.refresh(mem)
    return {"status": "ok", "memory": _mem_dict(mem)}


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: int,
    tenant_id: int = Query(..., description="本地租户 ID（单客户隔离）"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """软删除一条记忆（active=False，不再喂 prompt）。"""
    ctx.ensure_tenant(tenant_id)
    mem = await session.get(TenantMemory, memory_id)
    if mem is None or mem.tenant_id != tenant_id:
        raise HTTPException(404, "记忆不存在")
    mem.active = False
    await session.commit()
    return {"status": "ok"}
