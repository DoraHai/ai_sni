"""投放管理（计划级/账户级投放控制）。

第一项：账户日预算（安全总闸，L1 引导第一步）。
- GET  /account-budget：实时查当前账户日预算 + 余额/消费（getAccountInfo，失败降级）
- POST /account-budget：写回账户日预算（updateAccountInfo），dry-run + 台账留痕

后续计划日预算（updateCampaign budget）也归这个 router。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.services.account import AccountService
from app.baidu.sync import _account_client, _to_float, _to_int
from app.baidu.writeback import (
    MAX_ACCOUNT_BUDGET,
    MIN_ACCOUNT_BUDGET,
    WritebackError,
    apply_account_budget_writeback,
    apply_adgroup_bid_writeback,
    apply_adgroup_landing_url_writeback,
    apply_adgroup_pause_writeback,
    apply_campaign_budget_writeback,
    apply_campaign_pause_writeback,
)
from app.database import get_session
from app.models import Adgroup, BaiduAccount, Campaign
from app.security.auth import AuthContext, require_scoped_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/manage",
    tags=["投放管理"],
    dependencies=[Depends(require_scoped_auth)],
)


@router.get("/account-budget")
async def get_account_budget(
    tenant_id: int = Query(..., description="本地租户 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """实时查账户日预算 + 余额/消费。百度调用失败降级返回错误说明，不抛 500。"""
    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        return {"status": "error", "message": "该租户没有生效的百度账户授权"}
    try:
        resp = await AccountService(_account_client(acc)).get_account_info(
            ["balance", "cost", "budget", "budgetType"]
        )
    except Exception as e:  # noqa: BLE001  网络/接口异常降级
        logger.warning("tenant_id=%s 查账户预算失败: %s", tenant_id, e)
        return {"status": "error", "message": "百度账户信息暂时无法获取"}

    info = resp.get("data") or {}
    if isinstance(info, list):
        info = info[0] if info else {}
    budget_type = _to_int(info.get("budgetType"))
    return {
        "status": "ok",
        "budget": _to_float(info.get("budget")),
        "budget_type": budget_type,  # 0=不限 1=日预算
        "has_daily_budget": budget_type == 1,
        "balance": _to_float(info.get("balance")),
        "cost": _to_float(info.get("cost")),
        "min_budget": MIN_ACCOUNT_BUDGET,
        "max_budget": MAX_ACCOUNT_BUDGET,
    }


class AccountBudgetReq(BaseModel):
    tenant_id: int
    budget: float


@router.post("/account-budget")
async def set_account_budget(
    req: AccountBudgetReq,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """写回账户日预算。受 dry-run（演练只记台账不真改）+ 合法区间校验 + 台账保护。"""
    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_account_budget_writeback(
            session, req.tenant_id, req.budget,
            operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    return {
        "status": rec.status,  # dry_run / success / failed
        "dry_run": rec.dry_run,
        "old_budget": float(rec.old_value) if rec.old_value is not None else None,
        "new_budget": float(rec.new_value) if rec.new_value is not None else None,
        "error_msg": rec.error_msg,
    }


@router.get("/campaigns")
async def list_campaigns_budget(
    tenant_id: int = Query(..., description="本地租户 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """计划列表（计划管理：日预算/状态，行内可改预算）。数据来自本地维度表。"""
    camps = (
        await session.scalars(
            select(Campaign).where(Campaign.tenant_id == tenant_id)
        )
    ).all()
    rows = [
        {
            "campaign_id": c.campaign_id,
            "campaign_name": c.campaign_name,
            "budget": _to_float(c.budget) if c.budget is not None else None,
            "pause": c.pause,
            "status": c.status,
            "synced_at": c.synced_at.isoformat() if c.synced_at else None,
        }
        for c in camps
    ]
    rows.sort(key=lambda r: r["campaign_name"] or "")
    return {
        "total": len(rows),
        "campaigns": rows,
        "min_budget": MIN_ACCOUNT_BUDGET,
        "max_budget": MAX_ACCOUNT_BUDGET,
    }


class CampaignBudgetReq(BaseModel):
    tenant_id: int
    campaign_id: int
    budget: float


@router.post("/campaign-budget")
async def set_campaign_budget(
    req: CampaignBudgetReq,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """写回计划日预算。dry-run + 合法区间（≤账户预算）+ 台账保护。"""
    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_campaign_budget_writeback(
            session, req.tenant_id, req.campaign_id, req.budget,
            operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    return {
        "status": rec.status,
        "dry_run": rec.dry_run,
        "campaign_id": req.campaign_id,
        "old_budget": float(rec.old_value) if rec.old_value is not None else None,
        "new_budget": float(rec.new_value) if rec.new_value is not None else None,
        "error_msg": rec.error_msg,
    }


class CampaignPauseReq(BaseModel):
    tenant_id: int
    campaign_id: int
    pause: bool


@router.post("/campaign-pause")
async def set_campaign_pause(
    req: CampaignPauseReq,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """计划启停（暂停/恢复投放）。dry-run + 台账保护。"""
    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_campaign_pause_writeback(
            session, req.tenant_id, req.campaign_id, req.pause,
            operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    return {"status": rec.status, "dry_run": rec.dry_run, "pause": req.pause, "error_msg": rec.error_msg}


# ===== 单元管理（manage.adgroups）：列表 + 启停 + 出价 =====


@router.get("/adgroups")
async def list_adgroups_manage(
    tenant_id: int = Query(..., description="本地租户 ID"),
    campaign_id: int | None = Query(None, description="按计划筛选"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """单元列表（出价/启停状态，行内可改）。数据来自本地维度表。"""
    cond = [Adgroup.tenant_id == tenant_id]
    if campaign_id is not None:
        cond.append(Adgroup.campaign_id == campaign_id)
    adgroups = (await session.scalars(select(Adgroup).where(*cond))).all()
    camp_names = {
        c.campaign_id: c.campaign_name
        for c in (await session.scalars(select(Campaign).where(Campaign.tenant_id == tenant_id))).all()
    }
    rows = [
        {
            "adgroup_id": a.adgroup_id,
            "adgroup_name": a.adgroup_name,
            "campaign_id": a.campaign_id,
            "campaign_name": camp_names.get(a.campaign_id),
            "max_price": _to_float(a.max_price) if a.max_price is not None else None,
            "pause": a.pause,
            "status": a.status,
            "pc_final_url": a.pc_final_url,
            "mobile_final_url": a.mobile_final_url,
            "pc_track_param": a.pc_track_param,
            "mobile_track_param": a.mobile_track_param,
            "pc_track_template": a.pc_track_template,
            "mobile_track_template": a.mobile_track_template,
        }
        for a in adgroups
    ]
    rows.sort(key=lambda r: (r["campaign_name"] or "", r["adgroup_name"] or ""))
    return {"total": len(rows), "adgroups": rows}


class AdgroupPauseReq(BaseModel):
    tenant_id: int
    adgroup_id: int
    pause: bool


@router.post("/adgroup-pause")
async def set_adgroup_pause(
    req: AdgroupPauseReq,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """单元启停。dry-run + 台账保护。"""
    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_adgroup_pause_writeback(
            session, req.tenant_id, req.adgroup_id, req.pause,
            operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    return {"status": rec.status, "dry_run": rec.dry_run, "pause": req.pause, "error_msg": rec.error_msg}


class AdgroupBidReq(BaseModel):
    tenant_id: int
    adgroup_id: int
    max_price: float


@router.post("/adgroup-bid")
async def set_adgroup_bid(
    req: AdgroupBidReq,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """单元出价 maxPrice 写回。dry-run + 合法区间（≤计划预算）+ 台账保护。"""
    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_adgroup_bid_writeback(
            session, req.tenant_id, req.adgroup_id, req.max_price,
            operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    return {
        "status": rec.status,
        "dry_run": rec.dry_run,
        "adgroup_id": req.adgroup_id,
        "old_price": float(rec.old_value) if rec.old_value is not None else None,
        "new_price": float(rec.new_value) if rec.new_value is not None else None,
        "error_msg": rec.error_msg,
    }


class AdgroupLandingReq(BaseModel):
    tenant_id: int
    adgroup_id: int
    pc_final_url: str | None = None
    mobile_final_url: str | None = None
    pc_track_param: str | None = None
    mobile_track_param: str | None = None
    pc_track_template: str | None = None
    mobile_track_template: str | None = None


@router.post("/adgroup-landing-url")
async def set_adgroup_landing_url(
    req: AdgroupLandingReq,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """单元最终访问网址/监控字段写回。dry-run + 台账保护。"""
    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_adgroup_landing_url_writeback(
            session,
            req.tenant_id,
            req.adgroup_id,
            pc_final_url=req.pc_final_url,
            mobile_final_url=req.mobile_final_url,
            pc_track_param=req.pc_track_param,
            mobile_track_param=req.mobile_track_param,
            pc_track_template=req.pc_track_template,
            mobile_track_template=req.mobile_track_template,
            operator_user_id=ctx.user_id,
            operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    return {
        "status": rec.status,
        "dry_run": rec.dry_run,
        "adgroup_id": req.adgroup_id,
        "error_msg": rec.error_msg,
    }
