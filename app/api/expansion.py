"""拓词候选（原型 03-optimize/01-keyword-expand，优化执行工作流）。

候选聚合展示 + 本地状态标记 + 「加入计划」addWord 写回（dry-run 保护，见 app/baidu/writeback.py）。
候选词无所属单元，加入计划须由调用方指定目标 adgroup_id + 匹配方式 + 出价。
"""
import csv
import io
import logging
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, PositiveInt
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import is_enabled as ai_enabled
from app.ai.expansion_eval import (
    EVALUATION_META_KEY, FRESHNESS_LABELS, INTERACTIVE_WORD_LIMIT, MissingBusinessProfileError,
    context_fingerprint, evaluation_freshness, fingerprint_status,
    evaluate_candidates_for_tenant,
    supported_suggested_bid,
)
from app.baidu import BaiduAPIError
from app.baidu.writeback import (
    WritebackError,
    apply_add_word_writeback,
    apply_negative_batch_writeback,
)
from app.database import get_session
from app.models import (
    CANDIDATE_AI_RECOMMEND_LABELS,
    CANDIDATE_AI_RELEVANCE_LABELS,
    CANDIDATE_SOURCE_LABELS,
    CANDIDATE_STATUS_LABELS,
    SUGGESTED_CATEGORY_LABELS,
    KeywordCandidate,
    BaiduAccount,
    Tenant,
)
from app.security.auth import AuthContext, require_scoped_auth
from app.sem_expansion_sample import sample_planner_candidates

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/expansion",
    tags=["拓词"],
    dependencies=[Depends(require_scoped_auth)],
)

COMPETITION_LABELS = {1: "低", 2: "中", 3: "高"}


def _candidate_payload(c: KeywordCandidate, fingerprint: str | None = None) -> dict[str, Any]:
    freshness = evaluation_freshness(c, fingerprint)
    suggested_bid = supported_suggested_bid(
        c.ai_suggested_bid, c.ai_relevance, c.ai_recommend,
        c.recommend_price_pc, c.recommend_price_mobile,
    ) if freshness == "current" else None
    return {
        "id": c.id,
        "word": c.word,
        "source": c.source,
        "source_label": CANDIDATE_SOURCE_LABELS.get(c.source, c.source),
        "seed_word": c.seed_word,
        "monthly_pv": c.monthly_pv,
        "pc_pv": c.pc_pv,
        "mobile_pv": c.mobile_pv,
        "competition": c.competition,
        "competition_label": COMPETITION_LABELS.get(c.competition),
        "recommend_price_pc": float(c.recommend_price_pc) if c.recommend_price_pc is not None else None,
        "recommend_price_mobile": (
            float(c.recommend_price_mobile) if c.recommend_price_mobile is not None else None
        ),
        "preset_price": float(c.preset_price) if c.preset_price is not None else None,
        "preset_match_mode": c.preset_match_mode,
        "show_reasons": c.show_reasons or [],
        "impression": c.impression,
        "click": c.click,
        "cost": float(c.cost) if c.cost is not None else None,
        "matched_keyword": c.matched_keyword,
        "potential_score": float(c.potential_score) if c.potential_score is not None else None,
        "suggested_category": c.suggested_category,
        "suggested_category_label": SUGGESTED_CATEGORY_LABELS.get(c.suggested_category),
        "status": c.status,
        "status_label": CANDIDATE_STATUS_LABELS.get(c.status, c.status),
        # AI 语义相关性研判（未评估时为 null，前端不显示徽章）
        "ai_relevance": c.ai_relevance,
        "ai_relevance_label": CANDIDATE_AI_RELEVANCE_LABELS.get(c.ai_relevance),
        "ai_recommend": c.ai_recommend,
        "ai_recommend_label": CANDIDATE_AI_RECOMMEND_LABELS.get(c.ai_recommend),
        "ai_reason": c.ai_reason,
        "ai_suggested_bid": suggested_bid,
        "ai_bid_reason": c.ai_bid_reason if suggested_bid is not None else None,
        "ai_evaluated_at": c.ai_evaluated_at.isoformat() if c.ai_evaluated_at else None,
        "ai_freshness": freshness,
        "ai_freshness_label": FRESHNESS_LABELS[freshness],
    }


