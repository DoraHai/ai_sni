"""SEO-only diagnostic review; all writes are local, append-only intent records."""

from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, PositiveInt, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.module_workspace import SeoSite
from app.models.seo import SeoImageAltReview, SeoPageIndexReview, SeoSitePage, SeoPageSnapshot
from app.security.auth import AuthContext, require_scoped_auth
from app.seo_site_diagnostics import assessed_condition, checked_iso, diagnostic_payload

router = APIRouter()


async def _scope(session, ctx, tenant_id, site_id, *, write=False):
    ctx.ensure_tenant(tenant_id)
    if not (ctx.can_edit("seo.site") if write else ctx.can_view("seo.site")):
        raise HTTPException(403, "无权操作站内优化")
    site = await session.scalar(select(SeoSite.id).where(SeoSite.id == site_id, SeoSite.tenant_id == tenant_id))
    if site is None:
        raise HTTPException(404, "SEO 网站不存在")


def review_payload(row):
    if row is None:
        return None
    return {"id": row.id, "intent": row.intent, "reason": row.reason,
            "actor_id": row.actor_id, "actor_name": row.actor_name,
            "created_at": checked_iso(row.created_at), "evidence": row.evidence}


@router.get("/site-pages/diagnostics")
async def list_diagnostics(
    tenant_id: PositiveInt, site_id: PositiveInt,
    q: str = Query("", max_length=200),
    review_state: Literal["all", "unreviewed", "reviewed"] = "all",
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, tenant_id, site_id)
    p, r = SeoSitePage, SeoPageIndexReview
    latest = (select(r.page_id, func.max(r.id).label("review_id"))
              .where(r.tenant_id == tenant_id, r.site_id == site_id)
              .group_by(r.page_id).subquery())
    scope = [p.tenant_id == tenant_id, p.site_id == site_id]
    query = select(p, r).outerjoin(latest, latest.c.page_id == p.id).outerjoin(r, r.id == latest.c.review_id)
    conditions = list(scope)
    if q.strip():
        term = f"%{q.strip()}%"
        conditions.append(or_(p.url.ilike(term), p.title.ilike(term)))
    if review_state == "unreviewed":
        conditions.append(or_(r.id.is_(None), r.intent == "undecided"))
    elif review_state == "reviewed":
        conditions.append(r.intent.in_(("index", "noindex")))
    query = query.where(*conditions)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(query.order_by(p.id).offset((page - 1) * page_size).limit(page_size))).all()
    coverage = (await session.execute(select(
        func.count(p.id), func.count(p.id).filter(assessed_condition(p)),
        func.count(p.id).filter(p.last_checked_at.is_(None)), func.max(p.last_checked_at),
    ).where(*scope))).one()
    return {
        "items": [{"id": row.id, "url": row.url, "title": row.title,
                   "diagnostic": diagnostic_payload(row, review.intent if review else "undecided"),
                   "review": review_payload(review)} for row, review in rows],
        "total": int(total or 0), "page": page, "page_size": page_size,
        "coverage": {"inventory": coverage[0], "assessed": coverage[1], "not_checked": coverage[2],
                     "unavailable": coverage[0] - coverage[1] - coverage[2],
                     "latest_checked_at": checked_iso(coverage[3]), "scope": "stored_page_inventory"},
    }


@router.get("/site-pages/image-evidence")
async def get_image_evidence(
    tenant_id: PositiveInt, site_id: PositiveInt, page_id: PositiveInt,
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, tenant_id, site_id)
    page = await session.scalar(select(SeoSitePage).where(
        SeoSitePage.id == page_id, SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id,
    ))
    if page is None:
        raise HTTPException(404, "页面不存在")
    # Do not fall back to an older successful observation if the latest failed.
    snapshot = await session.scalar(select(SeoPageSnapshot).where(
        SeoPageSnapshot.tenant_id == tenant_id, SeoPageSnapshot.site_id == site_id,
        SeoPageSnapshot.url == page.url,
    ).order_by(SeoPageSnapshot.fetched_at.desc(), SeoPageSnapshot.id.desc()).limit(1))
    fetch_error = None
    fetched_at = None
    if snapshot is not None:
        fetch_error = snapshot.error_type
        if not fetch_error and (snapshot.status_code is None or not 200 <= snapshot.status_code < 300):
            fetch_error = "http_status_unavailable" if snapshot.status_code is None else f"http_{snapshot.status_code}"
        # fetched_at is DB-generated local CST, unlike site-page checked_at UTC.
        fetched_at = snapshot.fetched_at
        if fetched_at is not None and fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone(timedelta(hours=8)))
    return {"page_id": page.id, "url": page.url,
            "snapshot_id": snapshot.id if snapshot else None,
            "fetched_at": fetched_at.isoformat() if fetched_at else None,
            "fetch_error": fetch_error,
            "legacy_candidate_count": snapshot.images_missing_alt_count if snapshot else None,
            "evidence": snapshot.image_alt_evidence if snapshot and not fetch_error else None}


