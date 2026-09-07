"""搜索词报告接口（全量落库的搜索词查询 + 手动同步触发）。

数据源 = search_term_reports（百度搜索词报告 reportType 2307838 全量快照，app/baidu/sync.py）。
归 optimize.searchterms 菜单。加否词/转拓词写回为阶段二（复用 dry-run 框架）。
"""
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.sync import sync_search_terms_for_account
from app.baidu.writeback import (
    WritebackError,
    apply_add_word_writeback,
    apply_negative_writeback,
)
from app.database import get_session
from app.models import (
    MATCH_MODE_LABELS,
    QUERY_STATUS_LABELS,
    WB_ACTION_STATUS_LABELS,
    WRITEBACK_ACTION_LABELS,
    BaiduAccount,
    SearchTermReport,
    WritebackAction,
)
from app.security.auth import AuthContext, require_scoped_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/search-terms",
    tags=["搜索词报告"],
    dependencies=[Depends(require_scoped_auth)],
)


def _to_dict(r: SearchTermReport) -> dict:
    return {
        "id": r.id,
        "baidu_account_id": r.baidu_account_id,
        "query_word": r.query_word,
        "trigger_keyword": r.trigger_keyword,
        "query_status": r.query_status,
        "status_label": QUERY_STATUS_LABELS.get(r.query_status, "—"),
        "is_added": r.is_added,
        "campaign_id": r.campaign_id,
        "campaign_name": r.campaign_name,
        "adgroup_id": r.adgroup_id,
        "adgroup_name": r.adgroup_name,
        "impression": r.impression,
        "click": r.click,
        "cost": float(r.cost) if r.cost is not None else None,
        "ctr": float(r.ctr) if r.ctr is not None else None,
        "cpc": float(r.cpc) if r.cpc is not None else None,
    }


