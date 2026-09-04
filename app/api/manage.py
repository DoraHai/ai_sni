"""投放管理（计划级/账户级投放控制）。

第一项：账户日预算（安全总闸，L1 引导第一步）。
- GET  /account-budget：实时查当前账户日预算 + 余额/消费（getAccountInfo，失败降级）
- POST /account-budget：写回账户日预算（updateAccountInfo），dry-run + 台账留痕

后续计划日预算（updateCampaign budget）也归这个 router。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.regions import load_regions
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
    apply_campaign_region_writeback,
    apply_campaign_schedule_writeback,
)
from app.database import get_session
from app.models import Adgroup, BaiduAccount, Campaign
from app.security.auth import AuthContext, require_scoped_auth
from app.sem_asset_sync import public_sync_error

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/manage",
    tags=["投放管理"],
    dependencies=[Depends(require_scoped_auth)],
)


@router.get("/region-options")
async def list_region_options() -> dict:
    """省市地域下拉选项（只读常量，来自百度官方编码表快照）。"""
    return {"regions": list(load_regions())}


@router.get("/account-budget")
async def get_account_budget(
    tenant_id: int = Query(..., description="本地租户 ID"),
    baidu_account_id: int | None = Query(None, description="百度账户本地 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """实时查账户日预算 + 余额/消费。百度调用失败降级返回错误说明，不抛 500。"""
    stmt = (
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
        ).order_by(BaiduAccount.id)
    )
    if baidu_account_id is not None:
        stmt = stmt.where(BaiduAccount.id == baidu_account_id)
    accounts = list((await session.scalars(stmt)).all())
    if not accounts:
        return {"status": "error", "message": "该租户没有生效的百度账户授权"}
    if baidu_account_id is None and len(accounts) > 1:
        raise HTTPException(409, "当前客户有多个推广账户，请先选择要读取的账户")
    acc = accounts[0]
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
        "baidu_account_id": acc.id,
        "baidu_account_name": acc.baidu_username,
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
    baidu_account_id: int | None = None
    budget: float
    approval_id: int | None = None
    confirmation: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=16, max_length=128)


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
            approval_id=req.approval_id,
            confirmation=req.confirmation,
            idempotency_key=req.idempotency_key,
            baidu_account_id=req.baidu_account_id,
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
    baidu_account_id: int | None = Query(None, description="按百度账户筛选"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """计划列表（计划管理：日预算/状态，行内可改预算）。数据来自本地维度表。"""
    conditions = [Campaign.tenant_id == tenant_id]
    if baidu_account_id is not None:
        conditions.append(Campaign.baidu_account_id == baidu_account_id)
    camps = (
        await session.scalars(
            select(Campaign).where(*conditions)
        )
    ).all()
    accounts = (
        await session.scalars(
            select(BaiduAccount).where(BaiduAccount.tenant_id == tenant_id)
        )
    ).all()
    account_names = {account.id: account.baidu_username for account in accounts}
    rows = [
        {
            "campaign_id": c.campaign_id,
            "campaign_name": c.campaign_name,
            "baidu_account_id": c.baidu_account_id,
            "baidu_account_name": account_names.get(c.baidu_account_id),
            "budget": _to_float(c.budget) if c.budget is not None else None,
            "pause": c.pause,
            "status": c.status,
            "region_target": c.region_target or [],
            "region_price_factor": c.region_price_factor or [],
            "geo_location_status": c.geo_location_status,
            "schedule_price_factors": c.schedule_price_factors or [],
            "synced_at": c.synced_at.isoformat() if c.synced_at else None,
        }
        for c in camps
    ]
    rows.sort(key=lambda r: r["campaign_name"] or "")
    return {
        "total": len(rows),
        "campaigns": rows,
        "accounts": [
            {
                "id": account.id,
                "name": account.baidu_username,
                "status": account.status,
            }
            for account in sorted(accounts, key=lambda item: item.baidu_username or "")
        ],
        "min_budget": MIN_ACCOUNT_BUDGET,
        "max_budget": MAX_ACCOUNT_BUDGET,
    }


class CampaignBudgetReq(BaseModel):
    tenant_id: int
    campaign_id: int
    budget: float
    approval_id: int | None = None
    confirmation: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=16, max_length=128)


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
            approval_id=req.approval_id,
            confirmation=req.confirmation,
            idempotency_key=req.idempotency_key,
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


class CampaignScheduleFactorReq(BaseModel):
    time_id: int
    price_factor: float = 1.0


class CampaignScheduleReq(BaseModel):
    tenant_id: int
    campaign_id: int
    schedule_price_factors: list[CampaignScheduleFactorReq]
    pause: bool = False


@router.post("/campaign-schedule")
async def set_campaign_schedule(
    req: CampaignScheduleReq,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """按模板写回计划投放时段；支持节假日停投模板。"""
    ctx.ensure_tenant(req.tenant_id)
    factors = [
        {"timeId": item.time_id, "priceFactor": item.price_factor}
        for item in req.schedule_price_factors
    ]
    try:
        rec = await apply_campaign_schedule_writeback(
            session,
            req.tenant_id,
            req.campaign_id,
            factors,
            pause=req.pause,
            operator_user_id=ctx.user_id,
            operator_name=ctx.username,
        )
    except WritebackError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "status": rec.status,
        "dry_run": rec.dry_run,
        "campaign_id": req.campaign_id,
        "slot_count": len(factors),
        "pause": req.pause,
        "error_msg": rec.error_msg,
    }


class CampaignRegionFactorReq(BaseModel):
    region_id: int
    price_factor: float


class CampaignRegionReq(BaseModel):
    tenant_id: int
    campaign_id: int
    region_target: list[int]
    region_price_factor: list[CampaignRegionFactorReq] | None = None
    geo_location_status: int | None = None


@router.post("/campaign-region")
async def set_campaign_region(
    req: CampaignRegionReq,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """写回计划投放地域及分地域系数。dry-run + 台账保护。"""
    ctx.ensure_tenant(req.tenant_id)
    region_price_factor = (
        [
            {"regionId": item.region_id, "priceFactor": item.price_factor}
            for item in req.region_price_factor
        ]
        if req.region_price_factor is not None
        else None
    )
    try:
        rec = await apply_campaign_region_writeback(
            session,
            req.tenant_id,
            req.campaign_id,
            req.region_target,
            region_price_factor,
            req.geo_location_status,
            operator_user_id=ctx.user_id,
            operator_name=ctx.username,
        )
    except WritebackError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "status": rec.status,
        "dry_run": rec.dry_run,
        "baidu_account_id": rec.baidu_account_id,
        "campaign_id": req.campaign_id,
        "region_count": len(req.region_target),
        "error_msg": rec.error_msg,
    }


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
    accounts = (
        await session.scalars(
            select(BaiduAccount).where(BaiduAccount.tenant_id == tenant_id)
        )
    ).all()
    return {
        "total": len(rows),
        "adgroups": rows,
        "sync": {
            "accounts": len(accounts),
            "active_accounts": sum(account.status == "active" for account in accounts),
            "status": next(
                (account.sync_status for account in accounts if account.status == "active"),
                None,
            ),
            "last_synced_at": next(
                (
                    account.last_synced_at.isoformat()
                    for account in accounts
                    if account.status == "active" and account.last_synced_at
                ),
                None,
            ),
            "error": next(
                (
                    public_sync_error(account.last_sync_error)
                    for account in accounts
                    if account.status == "active" and account.last_sync_error
                ),
                None,
            ),
        },
    }


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
    approval_id: int | None = None
    confirmation: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=16, max_length=128)


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
            approval_id=req.approval_id,
            confirmation=req.confirmation,
            idempotency_key=req.idempotency_key,
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
