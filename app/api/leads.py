"""客户真线索台账接口（手动录入起步）。

百度埋码转化（ocpcConversionsDetail2 电话点击等）是代理指标、粗；真线索质量/成交在客户
销售台账里。本接口让客户把真线索录进来，和消费对齐算真实线索成本，是 L1 小白模式地基。
归 verify.leads 菜单。阶段一：录入/列表/状态流转/统计；阶段二再反哺 AI 调价砍词。
"""
import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.sync import sync_leads_for_account
from app.database import get_session
from app.models import (
    LEAD_INTENT_LABELS,
    LEAD_SOURCE_LABELS,
    LEAD_STATUS_LABELS,
    BaiduAccount,
    Lead,
)
from app.security.auth import AuthContext, require_scoped_auth
from app.sem_cockpit_readonly import validate_query, validate_window

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/leads",
    tags=["线索管理"],
    dependencies=[Depends(require_scoped_auth)],
)

_VALID_STATUS = set(LEAD_STATUS_LABELS)
_VALID_INTENT = set(LEAD_INTENT_LABELS)


def _lead_dict(r: Lead) -> dict:
    return {
        "id": r.id,
        "contact_name": r.contact_name,
        "phone": r.phone,
        "source_channel": r.source_channel,
        "source_label": LEAD_SOURCE_LABELS.get(r.source_channel, r.source_channel),
        "external_id": r.external_id,
        "campaign_id": r.campaign_id,
        "campaign_name": r.campaign_name,
        "keyword": r.keyword,
        "connect": r.connect,
        "status": r.status,
        "status_label": LEAD_STATUS_LABELS.get(r.status, r.status),
        "intent_level": r.intent_level,
        "intent_label": LEAD_INTENT_LABELS.get(r.intent_level) if r.intent_level else None,
        "deal_amount": float(r.deal_amount) if r.deal_amount is not None else None,
        "lead_time": r.lead_time.isoformat() if r.lead_time else None,
        "note": r.note,
        "operator_name": r.operator_name,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


class LeadCreate(BaseModel):
    tenant_id: int
    contact_name: str | None = None
    phone: str | None = None
    campaign_id: int | None = None
    campaign_name: str | None = None
    status: str = "new"
    intent_level: str | None = None
    deal_amount: float | None = Field(None, ge=0)
    lead_time: date | None = None
    note: str | None = None


class LeadUpdate(BaseModel):
    """部分更新（销售跟进）：只改传了的字段。"""

    status: str | None = None
    intent_level: str | None = None
    deal_amount: float | None = Field(None, ge=0)
    contact_name: str | None = None
    phone: str | None = None
    campaign_id: int | None = None
    campaign_name: str | None = None
    note: str | None = None


def _validate_enums(status: str | None, intent: str | None) -> None:
    if status is not None and status not in _VALID_STATUS:
        raise HTTPException(400, f"非法状态：{status}")
    if intent is not None and intent not in _VALID_INTENT:
        raise HTTPException(400, f"非法意向等级：{intent}")


def _lead_filters(tenant_id, status, campaign_id, start_date, end_date):
    _validate_enums(status, None)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "线索日期起不能晚于日期止")
    cond = [Lead.tenant_id == tenant_id]
    if status is not None:
        cond.append(Lead.status == status)
    if campaign_id is not None:
        cond.append(Lead.campaign_id == campaign_id)
    if start_date:
        cond.append(Lead.lead_time >= start_date)
    if end_date:
        cond.append(Lead.lead_time <= end_date)
    return cond