@router.get("")
async def list_search_terms(
    tenant_id: int = Query(..., description="本地租户 ID"),
    baidu_account_id: int | None = Query(None, gt=0, description="百度账户 ID；多账户时用于隔离窗口"),
    campaign_id: int | None = Query(None),
    adgroup_id: int | None = Query(None),
    status: str | None = Query(None, description="added / not_added，留空看全部"),
    has_click: bool | None = Query(None, description="true 只看有点击；false 只看零点击"),
    q: str | None = Query(None, description="搜索词模糊匹配"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """搜索词列表（分页 + 筛选）+ 汇总（总数/有点击数/展现·点击·消费合计 + 窗口）。"""
    cond = [SearchTermReport.tenant_id == tenant_id]
    if baidu_account_id is not None:
        cond.append(SearchTermReport.baidu_account_id == baidu_account_id)
    if campaign_id is not None:
        cond.append(SearchTermReport.campaign_id == campaign_id)
    if adgroup_id is not None:
        cond.append(SearchTermReport.adgroup_id == adgroup_id)
    if status == "added":
        cond.append(SearchTermReport.query_status == 0)
    elif status == "not_added":
        cond.append(SearchTermReport.query_status == 1)
    if has_click is True:
        cond.append(SearchTermReport.click > 0)
    elif has_click is False:
        cond.append(func.coalesce(SearchTermReport.click, 0) == 0)
    if q:
        cond.append(SearchTermReport.query_word.ilike(f"%{q}%"))

    total = await session.scalar(select(func.count()).select_from(SearchTermReport).where(*cond))

    rows = (
        await session.scalars(
            select(SearchTermReport)
            .where(*cond)
            .order_by(SearchTermReport.impression.desc().nulls_last(), SearchTermReport.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    # 汇总（不受分页影响，但受筛选影响）
    agg = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(SearchTermReport.click > 0),
                func.coalesce(func.sum(SearchTermReport.impression), 0),
                func.coalesce(func.sum(SearchTermReport.click), 0),
                func.coalesce(func.sum(SearchTermReport.cost), 0),
            ).where(*cond)
        )
    ).one()
    window_rows = (
        await session.execute(
            select(
                SearchTermReport.baidu_account_id,
                SearchTermReport.window_start,
                SearchTermReport.window_end,
                func.min(SearchTermReport.synced_at),
                func.max(SearchTermReport.synced_at),
                func.count(),
            )
            .where(*cond)
            .group_by(
                SearchTermReport.baidu_account_id,
                SearchTermReport.window_start,
                SearchTermReport.window_end,
            )
            .order_by(SearchTermReport.baidu_account_id, SearchTermReport.window_start, SearchTermReport.window_end)
        )
    ).all()
    windows = [
        {
            "baidu_account_id": row[0],
            "start": row[1].isoformat() if row[1] else None,
            "end": row[2].isoformat() if row[2] else None,
            "oldest_synced_at": row[3].isoformat() if row[3] else None,
            "synced_at": row[4].isoformat() if row[4] else None,
            "stored_rows": int(row[5]),
        }
        for row in window_rows
    ]
    mixed_windows = len({(row[1], row[2]) for row in window_rows}) > 1

    return {
        "total": int(total or 0),
        "summary": {
            "terms": int(agg[0]),
            "with_click": int(agg[1]),
            "impression": int(agg[2]),
            "click": int(agg[3]),
            "cost": float(agg[4]),
        },
        "account_scope": {"mode": "single" if baidu_account_id is not None else "all", "baidu_account_id": baidu_account_id},
        "windows": windows,
        "mixed_windows": mixed_windows,
        "summary_comparable": not mixed_windows,
        "window": windows[0] if len(windows) == 1 else None,
        "search_terms": [_to_dict(r) for r in rows],
        "scope_note": "多窗口数据仅展示已存快照合计，不代表同一统计期" if mixed_windows else None,
    }


@router.post("/sync")
async def sync_search_terms(
    tenant_id: int = Query(..., description="本地租户 ID"),
    baidu_account_id: int | None = Query(None, gt=0, description="百度账户 ID；多账户租户必须显式选择"),
    days: int = Query(30, ge=1, le=91, description="回溯天数（搜索词报告最大 91 天）"),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """手动从百度拉取搜索词报告并全量落库（窗口快照覆盖）。"""
    ctx.ensure_tenant(tenant_id)
    account_query = select(BaiduAccount).where(
        BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active"
    )
    if baidu_account_id is not None:
        account_query = account_query.where(BaiduAccount.id == baidu_account_id)
    accounts = (await session.scalars(account_query.order_by(BaiduAccount.id).limit(2))).all()
    if not accounts:
        raise HTTPException(404, "该租户没有生效的百度账户授权")
    if baidu_account_id is None and len(accounts) > 1:
        raise HTTPException(409, "该租户有多个生效百度账户，请先选择要同步的账户")
    acc = accounts[0]
    end = date.today()
    start = end - timedelta(days=days - 1)
    n = await sync_search_terms_for_account(session, acc, start, end)
    return {"status": "ok", "synced": n, "baidu_account_id": acc.id,
            "window": {"start": start.isoformat(), "end": end.isoformat()}}


# ===== 加否词 / 转拓词（写回百度，dry-run 保护，记 writeback_actions） =====


def _action_dict(r: WritebackAction) -> dict:
    return {
        "id": r.id,
        "baidu_account_id": r.baidu_account_id,
        "action_type": r.action_type,
        "action_label": WRITEBACK_ACTION_LABELS.get(r.action_type, r.action_type),
        "word": r.word,
        "match_mode": r.match_mode,
        "match_label": MATCH_MODE_LABELS.get(r.match_mode, r.match_mode),
        "price": float(r.price) if r.price is not None else None,
        "old_value": float(r.old_value) if r.old_value is not None else None,
        "new_value": float(r.new_value) if r.new_value is not None else None,
        "execution_mode": "dry_run" if r.dry_run else "live",
        "execution_mode_label": "演练（未修改百度）" if r.dry_run else "真实执行",
        "campaign_name": r.campaign_name,
        "adgroup_id": r.adgroup_id,
        "adgroup_name": r.adgroup_name,
        "dry_run": r.dry_run,
        "status": r.status,
        "status_label": WB_ACTION_STATUS_LABELS.get(r.status, r.status),
        "error_msg": r.error_msg,
        "operator_name": r.operator_name,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


class NegativeRequest(BaseModel):
    tenant_id: int
    word: str
    adgroup_id: int
    match_mode: str = "exact"  # exact=精确否 / phrase=短语否


class ExpandRequest(BaseModel):
    tenant_id: int
    word: str
    adgroup_id: int
    price: float
    match_mode: str = "phrase"


@router.post("/negative")
async def add_negative(
    req: NegativeRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """把搜索词加成单元否词（updateAdgroup 追加）。dry-run 保护 + 台账。"""
    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_negative_writeback(
            session, req.tenant_id, req.word, req.adgroup_id,
            match_mode=req.match_mode, operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "dry_run": rec.dry_run, "action": _action_dict(rec)}


@router.post("/expand")
async def expand_to_keyword(
    req: ExpandRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """把搜索词加成正式关键词（addWord）到指定单元。dry-run 保护 + 台账。"""
    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_add_word_writeback(
            session, req.tenant_id, req.word, req.adgroup_id,
            price=req.price, match_mode=req.match_mode,
            operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "dry_run": rec.dry_run, "action": _action_dict(rec)}


@router.get("/actions")
async def list_actions(
    tenant_id: int = Query(..., description="本地租户 ID"),
    action_type: str | None = Query(None, description="negative / add_word"),
    limit: int = Query(200, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """加否词 / 转拓词台账（按时间倒序）。"""
    cond = [WritebackAction.tenant_id == tenant_id]
    if action_type:
        cond.append(WritebackAction.action_type == action_type)
    rows = (
        await session.scalars(
            select(WritebackAction).where(*cond).order_by(WritebackAction.id.desc()).limit(limit)
        )
    ).all()
    return {"actions": [_action_dict(r) for r in rows]}