def _filters(
    tenant_id: int,
    source: str | None,
    status: str | None,
    suggested_category: str | None,
    min_score: float | None,
    q: str | None,
    ai_relevance: str | None = None,
) -> list:
    cond = [KeywordCandidate.tenant_id == tenant_id]
    if source:
        cond.append(KeywordCandidate.source == source)
    if status:
        cond.append(KeywordCandidate.status == status)
    if suggested_category:
        cond.append(KeywordCandidate.suggested_category == suggested_category)
    if min_score is not None:
        cond.append(KeywordCandidate.potential_score >= min_score)
    if q:
        cond.append(KeywordCandidate.word.ilike(f"%{q}%"))
    if ai_relevance:
        # "隐藏通用噪音" = 前端传 relevant，只看业务相关词
        cond.append(KeywordCandidate.ai_relevance == ai_relevance)
    return cond


@router.get("/candidates")
async def list_candidates(
    tenant_id: int = Query(..., description="本地租户 ID"),
    source: str | None = Query(None, description="planner / query"),
    status: str | None = Query(None, description="pending / adopted / ignored"),
    suggested_category: str | None = Query(None),
    min_score: float | None = Query(None, ge=0, le=10),
    q: str | None = Query(None, description="候选词模糊搜索"),
    ai_relevance: str | None = Query(
        None, description="AI 相关性：relevant / generic / irrelevant"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """候选列表（默认按潜力分降序）+ 各源待处理计数 + 状态计数 + AI 相关性计数。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")
    fingerprint = context_fingerprint(tenant)
    cond = _filters(tenant_id, source, status, suggested_category, min_score, q, ai_relevance)

    total = await session.scalar(
        select(func.count()).select_from(KeywordCandidate).where(*cond)
    )
    rows = (
        await session.scalars(
            select(KeywordCandidate)
            .where(*cond)
            .order_by(
                KeywordCandidate.potential_score.desc().nulls_last(),
                KeywordCandidate.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    # 源卡计数（pending 口径，不受筛选影响）+ 状态计数
    src_rows = (
        await session.execute(
            select(KeywordCandidate.source, func.count())
            .where(
                KeywordCandidate.tenant_id == tenant_id,
                KeywordCandidate.status == "pending",
            )
            .group_by(KeywordCandidate.source)
        )
    ).all()
    status_rows = (
        await session.execute(
            select(KeywordCandidate.status, func.count())
            .where(KeywordCandidate.tenant_id == tenant_id)
            .group_by(KeywordCandidate.status)
        )
    ).all()
    # AI 相关性计数（pending 口径，不受筛选影响）+ 待评估数（pending 且未评估）
    ai_rows = (
        await session.execute(
            select(KeywordCandidate.ai_relevance, func.count())
            .where(
                KeywordCandidate.tenant_id == tenant_id,
                KeywordCandidate.status == "pending",
            )
            .group_by(KeywordCandidate.ai_relevance)
        )
    ).all()
    ai_relevance_counts = {r: int(n) for r, n in ai_rows if r is not None}
    ai_unevaluated = sum(int(n) for r, n in ai_rows if r is None)

    # Pending only, independent of filters/pagination; no historical backfill.
    # Keep JSON types: a numeric hash must be unverified, not a string fingerprint.
    # Extraction also tolerates legacy non-object raw values.
    stamp = func.jsonb_extract_path(
        KeywordCandidate.raw, EVALUATION_META_KEY, "context_hash", type_=JSONB,
    )
    provenance_rows = (await session.execute(
        select(stamp, func.count()).where(
            KeywordCandidate.tenant_id == tenant_id,
            KeywordCandidate.status == "pending",
            KeywordCandidate.ai_evaluated_at.is_not(None),
        ).group_by(stamp)
    )).all()
    freshness_counts = {"current": 0, "stale": 0, "unverified": 0}
    for stored, count in provenance_rows:
        freshness_counts[fingerprint_status(stored, fingerprint)] += int(count)

    last_synced = await session.scalar(
        select(func.max(KeywordCandidate.synced_at)).where(
            KeywordCandidate.tenant_id == tenant_id
        )
    )
    last_ai_eval = await session.scalar(
        select(func.max(KeywordCandidate.ai_evaluated_at)).where(
            KeywordCandidate.tenant_id == tenant_id
        )
    )

    return {
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
        "last_synced_at": last_synced.isoformat() if last_synced else None,
        "source_pending_counts": {s: int(n) for s, n in src_rows},
        "status_counts": {s: int(n) for s, n in status_rows},
        "category_options": [
            {"code": code, "label": label}
            for code, label in SUGGESTED_CATEGORY_LABELS.items()
        ],
        # AI 评估：开关 + 相关性计数 + 待评估数 + 最近评估时间（前端控制评估按钮/筛选/徽章）
        "ai_enabled": ai_enabled(),
        "ai_relevance_counts": ai_relevance_counts,
        "ai_unevaluated": int(ai_unevaluated),
        "ai_freshness_counts": freshness_counts,
        "ai_relevance_options": [
            {"code": code, "label": label}
            for code, label in CANDIDATE_AI_RELEVANCE_LABELS.items()
        ],
        "last_ai_eval_at": last_ai_eval.isoformat() if last_ai_eval else None,
        "candidates": [_candidate_payload(c, fingerprint) for c in rows],
    }


@router.patch("/candidates/{candidate_id}/status")
async def update_candidate_status(
    candidate_id: int,
    tenant_id: int = Query(...),
    status: str = Query(..., description="pending / adopted / ignored"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """本地状态标记。adopted 仅是"已线下采纳"的记号，不写回百度（红线）。"""
    if status not in CANDIDATE_STATUS_LABELS:
        raise HTTPException(400, f"非法状态 {status}，可选 {list(CANDIDATE_STATUS_LABELS)}")
    cand = await session.get(KeywordCandidate, candidate_id)
    if cand is None or cand.tenant_id != tenant_id:
        raise HTTPException(404, "候选词不存在")
    cand.status = status
    cand.status_updated_at = datetime.utcnow()
    await session.commit()
    return {"status": "ok", "id": cand.id, "candidate_status": cand.status}


class CandidateBatchRequest(BaseModel):
    tenant_id: int
    candidate_ids: list[int] = Field(min_length=1, max_length=200)


class BatchSetPresetRequest(CandidateBatchRequest):
    preset_price: float | None = Field(default=None, ge=0.01, le=999.99)
    preset_match_mode: Literal["exact", "phrase", "smart"] | None = None


class BatchSetCategoryRequest(CandidateBatchRequest):
    category: Literal["brand", "focus", "normal", "longtail", "observe", "negative"]


class BatchStatusRequest(CandidateBatchRequest):
    status: Literal["ignored", "pending"]


class BatchNegativeRequest(CandidateBatchRequest):
    adgroup_id: int
    match_mode: Literal["exact", "phrase"] = "phrase"


async def _candidate_batch_rows(
    session: AsyncSession,
    tenant_id: int,
    candidate_ids: list[int],
) -> list[KeywordCandidate]:
    unique_ids = list(dict.fromkeys(candidate_ids))
    rows = (
        await session.scalars(
            select(KeywordCandidate).where(
                KeywordCandidate.tenant_id == tenant_id,
                KeywordCandidate.id.in_(unique_ids),
            )
        )
    ).all()
    if len(rows) != len(unique_ids):
        raise HTTPException(404, "部分候选词不存在")
    return rows


@router.post("/candidates/batch-set-preset")
async def batch_set_preset(
    req: BatchSetPresetRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """批量设置候选词的预设出价/匹配方式，供加入计划时默认填充。"""
    ctx.ensure_tenant(req.tenant_id)
    if req.preset_price is None and req.preset_match_mode is None:
        raise HTTPException(400, "预设出价和匹配方式至少填写一项")
    rows = await _candidate_batch_rows(session, req.tenant_id, req.candidate_ids)
    for cand in rows:
        if req.preset_price is not None:
            cand.preset_price = req.preset_price
        if req.preset_match_mode is not None:
            cand.preset_match_mode = req.preset_match_mode
    await session.commit()
    return {"status": "ok", "updated": len(rows)}


@router.post("/candidates/batch-set-category")
async def batch_set_category(
    req: BatchSetCategoryRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """批量设置建议分类（核心关键词圈选 = 批量设为 focus）。"""
    ctx.ensure_tenant(req.tenant_id)
    rows = await _candidate_batch_rows(session, req.tenant_id, req.candidate_ids)
    for cand in rows:
        cand.suggested_category = req.category
    await session.commit()
    return {"status": "ok", "updated": len(rows)}


@router.post("/candidates/batch-status")
async def batch_set_status(
    req: BatchStatusRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """批量标记已处理（忽略）或批量恢复。"""
    ctx.ensure_tenant(req.tenant_id)
    rows = await _candidate_batch_rows(session, req.tenant_id, req.candidate_ids)
    now = datetime.utcnow()
    for cand in rows:
        cand.status = req.status
        cand.status_updated_at = now
    await session.commit()
    return {"status": "ok", "updated": len(rows)}


@router.post("/candidates/batch-negative")
async def batch_add_negative(
    req: BatchNegativeRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """批量把候选词加为指定单元的否词，逐条返回台账结果。"""
    ctx.ensure_tenant(req.tenant_id)
    rows = await _candidate_batch_rows(session, req.tenant_id, req.candidate_ids)
    try:
        writeback_results = await apply_negative_batch_writeback(
            session,
            req.tenant_id,
            [cand.word for cand in rows],
            req.adgroup_id,
            match_mode=req.match_mode,
            operator_user_id=ctx.user_id,
            operator_name=ctx.username,
        )
    except WritebackError as exc:
        raise HTTPException(400, str(exc)) from exc

    results = []
    for cand, writeback_result in zip(rows, writeback_results, strict=True):
        if writeback_result.status == "success":
            cand.status = "ignored"
            cand.status_updated_at = datetime.utcnow()
        result = {
            "candidate_id": cand.id,
            "word": cand.word,
            "status": writeback_result.status,
            "no_op": writeback_result.no_op,
        }
        if writeback_result.error_msg:
            result["error"] = writeback_result.error_msg
        results.append(result)
    await session.commit()
    return {"status": "ok", "results": results}


class AddToPlanRequest(BaseModel):
    tenant_id: int
    adgroup_id: int
    price: float
    match_mode: Literal["exact", "phrase", "smart"] = "phrase"


@router.post("/candidates/{candidate_id}/add-to-plan")
async def add_candidate_to_plan(
    candidate_id: int,
    req: AddToPlanRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """把拓词候选加成正式关键词到指定单元（addWord 写回，dry-run 保护）。

    候选词本身无所属单元，目标 adgroup_id + 匹配方式 + 出价由调用方指定。
    真写成功后把候选标记为 adopted（从待处理移除）；演练模式保持 pending。
    """
    ctx.ensure_tenant(req.tenant_id)
    cand = await session.get(KeywordCandidate, candidate_id)
    if cand is None or cand.tenant_id != req.tenant_id:
        raise HTTPException(404, "候选词不存在")
    try:
        rec = await apply_add_word_writeback(
            session, req.tenant_id, cand.word, req.adgroup_id,
            price=req.price, match_mode=req.match_mode,
            operator_user_id=ctx.user_id, operator_name=ctx.username,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    if rec.status == "failed":
        raise HTTPException(502, "百度关键词写回失败，已记录失败台账，请稍后重试")
    if rec.status == "success":  # 真写成功才标已采纳；演练保持 pending
        cand.status = "adopted"
        cand.status_updated_at = datetime.utcnow()
        await session.commit()
    return {
        "status": "ok",
        "dry_run": rec.dry_run,
        "writeback_status": rec.status,
        "candidate_status": cand.status,
    }


@router.post("/sample")
async def sample_candidates(
    tenant_id: int = Query(...),
    seed: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """One seed, at most 20 local candidates; never auto-evaluate or add words."""
    if not seed.strip() or any(c in seed for c in ",，\n\r"):
        raise HTTPException(422, "小批量拉取必须填写一个种子词")
    if await session.get(Tenant, tenant_id) is None:
        raise HTTPException(404, "客户不存在")
    accounts = (await session.scalars(select(BaiduAccount).where(
        BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active",
    ).limit(2))).all()
    if len(accounts) != 1:
        raise HTTPException(409, "小批量拉取需客户恰有一个有效推广账户；未拉取任何候选")
    try:
        count = await sample_planner_candidates(session, accounts[0], seed, limit)
    except BaiduAPIError:
        raise HTTPException(502, "百度规划师拉取失败，请检查账户授权后重试") from None
    return {"status": "ok", "tenant_id": tenant_id, "candidates_written": count,
            "limit": limit, "ai_evaluated": False}


class EvaluationSelection(BaseModel):
    retry_ids: list[PositiveInt] = Field(min_length=1, max_length=20)


@router.post("/evaluate")
async def evaluate_candidates(
    tenant_id: int = Query(..., description="本地租户 ID"),
    force: bool = Query(False, description="true=重评已评估过的候选；默认只评未评估的"),
    limit: int = Query(
        INTERACTIVE_WORD_LIMIT, ge=1, le=20,
        description="本次最多评估 5 个去重词；兼容旧客户端 1–20 输入但按 5 截断，不自动继续"
    ),
    session: AsyncSession = Depends(get_session),
    after_id: Annotated[int, Query(ge=0)] = 0,
    selection: Annotated[EvaluationSelection | None, Body()] = None,
) -> dict:
    """AI 语义相关性评估（治通用词噪音）。只评 pending 候选，按词去重批量调 DeepSeek。

    🚫 红线：只产研判、不写回百度。未配 DEEPSEEK_API_KEY 时 enabled=false。
    返回 remaining=本次未评的剩余词数（>0 说明被 limit 截断，可再调一次）。
    """
    limit = min(limit, INTERACTIVE_WORD_LIMIT)
    if selection is not None and (after_id or len(selection.retry_ids) > limit):
        # Reject rather than silently truncate: an older UI removes all submitted
        # retry IDs from its queue, which would otherwise lose unattempted words.
        raise HTTPException(422, "重试不能同时使用游标，且每次最多重试 5 词（不能超过所选上限）")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    try:
        result = await evaluate_candidates_for_tenant(
            session, tenant, force=force, limit=limit, batch_size=INTERACTIVE_WORD_LIMIT, after_id=after_id,
            retry_ids=selection.retry_ids if selection is not None else None,
        )
    except MissingBusinessProfileError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "ok", "tenant_id": tenant_id, **result}


EXPORT_MAX_ROWS = 5000


@router.get("/candidates/export")
async def export_candidates(
    tenant_id: int = Query(...),
    source: str | None = Query(None),
    status: str | None = Query(None),
    suggested_category: str | None = Query(None),
    min_score: float | None = Query(None, ge=0, le=10),
    q: str | None = Query(None),
    ai_relevance: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """按当前筛选导出 CSV（只读，最多 5000 行）。utf-8-sig 带 BOM。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")
    fingerprint = context_fingerprint(tenant)
    cond = _filters(tenant_id, source, status, suggested_category, min_score, q, ai_relevance)
    rows = (
        await session.scalars(
            select(KeywordCandidate)
            .where(*cond)
            .order_by(
                KeywordCandidate.potential_score.desc().nulls_last(),
                KeywordCandidate.id,
            )
            .limit(EXPORT_MAX_ROWS)
        )
    ).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "候选词", "来源", "种子词", "潜力分", "建议分类",
        "百度月搜索量", "竞争度", "PC指导价", "移动指导价", "特色标签",
        "窗口展现", "窗口点击", "窗口消费", "触发关键词", "状态",
        "AI相关性", "AI建议", "AI理由", "AI结果有效性",
    ])
    for c in rows:
        p = _candidate_payload(c, fingerprint)
        writer.writerow([
            p["word"], p["source_label"], p["seed_word"] or "",
            p["potential_score"], p["suggested_category_label"] or "",
            p["monthly_pv"], p["competition_label"] or "",
            p["recommend_price_pc"], p["recommend_price_mobile"],
            " / ".join(p["show_reasons"]),
            p["impression"], p["click"], p["cost"], p["matched_keyword"] or "",
            p["status_label"],
            p["ai_relevance_label"] or "", p["ai_recommend_label"] or "", p["ai_reason"] or "",
            p["ai_freshness_label"],
        ])
    filename = f"expansion_candidates_{tenant_id}_{date.today().isoformat()}.csv"
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
