"""待验证调价接口（效果验证 · 待验证调价）。menu = verify.pending。

近 N 天出价调整 + 调前/后效果 + AI 研判 + 人工标记已验证。🚫 只读聚合 + 判定，不写回百度。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.adjustment_verify import build_one, generate_verdict, list_pending
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
    status: str | None = Query(None, description="pending / verified，默认全部"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    items = await list_pending(session, tenant, days=days, status=status)
    pending = sum(1 for it in items if it["review"]["status"] == "pending")
    return {
        "ai_enabled": ai_enabled(),
        "verdict_labels": VERDICT_LABELS,
        "summary": {"total": len(items), "pending": pending, "verified": len(items) - pending},
        "items": items,
    }


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
    rv = await session.scalar(
        select(AdjustmentReview).where(
            AdjustmentReview.tenant_id == tenant_id, AdjustmentReview.dedup_key == dedup_key
        )
    )
    if rv is None:
        rv = AdjustmentReview(tenant_id=tenant_id, dedup_key=dedup_key)
        session.add(rv)
    if req.reopen:
        rv.status = "pending"
        rv.verified_at = None
    else:
        rv.status = "verified"
        rv.verified_at = datetime.utcnow()
        if req.verdict is not None:
            rv.verdict = req.verdict
    if req.note is not None:
        rv.note = req.note or None
    await session.commit()
    return {"status": "ok", "review_status": rv.status, "verdict": rv.verdict}


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