@router.get("/cockpit-summary")
async def cockpit_lead_summary(
    request: Request,
    tenant_id: int = Query(..., gt=0),
    start_date: date = Query(...),
    end_date: date = Query(...),
    status: str | None = Query(None),
    campaign_id: int | None = Query(None),
    baidu_account_id: int | None = Query(None, gt=0),
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """无个人信息的线索台账汇总；不能推断账户归因或有效咨询。"""
    ctx.ensure_tenant(tenant_id)
    validate_query(request.query_params, {"tenant_id", "start_date", "end_date",
                                          "status", "campaign_id", "baidu_account_id"})
    validate_window(start_date, end_date)
    if baidu_account_id is not None:
        raise HTTPException(422, "线索台账无可靠账户归属，不支持账户筛选")
    cond = _lead_filters(tenant_id, status, campaign_id, start_date, end_date)
    summary = await _summary(session, tenant_id, cond)
    return {
        "contract_version": "sem-cockpit-v1", "module": "sem", "is_demo": False,
        "read_only": True, "tenant_id": tenant_id, "source": "leads",
        "window": {"start": start_date.isoformat(), "end": end_date.isoformat(),
                   "timezone": "Asia/Shanghai", "inclusive": True},
        "filters": {"status": status, "campaign_id": campaign_id, "account_scope": "tenant_only"},
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": None, "completeness": "unknown",
        "metrics": {"received_leads": summary["total"], "new": summary["new"],
                    "following": summary["following"], "won": summary["won"],
                    "invalid": summary["invalid"], "not_invalid": summary["not_invalid"],
                    "deal_amount": (summary["deal_amount"] if summary["won_with_amount"] == summary["won"] else None),
                    "valid_consultations": None},
        "deal_amount_coverage": {"won": summary["won"], "with_amount": summary["won_with_amount"]},
        "units": {"counts": "count", "deal_amount": "CNY"},
        "limitations": ["仅按 lead_time 统计已有台账，未填日期不计入",
                        "状态为当前值，非历史时点状态；未标无效包含未核实新线索",
                        "无来源同步完成证据；零条不证明零咨询；更新时间未知"],
    }


@router.post("")
async def create_lead(
    req: LeadCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    _validate_enums(req.status, req.intent_level)
    if not (req.contact_name or req.phone):
        raise HTTPException(400, "姓名和联系方式至少填一项")
    lead = Lead(
        tenant_id=req.tenant_id,
        contact_name=req.contact_name,
        phone=req.phone,
        source_channel="manual",
        campaign_id=req.campaign_id,
        campaign_name=req.campaign_name,
        status=req.status,
        intent_level=req.intent_level,
        deal_amount=req.deal_amount,
        lead_time=req.lead_time,
        note=req.note,
        operator_user_id=ctx.user_id,
        operator_name=ctx.username,
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    return {"status": "ok", "lead": _lead_dict(lead)}


@router.post("/sync")
async def sync_leads(
    tenant_id: int = Query(..., description="本地租户 ID"),
    days: int = Query(30, ge=1, le=30, description="回溯天数（线索接口窗口≤30天）"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """从百度拉基木鱼营销通线索（getNoticeList）落库，按 clueId 幂等去重（已存在跳过）。"""
    ctx.ensure_tenant(tenant_id)
    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        raise HTTPException(404, "该租户没有生效的百度账户授权")
    end = date.today()
    start = end - timedelta(days=days - 1)
    n = await sync_leads_for_account(session, acc, start, end)
    return {"status": "ok", "synced": n, "window": {"start": start.isoformat(), "end": end.isoformat()}}


@router.get("")
async def list_leads(
    tenant_id: int = Query(..., description="本地租户 ID"),
    status: str | None = Query(None, description="按状态筛选"),
    campaign_id: int | None = Query(None, description="按归因计划筛选"),
    start_date: date | None = Query(None, description="线索日期起"),
    end_date: date | None = Query(None, description="线索日期止"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """线索列表及同筛选统计；统计不受分页影响。"""
    cond = _lead_filters(tenant_id, status, campaign_id, start_date, end_date)

    total = (await session.scalar(select(func.count()).select_from(Lead).where(*cond))) or 0
    rows = (
        await session.scalars(
            select(Lead).where(*cond).order_by(Lead.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    summary = await _summary(session, tenant_id, cond)
    return {
        "total": total,
        "summary": summary,
        "summary_scope": "filtered",
        "leads": [_lead_dict(r) for r in rows],
    }


async def _summary(session: AsyncSession, tenant_id: int, filters=None) -> dict:
    cond = [Lead.tenant_id == tenant_id, *(filters or [])]
    base = select(func.count()).select_from(Lead).where(*cond)
    total = (await session.scalar(base)) or 0
    following = (await session.scalar(base.where(Lead.status == "following"))) or 0
    won = (await session.scalar(base.where(Lead.status == "won"))) or 0
    deal_sum = (
        await session.scalar(
            select(func.coalesce(func.sum(Lead.deal_amount), 0)).where(
                *cond, Lead.status == "won"
            )
        )
    ) or 0
    # 未标无效包含未核实 new，不能称有效咨询。
    valid = (await session.scalar(base.where(Lead.status != "invalid"))) or 0
    win_rate = round(won / valid * 100, 1) if valid else 0.0
    return {
        "total": total,
        "following": following,
        "won": won,
        "won_with_amount": (await session.scalar(base.where(Lead.status == "won", Lead.deal_amount.is_not(None)))) or 0,
        "deal_amount": float(deal_sum),
        "win_rate": win_rate,
        "win_rate_unit": "percent",
        "win_rate_denominator": "not_invalid_in_filtered_scope",
        "not_invalid": valid,
        "new": (await session.scalar(base.where(Lead.status == "new"))) or 0,
        "invalid": (await session.scalar(base.where(Lead.status == "invalid"))) or 0,
    }


@router.patch("/{lead_id}")
async def update_lead(
    lead_id: int,
    req: LeadUpdate,
    tenant_id: int = Query(..., description="本地租户 ID（单客户隔离校验）"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    _validate_enums(req.status, req.intent_level)
    lead = await session.get(Lead, lead_id)
    if lead is None or lead.tenant_id != tenant_id:
        raise HTTPException(404, "线索不存在")
    for field, val in req.model_dump(exclude_unset=True).items():
        setattr(lead, field, val)
    await session.commit()
    await session.refresh(lead)
    return {"status": "ok", "lead": _lead_dict(lead)}


@router.delete("/{lead_id}")
async def delete_lead(
    lead_id: int,
    tenant_id: int = Query(..., description="本地租户 ID（单客户隔离校验）"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    lead = await session.get(Lead, lead_id)
    if lead is None or lead.tenant_id != tenant_id:
        raise HTTPException(404, "线索不存在")
    await session.delete(lead)
    await session.commit()
    return {"status": "ok"}
