"""待验证调价接口（效果验证 · 待验证调价）。menu = verify.pending。

近 N 天出价调整 + 调前/后效果 + AI 研判 + 人工标记已验证。🚫 只读聚合 + 判定，不写回百度。
"""
from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.adjustment_verify import build_one, generate_verdict, list_pending
from app.ai.budget_adjustment_verify import list_pending_budget
from app.ai.effect_verification import REVIEW_PREFIX
from app.ai.deepseek import is_enabled as ai_enabled
from app.database import get_session
from app.models import VERDICT_LABELS, AdjustmentReview, Tenant
from app.security.auth import require_scoped_auth

router = APIRouter(
    prefix="/api/v1/adjustment-verify",
    tags=["待验证调价"],
    dependencies=[Depends(require_scoped_auth)],
)


@router.get("")
async def list_adjustments(
    tenant_id: int = Query(..., description="本地租户 ID"),
    days: int = Query(7, ge=1, le=90, description="回看天数，默认近 7 天"),
    status: str | None = Query(None, pattern="^(pending|verified)$", description="pending / verified，默认全部"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    page = await list_pending(session, tenant, days=days, status=status, offset=offset, limit=limit, paged=True)
    return {
        "ai_enabled": ai_enabled(),
        "verdict_labels": VERDICT_LABELS,
        **page,
    }


@router.get("/budget")
async def list_budget_adjustments(
    tenant_id: int = Query(...), days: int = Query(7, ge=1, le=90),
    status: str | None = Query(None, pattern="^(pending|verified)$"),
    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在")
    page = await list_pending_budget(session, tenant, days=days, status=status,
                                     offset=offset, limit=limit, paged=True)
    return {"ai_enabled": False, "verdict_labels": VERDICT_LABELS, **page}


class VerifyRequest(BaseModel):
    verdict: str | None = Field(None, description="achieved / missed / watch")
    note: str | None = Field(None, max_length=500)
    reopen: bool = False  # True=改回未验证


@router.patch("/{dedup_key}")
async def mark_verified(
    dedup_key: str,
    tenant_id: int = Query(...),
    req: VerifyRequest = ...,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """标记已验证（+判定+备注）；reopen=true 改回未验证。"""
    if req.verdict is not None and req.verdict not in VERDICT_LABELS:
        raise HTTPException(400, f"非法判定 {req.verdict}，可选 {list(VERDICT_LABELS)}")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在")
    item = await build_one(session, tenant, dedup_key)
    if item is None:
        items = await list_pending_budget(session, tenant, dedup_key=dedup_key)
        item = items[0] if items else None
    if item is None:
        raise HTTPException(404, "未找到当前客户的真实调整记录")
    if not req.reopen and req.verdict in ("achieved", "missed"):
        if item["effect"]["sample"]["state"] != "ready":
            raise HTTPException(409, "样本不足或身份不明确，只能继续观察")
        if len((req.note or "").strip()) < 4:
            raise HTTPException(422, "请填写至少 4 个字的人工核对依据")
    if not req.reopen and req.verdict is None:
        raise HTTPException(422, "请选择达成、未达成或继续观察")
    rv = await session.scalar(
        select(AdjustmentReview).where(
            AdjustmentReview.tenant_id == tenant_id, AdjustmentReview.dedup_key == dedup_key
        )
    )
    if req.reopen and rv is None:
        raise HTTPException(409, "该记录尚无审核结果")
    completed = not req.reopen and req.verdict in ("achieved", "missed")
    values = {
        "status": "verified" if completed else "pending",
        "verified_at": datetime.utcnow() if completed else None,
        "verdict": None if req.reopen else req.verdict,
    }
    if not req.reopen:
        # 保存服务器重算的指标，不信任客户端上传指标；不新增表/迁移。
        values["note"] = REVIEW_PREFIX + json.dumps({
            "note": (req.note or "").strip(), "dedup_key": dedup_key,
            "baidu_account_id": item.get("baidu_account_id"),
            "keyword_id": item.get("keyword_id"), "entity_id": item.get("entity_id"),
            "effect": item["effect"], "recorded_at": datetime.utcnow().isoformat() + "Z",
        }, ensure_ascii=False)
    stmt = insert(AdjustmentReview).values(tenant_id=tenant_id, dedup_key=dedup_key, **values)
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[AdjustmentReview.tenant_id, AdjustmentReview.dedup_key], set_=values))
    await session.commit()
    return {"status": "ok", "review_status": values["status"], "verdict": values["verdict"]}


@router.post("/{dedup_key}/ai")
async def ai_verdict(
    dedup_key: str,
    tenant_id: int = Query(...),
    force: bool = Query(False),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """对一条调价生成 AI 研判（达成/未达成/继续观察）。未配 key 返回 enabled=false。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    if not ai_enabled():
        return {"enabled": False}
    item = await build_one(session, tenant, dedup_key)
    if item is None:
        raise HTTPException(404, "调价记录不存在")
    res = await generate_verdict(session, tenant, item, force=force)
    return {"enabled": True, "ai": res}