def image_review_payload(row):
    return {
        "id": row.id, "snapshot_id": row.snapshot_id, "position": row.position,
        "source_url": row.source_url, "observed_alt_state": row.observed_alt_state,
        "decision": row.decision, "alt_suggestion": row.alt_suggestion,
        "note": row.note, "review_status": row.review_status,
        "actor_id": row.actor_id, "actor_name": row.actor_name,
        "reviewed_at": checked_iso(row.reviewed_at), "updated_at": checked_iso(row.updated_at),
    }


async def _page_and_latest_snapshot(session, tenant_id, site_id, page_id, *, lock_page=False):
    page_query = select(SeoSitePage).where(
        SeoSitePage.id == page_id, SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id,
    )
    page = await session.scalar(page_query.with_for_update() if lock_page else page_query)
    if page is None:
        raise HTTPException(404, "页面不存在")
    snapshot = await session.scalar(select(SeoPageSnapshot).where(
        SeoPageSnapshot.tenant_id == tenant_id, SeoPageSnapshot.site_id == site_id,
        SeoPageSnapshot.url == page.url,
    ).order_by(SeoPageSnapshot.fetched_at.desc(), SeoPageSnapshot.id.desc()).limit(1))
    return page, snapshot


@router.get("/site-pages/image-remediation")
async def get_image_remediation(
    tenant_id: PositiveInt, site_id: PositiveInt, page_id: PositiveInt,
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, tenant_id, site_id)
    _, snapshot = await _page_and_latest_snapshot(session, tenant_id, site_id, page_id)
    if snapshot is None or snapshot.error_type or not snapshot.image_alt_evidence:
        return {"snapshot_id": snapshot.id if snapshot else None, "items": []}
    reviews = list(await session.scalars(select(SeoImageAltReview).where(
        SeoImageAltReview.tenant_id == tenant_id, SeoImageAltReview.site_id == site_id,
        SeoImageAltReview.page_id == page_id, SeoImageAltReview.snapshot_id == snapshot.id,
    ).order_by(SeoImageAltReview.position)))
    return {"snapshot_id": snapshot.id, "items": [image_review_payload(row) for row in reviews]}


class ImageAltReviewUpdate(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    page_id: PositiveInt
    expected_snapshot_id: PositiveInt
    expected_review_id: PositiveInt | None
    position: PositiveInt
    decision: Literal["undecided", "decorative", "informative"]
    alt_suggestion: str | None = Field(None, max_length=300)
    note: str | None = Field(None, max_length=1000)
    review_status: Literal["draft", "approved"] = "draft"

    @field_validator("alt_suggestion", "note")
    @classmethod
    def trim_optional(cls, value):
        return value.strip() or None if value is not None else None


@router.put("/site-pages/image-remediation")
async def save_image_remediation(
    req: ImageAltReviewUpdate, ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, req.tenant_id, req.site_id, write=True)
    if ctx.user_id is None:
        raise HTTPException(403, "图片用途必须由已登录的真实用户确认")
    _, snapshot = await _page_and_latest_snapshot(
        session, req.tenant_id, req.site_id, req.page_id, lock_page=True)
    if snapshot is None or snapshot.id != req.expected_snapshot_id:
        raise HTTPException(409, "图片证据已更新，请重新读取后确认")
    evidence = snapshot.image_alt_evidence if not snapshot.error_type else None
    candidates = evidence.get("items", []) if isinstance(evidence, dict) else []
    candidate = next((item for item in candidates if item.get("position") == req.position), None)
    if candidate is None:
        raise HTTPException(409, "当前快照中不存在该图片证据")
    observed_state = candidate.get("alt_state")
    if observed_state not in {"missing", "empty", "whitespace"}:
        raise HTTPException(409, "当前图片证据状态无效，请重新检测页面后再确认")
    suggestion = req.alt_suggestion
    if req.decision != "informative":
        suggestion = None
    if req.review_status == "approved" and req.decision == "undecided":
        raise HTTPException(422, "审核前请先确认图片用途")
    if req.review_status == "approved" and req.decision == "informative" and not suggestion:
        raise HTTPException(422, "内容图审核通过前必须填写 Alt 建议")
    row = await session.scalar(select(SeoImageAltReview).where(
        SeoImageAltReview.snapshot_id == snapshot.id,
        SeoImageAltReview.position == req.position,
    ).with_for_update())
    if (row.id if row else None) != req.expected_review_id:
        raise HTTPException(409, "图片整改记录已被其他操作更新，请刷新后重试")
    values = {
        "tenant_id": req.tenant_id, "site_id": req.site_id, "page_id": req.page_id,
        "snapshot_id": snapshot.id, "position": req.position,
        "source_url": candidate.get("source_url"),
        "observed_alt_state": observed_state, "decision": req.decision,
        "alt_suggestion": suggestion, "note": req.note, "review_status": req.review_status,
        "actor_id": ctx.user_id, "actor_name": ctx.username,
        "reviewed_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    if row is None:
        row = SeoImageAltReview(**values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return image_review_payload(row)


class IndexReviewCreate(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    page_id: PositiveInt
    # Required even on the first review (null); optimistic concurrency token.
    expected_review_id: PositiveInt | None
    intent: Literal["undecided", "index", "noindex"]
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请填写确认原因")
        return value


@router.post("/site-pages/index-reviews")
async def create_index_review(
    req: IndexReviewCreate, ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, req.tenant_id, req.site_id, write=True)
    if ctx.user_id is None:
        raise HTTPException(403, "索引意图必须由已登录的真实用户确认")
    row = await session.scalar(select(SeoSitePage).where(
        SeoSitePage.id == req.page_id, SeoSitePage.tenant_id == req.tenant_id,
        SeoSitePage.site_id == req.site_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(404, "页面不存在")
    latest = await session.scalar(select(SeoPageIndexReview).where(
        SeoPageIndexReview.tenant_id == req.tenant_id, SeoPageIndexReview.site_id == req.site_id,
        SeoPageIndexReview.page_id == req.page_id,
    ).order_by(SeoPageIndexReview.id.desc()).limit(1))
    if (latest.id if latest else None) != req.expected_review_id:
        raise HTTPException(409, "索引意图已被其他操作更新，请刷新后重试")
    review = SeoPageIndexReview(
        tenant_id=req.tenant_id, site_id=req.site_id, page_id=req.page_id,
        intent=req.intent, reason=req.reason, actor_id=ctx.user_id, actor_name=ctx.username,
        evidence=diagnostic_payload(row, req.intent), created_at=datetime.now(timezone.utc),
    )
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return {"review": review_payload(review), "diagnostic": review.evidence}


@router.get("/site-pages/index-reviews")
async def list_index_reviews(
    tenant_id: PositiveInt, site_id: PositiveInt, page_id: PositiveInt,
    before_id: PositiveInt | None = None, limit: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, tenant_id, site_id)
    page = await session.scalar(select(SeoSitePage.id).where(
        SeoSitePage.id == page_id, SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id,
    ))
    if page is None:
        raise HTTPException(404, "页面不存在")
    r = SeoPageIndexReview
    query = select(r).where(r.tenant_id == tenant_id, r.site_id == site_id, r.page_id == page_id)
    if before_id is not None:
        query = query.where(r.id < before_id)
    rows = list(await session.scalars(query.order_by(r.id.desc()).limit(limit + 1)))
    return {"items": [review_payload(row) for row in rows[:limit]],
            "next_before_id": rows[limit - 1].id if len(rows) > limit else None}
